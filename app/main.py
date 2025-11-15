# CÓDIGO COMPLETO PARA: app/main.py
# (Implementa a CRIAÇÃO de agendamentos e VERIFICAÇÃO de email)

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
# Importação para a página de verificação de email
from fastapi.responses import StreamingResponse, HTMLResponse 
from supabase import create_client

# --- Serviços do Marco 1 ---
from app.services.ingest_service import ingest_repo
from app.services.rag_service import gerar_resposta_rag
# --- Serviços dos Marcos Anteriores ---
from app.services.llm_service import LLMService
from app.services.report_service import processar_e_salvar_relatorio
# --- NOVAS IMPORTAÇÕES (Marco 5) ---
from app.services.scheduler_service import create_schedule, verify_email_token

import hashlib
import json

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

# --- Modelos de Dados Pydantic (Atualizados) ---

class ChatRequest(BaseModel):
    """ O que o frontend envia para /api/chat """
    prompt: str
    # O email é necessário para o agendamento
    user_email: Optional[str] = None 

class ChatResponse(BaseModel):
    """ O que o backend envia de volta """
    response_type: str
    message: str
    job_id: Optional[str] = None
    fontes: Optional[List[Dict[str, Any]]] = None
    contexto: Optional[Dict[str, Any]] = None

# --- Dependência de Segurança (Token) ---
async def verificar_token(x_api_key: str = Header(...)):
    # (Sem alterações)
    api_token = os.getenv("API_TOKEN")
    if not api_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token de API não configurado no servidor."
        )
    if x_api_key != api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de API inválido"
        )
    return x_api_key

# --- Rotas da API (v2) ---

@app.get("/health")
async def health_check():
    # (Sem alterações)
    redis_status = "desconectado"
    if conn:
        try:
            conn.ping()
            redis_status = "conectado"
        except Exception as e:
            redis_status = f"erro ({e})"
    return {"status": "online", "version": "0.3.0", "redis_status": redis_status}

# --- Endpoint /api/chat (ATUALIZADO) ---
@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat(request: ChatRequest):
    """
    Endpoint unificado que roteia a intenção do usuário.
    Agora inclui a lógica de AGENDAMENTO.
    """
    
    if not llm_service or not q_ingest or not q_reports or not conn:
        raise HTTPException(status_code=500, detail="Serviços de backend (LLM ou Redis) não inicializados.")

    user_prompt = request.prompt
    if not user_prompt or not user_prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt não pode ser vazio.")

    try:
        # 1. Chamar o Roteador de Intenção
        intent_data = llm_service.get_intent(user_prompt)
        intent = intent_data.get("intent")
        args = intent_data.get("args", {})

        # --- Lógica de Roteamento ---
        
        # CASO 1: Consulta RAG (QUERY)
        if intent == "call_query_tool":
            print(f"[ChatRouter] Rota: QUERY. Args: {args}")
            repo = args.get("repositorio")
            prompt = args.get("prompt_usuario")
            
            # --- Lógica de Cache (do Marco 3) ---
            cache_key = f"cache:query:{repo}:{hashlib.md5(prompt.encode()).hexdigest()}"
            try:
                cached_result = conn.get(cache_key)
                if cached_result:
                    print(f"[Cache] HIT! Retornando resultado de {cache_key}")
                    return json.loads(cached_result)
            except Exception as e:
                print(f"[Cache] ERRO no Redis (GET): {e}")
            
            print(f"[Cache] MISS! Executando RAG para {cache_key}")
            resultado_rag = gerar_resposta_rag(prompt, repo)
            response_data = {
                "response_type": "answer",
                "message": resultado_rag["texto"],
                "job_id": None,
                "fontes": [{"tipo": "repositório", "id": "contexto", "url": f"https://github.com/{repo}"}],
                "contexto": {"trechos": resultado_rag["contexto"]}
            }
            try:
                conn.set(cache_key, json.dumps(response_data), ex=3600)
                print(f"[Cache] SET! Resultado salvo em {cache_key}")
            except Exception as e:
                print(f"[Cache] ERRO no Redis (SET): {e}")
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
            repo = args.get("repositorio")
            prompt = args.get("prompt_usuario")
            job = q_reports.enqueue(processar_e_salvar_relatorio, repo, prompt, "html", job_timeout=1800)
            msg = f"Solicitação de relatório para {repo} recebida e enfileirada."
            return {"response_type": "job_enqueued", "message": msg, "job_id": job.id}

        # --- CASO 4: Agendamento (SCHEDULE) - (NOVO!) ---
        elif intent == "call_schedule_tool":
            print(f"[ChatRouter] Rota: SCHEDULE. Args: {args}")
            
            # Verificação de Email
            user_email = request.user_email
            if not user_email:
                print("[ChatRouter] ERRO: Tentativa de agendamento sem user_email.")
                return {
                    "response_type": "clarification",
                    "message": "Para agendar relatórios, preciso do seu email. (O frontend deve enviar 'user_email')",
                    "job_id": None
                }
            
            # Chama o novo scheduler_service
            mensagem_retorno = create_schedule(
                user_email=user_email,
                repo=args.get("repositorio"),
                prompt=args.get("prompt_relatorio"),
                freq=args.get("frequencia"),
                hora=args.get("hora"),
                tz=args.get("timezone")
            )
            
            return {
                "response_type": "answer", # É uma resposta direta
                "message": mensagem_retorno,
                "job_id": None
            }

        # CASO 5: Clarificação (CLARIFY)
        elif intent == "CLARIFY":
            print(f"[ChatRouter] Rota: CLARIFY. Msg: {intent_data.get('response_text')}")
            return {
                "response_type": "clarification",
                "message": intent_data.get('response_text', "Não entendi. Pode reformular?"),
                "job_id": None
            }
        
        else:
            raise Exception(f"Intenção desconhecida recebida da LLM: {intent}")

    except Exception as e:
        print(f"[ChatRouter] Erro CRÍTICO no /api/chat: {e}")
        return {
            "response_type": "error",
            "message": f"Erro ao processar sua solicitação: {e}",
            "job_id": None
        }

