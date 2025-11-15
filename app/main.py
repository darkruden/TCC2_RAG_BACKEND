# CÓDIGO COMPLETO PARA: app/main.py
# (Corrigido o erro de tipo status_code=4.04 para 404)

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends, HTTPException, status, Header, Form, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import redis
from rq import Queue
import io
from fastapi.responses import StreamingResponse, HTMLResponse 
from supabase import create_client

# --- Serviços ---
from app.services.ingest_service import ingest_repo, save_instruction
from app.services.rag_service import gerar_resposta_rag
from app.services.llm_service import LLMService
from app.services.report_service import processar_e_salvar_relatorio
from app.services.scheduler_service import create_schedule, verify_email_token

import hashlib
import json
import hmac

# --- Configuração das Filas (RQ) ---
try:
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    conn = redis.from_url(redis_url)
    conn.ping()
    print("[Main] Conexão com Redis estabelecida.")
except Exception as e:
    print(f"[Main] ERRO CRÍTICO: Não foi possível conectar ao Redis em {redis_url}. {e}")
    conn = None

if conn:
    q_ingest = Queue('ingest', connection=conn) 
    q_reports = Queue('reports', connection=conn)
else:
    q_ingest = None
    q_reports = None

# --- Inicialização dos Serviços Singleton ---
try:
    llm_service = LLMService() 
    print("[Main] LLMService inicializado.")
except Exception as e:
    print(f"[Main] ERRO: Falha ao inicializar LLMService: {e}")
    llm_service = None

# Inicializar aplicação FastAPI
app = FastAPI(
    title="GitHub RAG API (v2 - Chat com Agendamento)",
    description="API unificada para análise, rastreabilidade e relatórios agendados.",
    version="0.3.0"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Modelos de Dados Pydantic ---
class ChatRequest(BaseModel):
    prompt: str
    user_email: Optional[str] = None 

class ChatResponse(BaseModel):
    response_type: str
    message: str
    job_id: Optional[str] = None
    fontes: Optional[List[Dict[str, Any]]] = None
    contexto: Optional[Dict[str, Any]] = None

# --- Dependência de Segurança (Token API Padrão) ---
async def verificar_token(x_api_key: str = Header(...)):
    api_token = os.getenv("API_TOKEN")
    if not api_token:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Token de API não configurado no servidor.")
    if x_api_key != api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de API inválido")
    return x_api_key

# --- Dependência de Segurança (Webhook do GitHub) ---
async def verify_github_signature(request: Request, x_hub_signature_256: str = Header(...)):
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="O servidor não está configurado para webhooks.")
    try:
        body = await request.body()
        hash_obj = hmac.new(secret.encode('utf-8'), msg=body, digestmod=hashlib.sha256)
        expected_signature = "sha256=" + hash_obj.hexdigest()
        if not hmac.compare_digest(expected_signature, x_hub_signature_256):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura do webhook inválida.")
        return body
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Erro ao processar assinatura do webhook.")

