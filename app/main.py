# CÓDIGO CORRIGIDO E COMPLETO PARA: app/main.py
# (Restaura /api/chat e remove duplicatas)

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends, HTTPException, status, Header, Form, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import redis
from rq import Queue
import io
from fastapi.responses import StreamingResponse, HTMLResponse 
from supabase import create_client
import hashlib
import json
import hmac

# --- Serviços ---
from app.services.rag_service import gerar_resposta_rag, gerar_resposta_rag_stream
from app.services.llm_service import LLMService
from app.services.scheduler_service import create_schedule, verify_email_token
from worker_tasks import (
    ingest_repo, 
    save_instruction, 
    processar_e_salvar_relatorio,
    process_webhook_payload
)

# --- Configuração ---
try:
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    conn = redis.from_url(redis_url)
    conn.ping()
    print("[Main] Conexão com Redis estabelecida.")
except Exception as e:
    print(f"[Main] ERRO CRÍTICO: Não foi possível conectar ao Redis em {redis_url}. {e}")
    conn = None

QUEUE_PREFIX = os.getenv('RQ_QUEUE_PREFIX', '')
if QUEUE_PREFIX: print(f"[Main] Usando prefixo de fila: '{QUEUE_PREFIX}'")

if conn:
    q_ingest = Queue(f'{QUEUE_PREFIX}ingest', connection=conn) 
    q_reports = Queue(f'{QUEUE_PREFIX}reports', connection=conn)
else:
    q_ingest = None; q_reports = None

try:
    llm_service = LLMService() 
    print("[Main] LLMService inicializado.")
except Exception as e:
    print(f"[Main] ERRO: Falha ao inicializar LLMService: {e}")
    llm_service = None

