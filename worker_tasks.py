# CÓDIGO COMPLETO PARA: worker_tasks.py
# (Refatorado para usar Classes)

# (Importa as Classes dos serviços)
from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from app.services.report_service import ReportService
from app.services.email_service import send_report_email

from supabase import create_client
import os
from datetime import datetime
import pytz
from typing import List, Dict, Any

# --- TAREFA DO MARCO 5 (Agendamento) ---
def enviar_relatorio_agendado(agendamento_id: str, user_email: str, repo_name: str, user_prompt: str):
    """
    Tarefa do Worker (RQ) que gera um relatório e o ENVIA POR EMAIL.
    """
    print(f"[WorkerTask] Iniciando relatório agendado {agendamento_id} para {user_email}")
    
    try:
        # 1. Inicializa os serviços (dentro da tarefa)
        llm_service = LLMService()
        report_service = ReportService() # Esta instância contém o metadata_service
        
        print(f"[WorkerTask] Buscando dados de {repo_name}...")
        
        # 2. Busca os dados para a análise
        # (Usamos a instância do report_service para acessar o metadata_service)
        dados_brutos = report_service.metadata_service.get_all_documents_by_repo(repo_name)
        if not dados_brutos:
            print(f"[WorkerTask] Nenhum dado encontrado para {repo_name}.")
            
        print(f"[WorkerTask] Gerando JSON da LLM...")
        
        # (Aqui não temos RAG de instrução, é o job agendado)
        report_json_string = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=user_prompt, # Usa o prompt salvo no agendamento
            raw_data=dados_brutos
        )
        
        print(f"[WorkerTask] Gerando HTML do relatório...")
        # (Usamos o método privado do report_service)
        (html_content, _, _) = report_service._generate_report_content(
            repo_name,
            report_json_string,
            "html"
        )
        
        print(f"[WorkerTask] Enviando email para {user_email}...")
        subject = f"Seu Relatório Agendado: {repo_name}"
        send_report_email(user_email, subject, html_content)
        
        # 6. Atualiza o 'ultimo_envio' no Supabase
        url: str = os.getenv("SUPABASE_URL")
        key: str = os.getenv("SUPABASE_KEY")
        supabase: Client = create_client(url, key)
        
        supabase.table("agendamentos").update({
            "ultimo_envio": datetime.now(pytz.utc).isoformat()
        }).eq("id", agendamento_id).execute()
        
        print(f"[WorkerTask] Relatório agendado {agendamento_id} concluído com sucesso.")

    except Exception as e:
        print(f"[WorkerTask] ERRO CRÍTICO no job {agendamento_id}: {e}")
        raise

# --- TAREFAS DO MARCO 6 (Webhooks) ---

def _parse_issue_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    # (Função helper, sem alterações)
    action = payload.get("action")
    if action not in ["opened", "edited"]:
        print(f"[WebhookWorker] Ação de issue ignorada: {action}")
        return []
    issue = payload.get("issue", {}); repo_name = payload.get("repository", {}).get("full_name")
    if not issue or not repo_name: return []
    conteudo = f"Issue #{issue.get('number')}: {issue.get('title')}\n{issue.get('body')}"
    documento = {
        "repositorio": repo_name, "tipo": "issue",
        "metadados": {
            "id": issue.get('number'), "autor": issue.get('user', {}).get('login'),
            "data": issue.get('created_at'), "url": issue.get('html_url'), "titulo": issue.get('title')
        },
        "conteudo": conteudo
    }
    return [documento]

def _parse_push_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    # (Função helper, sem alterações)
    repo_name = payload.get("repository", {}).get("full_name")
    commits = payload.get("commits", [])
    if not commits or not repo_name:
        print("[WebhookWorker] Evento Push sem commits ou nome de repositório.")
        return []
    documentos_para_salvar = []
    for commit in commits:
        if commit.get("message", "").startswith("Merge pull request"): continue
        conteudo = f"Commit de {commit.get('author', {}).get('name')}: {commit.get('message')}"
        documento = {
            "repositorio": repo_name, "tipo": "commit",
            "metadados": {
                "sha": commit.get('id'), "autor": commit.get('author', {}).get('name'),
                "data": commit.get('timestamp'), "url": commit.get('url')
            },
            "conteudo": conteudo
        }
        documentos_para_salvar.append(documento)
    return documentos_para_salvar

def process_webhook_payload(event_type: str, payload: Dict[str, Any]):
    """
    Tarefa do Worker (RQ) que processa um webhook do GitHub (Ingestão Delta).
    """
    print(f"[WebhookWorker] Processando evento: {event_type}")
    
    try:
        # Instancia o MetadataService DENTRO do worker
        metadata_service = MetadataService()
        
        documentos_para_salvar = []
        if event_type == "issues":
            documentos_para_salvar = _parse_issue_payload(payload)
        elif event_type == "push":
            documentos_para_salvar = _parse_push_payload(payload)
        elif event_type == "pull_request":
            print(f"[WebhookWorker] Parser de 'pull_request' ainda não implementado.")
        else:
            print(f"[WebhookWorker] Evento {event_type} não suportado.")
            return
            
        if not documentos_para_salvar:
            print("[WebhookWorker] Nenhum documento novo para salvar.")
            return

        print(f"[WebhookWorker] Salvando {len(documentos_para_salvar)} novos documentos no Supabase...")
        
        # Chama o MÉTODO da classe
        metadata_service.save_documents_batch(documentos_para_salvar)
        
        print(f"[WebhookWorker] Evento {event_type} processado com sucesso.")

    except Exception as e:
        print(f"[WebhookWorker] ERRO CRÍTICO ao processar webhook {event_type}: {e}")
        raise