# --- FUNÇÃO HELPER: Roteador de Intenção (Refatorado) ---
async def _route_intent(intent: str, args: Dict[str, Any], user_email: Optional[str] = None) -> Dict[str, Any]:
    """
    Função helper que executa a lógica de negócios com base na intenção
    classificada pela LLM.
    """
    
    # CASO 1: Consulta RAG (QUERY)
    if intent == "call_query_tool":
        print(f"[ChatRouter] Rota: QUERY. Args: {args}")
        repo = args.get("repositorio"); prompt = args.get("prompt_usuario")
        cache_key = f"cache:query:{repo}:{hashlib.md5(prompt.encode()).hexdigest()}"
        try:
            cached_result = conn.get(cache_key)
            if cached_result:
                print(f"[Cache] HIT!")
                return json.loads(cached_result)
        except Exception as e: print(f"[Cache] ERRO no Redis (GET): {e}")
        
        print(f"[Cache] MISS! Executando RAG...")
        resultado_rag = gerar_resposta_rag(prompt, repo)
        response_data = {
            "response_type": "answer", "message": resultado_rag["texto"], "job_id": None,
            "fontes": [{"tipo": "repositório", "id": "contexto", "url": f"https://github.com/{repo}"}],
            "contexto": {"trechos": resultado_rag["contexto"]}
        }
        try: conn.set(cache_key, json.dumps(response_data), ex=3600)
        except Exception as e: print(f"[Cache] ERRO no Redis (SET): {e}")
        return response_data

    # CASO 2: Ingestão (INGEST)
    elif intent == "call_ingest_tool":
        print(f"[ChatRouter] Rota: INGEST. Args: {args}")
        repo = args.get("repositorio")
        job = q_ingest.enqueue(ingest_repo, repo, 20, 10, 15, job_timeout=1200)
        msg = f"Solicitação de ingestão para {repo} recebida e enfileirada."
        return {"response_type": "job_enqueued", "message": msg, "job_id": job.id}

    # CASO 3: Relatório (REPORT)
    elif intent == "call_report_tool":
        print(f"[ChatRouter] Rota: REPORT. Args: {args}")
        repo = args.get("repositorio"); prompt = args.get("prompt_usuario")
        job = q_reports.enqueue(processar_e_salvar_relatorio, repo, prompt, "html", job_timeout=1800)
        msg = f"Solicitação de relatório para {repo} recebida e enfileirada."
        return {"response_type": "job_enqueued", "message": msg, "job_id": job.id}

    # CASO 4: Agendamento (SCHEDULE)
    elif intent == "call_schedule_tool":
        print(f"[ChatRouter] Rota: SCHEDULE. Args: {args}")
        if not user_email:
            return {"response_type": "clarification", "message": "Para agendar relatórios, preciso do seu email.", "job_id": None}
        mensagem_retorno = create_schedule(
            user_email=user_email, repo=args.get("repositorio"),
            prompt=args.get("prompt_relatorio"), freq=args.get("frequencia"),
            hora=args.get("hora"), tz=args.get("timezone")
        )
        return {"response_type": "answer", "message": mensagem_retorno, "job_id": None}

    # CASO 5: Salvar Instrução (SAVE_INSTRUCTION)
    elif intent == "call_save_instruction_tool":
        print(f"[ChatRouter] Rota: SAVE_INSTRUCTION. Args: {args}")
        repo = args.get("repositorio")
        instrucao = args.get("instrucao")
        mensagem_retorno = save_instruction(repo, instrucao)
        return {"response_type": "answer", "message": mensagem_retorno, "job_id": None}

    # CASO 6: Clarificação (CLARIFY)
    elif intent == "CLARIFY":
        print(f"[ChatRouter] Rota: CLARIFY.")
        return {"response_type": "clarification", "message": args.get('response_text', "Não entendi. Pode reformular?"), "job_id": None}
    
    else:
        raise Exception(f"Intenção desconhecida recebida da LLM: {intent}")

# --- Rotas da API (v2) ---

@app.get("/health")
async def health_check():
    redis_status = "desconectado"
    if conn:
        try: conn.ping(); redis_status = "conectado"
        except Exception as e: redis_status = f"erro ({e})"
    return {"status": "online", "version": "0.3.0", "redis_status": redis_status}

@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat(request: ChatRequest):
    if not llm_service or not conn:
        raise HTTPException(status_code=500, detail="Serviços de backend (LLM ou Redis) não inicializados.")
    user_prompt = request.prompt
    if not user_prompt or not user_prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt não pode ser vazio.")
    try:
        intent_data = llm_service.get_intent(user_prompt)
        intent = intent_data.get("intent")
        args = intent_data.get("args", {})
        if intent == "CLARIFY":
            args["response_text"] = intent_data.get("response_text")
        return await _route_intent(intent, args, request.user_email)
    except Exception as e:
        print(f"[ChatRouter] Erro CRÍTICO no /api/chat: {e}")
        return {"response_type": "error", "message": f"Erro ao processar sua solicitação: {e}", "job_id": None}

