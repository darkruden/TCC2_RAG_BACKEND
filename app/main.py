# CÓDIGO COMPLETO E CORRIGIDO PARA: app/main.py
# (Implementa o Agente de Encadeamento de Tarefas com Confirmação no Loop)

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends, HTTPException, status, Header, Form, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
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
import uuid  # Para gerar a API key
import requests  # <-- Importação necessária para o login

# --- Serviços ---
from app.services.rag_service import gerar_resposta_rag, gerar_resposta_rag_stream
from app.services.llm_service import LLMService
from app.services.scheduler_service import create_schedule, verify_email_token
from worker_tasks import (
    ingest_repo,
    save_instruction,
    processar_e_salvar_relatorio,
    enviar_relatorio_agendado,
    process_webhook_payload,
)


# --- Configuração ---
try:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    conn = redis.from_url(redis_url)
    conn.ping()
    print(f"[Main] Conexão com Redis estabelecida em {redis_url}.")
except Exception as e:
    print(f"[Main] ERRO CRÍTICO: Não foi possível conectar ao Redis em {redis_url}. {e}")
    conn = None

QUEUE_PREFIX = os.getenv("RQ_QUEUE_PREFIX", "")
if QUEUE_PREFIX:
    print(f"[Main] Usando prefixo de fila: '{QUEUE_PREFIX}'")

if conn:
    q_ingest = Queue(f"{QUEUE_PREFIX}ingest", connection=conn)
    q_reports = Queue(f"{QUEUE_PREFIX}reports", connection=conn)
else:
    q_ingest = None
    q_reports = None

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

# --- Inicialização de Serviços ---
try:
    llm_service = LLMService()
    print("[Main] LLMService (para roteamento) inicializado.")
except Exception as e:
    print(f"[Main] ERRO: Falha ao inicializar LLMService: {e}")
    llm_service = None

# --- NOVO: Configuração de Auth ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

# --- App FastAPI ---
app = FastAPI(
    title="GitRAG API (v2 - Plataforma de Chat e Relatórios)",
    description=(
        "API unificada da plataforma GitRAG para análise, rastreabilidade de requisitos "
        "e relatórios (imediatos e agendados) baseados em repositórios GitHub."
    ),
    version="0.4.0",
)

# --- INÍCIO DA CORREÇÃO DE CORS ---
# Substituímos o ["*"] por uma lista explícita de origens.
# O wildcard "*" é incompatível com allow_credentials=True.
ALLOWED_ORIGINS = [
    "chrome-extension://ajiinnakfafbdkfmodpbmdlbegjmehfh", # ID da sua extensão 
    "http://localhost:3000", # Para desenvolvimento local do frontend
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS, # <-- ALTERADO AQUI
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- FIM DA CORREÇÃO DE CORS ---

# --- Modelos Pydantic ---
class Message(BaseModel):
    sender: str = "assistant" 
    text: str = ""

    # Configuração Pydantic V2 para ignorar campos extras (job_id, response_type, etc.)
    model_config = { "extra": "ignore" }

    # Validador "Before" (roda ANTES do Pydantic tentar checar os tipos)
    @model_validator(mode='before')
    @classmethod
    def normalizar_dados(cls, data: Any) -> Any:
        # Se data não for um dicionário, retorna como está (vai falhar na validação padrão)
        if not isinstance(data, dict):
            return data
            
        # 1. Mapeia 'message' (resposta antiga) para 'text' (campo esperado)
        if 'text' not in data and 'message' in data:
            data['text'] = data['message']
            
        # 2. Define 'assistant' se o sender estiver ausente
        if 'sender' not in data:
            data['sender'] = 'assistant'
            
        # 3. Converte None/Null para string vazia para não quebrar
        if data.get('text') is None:
            data['text'] = ""
            
        return data


class ChatRequest(BaseModel):
    messages: List[Message]

# Modelo para atualização de agendamento
class ScheduleUpdate(BaseModel):
    titulo: Optional[str] = None
    prompt_relatorio: Optional[str] = None
    frequencia: Optional[str] = None
    ativo: Optional[bool] = None

class GoogleLoginRequest(BaseModel):
    credential: str  # O Access Token vindo do chrome.identity


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


# --- Dependências de Segurança ---
async def verificar_token(x_api_key: str = Header(...)) -> Dict[str, Any]:
    """
    Verifica se a X-API-Key existe na tabela 'usuarios' e retorna
    o registro do usuário autenticado.
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


async def verify_github_signature(
    request: Request, x_hub_signature_256: str = Header(...)
):
    """
    Verifica a assinatura HMAC do webhook do GitHub usando SHA-256.
    O cabeçalho esperado é: X-Hub-Signature-256: sha256=<hex>
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="O servidor não está configurado para webhooks (GITHUB_WEBHOOK_SECRET ausente).",
        )
    try:
        body = await request.body()
        hash_obj = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
        expected_signature = "sha256=" + hash_obj.hexdigest()

        if not hmac.compare_digest(expected_signature, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.")
        return body
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Webhook] Erro ao processar assinatura: {e}")
        raise HTTPException(status_code=400, detail="Erro ao processar assinatura do webhook.")