# --- NOVO ENDPOINT DE VERIFICAÇÃO DE EMAIL ---

@app.get("/api/email/verify", response_class=HTMLResponse)
async def verify_email(token: str, email: str):
    """
    Endpoint que o usuário clica no email de confirmação.
    """
    try:
        sucesso = verify_email_token(email, token)
        
        if sucesso:
            print(f"[EmailVerify] Sucesso: Email {email} verificado.")
            # Retorna uma página HTML simples de sucesso
            return """
            <html><head><title>Email Verificado</title><style>
            body { font-family: Arial, sans-serif; display: grid; place-items: center; min-height: 90vh; background-color: #f4f4f4; }
            div { text-align: center; padding: 40px; background-color: white; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
            h1 { color: #28a745; }
            </style></head><body><div>
            <h1>✅ Email Verificado com Sucesso!</h1>
            <p>Seus relatórios agendados estão ativados. Você já pode fechar esta aba.</p>
            </div></body></html>
            """
        else:
            print(f"[EmailVerify] FALHA: Token inválido para {email}.")
            # Retorna uma página HTML de falha
            return """
            <html><head><title>Falha na Verificação</title><style>
            body { font-family: Arial, sans-serif; display: grid; place-items: center; min-height: 90vh; background-color: #f4f4f4; }
            div { text-align: center; padding: 40px; background-color: white; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
            h1 { color: #dc3545; }
            </style></head><body><div>
            <h1>❌ Falha na Verificação</h1>
            <p>O link de verificação é inválido ou expirou.</p>
            <p>Por favor, tente agendar o relatório novamente para receber um novo link.</p>
            </div></body></html>
            """
            
    except Exception as e:
        print(f"[EmailVerify] ERRO CRÍTICO: {e}")
        return HTMLResponse(content=f"<h1>Erro 500</h1><p>Ocorreu um erro no servidor.</p>", status_code=500)


# --- Endpoints de Suporte (Permanecem Inalterados) ---

@app.get("/api/ingest/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_job_status(job_id: str):
    # (Código de verificação de status de ingestão - sem alterações)
    if not q_ingest: raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    print(f"[API] Verificando status do Job ID (Ingest): {job_id}")
    try: job = q_ingest.fetch_job(job_id)
    except Exception as e: raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None: return {"status": "not_found"}
    status = job.get_status(); result = None; error_info = None
    if status == 'finished': result = job.result
    elif status == 'failed': error_info = str(job.exc_info)
    return {"status": status, "result": result, "error": error_info}

@app.get("/api/relatorio/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_report_job_status(job_id: str):
    # (Código de verificação de status de relatório - sem alterações)
    if not q_reports: raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    print(f"[API] Verificando status do Job ID (Report): {job_id}")
    try: job = q_reports.fetch_job(job_id)
    except Exception as e: raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None: return {"status": "not_found"}
    status = job.get_status(); result = None; error_info = None
    if status == 'finished': result = job.result
    elif status == 'failed': error_info = str(job.exc_info)
    return {"status": status, "result": result, "error": error_info}

@app.get("/api/relatorio/download/{filename}", dependencies=[Depends(verificar_token)])
async def download_report(filename: str):
    # (Código de download do relatório - sem alterações)
    SUPABASE_BUCKET_NAME = "reports"
    try:
        url = os.getenv('SUPABASE_URL'); key = os.getenv('SUPABASE_KEY')
        if not url or not key: raise Exception("Credenciais Supabase não encontradas")
        client = create_client(url, key)
        print(f"[API-DOWNLOAD] Usuário solicitou download de: {filename}")
        file_bytes = client.storage.from_(SUPABASE_BUCKET_NAME).download(filename)
        if not file_bytes: raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
        print(f"[API-DOWNLOAD] Arquivo encontrado. Transmitindo...")
        headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
        return StreamingResponse(io.BytesIO(file_bytes), media_type='text/html', headers=headers)
    except Exception as e:
        print(f"[API-DOWNLOAD] Erro ao baixar o arquivo: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar download: {repr(e)}")

# Ponto de entrada (não muda)
if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor Uvicorn local em http://0.0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)