# CÓDIGO COMPLETO PARA: app/main.py
# (Implementa o endpoint /api/chat_stream)

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
import hashlib
import json
import hmac

# --- Serviços ---
# (Importa as duas funções RAG)
from app.services.rag_service import gerar_resposta_rag, gerar_resposta_rag_stream
from app.services.llm_service import LLMService
from app.services.scheduler_service import create_schedule, verify_email_token
from worker_tasks import (
    ingest_repo, 
    save_instruction, 
    processar_e_salvar_relatorio,
    process_webhook_payload
)

# --- Configuração (Sem alterações) ---
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

# --- App FastAPI (Sem alterações) ---
app = FastAPI(title="GitHub RAG API (v2 - Chat com Agendamento)", ...)
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)

# --- Modelos Pydantic (Atualizados) ---
class ChatRequest(BaseModel):
    prompt: str
    user_email: Optional[str] = None 

class ChatResponse(BaseModel):
    response_type: str # 'stream_answer', 'job_enqueued', 'clarification', 'error'
    message: str # (Agora usado para a *próxima* chamada, se for stream)
    job_id: Optional[str] = None

# (Este novo modelo é para o endpoint de stream)
class StreamRequest(BaseModel):
    repositorio: str
    prompt_usuario: str

# --- Dependências de Segurança (Sem alterações) ---
async def verificar_token(x_api_key: str = Header(...)): ...
async def verify_github_signature(request: Request, x_hub_signature_256: str = Header(...)): ...

# --- FUNÇÃO HELPER: Roteador de Intenção (ATUALIZADO) ---
async def _route_intent(intent: str, args: Dict[str, Any], user_email: Optional[str] = None) -> Dict[str, Any]:
    
    if not conn or not q_ingest or not q_reports:
        return {"response_type": "error", "message": "Erro de servidor: O serviço de fila (Redis) está indisponível.", "job_id": None}

    # CASO 1: Consulta RAG (QUERY)
    if intent == "call_query_tool":
        print(f"[ChatRouter] Rota: QUERY. Args: {args}")
        repo = args.get("repositorio"); prompt = args.get("prompt_usuario")
        
        # --- MUDANÇA (Streaming) ---
        # Não rodamos o RAG aqui. Apenas dizemos ao frontend
        # para chamar o endpoint de streaming.
        
        # (O Cache é movido para o endpoint de stream)
        
        return {
            "response_type": "stream_answer", # <-- NOVO TIPO
            # 'message' agora é o JSON de argumentos para a próxima chamada
            "message": json.dumps({"repositorio": repo, "prompt_usuario": prompt}),
            "job_id": None
        }

    # (O restante das intenções (INGEST, REPORT, SCHEDULE, etc.)
    #  permanece o mesmo da etapa anterior)
    # ...
    elif intent == "call_ingest_tool":
        repo = args.get("repositorio")
        job = q_ingest.enqueue(ingest_repo, repo, 20, 10, 15, job_timeout=1200)
        return {"response_type": "job_enqueued", "message": f"Solicitação de ingestão para {repo} recebida...", "job_id": job.id}
    elif intent == "call_report_tool":
        repo = args.get("repositorio"); prompt = args.get("prompt_usuario")
        job = q_reports.enqueue(processar_e_salvar_relatorio, repo, prompt, "html", job_timeout=1800)
        return {"response_type": "job_enqueued", "message": f"Solicitação de relatório para {repo} recebida...", "job_id": job.id}
    elif intent == "call_schedule_tool":
        if not user_email: return {"response_type": "clarification", "message": "Para agendar relatórios, preciso do seu email.", "job_id": None}
        msg = create_schedule(user_email, **args)
        return {"response_type": "answer", "message": msg, "job_id": None}
    elif intent == "call_save_instruction_tool":
        repo = args.get("repositorio"); instrucao = args.get("instrucao")
        job = q_ingest.enqueue(save_instruction, repo, instrucao, job_timeout=300)
        return {"response_type": "job_enqueued", "message": "Ok, estou salvando sua instrução...", "job_id": job.id}
    elif intent == "CLARIFY":
        return {"response_type": "clarification", "message": args.get('response_text', "Não entendi."), "job_id": None}
    else:
        raise Exception(f"Intenção desconhecida: {intent}")

# --- Rotas da API (v2) ---
@app.get("/health")
async def health_check():
    # (Sem alterações)
    redis_status = "desconectado"
    if conn:
        try: conn.ping(); redis_status = "conectado"
        except Exception as e: redis_status = f"erro ({e})"
    return {"status": "online", "version": "0.4.0", "redis_status": redis_status}