# Palavras-chave que contam como uma confirmação do usuário
CONFIRMATION_WORDS = ["sim", "s", "yes", "y", "correto", "confirmo", "pode", "isso", "isso mesmo"]


# --- FUNÇÃO HELPER: Roteador de Intenção (Multi-Step) ---
async def _route_intent(
    intent_data: Dict[str, Any], 
    user_id: str,
    user_email: str,
    last_user_prompt: str = "",
    file_content: str = None # <-- NOVO PARÂMETRO
) -> Dict[str, Any]:
    """
    Converte a saída do LLM em chamadas concretas.
    Agora suporta injeção direta de conteúdo de arquivo para evitar resumos indesejados.
    """
    # Verifica serviços globais
    if not conn or not q_ingest or not q_reports or not llm_service:
        return {
            "response_type": "error",
            "message": "Erro de servidor: Serviços indisponíveis.",
            "job_id": None,
        }

    if intent_data["type"] == "clarify":
        return {"response_type": "clarification", "message": intent_data.get("response_text", "Não entendi."), "job_id": None}

    if intent_data["type"] == "simple_chat":
        simple_response = llm_service.generate_simple_response(intent_data.get("response_text", last_user_prompt))
        return {"response_type": "answer", "message": simple_response, "job_id": None}

    steps = intent_data.get("steps", [])
    print(f"[TRACER] Processando {len(steps)} intenções para User {user_id}...")

    last_job_id: Optional[str] = None
    final_message = "Tarefas enfileiradas."
    job_messages = {}

    for i, step in enumerate(steps):
        intent = step.get("intent")
        args = step.get("args", {}) or {}
        repo = args.get("repositorio")

        # --- Lógica de Contexto Implícito (Repo) ---
        intents_needing_repo = [
            "call_query_tool", "call_report_tool", "call_ingest_tool", 
            "call_schedule_tool", "call_save_instruction_tool", "call_send_onetime_report_tool"
        ]
        
        if intent in intents_needing_repo and not repo:
            # ... (Lógica de buscar last_ingested_repo no Supabase mantida igual) ...
            # Para economizar espaço na resposta, assumo que você manteve o trecho de busca do user_data aqui
            try:
                user_data = supabase_client.table("usuarios").select("last_ingested_repo").eq("id", user_id).execute()
                if user_data.data and user_data.data[0].get("last_ingested_repo"):
                    repo = user_data.data[0]["last_ingested_repo"]
                    args["repositorio"] = repo
            except: pass

        # --- INJEÇÃO DE CONTEÚDO DE ARQUIVO (A CORREÇÃO) ---
        # Se temos um arquivo e a intenção usa 'prompt_relatorio', injetamos o conteúdo bruto.
        if file_content and "prompt_relatorio" in args:
            print(f"[TRACER] Injetando conteúdo do arquivo no prompt da intenção {intent}.")
            prompt_atual = args.get("prompt_relatorio", "")
            # Adiciona o conteúdo do arquivo ao final do prompt
            args["prompt_relatorio"] = f"{prompt_atual}\n\n--- CONTEÚDO DO ARQUIVO DE INSTRUÇÕES ---\n{file_content}"

        # Se a intenção for 'report' (download), o campo costuma ser 'prompt_usuario'
        if file_content and intent == "call_report_tool" and "prompt_usuario" in args:
             print(f"[TRACER] Injetando conteúdo do arquivo no prompt de relatório.")
             prompt_atual = args.get("prompt_usuario", "")
             args["prompt_usuario"] = f"{prompt_atual}\n\n--- CONTEÚDO DO ARQUIVO DE INSTRUÇÕES ---\n{file_content}"


        # ... Execução das ferramentas ...
        func = None
        params = []
        target_queue = None

        if intent == "call_query_tool":
             # Se for Query, retornamos para o frontend iniciar o stream
             if i == len(steps) - 1:
                
                # --- CORREÇÃO: Injeção de Arquivo para Análise de Código ---
                prompt_final = args.get("prompt_usuario")
                if file_content:
                    # Anexa o código/texto bruto para garantir que nada se perca no resumo
                    prompt_final = f"{prompt_final}\n\n--- ARQUIVO ANEXADO ---\n{file_content}"
                # -----------------------------------------------------------

                payload = {
                    "repositorio": repo,
                    "prompt_usuario": prompt_final, # Usa o prompt turbinado
                }
                return {
                    "response_type": "stream_answer",
                    "message": json.dumps(payload),
                    "job_id": None,
                }
             continue

        elif intent == "call_ingest_tool":
            func = ingest_repo
            params = [user_id, repo, 1000, 20, 30]
            target_queue = q_ingest
            final_message = f"Solicitação de ingestão para {repo} recebida."

        elif intent == "call_send_onetime_report_tool":
            print(f"[TRACER] Roteando {intent} para envio imediato.")
            email_destino = args.get("email_destino") or user_email
            func = enviar_relatorio_agendado
            # Note que agora 'args["prompt_relatorio"]' já contém o arquivo anexado
            params = [None, email_destino, repo, args.get("prompt_relatorio"), user_id]
            target_queue = q_reports
            final_message = f"Iniciando envio de relatório para {email_destino}."

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

        elif intent == "call_schedule_tool":
            freq = args.get("frequencia")
            email_to_use = args.get("user_email") or user_email
            hora = args.get("hora")
            tz = args.get("timezone")
            data_inicio = args.get("data_inicio")
            data_fim = args.get("data_fim")
            
            # args["prompt_relatorio"] aqui já está turbinado com o arquivo
            
            if not repo or not args.get("prompt_relatorio") or not freq:
                 return { "response_type": "clarification", "message": "Dados incompletos para agendamento.", "job_id": None }

            if freq == "once":
                func = enviar_relatorio_agendado
                params = [None, email_to_use, repo, args.get("prompt_relatorio"), user_id]
                target_queue = q_reports
                final_message = f"Relatório agendado para envio imediato."
            else:
                if not hora or not tz:
                     return { "response_type": "clarification", "message": "Preciso da hora e timezone para agendar.", "job_id": None }
                
                msg = create_schedule(
                    user_id, email_to_use, repo, args["prompt_relatorio"], 
                    freq, hora, tz, data_inicio, data_fim
                )
                final_message = msg
                continue 

        if func and target_queue:
            job = target_queue.enqueue(func, *params, depends_on=last_job_id if last_job_id else None, job_timeout=1800)
            last_job_id = job.id
            job_messages[last_job_id] = final_message
    
    if last_job_id:
        return { "response_type": "job_enqueued", "message": job_messages.get(last_job_id, "Tarefas enfileiradas."), "job_id": last_job_id }
    
    return { "response_type": "answer", "message": final_message, "job_id": None }


