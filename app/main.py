# CÓDIGO COMPLETO E CORRIGIDO PARA: app/main.py
# (Corrige a rota /api/auth/google para usar o Access Token
#  em vez de tentar validá-lo como um ID Token)

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
import requests # <-- IMPORTAÇÃO NECESSÁRIA

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
    print("[Main] LLMService inicializado.")
except Exception as e:
    print(f"[Main] ERRO: Falha ao inicializar LLMService: {e}")
    llm_service = None

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

# --- Dependências de Segurança (Refatoradas) ---
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
        expected_signature = "sha256=" + hash_obj.hexdigest()
        if not hmac.compare_digest(expected_signature, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.")
        return body
    except Exception as e:
        raise HTTPException(status_code=400, detail="Erro ao processar assinatura do webhook.")


# Palavras-chave que contam como uma confirmação do usuário
CONFIRMATION_WORDS = ["sim", "s", "yes", "y", "correto", "confirmo", "pode", "isso", "isso mesmo"]

# --- FUNÇÃO HELPER: Roteador de Intenção (ATUALIZADA) ---
async def _route_intent(
    intent: str, 
    args: Dict[str, Any], 
    user_id: str,
    user_email: str,
    last_user_prompt: str = ""
) -> Dict[str, Any]:
    
    if not conn or not q_ingest or not q_reports:
        return {"response_type": "error", "message": "Erro de servidor: O serviço de fila (Redis) está indisponível.", "job_id": None}

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
        # Passa o user_id (SEMPRE)
        job = q_ingest.enqueue(ingest_repo, user_id, repo, 20, 10, 15, job_timeout=1200) 
        return {"response_type": "job_enqueued", "message": f"Solicitação de ingestão para {repo} recebida...", "job_id": job.id}
    
    # CASO 3: Relatório (REPORT)
    elif intent == "call_report_tool":
        repo = args.get("repositorio"); prompt = args.get("prompt_usuario")
        # Passa o user_id
        job = q_reports.enqueue(processar_e_salvar_relatorio, user_id, repo, prompt, "html", job_timeout=1800) 
        return {"response_type": "job_enqueued", "message": f"Solicitação de relatório para {repo} recebida...", "job_id": job.id}
    
    # CASO 4: Agendamento (SCHEDULE)
    elif intent == "call_schedule_tool":
        print(f"[ChatRouter] Rota: SCHEDULE. Args: {args}")
        
        repo = args.get("repositorio")
        prompt = args.get("prompt_relatorio")
        freq = args.get("frequencia")
        hora = args.get("hora")
        tz = args.get("timezone")
        email_from_args = args.get("user_email")
        
        # Usa o email dos argumentos (se o usuário digitou) ou o email do usuário logado
        final_email = email_from_args or user_email 

        if not final_email: 
            return {"response_type": "clarification", "message": "Não consegui identificar seu email para o agendamento.", "job_id": None}

        # Envio imediato (agora)
        if freq == "once":
            print(f"[ChatRouter] Envio imediato (once) detectado. Enfileirando job de email para {final_email}.")
            job = q_reports.enqueue(
                'worker_tasks.enviar_relatorio_agendado', 
                agendamento_id=None,
                user_email=final_email,
                repo_name=repo,
                user_prompt=prompt,
                user_id=user_id, # Passa user_id
                job_timeout=1800
            )
            return {"response_type": "answer", "message": f"Ok! Estou preparando seu relatório para `{repo}` e o enviarei para `{final_email}` em breve.", "job_id": job.id}

        # Agendamento futuro (diário, semanal, etc.)
        else:
            confirmation_args = {
                "repositorio": repo, "prompt_relatorio": prompt,
                "frequencia": freq, "hora": hora, "timezone": tz,
                "user_email": final_email
            }
        
            if is_confirmation:
                print(f"[ChatRouter] Confirmação recebida. Criando agendamento para {final_email}.")
                msg = create_schedule(
                    user_id=user_id, # Passa user_id
                    user_email=final_email, repo=repo, prompt=prompt, 
                    freq=freq, hora=hora, tz=tz
                )
                return {"response_type": "answer", "message": msg, "job_id": None}
            else:
                print("[ChatRouter] Agendamento detectado. Solicitando confirmação.")
                if not llm_service:
                    return {"response_type": "error", "message": "Erro: LLMService não inicializado para confirmação."}
                
                confirmation_text = llm_service.summarize_action_for_confirmation(
                    intent_name="agendamento", 
                    args=confirmation_args
                )
                return {"response_type": "clarification", "message": confirmation_text, "job_id": None}
    
    # CASO 5: Salvar Instrução (SAVE_INSTRUCTION)
    elif intent == "call_save_instruction_tool":
        repo = args.get("repositorio"); instrucao = args.get("instrucao")
        # Passa user_id
        job = q_ingest.enqueue(save_instruction, user_id, repo, instrucao, job_timeout=300) 
        return {"response_type": "job_enqueued", "message": "Ok, estou salvando sua instrução...", "job_id": job.id}
    
    # CASO (NOVO): Bate-papo (CHAT)
    elif intent == "call_chat_tool":
        print("[ChatRouter] Rota: CHAT.")
        if not llm_service:
            return {"response_type": "answer", "message": "👍", "job_id": None}
        
        chat_response = llm_service.generate_simple_response(last_user_prompt)
        return {"response_type": "answer", "message": chat_response, "job_id": None}
        
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
    return {"status": "online", "version": "0.4.0", "redis_status": redis_status, "supabase_status": "conectado" if supabase_client else "desconectado"}

# --- ROTA DE LOGIN (CORRIGIDA) ---
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
        
        # 1. Usar o Access Token para chamar a API userinfo
        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        response = requests.get(userinfo_url, headers=headers)
        
        if response.status_code != 200:
            print(f"[Auth] Erro de verificação de token: {response.text}")
            raise ValueError(f"Token Google inválido (status {response.status_code}): {response.text}")

        id_info = response.json()
        
        # 2. Extrair dados do usuário
        email = id_info.get('email')
        google_id = id_info.get('sub') # 'sub' é o Google ID
        nome = id_info.get('name')

        if not email or not google_id:
            raise ValueError("Token do Google não retornou email ou ID.")

        # 3. Verificar se o usuário existe (pelo google_id)
        response = supabase_client.table("usuarios").select("*").eq("google_id", google_id).execute()
        
        if response.data:
            # 4a. Usuário existe, retorna a API key
            user = response.data[0]
            print(f"[Auth] Usuário existente logado: {email}")
            return {"api_key": user['api_key'], "email": user['email'], "nome": user['nome']}
        else:
            # 4b. Novo usuário, cria e retorna a API key
            print(f"[Auth] Novo usuário detectado: {email}")
            new_api_key = str(uuid.uuid4())
            
            insert_response = supabase_client.table("usuarios").insert(
                {
                    "google_id": google_id,
                    "email": email,
                    "nome": nome,
                    "api_key": new_api_key
                },
                returning="representation" # Pede ao Supabase para retornar o registro criado
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

# --- ROTA DE CHAT ---
@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat(request: ChatRequest, current_user: Dict[str, Any] = Depends(verificar_token)):
    if not llm_service or not conn: raise HTTPException(status_code=500, detail="Serviços de backend não inicializados.")
    
    user_id = current_user['id']
    user_email = current_user['email']
    
    history_lines = [f"{msg.sender.capitalize()}: {msg.text}" for msg in request.messages]
    full_prompt = "\n".join(history_lines)
    last_user_prompt = request.messages[-1].text if request.messages else ""
    
    if not full_prompt.strip(): raise HTTPException(status_code=400, detail="Prompt não pode ser vazio.")
    
    try: 
        intent_data = llm_service.get_intent(full_prompt)
        
        # Se for CLARIFY
        if intent_data.get("intent") == "CLARIFY":
            return {"response_type": "clarification", "message": intent_data.get("response_text", "Não entendi."), "job_id": None}
            
        # Se NÃO for multi-step (resposta simples de chat ou query)
        if not intent_data.get("multi_step"):
            intent = intent_data.get("intent")
            args = intent_data.get("args", {})
            
            # Se for chat, já temos a resposta
            if intent == "call_chat_tool":
                return {"response_type": "answer", "message": args.get("prompt"), "job_id": None}
            
            # Se for query (stream), também é uma etapa única
            if intent == "call_query_tool":
                 return {
                    "response_type": "stream_answer", 
                    "message": json.dumps({"repositorio": args.get("repositorio"), "prompt_usuario": args.get("prompt_usuario")}),
                    "job_id": None
                }
            
            # Se for qualquer outra coisa (ingestão única, relatório único), tratamos como uma cadeia de 1 etapa
            steps = [intent_data]
        else:
            steps = intent_data.get("steps", [])

        # --- LÓGICA DE ENCADEAMENTO DE JOBS (Multi-Step) ---
        print(f"[ChatRouter] Iniciando cadeia de {len(steps)} jobs...")
        
        last_job_id = None
        final_message = "Tarefas enfileiradas."
        
        for i, step in enumerate(steps):
            intent = step.get("intent")
            args = step.get("args", {})
            
            print(f"--- Enfileirando Etapa {i+1}/{len(steps)}: {intent} ---")
            print(f"Argumentos: {args}")
            print(f"Depende de: {last_job_id}")
            
            # Determina a fila correta (ingestão ou relatórios)
            target_queue = q_ingest if "ingest" in intent or "save_instruction" in intent else q_reports
            
            # Mapeia a intenção para a função real do worker
            if intent == "call_ingest_tool":
                func = ingest_repo
                params = [user_id, args.get("repositorio"), 20, 10, 15]
                final_message = f"Ingestão de {args.get('repositorio')} iniciada..."
            
            elif intent == "call_report_tool":
                func = processar_e_salvar_relatorio
                params = [user_id, args.get("repositorio"), args.get("prompt_usuario"), "html"]
                final_message = f"Relatório de {args.get('repositorio')} sendo gerado..."

            # (Adicione 'call_schedule_tool' e 'call_save_instruction_tool' aqui...)
            
            else:
                print(f"AVISO: Intenção {intent} não é uma tarefa de worker. Pulando.")
                continue

            # Enfileira o job, fazendo-o depender do job anterior
            job = target_queue.enqueue(
                func, 
                *params, 
                depends_on=last_job_id, 
                job_timeout=1800
            )
            last_job_id = job.id

        # Retorna o ID do ÚLTIMO job para o frontend fazer polling
        return {"response_type": "job_enqueued", "message": final_message, "job_id": last_job_id}
        
    except Exception as e:
        print(f"[ChatRouter] Erro CRÍTICO no /api/chat: {e}")
        return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}

# --- ROTA DE CHAT COM ARQUIVO --- apenas registrando o sucesso
@app.post("/api/chat_file", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat_with_file(
    prompt: str = Form(...), 
    messages_json: str = Form(...), 
    arquivo: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(verificar_token)
):
    if not llm_service or not conn: raise HTTPException(status_code=500, detail="Serviços de backend não inicializados.")
    
    user_id = current_user['id']
    user_email = current_user['email']
    
    try: 
        conteudo_bytes = await arquivo.read(); file_text = conteudo_bytes.decode("utf-8")
        if not file_text.strip(): raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")

        try:
            messages = json.loads(messages_json)
            history_text = "\n".join([f"{m['sender'].capitalize()}: {m['text']}" for m in messages])
        except json.JSONDecodeError:
            history_text = ""
        
        combined_prompt = f"{history_text}\nUser: {prompt}\n\nArquivo ({arquivo.filename}):\n\"{file_text}\""

        intent_data = llm_service.get_intent(combined_prompt)
        intent = intent_data.get("intent"); args = intent_data.get("args", {})
        
        print(f"--- [DEBUG /api/chat_file] (User: {user_id}) ---")
        print(f"Intenção detectada: {intent}")
        print(f"Argumentos extraídos: {args}")
        print(f"------------------------------")
        
        if intent == "CLARIFY": args["response_text"] = intent_data.get("response_text")
        
        return await _route_intent(intent, args, user_id, user_email, prompt)
    
    except Exception as e:
        print(f"[ChatRouter-File] Erro CRÍTICO no /api/chat_file: {e}")
        return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}

# --- ROTA DE STREAMING ---
@app.post("/api/chat_stream", dependencies=[Depends(verificar_token)])
async def handle_chat_stream(request: StreamRequest, current_user: Dict[str, Any] = Depends(verificar_token)):
    if not gerar_resposta_rag_stream:
        raise HTTPException(status_code=500, detail="Serviço RAG (streaming) não inicializado.")
        
    try:
        user_id = current_user['id']
        repo = request.repositorio; prompt = request.prompt_usuario
        # Chave de cache agora é específica do usuário
        cache_key = f"cache:query:user_{user_id}:{repo}:{hashlib.md5(prompt.encode()).hexdigest()}"
        
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
        
        # Passa o user_id para o RAG
        response_generator = gerar_resposta_rag_stream(user_id, prompt, repo)
        
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

# --- Endpoints de Suporte (Webhook, Verify, Status) ---
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
async def get_job_status(job_id: str, current_user: Dict[str, Any] = Depends(verificar_token)):
    if not q_ingest: raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    try: job = q_ingest.fetch_job(job_id)
    except Exception as e: raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None: return {"status": "not_found"}
    status = job.get_status(); result = None; error_info = None
    if status == 'finished': result = job.result
    elif status == 'failed': error_info = str(job.exc_info)
    return {"status": status, "result": result, "error": error_info}

@app.get("/api/relatorio/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_report_job_status(job_id: str, current_user: Dict[str, Any] = Depends(verificar_token)):
    if not q_reports: raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    try: job = q_reports.fetch_job(job_id)
    except Exception as e: raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None: return {"status": "not_found"}
    status = job.get_status(); result = None; error_info = None
    if status == 'finished': result = job.result
    elif status == 'failed': error_info = str(job.exc_info)
    return {"status": status, "result": result, "error": error_info}

@app.get("/api/relatorio/download/{filename}", dependencies=[Depends(verificar_token)])
async def download_report(filename: str, current_user: Dict[str, Any] = Depends(verificar_token)):
    SUPABASE_BUCKET_NAME = "reports"
    try:
        if not supabase_client: raise Exception("Cliente Supabase não inicializado")
        file_bytes = supabase_client.storage.from_(SUPABASE_BUCKET_NAME).download(filename)
        if not file_bytes: raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
        headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
        return StreamingResponse(io.BytesIO(file_bytes), media_type='text/html', headers=headers)
    except Exception as e:
        print(f"[API-DOWNLOAD] Erro ao baixar o arquivo: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar download: {repr(e)}")

@app.get("/api/schedules", response_model=List[Dict[str, Any]], dependencies=[Depends(verificar_token)])
async def get_schedules(current_user: Dict[str, Any] = Depends(verificar_token)):
    """
    Busca todos os agendamentos de relatórios ativos para o usuário logado.
    """
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Serviço de DB não inicializado.")
    
    user_id = current_user['id']
    print(f"[API] Buscando agendamentos para User: {user_id}")
    
    try:
        response = supabase_client.table("agendamentos") \
            .select("id, repositorio, prompt_relatorio, frequencia, hora_utc, timezone, ultimo_envio") \
            .eq("user_id", user_id) \
            .eq("ativo", True) \
            .order("repositorio", desc=False) \
            .execute()
        
        return response.data
    
    except Exception as e:
        print(f"[API] Erro ao buscar agendamentos: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao buscar agendamentos: {e}")

@app.delete("/api/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verificar_token)])
async def delete_schedule(schedule_id: str, current_user: Dict[str, Any] = Depends(verificar_token)):
    """
    Deleta (desativa) um agendamento de relatório.
    """
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Serviço de DB não inicializado.")
        
    user_id = current_user['id']
    print(f"[API] Deletando agendamento {schedule_id} para User: {user_id}")

    try:
        # Importante: Deletamos apenas se o 'user_id' bater,
        # para que um usuário não possa deletar o agendamento de outro.
        response = supabase_client.table("agendamentos") \
            .delete() \
            .eq("id", schedule_id) \
            .eq("user_id", user_id) \
            .execute()
            
        if not response.data:
            # Isso acontece se o ID não existe OU se o user_id não bateu
            print(f"[API] Falha ao deletar: Agendamento {schedule_id} não encontrado ou não pertence ao usuário {user_id}.")
            raise HTTPException(status_code=404, detail="Agendamento não encontrado ou não autorizado.")
        
        print(f"[API] Agendamento {schedule_id} deletado com sucesso.")
        return
    
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        print(f"[API] Erro ao deletar agendamento: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao deletar agendamento: {e}")

# Ponto de entrada (corpo completo)
if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor Uvicorn local em http://0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)