# --- App FastAPI ---
app = FastAPI(
    title="GitHub RAG API (v2 - Chat com Agendamento)",
    description="API unificada para análise, rastreabilidade e relatórios agendados.",
    version="0.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Modelos Pydantic (CORRIGIDOS) ---
# (Removida a duplicação de ChatRequest)

class Message(BaseModel):
    # O frontend envia 'id', mas não precisamos dele no backend
    sender: str
    text: str

class ChatRequest(BaseModel):
    # Esta é a definição correta para "Memória de Chat"
    messages: List[Message]
    user_email: Optional[str] = None 

class ChatResponse(BaseModel):
    response_type: str
    message: str
    job_id: Optional[str] = None
    fontes: Optional[List[Dict[str, Any]]] = None
    contexto: Optional[Dict[str, Any]] = None

class StreamRequest(BaseModel):
    repositorio: str
    prompt_usuario: str

# --- Dependências de Segurança ---
async def verificar_token(x_api_key: str = Header(...)):
    api_token = os.getenv("API_TOKEN")
    if not api_token:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Token de API não configurado no servidor.")
    if x_api_key != api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de API inválido")
    return x_api_key

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

# Palavras-chave que contam como uma confirmação do usuário
CONFIRMATION_WORDS = ["sim", "s", "yes", "y", "correto", "confirmo", "pode", "isso", "isso mesmo"]

# --- FUNÇÃO HELPER: Roteador de Intenção (ATUALIZADA) ---
async def _route_intent(
    intent: str, 
    args: Dict[str, Any], 
    user_email: Optional[str] = None,
    last_user_prompt: str = ""
) -> Dict[str, Any]:
    
    if not conn or not q_ingest or not q_reports:
        return {"response_type": "error", "message": "Erro de servidor: O serviço de fila (Redis) está indisponível.", "job_id": None}

    # Verifica se a última mensagem foi uma confirmação
    is_confirmation = last_user_prompt.strip().lower() in CONFIRMATION_WORDS

    # CASO 1: Consulta RAG (QUERY)
    if intent == "call_query_tool":
        print(f"[ChatRouter] Rota: QUERY. Args: {args}")
        repo = args.get("repositorio"); prompt = args.get("prompt_usuario")
        return {
            "response_type": "stream_answer", 
            "message": json.dumps({"repositorio": repo, "prompt_usuario": prompt}),
            "job_id": None
        }

    # CASO 2: Ingestão (INGEST)
    elif intent == "call_ingest_tool":
        repo = args.get("repositorio")
        job = q_ingest.enqueue(ingest_repo, repo, 20, 10, 15, job_timeout=1200)
        return {"response_type": "job_enqueued", "message": f"Solicitação de ingestão para {repo} recebida...", "job_id": job.id}
    
    # CASO 3: Relatório (REPORT)
    elif intent == "call_report_tool":
        repo = args.get("repositorio"); prompt = args.get("prompt_usuario")
        job = q_reports.enqueue(processar_e_salvar_relatorio, repo, prompt, "html", job_timeout=1800)
        return {"response_type": "job_enqueued", "message": f"Solicitação de relatório para {repo} recebida...", "job_id": job.id}
    
    # CASO 4: Agendamento (SCHEDULE)
    elif intent == "call_schedule_tool":
        print(f"[ChatRouter] Rota: SCHEDULE. Args: {args}")
        
        # --- INÍCIO DA ATUALIZAÇÃO (Lógica de Email) ---
        
        # 1. Extrai todos os argumentos
        repo = args.get("repositorio")
        prompt = args.get("prompt_relatorio")
        freq = args.get("frequencia")
        hora = args.get("hora")
        tz = args.get("timezone")
        email_from_args = args.get("user_email") # <-- Pega o email extraído pelo LLM
        
        # 2. Define o email final: usa o extraído do prompt, ou (como fallback) o enviado pelo frontend
        final_email = email_from_args or user_email 
        
        # 3. Verifica se TEMOS um email
        if not final_email: 
            # Se não, pede
            return {"response_type": "clarification", "message": "Para agendar relatórios, preciso do seu email.", "job_id": None}

        # --- INÍCIO DA ATUALIZAÇÃO (Lógica "Once" vs "Agendado") ---

        # 4. LÓGICA DE ENVIO IMEDIATO (freq == "once")
        if freq == "once":
            print(f"[ChatRouter] Envio imediato (once) detectado. Enfileirando job de email para {final_email}.")
            
            job = q_reports.enqueue(
                'worker_tasks.enviar_relatorio_agendado', 
                agendamento_id=None, # <-- Passa None para pular a DB
                user_email=final_email,
                repo_name=repo,
                user_prompt=prompt,
                job_timeout=1800
            )
            
            # Responde imediatamente, sem confirmação
            return {"response_type": "answer", "message": f"Ok! Estou preparando seu relatório para `{repo}` e o enviarei para `{final_email}` em breve.", "job_id": job.id}

        # 5. LÓGICA DE AGENDAMENTO (daily, weekly, etc.)
        else:
            # Prepara os argumentos para a confirmação
            confirmation_args = {
                "repositorio": repo, "prompt_relatorio": prompt,
                "frequencia": freq, "hora": hora, "timezone": tz,
                "user_email": final_email
            }
        
            # 5a. Verifica se é a confirmação ("Sim")
            if is_confirmation:
                print(f"[ChatRouter] Confirmação recebida. Criando agendamento para {final_email}.")
                msg = create_schedule(
                    user_email=final_email, repo=repo, prompt=prompt, 
                    freq=freq, hora=hora, tz=tz
                )
                return {"response_type": "answer", "message": msg, "job_id": None}
            
            # 5b. Pede a confirmação
            else:
                print("[ChatRouter] Agendamento detectado. Solicitando confirmação.")
                if not llm_service:
                    return {"response_type": "error", "message": "Erro: LLMService não inicializado para confirmação."}
                
                confirmation_text = llm_service.summarize_action_for_confirmation(
                    intent_name="agendamento", 
                    args=confirmation_args
                )
                return {"response_type": "clarification", "message": confirmation_text, "job_id": None}
        
        # --- FIM DA ATUALIZAÇÃO ---
    
    # CASO 5: Salvar Instrução (SAVE_INSTRUCTION)
    elif intent == "call_save_instruction_tool":
        repo = args.get("repositorio"); instrucao = args.get("instrucao")
        job = q_ingest.enqueue(save_instruction, repo, instrucao, job_timeout=300)
        return {"response_type": "job_enqueued", "message": "Ok, estou salvando sua instrução...", "job_id": job.id}
    
    # CASO 6: Clarificação (CLARIFY)
    elif intent == "CLARIFY":
        return {"response_type": "clarification", "message": args.get('response_text', "Não entendi."), "job_id": None}
    
    else:
        raise Exception(f"Intenção desconhecida: {intent}")

# --- Rotas da API (v2) ---
@app.get("/health")
async def health_check():
    redis_status = "desconectado"
    if conn:
        try: conn.ping(); redis_status = "conectado"
        except Exception as e: redis_status = f"erro ({e})"
    return {"status": "online", "version": "0.4.0", "redis_status": redis_status}


# --- INÍCIO DA CORREÇÃO (ENDPOINT RESTAURADO) ---
@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat(request: ChatRequest):
    if not llm_service or not conn: raise HTTPException(status_code=500, detail="Serviços de backend não inicializados.")
    
    user_email = request.user_email
    
    # 1. Formata o histórico
    history_lines = [f"{msg.sender.capitalize()}: {msg.text}" for msg in request.messages]
    full_prompt = "\n".join(history_lines)
    
    # 2. Pega a última mensagem do usuário
    last_user_prompt = request.messages[-1].text if request.messages else ""
    
    if not full_prompt.strip(): raise HTTPException(status_code=400, detail="Prompt não pode ser vazio.")
    
    try: 
        intent_data = llm_service.get_intent(full_prompt) # Envia o histórico completo
        intent = intent_data.get("intent"); args = intent_data.get("args", {})
        
        print(f"--- [DEBUG /api/chat] ---")
        print(f"Prompt (Completo): {full_prompt[-500:]}") # Log dos últimos 500 chars
        print(f"Intenção detectada: {intent}")
        print(f"Argumentos extraídos: {args}")
        print(f"---------------------------")
        
        if intent == "CLARIFY": args["response_text"] = intent_data.get("response_text")
        
        # 3. Passa a 'last_user_prompt' para o roteador
        return await _route_intent(intent, args, user_email, last_user_prompt)
        
    except Exception as e:
        print(f"[ChatRouter] Erro CRÍTICO no /api/chat: {e}")
        return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}