# --- Rotas da API (v2) ---

@app.get("/health")
async def health_check():
    redis_status = "desconectado"
    if conn:
        try:
            conn.ping()
            redis_status = "conectado"
        except Exception as e:
            redis_status = f"erro ({e})"
    return {
        "status": "online",
        "version": "0.4.0",
        "redis_status": redis_status,
        "supabase_status": "conectado" if supabase_client else "desconectado",
    }


@app.post("/api/auth/google", response_model=AuthResponse)
async def google_login(request: GoogleLoginRequest):
    """
    Endpoint de login com Google.

    Aceita tanto:
    - Access Token (flow via chrome.identity / OAuth2) → usa /userinfo
    - ID Token (JWT) → usa /tokeninfo e valida audiência (aud == GOOGLE_CLIENT_ID)

    Cria ou recupera o usuário na tabela 'usuarios' do Supabase
    e retorna a API key pessoal.
    """
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Serviço de DB não inicializado.")

    google_client_id = GOOGLE_CLIENT_ID
    if not google_client_id:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_CLIENT_ID não configurado no servidor."
        )

    raw_token = request.credential
    if not raw_token:
        raise HTTPException(status_code=400, detail="Token do Google não enviado.")

    try:
        # 1ª TENTATIVA: tratar como ACCESS TOKEN (Bearer) usando /userinfo
        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {"Authorization": f"Bearer {raw_token}"}
        resp = requests.get(userinfo_url, headers=headers)

        id_info = None

        if resp.status_code == 200:
            # Deu certo como access token
            id_info = resp.json()
            google_id = id_info.get("sub")
            email = id_info.get("email")
            nome = id_info.get("name") or email
            # Para access token normalmente não há 'aud', então não dá para validar client_id aqui.
            print("[Auth] Login Google via access_token (/userinfo)")
        else:
            # 2ª TENTATIVA: tratar como ID TOKEN (JWT) usando /tokeninfo
            tokeninfo_url = "https://oauth2.googleapis.com/tokeninfo"
            resp2 = requests.get(tokeninfo_url, params={"id_token": raw_token})

            if resp2.status_code != 200:
                print(f"[Auth] Erro de verificação de token (userinfo e tokeninfo falharam): {resp.text} / {resp2.text}")
                raise ValueError(
                    f"Token Google inválido (userinfo={resp.status_code}, tokeninfo={resp2.status_code})."
                )

            id_info = resp2.json()
            print("[Auth] Login Google via id_token (/tokeninfo)")

            # Campos típicos em tokeninfo
            google_id = id_info.get("sub")
            email = id_info.get("email")
            nome = id_info.get("name") or email
            aud = id_info.get("aud")

            # Valida se o token foi realmente emitido para o nosso client_id
            if aud != google_client_id:
                print(f"[Auth] AUDIENCE mismatch. Esperado: {google_client_id}, recebido: {aud}")
                raise ValueError("ID Token não foi emitido para este client_id (audience inválida).")

        if not email or not google_id:
            raise ValueError("Token do Google não retornou email ou ID.")

        # 3. Busca usuário no Supabase pela google_id
        resp_db = (
            supabase_client
            .table("usuarios")
            .select("*")
            .eq("google_id", google_id)
            .execute()
        )

        if resp_db.data:
            user = resp_db.data[0]
            print(f"[Auth] Usuário existente logado: {email}")
            return {
                "api_key": user["api_key"],
                "email": user["email"],
                "nome": user["nome"],
            }

        # 4. Se não existir, cria um novo usuário
        print(f"[Auth] Novo usuário detectado: {email}")
        new_api_key = str(uuid.uuid4())

        insert_resp = (
            supabase_client
            .table("usuarios")
            .insert(
                {
                    "google_id": google_id,
                    "email": email,
                    "nome": nome,
                    "api_key": new_api_key,
                },
                returning="representation",
            )
            .execute()
        )

        if not insert_resp.data:
            raise Exception("Falha ao inserir novo usuário no Supabase.")

        user = insert_resp.data[0]
        return {
            "api_key": user["api_key"],
            "email": user["email"],
            "nome": user["nome"],
        }

    except ValueError as e:
        print(f"[Auth] Erro de verificação de token: {e}")
        raise HTTPException(status_code=401, detail=f"Token Google inválido: {e}")
    except Exception as e:
        print(f"[Auth] Erro crítico no login: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno no servidor: {e}")

