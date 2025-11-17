# CÓDIGO COMPLETO E CORRIGIDO PARA: app/main.py
# (Implementa o Veto Explícito para Negativa do Usuário)

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
from supabase import create_client, Client
import hashlib
import json
import hmac
import uuid # Para gerar a API key
import requests # <-- Importação necessária para o login

# --- Serviços ---
from app.services.rag_service import gerar_resposta_rag, gerar_resposta_rag_stream
from app.services.llm_service import LLMService
from app.services.scheduler_service import create_schedule, verify_email_token
from worker_tasks import (
    ingest_repo, 
    save_instruction, 
    processar_e_salvar_relatorio,
    enviar_relatorio_agendado,
    process_webhook_payload
)
from app.services.metadata_service import MetadataService 

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

# --- Inicialização de Serviços (Supabase agora é pego daqui) ---
try:
    url: str = os.getenv("SUPABASE_URL")
    key: str = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
    
    supabase_client: Client = create_client(url, key)
    print("[Main] Cliente Supabase global inicializado.")
    
except Exception as e:
    print(f"[Main] ERRO CRÍTICO ao inicializar Supabase: {e}")
    supabase_client = None

try:
    llm_service = LLMService() 
    metadata_service = MetadataService()
    print("[Main] LLMService e MetadataService inicializados.")
except Exception as e:
    print(f"[Main] ERRO: Falha ao inicializar LLMService/MetadataService: {e}")
    llm_service = None
    metadata_service = None

# --- NOVO: Configuração de Auth ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") 