# --- FIM DA CORREÇÃO ---


# --- INÍCIO DA CORREÇÃO (ENDPOINT ÚNICO E CORRIGIDO) ---
@app.post("/api/chat_file", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat_with_file(
    prompt: str = Form(...), 
    messages_json: str = Form(...), # <-- NOVO
    user_email: Optional[str] = Form(None), 
    arquivo: UploadFile = File(...)
):
    if not llm_service or not conn: raise HTTPException(status_code=500, detail="Serviços de backend não inicializados.")
    try: 
        conteudo_bytes = await arquivo.read(); file_text = conteudo_bytes.decode("utf-8")
        if not file_text.strip(): raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")

        # 1. Formata o histórico
        try:
            messages = json.loads(messages_json)
            history_text = "\n".join([f"{m['sender'].capitalize()}: {m['text']}" for m in messages])
        except json.JSONDecodeError:
            history_text = ""
        
        # 2. Cria o prompt combinado
        # O 'prompt' é a mensagem atual do usuário
        # O 'history_text' são as mensagens anteriores
        combined_prompt = f"{history_text}\nUser: {prompt}\n\nArquivo ({arquivo.filename}):\n\"{file_text}\""

        intent_data = llm_service.get_intent(combined_prompt) # Envia o histórico completo
        intent = intent_data.get("intent"); args = intent_data.get("args", {})
        
        print(f"--- [DEBUG /api/chat_file] ---")
        print(f"Prompt Combinado: {combined_prompt[-500:]}...") # Log dos últimos 500 chars
        print(f"Intenção detectada: {intent}")
        print(f"Argumentos extraídos: {args}")
        print(f"------------------------------")
        
        if intent == "CLARIFY": args["response_text"] = intent_data.get("response_text")
        
        # 3. Passa o 'prompt' (que é a última mensagem) para o roteador
        return await _route_intent(intent, args, user_email, prompt)
    
    except Exception as e:
        print(f"[ChatRouter-File] Erro CRÍTICO no /api/chat_file: {e}")
        return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}