@app.patch(
    "/api/schedules/{schedule_id}",
    response_model=Dict[str, Any],
    dependencies=[Depends(verificar_token)],
)
async def update_schedule(
    schedule_id: str, 
    update_data: ScheduleUpdate, 
    current_user: Dict[str, Any] = Depends(verificar_token)
):
    """
    Atualiza campos de um agendamento (Título, Prompt, Frequência, Status).
    """
    if not supabase_client:
        raise HTTPException(status_code=500, detail="DB não inicializado.")

    user_id = current_user["id"]
    
    # Filtra apenas os campos que foram enviados (não nulos)
    campos_para_atualizar = {k: v for k, v in update_data.model_dump().items() if v is not None}
    
    if not campos_para_atualizar:
        raise HTTPException(status_code=400, detail="Nenhum dado para atualizar.")

    try:
        print(f"[API] Atualizando agendamento {schedule_id} para User {user_id}: {campos_para_atualizar}")
        
        response = (
            supabase_client.table("agendamentos")
            .update(campos_para_atualizar)
            .eq("id", schedule_id)
            .eq("user_id", user_id)
            .execute()
        )

        if not response.data:
             raise HTTPException(status_code=404, detail="Agendamento não encontrado ou não autorizado.")
             
        return response.data[0]

    except Exception as e:
        print(f"[API] Erro ao atualizar: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- ROTA DE CHAT ---
@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat(
    request: ChatRequest, current_user: Dict[str, Any] = Depends(verificar_token)
):
    if not llm_service or not conn:
        raise HTTPException(status_code=500, detail="Serviços de backend não inicializados.")

    user_id = current_user["id"]
    user_email = current_user["email"]

    # Formata o histórico de forma mais explícita para o roteador de intenção
    history_lines: List[str] = []
    for msg in request.messages:
        # --- PROTEÇÃO CONTRA MENSAGENS VAZIAS ---
        conteudo_texto = msg.text or "" # Garante que não seja None
        if not conteudo_texto.strip(): 
            continue # Pula mensagens sem texto (ex: mensagens de status do sistema)
            
        sender_norm = msg.sender.lower()
        if sender_norm in ("user", "usuário", "usuario"):
            role_label = "Usuário"
        elif sender_norm in ("assistant", "bot", "gitrag"):
            role_label = "Assistente"
        else:
            role_label = msg.sender.capitalize()

        history_lines.append(f"{role_label}: {conteudo_texto}") # Usa a variável protegida

    full_prompt = (
        "Histórico da conversa entre Usuário e Assistente GitRAG (mensagens mais recentes ao final):\n"
        + "\n".join(history_lines)
    )

    last_user_prompt = request.messages[-1].text if request.messages else ""

    if not full_prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt não pode ser vazio.")

    try:
        intent_data = llm_service.get_intent(full_prompt)

        print(f"--- [DEBUG /api/chat] (User: {user_id}) ---")
        print(f"Intenção detectada: {intent_data.get('type')}")

        return await _route_intent(intent_data, user_id, user_email, last_user_prompt, file_content=None)

    except Exception as e:
        print(f"[ChatRouter] Erro CRÍTICO no /api/chat: {e}")
        return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}