@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat(request: ChatRequest):
    # (Sem alterações)
    if not llm_service or not conn: raise HTTPException(status_code=500, detail="Serviços de backend não inicializados.")
    user_prompt = request.prompt
    if not user_prompt.strip(): raise HTTPException(status_code=400, detail="Prompt não pode ser vazio.")
    try:
        intent_data = llm_service.get_intent(user_prompt)
        intent = intent_data.get("intent"); args = intent_data.get("args", {})
        if intent == "CLARIFY": args["response_text"] = intent_data.get("response_text")
        return await _route_intent(intent, args, request.user_email)
    except Exception as e:
        print(f"[ChatRouter] Erro CRÍTICO no /api/chat: {e}")
        return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}

@app.post("/api/chat_file", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat_with_file(prompt: str = Form(...), user_email: Optional[str] = Form(None), arquivo: UploadFile = File(...)):
    # (Sem alterações)
    if not llm_service or not conn: raise HTTPException(status_code=500, detail="Serviços de backend não inicializados.")
    try:
        conteudo_bytes = await arquivo.read(); file_text = conteudo_bytes.decode("utf-8")
        if not file_text.strip(): raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
        combined_prompt = f"Prompt: \"{prompt}\"\n\nArquivo ({arquivo.filename}):\n\"{file_text}\""
        intent_data = llm_service.get_intent(combined_prompt)
        intent = intent_data.get("intent"); args = intent_data.get("args", {})
        if intent == "CLARIFY": args["response_text"] = intent_data.get("response_text")
        return await _route_intent(intent, args, user_email)
    except Exception as e:
        print(f"[ChatRouter-File] Erro CRÍTICO no /api/chat_file: {e}")
        return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}

# --- NOVO ENDPOINT (Marco 8 - Streaming) ---
@app.post("/api/chat_stream", dependencies=[Depends(verificar_token)])
async def handle_chat_stream(request: StreamRequest):
    """
    Endpoint que lida APENAS com a resposta RAG em streaming.
    """
    if not gerar_resposta_rag_stream:
        raise HTTPException(status_code=500, detail="Serviço RAG (streaming) não inicializado.")
        
    try:
        # 1. Implementação do Cache (igual ao do /api/chat)
        repo = request.repositorio; prompt = request.prompt_usuario
        cache_key = f"cache:query:{repo}:{hashlib.md5(prompt.encode()).hexdigest()}"
        
        if conn:
            try:
                cached_result = conn.get(cache_key)
                if cached_result:
                    print(f"[Cache-Stream] HIT! Retornando stream de cache para {cache_key}")
                    # Se está no cache, não é stream, é texto completo.
                    # Embrulhamos em um gerador simples.
                    async def cached_stream():
                        yield json.loads(cached_result)["message"] # Retorna o texto salvo
                    return StreamingResponse(cached_stream(), media_type="text/plain")
            except Exception as e: print(f"[Cache-Stream] ERRO no Redis (GET): {e}")
        
        print(f"[Cache-Stream] MISS! Executando RAG Stream para {cache_key}")
        
        # 2. Chama a função geradora (ex: 'gerar_resposta_rag_stream')
        response_generator = gerar_resposta_rag_stream(repo, prompt)
        
        # 3. Cacheia a resposta completa
        full_response_chunks = []
        async def caching_stream_generator():
            try:
                for chunk in response_generator:
                    full_response_chunks.append(chunk)
                    yield chunk
                
                # Após o stream terminar, salva a resposta completa no cache
                full_response_text = "".join(full_response_chunks)
                if conn:
                    # (Precisamos construir o JSON de resposta completo)
                    response_data = {
                        "response_type": "answer", "message": full_response_text, "job_id": None,
                        "fontes": [{"tipo": "repositório", "id": "contexto", "url": f"https://github.com/{repo}"}],
                        "contexto": {"trechos": "Contexto buscado via stream."} # (Simplificado)
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

# (O restante do main.py: /webhook, /verify, /status, /download, etc.
#  permanece o mesmo)
# ...
@app.post("/api/webhook/github")
async def handle_github_webhook(request: Request, x_github_event: str = Header(...), payload_bytes: bytes = Depends(verify_github_signature)): ...
@app.get("/api/email/verify", response_class=HTMLResponse)
async def verify_email(token: str, email: str): ...
@app.get("/api/ingest/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_job_status(job_id: str): ...
@app.get("/api/relatorio/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_report_job_status(job_id: str): ...
@app.get("/api/relatorio/download/{filename}", dependencies=[Depends(verificar_token)])
async def download_report(filename: str): ...
if __name__ == "__main__": ...