# --- App FastAPI ---
app = FastAPI(
    title="GitHub RAG API (v2 - Chat com Agendamento)",
    description="API unificada para análise, rastreabilidade e relatórios agendados.",
    version="0.4.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Modelos Pydantic ---
class Message(BaseModel):
    sender: str
    text: str

class ChatRequest(BaseModel):
    messages: List[Message]

class GoogleLoginRequest(BaseModel):
    credential: str # O Access Token vindo do chrome.identity

class AuthResponse(BaseModel):
    api_key: str
    email: str
    nome: str

class ChatResponse(BaseModel):
    response_type: str
    message: str
    job_id: Optional[str] = None
    fontes: Optional[List[Dict[str, Any]]] = None
    contexto: Optional[Dict[str, Any]] = None

class StreamRequest(BaseModel):
    repositorio: str
    prompt_usuario: str

# Palavras-chave de Confirmação e Negação
CONFIRMATION_WORDS = ["sim", "s", "yes", "y", "correto", "confirmo", "pode", "isso", "isso mesmo"]
NEGATION_WORDS = ["nao", "não", "n", "negativo", "cancelar", "errado"]

# --- Dependências de Segurança ---
async def verificar_token(x_api_key: str = Header(...)) -> Dict[str, Any]:
    """
    Verifica se a X-API-Key existe na tabela 'usuarios' e retorna
    o registro do usuário.
    """
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Serviço de DB não inicializado.")
    
    try:
        response = supabase_client.table("usuarios").select("*").eq("api_key", x_api_key).execute()
        
        if not response.data or len(response.data) == 0:
            print("[Auth] Token de API não encontrado (0 linhas).")
            raise HTTPException(status_code=401, detail="Token de API inválido")

        return response.data[0]
        
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        print(f"[Auth] Erro ao verificar token: {e}")
        raise HTTPException(status_code=401, detail="Token de API inválido ou erro na consulta.")

async def verify_github_signature(request: Request, x_hub_signature_256: str = Header(...)):
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="O servidor não está configurado para webhooks.")
    try:
        body = await request.body()
        hash_obj = hmac.new(secret.encode('utf-8'), msg=body, digestmod=hashlib.sha256)
        expected_signature = "sha512=" + hash_obj.hexdigest()
        if not hmac.compare_digest(expected_signature, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.")
        return body
    except Exception as e:
        raise HTTPException(status_code=400, detail="Erro ao processar assinatura do webhook.")

# --- FUNÇÃO HELPER: Roteador de Intenção (Multi-Step) ---
async def _route_intent(
    intent_data: Dict[str, Any], 
    user_id: str,
    user_email: str,
    last_user_prompt: str = ""
) -> Dict[str, Any]:
    
    if not conn or not q_ingest or not q_reports or not llm_service or not metadata_service:
        return {"response_type": "error", "message": "Erro de servidor: O serviço de fila (Redis) ou LLM está indisponível.", "job_id": None}

    # Tratamento de CLARIFY
    if intent_data["type"] == "clarify":
        return {"response_type": "clarification", "message": intent_data.get('response_text', "Não entendi."), "job_id": None}
        
    # Tratamento de CHAT simples
    if intent_data["type"] == "simple_chat":
        simple_response = llm_service.generate_simple_response(intent_data.get("response_text", last_user_prompt))
        return {"response_type": "answer", "message": simple_response, "job_id": None}

    # --- LÓGICA DE EXECUÇÃO E CONFIRMAÇÃO ---
    steps = intent_data.get("steps", [])
    if not steps:
        return {"response_type": "clarification", "message": "Não consegui identificar nenhuma ação válida para executar. Tente reformular sua pergunta.", "job_id": None}
    
    is_confirmation = last_user_prompt.strip().lower() in CONFIRMATION_WORDS
    is_negation = last_user_prompt.strip().lower() in NEGATION_WORDS # NOVO: Palavra de negação
    
    # 1. IDENTIFICAÇÃO DE CONFIRMAÇÃO NECESSÁRIA
    is_multi_step = len(steps) > 1
    # Verifica se a primeira etapa é um agendamento recorrente.
    is_recurring_schedule = steps[0]["intent"] == "call_schedule_tool" and steps[0]["args"].get("frequencia") not in ["once", None]
    
    # CORREÇÃO CRÍTICA DO FLUXO: Se for uma negação, CANCELAMOS IMEDIATAMENTE.
    if is_negation:
        return {"response_type": "answer", "message": "Entendido. A execução do plano foi cancelada.", "job_id": None}
    
    # Se for multi-step OU agendamento recorrente E NÃO for uma confirmação: PEDIR CONFIRMAÇÃO
    if (is_multi_step or is_recurring_schedule) and not is_confirmation:
        
        # A. AGENDAMENTO RECORRENTE (Single-step): 
        if is_recurring_schedule and not is_multi_step:
            confirmation_text = llm_service.summarize_action_for_confirmation(steps[0]["intent"], steps[0]["args"])
            return {"response_type": "clarification", "message": confirmation_text, "job_id": None}
        
        # B. MULTI-STEP: Usa a função de sumarização de plano
        elif is_multi_step:
            confirmation_text = llm_service.summarize_plan_for_confirmation(steps, user_email)
            return {"response_type": "clarification", "message": confirmation_text, "job_id": None}

    # 2. PASSO DE EXECUÇÃO (Se for confirmação OU ação imediata/única)
    print(f"[ChatRouter] Iniciando cadeia de {len(steps)} jobs...")
    
    last_job_id = None
    final_message = "Tarefas enfileiradas."
    
    for i, step in enumerate(steps):
        intent = step.get("intent")
        args = step.get("args", {})
        repo = args.get("repositorio")

        print(f"--- Enfileirando Etapa {i+1}/{len(steps)}: {intent} ---")
        
        # CASO 1: Consulta RAG (QUERY)
        if intent == "call_query_tool":
            if i == len(steps) - 1:
                return {"response_type": "stream_answer", "message": json.dumps({"repositorio": repo, "prompt_usuario": args.get("prompt_usuario")}), "job_id": None}
            continue

        # CASO 2, 3, 4: INGEST, REPORT, SAVE_INSTRUCTION
        elif intent == "call_ingest_tool":
            func = ingest_repo
            params = [user_id, repo, 50, 20, 30] 
            target_queue = q_ingest
            final_message = f"Solicitação de ingestão para {repo} recebida."
        
        elif intent == "call_report_tool":
            func = processar_e_salvar_relatorio
            params = [user_id, repo, args.get("prompt_usuario"), "html"]
            target_queue = q_reports
            final_message = f"Solicitação de relatório para {repo} recebida."

        elif intent == "call_save_instruction_tool":
            func = save_instruction
            params = [user_id, repo, args.get("instrucao")]
            target_queue = q_ingest
            final_message = f"Instrução para {repo} salva."
            
        # CASO 5: Agendamento (SCHEDULE)
        elif intent == "call_schedule_tool":
            freq = args.get("frequencia")
            email_to_use = args.get('user_email') or user_email
            
            if freq == "once":
                # Envio Imediato (Job no RQ)
                func = enviar_relatorio_agendado
                params = [None, email_to_use, repo, args.get("prompt_relatorio"), user_id]
                target_queue = q_reports
                final_message = f"Relatório para {repo} será enviado para {email_to_use} em breve."
            
            elif is_recurring_schedule:
                # Cria o agendamento recorrente no DB (não é um job do RQ)
                msg = create_schedule(user_id=user_id, user_email=email_to_use, repo=repo, prompt=args["prompt_relatorio"], 
                                      freq=freq, hora=args["hora"], tz=args["timezone"])
                return {"response_type": "answer", "message": msg, "job_id": None}

            else:
                continue

        else:
            print(f"AVISO: Intenção {intent} não é processável como tarefa de worker. Pulando.")
            continue

        # Enfileira o job, fazendo-o depender do job anterior
        job = target_queue.enqueue(
            func, 
            *params, 
            depends_on=last_job_id if last_job_id else None,
            job_timeout=1800
        )
        last_job_id = job.id
    
    # Retorna o ID do ÚLTIMO job para o frontend fazer polling
    if last_job_id:
        return {"response_type": "job_enqueued", "message": final_message, "job_id": last_job_id}
    else:
        return {"response_type": "clarification", "message": "Não foi possível enfileirar a(s) tarefa(s). Verifique os argumentos e tente novamente.", "job_id": None}


# --- Rotas da API (v2) ---
# ... (O restante do app.main.py permanece inalterado)
# ... (Você precisará copiar todo o conteúdo do arquivo)

@app.get("/health")
async def health_check():
    redis_status = "desconectado"
    if conn:
        try: conn.ping(); redis_status = "conectado"
        except Exception as e: redis_status = f"erro ({e})"
    return {"status": "online", "version": "0.4.0", "redis_status": redis_status, "supabase_status": "conectado" if supabase_client else "desconectado"}

@app.post("/api/auth/google", response_model=AuthResponse)
async def google_login(request: GoogleLoginRequest):
    """
    Verifica o Access Token (vindo do chrome.identity) chamando a
    API userinfo do Google. Cria/atualiza o usuário no banco
    e retorna a API Key pessoal desse usuário.
    """
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Serviço de DB não inicializado.")

    try:
        access_token = request.credential
        
        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        response = requests.get(userinfo_url, headers=headers)
        
        if response.status_code != 200:
            print(f"[Auth] Erro de verificação de token: {response.text}")
            raise ValueError(f"Token Google inválido (status {response.status_code}): {response.text}")

        id_info = response.json()
        
        email = id_info.get('email')
        google_id = id_info.get('sub') # 'sub' é o Google ID
        nome = id_info.get('name')

        if not email or not google_id:
            raise ValueError("Token do Google não retornou email ou ID.")

        response = supabase_client.table("usuarios").select("*").eq("google_id", google_id).execute()
        
        if response.data:
            user = response.data[0]
            print(f"[Auth] Usuário existente logado: {email}")
            return {"api_key": user['api_key'], "email": user['email'], "nome": user['nome']}
        else:
            print(f"[Auth] Novo usuário detectado: {email}")
            new_api_key = str(uuid.uuid4())
            
            insert_response = supabase_client.table("usuarios").insert(
                {
                    "google_id": google_id,
                    "email": email,
                    "nome": nome,
                    "api_key": new_api_key
                },
                returning="representation" 
            ).execute()
            
            if not insert_response.data:
                 raise Exception("Falha ao inserir novo usuário no Supabase.")

            user = insert_response.data[0]
            return {"api_key": user['api_key'], "email": user['email'], "nome": user['nome']}

    except ValueError as e:
        print(f"[Auth] Erro de verificação de token: {e}")
        raise HTTPException(status_code=401, detail=f"Token Google inválido: {e}")
    except Exception as e:
        print(f"[Auth] Erro crítico no login: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno no servidor: {e}")

# ... (restante do arquivo)
if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor Uvicorn local em http://0.0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)