# --- ROTA DE CHAT COM ARQUIVO ---
@app.post("/api/chat_file", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat_with_file(
    prompt: str = Form(...),
    messages_json: str = Form(...),
    arquivo: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(verificar_token),
):
    if not llm_service or not conn:
        raise HTTPException(status_code=500, detail="Serviços de backend não inicializados.")

    user_id = current_user["id"]
    user_email = current_user["email"]

    try:
        conteudo_bytes = await arquivo.read()
        file_text = conteudo_bytes.decode("utf-8")

        if not file_text.strip():
            raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")

        try:
            messages = json.loads(messages_json)
            history_text_lines = []
            for m in messages:
                sender_norm = m["sender"].lower()
                if sender_norm in ("user", "usuário", "usuario"):
                    role_label = "Usuário"
                elif sender_norm in ("assistant", "bot", "gitrag"):
                    role_label = "Assistente"
                else:
                    role_label = m["sender"].capitalize()
                history_text_lines.append(f"{role_label}: {m['text']}")
            history_text = "\n".join(history_text_lines)
        except json.JSONDecodeError:
            history_text = ""

        combined_prompt = (
            "Histórico da conversa entre Usuário e Assistente GitRAG (mensagens mais recentes ao final):\n"
            f"{history_text}\n\n"
            f"Última mensagem do Usuário: {prompt}\n\n"
            f"Conteúdo do arquivo anexado '{arquivo.filename}':\n{file_text}"
        )

        intent_data = llm_service.get_intent(combined_prompt)

        print(f"--- [DEBUG /api/chat_file] (User: {user_id}) ---")
        print(f"Intenção detectada: {intent_data.get('type')}")

        return await _route_intent(intent_data, user_id, user_email, prompt, file_content=file_text)

    except Exception as e:
        print(f"[ChatRouter-File] Erro CRÍTICO no /api/chat_file: {e}")
        return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}


