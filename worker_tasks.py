# CÓDIGO COMPLETO E CORRIGIDO PARA: worker_tasks.py
# (Usa a arquitetura de Classes e corrige o bug 'download/null')

import os
import redis
from rq import Queue
import time
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import io 
import traceback 

from dotenv import load_dotenv
load_dotenv()

# Importa as CLASSES dos serviços
from app.services.github_service import GithubService
from app.services.ingest_service import IngestService
from app.services.metadata_service import MetadataService
from app.services.embedding_service import EmbeddingService
from app.services.report_service import ReportService
from app.services.llm_service import LLMService
from app.services.email_service import send_report_email

# --- Configuração de Conexão (Redis, Supabase) ---
try:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise ValueError("REDIS_URL não definida")
    conn = redis.from_url(redis_url)
    conn.ping()
    print(f"[WorkerTasks] Conexão com Redis em {redis_url} estabelecida.")
except Exception as e:
    print(f"[WorkerTasks] ERRO CRÍTICO: Não foi possível conectar ao Redis. {e}")
    conn = None

QUEUE_PREFIX = os.getenv("RQ_QUEUE_PREFIX", "")
if QUEUE_PREFIX:
    print(f"[WorkerTasks] Usando prefixo de fila: '{QUEUE_PREFIX}'")

try:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL e SUPABASE_KEY não definidas")

    from supabase import create_client, Client
    supabase_client: Client = create_client(supabase_url, supabase_key)
    print("[WorkerTasks] Cliente Supabase global inicializado.")
    SUPABASE_BUCKET_NAME = "reports"
except Exception as e:
    print(f"[WorkerTasks] ERRO CRÍTICO: Não foi possível conectar ao Supabase. {e}")
    supabase_client = None

# --- Inicialização de Serviços (Arquitetura de Injeção de Dependência) ---
try:
    llm_service = LLMService()
    
    embedding_service = EmbeddingService(
        model_name=os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small"), 
        max_retries=3, 
        delay=5
    )
    metadata_service = MetadataService(embedding_service=embedding_service) 
    github_service = GithubService(os.getenv("GITHUB_TOKEN"))
    ingest_service = IngestService(github_service, metadata_service, embedding_service)
    report_service = ReportService(llm_service, metadata_service)
    
    print("[WorkerTasks] Todos os serviços (LLM, Embedding, Metadata, GitHub, Ingest, Report) inicializados.")
except Exception as e:
    print(f"[WorkerTasks] ERRO: Falha ao inicializar serviços: {e}")
    traceback.print_exc() # Printa o stack trace completo do erro de inicialização
    llm_service = None
    embedding_service = None
    metadata_service = None
    github_service = None
    ingest_service = None
    report_service = None

# --- Funções de Tarefa (Executadas pelo Worker) ---

def _run_with_logs(task_func, *args, **kwargs):
    """
    Helper para garantir que os serviços estejam prontos antes de rodar.
    """
    print(f"[WorkerTask] Executando: {task_func.__name__} com args={args}")
    start_time = time.time()
    
    if not all([conn, supabase_client, llm_service, ingest_service, report_service, metadata_service]):
        msg = "Um ou mais serviços críticos (Redis, Supabase, LLM, etc.) não estão inicializados."
        print(f"[WorkerTask] ERRO: {msg}")
        raise RuntimeError(msg)

    try:
        result = task_func(*args, **kwargs)
        end_time = time.time()
        print(f"[WorkerTask] Sucesso: {task_func.__name__}. Duração: {end_time - start_time:.2f}s")
        return result
    except Exception as e:
        print(f"[WorkerTask] FALHA: {task_func.__name__}. Erro: {e}")
        traceback.print_exc()
        raise e

def ingest_repo(user_id: str, repo_url: str, max_items: int = 50, batch_size: int = 20, max_depth: int = 30):
    return _run_with_logs(
        ingest_service.ingest_repository,
        user_id,
        repo_url,
        max_items,
        batch_size,
        max_depth,
    )

def processar_e_salvar_relatorio(user_id: str, repo_url: str, prompt: str, formato: str = "html") -> str:
    print(f"[WorkerTask] Iniciando geração de relatório ({formato}) para {repo_url}...")
    if not report_service:
         raise RuntimeError("ReportService não inicializado.")

    filename = report_service.gerar_e_salvar_relatorio(
        user_id, repo_url, prompt
    )
    print(f"[WorkerTask] Upload com sucesso! Retornando filename: {filename}")
    return filename

def save_instruction(user_id: str, repo_url: str, instrucao: str):
    return _run_with_logs(
        ingest_service.save_instruction_document,
        user_id,
        repo_url,
        instrucao
    )

def enviar_relatorio_agendado(
    schedule_id: str, 
    to_email: str, 
    repo_url: str, 
    prompt: str, 
    user_id: str
) -> str:
    print(f"[WorkerTask] Iniciando tarefa de envio de relatório para {to_email} (Repo: {repo_url})...")
    
    if not report_service or not supabase_client:
         raise RuntimeError("ReportService ou Supabase Client não inicializado.")

    html_content, filename = report_service.gerar_relatorio_html(
        user_id, repo_url, prompt
    )
    
    if not html_content or filename == "error_report.html":
        raise ValueError("Falha ao gerar o conteúdo HTML do relatório.")

    try:
        print(f"[WorkerTask] Salvando cópia do relatório de email no Storage: {filename}...")
        supabase_client.storage.from_(SUPABASE_BUCKET_NAME).upload(
            file=io.BytesIO(html_content.encode('utf-8')),
            path=filename,
            file_options={"content-type": "text/html"}
        )
        print(f"[WorkerTask] Upload de cópia (email job) com sucesso.")
    except Exception as e:
        print(f"[WorkerTask] AVISO: Falha ao salvar cópia no Storage. {e}")

    subject = f"Seu Relatório Agendado: {repo_url}"
    send_report_email(to_email, subject, html_content)
    
    print(f"[WorkerTask] Relatório (agendado/once) para {to_email} concluído.")
    
    # Retorna o filename para corrigir o bug 'download/null'
    return filename

def process_webhook_payload(event_type: str, payload: dict):
    return _run_with_logs(
        ingest_service.handle_webhook,
        event_type,
        payload
    )