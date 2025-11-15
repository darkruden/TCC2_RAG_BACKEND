# CÓDIGO COMPLETO PARA: app/main.py
# (Implementa Caching com Redis no endpoint /api/chat)

from dotenv import load_dotenv
load_dotenv()
from app.services.report_service import processar_e_salvar_relatorio
from fastapi import FastAPI, Depends, HTTPException, status, Header, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import redis
from rq import Queue
import io
from fastapi.responses import StreamingResponse
from supabase import create_client

# --- Serviços do Marco 1 ---
from app.services.ingest_service import ingest_repo
from app.services.rag_service import gerar_resposta_rag
# --- Serviços Antigos (Ainda usados) ---
from app.services.llm_service import LLMService

# --- NOVAS IMPORTAÇÕES PARA O CACHE ---
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

# Filas (só inicializa se o Redis conectar)
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
    title="GitHub RAG API (v2 - Chat)",
    description="API unificada para análise e rastreabilidade de repositórios",
    version="0.2.0"
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
    """ O que o frontend envia para /api/chat """
    prompt: str

class ChatResponse(BaseModel):
    """ O que o backend envia de volta """
    response_type: str # 'answer', 'job_enqueued', 'clarification', 'error'
    message: str
    job_id: Optional[str] = None
    fontes: Optional[List[Dict[str, Any]]] = None
    contexto: Optional[Dict[str, Any]] = None

# --- Dependência de Segurança (Token) ---
async def verificar_token(x_api_key: str = Header(...)):
    """Verifica se o X-API-Key corresponde ao token de ambiente."""
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
    """Verifica o status da API e serviços dependentes (Redis)."""
    redis_status = "desconectado"
    if conn:
        try:
            conn.ping()
            redis_status = "conectado"
        except Exception as e:
            redis_status = f"erro ({e})"
            
    return {
        "status": "online", 
        "version": "0.2.0",
        "redis_status": redis_status
    }

# --- O "CÉREBRO": Endpoint /api/chat (AGORA COM CACHE) ---
@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verificar_token)])
async def handle_chat(request: ChatRequest):
    """
    Endpoint unificado que roteia a intenção do usuário.
    """
    
    # --- Verificação de Serviços ---
    if not llm_service:
        raise HTTPException(status_code=500, detail="Serviço de LLM não inicializado no servidor.")
    if not q_ingest or not q_reports or not conn:
        raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado no servidor.")

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
            
            # --- INÍCIO DA LÓGICA DE CACHE ---
            # Cria uma chave única para esta consulta
            cache_key = f"cache:query:{repo}:{hashlib.md5(prompt.encode()).hexdigest()}"
            
            try:
                cached_result = conn.get(cache_key)
                if cached_result:
                    print(f"[Cache] HIT! Retornando resultado de {cache_key}")
                    # Deserializa o JSON salvo e retorna
                    return json.loads(cached_result)
            except Exception as e:
                print(f"[Cache] ERRO no Redis (GET): {e}")
                # Continua sem cache se o Redis falhar
            
            print(f"[Cache] MISS! Executando RAG para {cache_key}")
            # --- FIM DA LÓGICA DE CACHE ---

            # Chama o RAG Service (do Marco 1)
            resultado_rag = gerar_resposta_rag(prompt, repo)
            
            # Prepara a resposta
            response_data = {
                "response_type": "answer",
                "message": resultado_rag["texto"],
                "job_id": None,
                "fontes": [
                    {
                        "tipo": "repositório",
                        "id": "contexto",
                        "url": f"https://github.com/{repo}"
                    }
                ],
                "contexto": {"trechos": resultado_rag["contexto"]}
            }
            
            # --- INÍCIO DA LÓGICA DE CACHE (SALVAR) ---
            try:
                # Salva a resposta no Redis por 1 hora (3600 segundos)
                conn.set(cache_key, json.dumps(response_data), ex=3600)
                print(f"[Cache] SET! Resultado salvo em {cache_key}")
            except Exception as e:
                print(f"[Cache] ERRO no Redis (SET): {e}")
            # --- FIM DA LÓGICA DE CACHE (SALVAR) ---
            
            return response_data

        # CASO 2: Ingestão (INGEST)
        elif intent == "call_ingest_tool":
            print(f"[ChatRouter] Rota: INGEST. Args: {args}")
            repo = args.get("repositorio")

            job = q_ingest.enqueue(
                ingest_repo, 
                repo, 
                20, 10, 15, # (Limites padrão)
                job_timeout=1200
            )
            msg = f"Solicitação de ingestão para {repo} recebida e enfileirada."
            return {
                "response_type": "job_enqueued",
                "message": msg,
                "job_id": job.id
            }

        # CASO 3: Relatório (REPORT)
        elif intent == "call_report_tool":
            print(f"[ChatRouter] Rota: REPORT. Args: {args}")
            repo = args.get("repositorio")
            prompt = args.get("prompt_usuario")

            job = q_reports.enqueue(
                processar_e_salvar_relatorio, 
                repo, 
                prompt,
                "html",
                job_timeout=1800
            )
            msg = f"Solicitação de relatório para {repo} recebida e enfileirada."
            return {
                "response_type": "job_enqueued",
                "message": msg,
                "job_id": job.id
            }

        # CASO 4: Agendamento (SCHEDULE) - (Marco 5)
        elif intent == "call_schedule_tool":
            print(f"[ChatRouter] Rota: SCHEDULE (Não implementado).")
            return {
                "response_type": "clarification",
                "message": "Desculpe, a função de agendamento de relatórios ainda está em desenvolvimento.",
                "job_id": None
            }

        # CASO 5: Clarificação (CLARIFY)
        elif intent == "CLARIFY":
            print(f"[ChatRouter] Rota: CLARIFY. Msg: {intent_data.get('response_text')}")
            return {
                "response_type": "clarification",
                "message": intent_data.get("response_text", "Não entendi. Pode reformular?"),
                "job_id": None
            }
        
        # CASO 6: Erro desconhecido
        else:
            raise Exception(f"Intenção desconhecida recebida da LLM: {intent}")

    except Exception as e:
        print(f"[ChatRouter] Erro CRÍTICO no /api/chat: {e}")
        return {
            "response_type": "error",
            "message": f"Erro ao processar sua solicitação: {e}",
            "job_id": None
        }

# --- Endpoints de Suporte (Permanecem Inalterados) ---

@app.get("/api/ingest/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_job_status(job_id: str):
    # (Código de verificação de status de ingestão - sem alterações)
    if not q_ingest: raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    print(f"[API] Verificando status do Job ID (Ingest): {job_id}")
    try:
        job = q_ingest.fetch_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None: return {"status": "not_found"}
    status = job.get_status()
    result = None
    error_info = None
    if status == 'finished': result = job.result
    elif status == 'failed': error_info = str(job.exc_info)
    return {"status": status, "result": result, "error": error_info}

@app.get("/api/relatorio/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_report_job_status(job_id: str):
    # (Código de verificação de status de relatório - sem alterações)
    if not q_reports: raise HTTPException(status_code=500, detail="Serviço de Fila (Redis) não inicializado.")
    print(f"[API] Verificando status do Job ID (Report): {job_id}")
    try:
        job = q_reports.fetch_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")
    if job is None: return {"status": "not_found"}
    status = job.get_status()
    result = None
    error_info = None
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