# --- ROTA DE STREAMING ---
@app.post("/api/chat_stream", dependencies=[Depends(verificar_token)])
async def handle_chat_stream(
    request: StreamRequest, current_user: Dict[str, Any] = Depends(verificar_token)
):
    if not gerar_resposta_rag_stream:
        raise HTTPException(status_code=500, detail="Serviço RAG (streaming) não inicializado.")

    try:
        user_id = current_user["id"]
        repo = request.repositorio
        prompt = request.prompt_usuario

        # Chave de cache agora é específica do usuário
        cache_key = f"cache:query:user_{user_id}:{repo}:{hashlib.md5(prompt.encode()).hexdigest()}"
        
        # --- COMENTE ESTE BLOCO PARA DESATIVAR O CACHE ---
        # if conn:
        #     try:
        #         cached_result = conn.get(cache_key)
        #         if cached_result:
        #             print(f"[Cache-Stream] HIT! Retornando stream de cache para {cache_key}")
        #             async def cached_stream():
        #                 yield json.loads(cached_result)["message"]
        #             return StreamingResponse(cached_stream(), media_type="text/plain")
        #     except Exception as e:
        #         print(f"[Cache-Stream] ERRO no Redis (GET): {e}")
        # -------------------------------------------------

        response_generator = gerar_resposta_rag_stream(user_id, prompt, repo)

        full_response_chunks: List[str] = []

        async def caching_stream_generator():
            try:
                for chunk in response_generator:
                    full_response_chunks.append(chunk)
                    yield chunk

                full_response_text = "".join(full_response_chunks)
                if conn:
                    response_data = {
                        "response_type": "answer",
                        "message": full_response_text,
                        "job_id": None,
                        "fontes": [
                            {
                                "tipo": "repositório",
                                "id": "contexto",
                                "url": f"https://github.com/{repo}",
                            }
                        ],
                        "contexto": {"trechos": "Contexto buscado via stream."},
                    }
                    try:
                        conn.set(cache_key, json.dumps(response_data), ex=3600)
                        print(f"[Cache-Stream] SET! Resposta salva em {cache_key}")
                    except Exception as e:
                        print(f"[Cache-Stream] ERRO no Redis (SET): {e}")

            except Exception as e:
                print(f"[Stream] Erro durante a geração do stream: {e}")
                yield f"\n\n**Erro no servidor durante o stream:** {e}"

        return StreamingResponse(caching_stream_generator(), media_type="text/plain")

    except Exception as e:
        print(f"[ChatStream] Erro CRÍTICO no /api/chat_stream: {e}")
        return StreamingResponse((f"Erro: {e}"), media_type="text/plain")


# --- Endpoints de Suporte (Webhook, Verify, Status) ---

@app.post("/api/webhook/github")
async def handle_github_webhook(
    request: Request,
    x_github_event: str = Header(...),
    payload_bytes: bytes = Depends(verify_github_signature),
):
    if not q_ingest:
        raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload do webhook mal formatado.")

    print(f"[Webhook] Recebido evento '{x_github_event}' validado.")

    if x_github_event in ["push", "issues", "pull_request"]:
        try:
            job = q_ingest.enqueue(
                "worker_tasks.process_webhook_payload", x_github_event, payload, job_timeout=600
            )
            print(f"[Webhook] Evento '{x_github_event}' enfileirado. Job ID: {job.id}")
        except Exception as e:
            print(f"[Webhook] ERRO ao enfileirar job: {e}")
            raise HTTPException(status_code=500, detail="Erro ao enfileirar tarefa do webhook.")
        return {
            "status": "success",
            "message": f"Evento '{x_github_event}' recebido e enfileirado.",
        }
    else:
        return {
            "status": "ignored",
            "message": f"Evento '{x_github_event}' não é processado.",
        }


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
        print(f"[VerifyEmail] Erro: {e}")
        return HTMLResponse(
            content="<h1>Erro 500</h1><p>Ocorreu um erro no servidor.</p>", status_code=500
        )


