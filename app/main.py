# CÓDIGO ATUALIZADO PARA: app/main.py
# (Adicionado log de depuração na rota /api/chat)

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
if QUEU_PREFIX: print(f"[Main] Usando prefixo de fila: '{QUEUE_PREFIX}'")

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

# --- Modelos Pydantic (Atualizados) ---
class ChatRequest(BaseModel):
    prompt: str
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

# --- Dependências de Segurança (Corpo completo) ---
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


# --- FUNÇÃO HELPER: Roteador de Intenção (Corpo completo) ---
async def _route_intent(intent: str, args: Dict[str, Any], user_email: Optional[str] = None) -> Dict[str, Any]:
    
    if not conn or not q_ingest or not q_reports:
        return {"response_type": "error", "message": "Erro de servidor: O serviço de fila (Redis) está indisponível.", "job_id": None}

    # CASO 1: Consulta RAG (QUERY)
    if intent == "call_query_tool":
        print(f"[ChatRouter] Rota: QUERY. Args: {args}")
        repo = args.get("repositorio"); prompt = args.get("prompt_usuario")
        
        # Retorna a instrução para o frontend chamar o stream
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
        print(f"[ChatRouter] Rota: SCHEDULE. Args: {args}") # <-- LOG ADICIONAL AQUI
        if not user_email: return {"response_type": "clarification", "message": "Para agendar relatórios, preciso do seu email.", "job_id": None}
        msg = create_schedule(user_email, **args)
        return {"response_type": "answer", "message": msg, "job_id": None}
    
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

@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat(request: ChatRequest):
    if not llm_service or not conn: raise HTTPException(status_code=500, detail="Serviços de backend não inicializados.")
    user_prompt = request.prompt
    if not user_prompt.strip(): raise HTTPException(status_code=400, detail="Prompt não pode ser vazio.")
    try: 
        intent_data = llm_service.get_intent(user_prompt)
        intent = intent_data.get("intent"); args = intent_data.get("args", {})
        
        # --- INÍCIO DA ADIÇÃO (DEBUG) ---
        print(f"--- [DEBUG /api/chat] ---")
        print(f"Prompt: {user_prompt}")
        print(f"Intenção detectada: {intent}")
        print(f"Argumentos extraídos: {args}")
        print(f"---------------------------")
        # --- FIM DA ADIÇÃO (DEBUG) ---
        
        if intent == "CLARIFY": args["response_text"] = intent_data.get("response_text")
        return await _route_intent(intent, args, request.user_email)
    except Exception as e:
        print(f"[ChatRouter] Erro CRÍTICO no /api/chat: {e}")
        return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}

# (O resto do arquivo 'main.py' permanece o mesmo)
# ... /api/chat_file
# ... /api/chat_stream
# ... /api/webhook/github
# ... /api/email/verify
# ... /api/ingest/status
# ... /api/relatorio/status
# ... /api/relatorio/download
# ... if __name__ == "__main__":