@app.post("/api/chat_file", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat_with_file(
    prompt: str = Form(...),
    user_email: Optional[str] = Form(None),
    arquivo: UploadFile = File(...)
):
    if not llm_service or not conn:
        raise HTTPException(status_code=500, detail="Serviços de backend (LLM ou Redis) não inicializados.")
    try:
        conteudo_bytes = await arquivo.read()
        try:
            file_text = conteudo_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Não foi possível decodificar o arquivo (use UTF-8).")
        if not file_text.strip():
            raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
        
        combined_prompt = f"""
        Prompt do Usuário: "{prompt}"
        ---
        Conteúdo do Arquivo Anexado ({arquivo.filename}):
        "{file_text}"
        ---
        Analise o prompt do usuário e o conteúdo do arquivo, e chame a ferramenta correta.
        Se o usuário quiser salvar a instrução, use o 'Conteúdo do Arquivo' como a instrução.
        Se o usuário quiser consultar, use o 'Conteúdo do Arquivo' como o prompt da consulta.
        """
        
        intent_data = llm_service.get_intent(combined_prompt)
        intent = intent_data.get("intent")
        args = intent_data.get("args", {})
        if intent == "CLARIFY":
            args["response_text"] = intent_data.get("response_text")
        return await _route_intent(intent, args, user_email)
    except Exception as e:
        print(f"[ChatRouter-File] Erro CRÍTICO no /api/chat_file: {e}")
        return {"response_type": "error", "message": f"Erro ao processar sua solicitação: {e}", "job_id": None}

@app.post("/api/webhook/github")
async def handle_github_webhook(request: Request, x_github_event: str = Header(...), payload_bytes: bytes = Depends(verify_github_signature)):
    if not q_ingest: raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    try: payload = json.loads(payload_bytes.decode('utf-8'))
    except json.JSONDecodeError: raise HTTPException(status_code=400, detail="Payload do webhook mal formatado.")
    print(f"[Webhook] Recebido evento '{x_github_event}' validado.")
    if x_github_event in ['push', 'issues', 'pull_request']:
        try:
            job = q_ingest.enqueue('worker_tasks.process_webhook_payload', x_github_event, payload, job_timeout=600)
            print(f"[Webhook] Evento '{x_github_event}' enfileirado. Job ID: {job.id}")
        except Exception as e:
            print(f"[Webhook] ERRO ao enfileirar job: {e}")
            raise HTTPException(status_code=500, detail="Erro ao enfileirar tarefa do webhook.")
        return {"status": "success", "message": f"Evento '{x_github_event}' recebido e enfileirado."}
    else:
        return {"status": "ignored", "message": f"Evento '{x_github_event}' não é processado."}

@app.get("/api/email/verify", response_class=HTMLResponse)
async def verify_email(token: str, email: str):
    try:
        sucesso = verify_email_token(email, token)
        if sucesso:
            return """<html>...<h1>✅ Email Verificado com Sucesso!</h1>...</html>"""
        else:
            return """<html>...<h1>❌ Falha na Verificação</h1>...</html>"""
    except Exception as e:
        return HTMLResponse(content=f"<h1>Erro 500</h1><p>Ocorreu um erro.</p>", status_code=500)

@app.get("/api/ingest/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_job_status(job_id: str):
    if not q_ingest: raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    try: job = q_ingest.fetch_job(job_id)
    except Exception as e: raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None: return {"status": "not_found"}
    status = job.get_status(); result = None; error_info = None
    if status == 'finished': result = job.result
    elif status == 'failed': error_info = str(job.exc_info)
    return {"status": status, "result": result, "error": error_info}

@app.get("/api/relatorio/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_report_job_status(job_id: str):
    if not q_reports: raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    try: job = q_reports.fetch_job(job_id)
    except Exception as e: raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None: return {"status": "not_found"}
    status = job.get_status(); result = None; error_info = None
    if status == 'finished': result = job.result
    elif status == 'failed': error_info = str(job.exc_info)
    return {"status": status, "result": result, "error": error_info}

@app.get("/api/relatorio/download/{filename}", dependencies=[Depends(verificar_token)])
async def download_report(filename: str):
    SUPABASE_BUCKET_NAME = "reports"
    try:
        url = os.getenv('SUPABASE_URL'); key = os.getenv('SUPABASE_KEY')
        if not url or not key: raise Exception("Credenciais Supabase não encontradas")
        client = create_client(url, key)
        
        print(f"[API-DOWNLOAD] Usuário solicitou download de: {filename}")
        file_bytes = client.storage.from_(SUPABASE_BUCKET_NAME).download(filename)
        
        # --- CORREÇÃO DO ERRO DE SINTAXE ---
        # (status_code=4.04 foi corrigido para 404)
        if not file_bytes: 
            raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
            
        print(f"[API-DOWNLOAD] Arquivo encontrado. Transmitindo...")
        headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
        
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type='text/html',
            headers=headers
        )
    except Exception as e:
        print(f"[API-DOWNLOAD] Erro ao baixar o arquivo: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar download: {repr(e)}")

# Ponto de entrada (não muda)
if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor Uvicorn local em http://0.0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)