@app.get("/api/ingest/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_job_status(job_id: str, current_user: Dict[str, Any] = Depends(verificar_token)):
    if not q_ingest:
        raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    try:
        job = q_ingest.fetch_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None:
        return {"status": "not_found"}
    status_job = job.get_status()
    result = None
    error_info = None
    if status_job == "finished":
        result = job.result
    elif status_job == "failed":
        error_info = str(job.exc_info)
    return {"status": status_job, "result": result, "error": error_info}


@app.get("/api/relatorio/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_report_job_status(
    job_id: str, current_user: Dict[str, Any] = Depends(verificar_token)
):
    if not q_reports:
        raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    try:
        job = q_reports.fetch_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None:
        return {"status": "not_found"}
    status_job = job.get_status()
    result = None
    error_info = None
    if status_job == "finished":
        result = job.result
    elif status_job == "failed":
        error_info = str(job.exc_info)
    return {"status": status_job, "result": result, "error": error_info}


@app.get("/api/relatorio/download/{filename}", dependencies=[Depends(verificar_token)])
async def download_report(
    filename: str, current_user: Dict[str, Any] = Depends(verificar_token)
):
    SUPABASE_BUCKET_NAME = "reports"
    try:
        if not supabase_client:
            raise Exception("Cliente Supabase não inicializado")
        file_bytes = supabase_client.storage.from_(SUPABASE_BUCKET_NAME).download(filename)
        if not file_bytes:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        return StreamingResponse(
            io.BytesIO(file_bytes), media_type="text/html", headers=headers
        )
    except Exception as e:
        print(f"[API-DOWNLOAD] Erro ao baixar o arquivo: {repr(e)}")
        raise HTTPException(
            status_code=500, detail=f"Erro ao processar download: {repr(e)}"
        )


@app.get("/api/schedules", response_model=List[Dict[str, Any]], dependencies=[Depends(verificar_token)])
async def get_schedules(current_user: Dict[str, Any] = Depends(verificar_token)):
    """
    Busca todos os agendamentos de relatórios ativos para o usuário logado.
    """
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Serviço de DB não inicializado.")

    user_id = current_user["id"]
    print(f"[API] Buscando agendamentos para User: {user_id}")

    try:
        response = (
            supabase_client.table("agendamentos")
            .select(
                "id, repositorio, prompt_relatorio, frequencia, hora_utc, timezone, ultimo_envio, titulo, ativo" # <-- Adicionado titulo e ativo
            )
            .eq("user_id", user_id)
            .eq("ativo", True)
            .order("repositorio", desc=False)
            .execute()
        )

        return response.data

    except Exception as e:
        print(f"[API] Erro ao buscar agendamentos: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao buscar agendamentos: {e}")


@app.delete(
    "/api/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_token)],
)
async def delete_schedule(
    schedule_id: str, current_user: Dict[str, Any] = Depends(verificar_token)
):
    """
    Deleta (desativa) um agendamento de relatório pertencente ao usuário logado.
    """
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Serviço de DB não inicializado.")

    user_id = current_user["id"]
    print(f"[API] Deletando agendamento {schedule_id} para User: {user_id}")

    try:
        response = (
            supabase_client.table("agendamentos")
            .delete()
            .eq("id", schedule_id)
            .eq("user_id", user_id)
            .execute()
        )

        if not response.data:
            print(
                f"[API] Falha ao deletar: Agendamento {schedule_id} não encontrado ou não pertence ao usuário {user_id}."
            )
            raise HTTPException(
                status_code=404, detail="Agendamento não encontrado ou não autorizado."
            )

        print(f"[API] Agendamento {schedule_id} deletado com sucesso.")
        return

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        print(f"[API] Erro ao deletar agendamento: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao deletar agendamento: {e}")


# Ponto de entrada (execução local)
if __name__ == "__main__":
    import uvicorn

    print("Iniciando servidor Uvicorn local em http://0.0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)