# --- FIM DA CORREÇÃO (REMOVIDA A DUPLICATA) ---


# --- NOVO ENDPOINT (Marco 8 - Streaming) ---
@app.post("/api/chat_stream", dependencies=[Depends(verificar_token)])
async def handle_chat_stream(request: StreamRequest):
    """
    Endpoint que lida APENAS com a resposta RAG em streaming.
    """
    if not gerar_resposta_rag_stream:
        raise HTTPException(status_code=500, detail="Serviço RAG (streaming) não inicializado.")
        
    try:
        repo = request.repositorio; prompt = request.prompt_usuario
        cache_key = f"cache:query:{repo}:{hashlib.md5(prompt.encode()).hexdigest()}"
        
        if conn:
            try:
                cached_result = conn.get(cache_key)
                if cached_result:
                    print(f"[Cache-Stream] HIT! Retornando stream de cache para {cache_key}")
                    async def cached_stream():
                        yield json.loads(cached_result)["message"]
                    return StreamingResponse(cached_stream(), media_type="text/plain")
            except Exception as e: print(f"[Cache-Stream] ERRO no Redis (GET): {e}")
        
        print(f"[Cache-Stream] MISS! Executando RAG Stream para {cache_key}")
        
        response_generator = gerar_resposta_rag_stream(repo, prompt)
        
        full_response_chunks = []
        async def caching_stream_generator():
            try:
                for chunk in response_generator:
                    full_response_chunks.append(chunk)
                    yield chunk
                
                full_response_text = "".join(full_response_chunks)
                if conn:
                    response_data = {
                        "response_type": "answer", "message": full_response_text, "job_id": None,
                        "fontes": [{"tipo": "repositório", "id": "contexto", "url": f"https://github.com/{repo}"}],
                        "contexto": {"trechos": "Contexto buscado via stream."}
                    }
                    try:
                        conn.set(cache_key, json.dumps(response_data), ex=3600)
                        print(f"[Cache-Stream] SET! Resposta salva em {cache_key}")
                    except Exception as e: print(f"[Cache-Stream] ERRO no Redis (SET): {e}")
            
            except Exception as e:
                print(f"[Stream] Erro durante a geração do stream: {e}")
                yield f"\n\n**Erro no servidor durante o stream:** {e}"

        return StreamingResponse(caching_stream_generator(), media_type="text/plain")

    except Exception as e:
        print(f"[ChatStream] Erro CRÍTICO no /api/chat_stream: {e}")
        return StreamingResponse((f"Erro: {e}"), media_type="text/plain")

# --- Endpoints de Suporte (Corpo completo) ---
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
        return HTMLResponse(content=f"<h1>Erro 500</h1><p>Ocorreu um erro no servidor.</p>", status_code=500)

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
        file_bytes = client.storage.from_(SUPABASE_BUCKET_NAME).download(filename)
        if not file_bytes: raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
        headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
        return StreamingResponse(io.BytesIO(file_bytes), media_type='text/html', headers=headers)
    except Exception as e:
        print(f"[API-DOWNLOAD] Erro ao baixar o arquivo: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar download: {repr(e)}")

# Ponto de entrada (corpo completo)
if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor Uvicorn local em http://0.0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)