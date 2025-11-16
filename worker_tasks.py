# CÓDIGO COMPLETO PARA: worker_tasks.py
# (Corrigido para 'raise' exceções em vez de 'return' strings de erro)

# --- Importações de Serviços (Classes) ---
from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from app.services.report_service import ReportService, SupabaseStorageService
from app.services.ingest_service import IngestService, GithubService
from app.services.email_service import send_report_email
from app.services.embedding_service import get_embedding

from supabase import create_client
import os
from datetime import datetime
import pytz
from typing import List, Dict, Any, Optional
import requests # <-- Adicione esta importação
import json     # <-- Adicione esta importação
# -------------------------------------------------------------------
# TAREFA (do Marco 1, 6, 7): Ingestão
# -------------------------------------------------------------------

def ingest_repo(repo_name: str, issues_limit: int, prs_limit: int, commits_limit: int) -> Dict[str, Any]:
    """
    Tarefa do Worker (RQ) para ingestão (Delta Pull).
    """
    print(f"[WorkerTask] INICIANDO INGESTÃO para {repo_name}...")
    try:
        metadata_service = MetadataService()
        github_service = GithubService()
        ingest_service = IngestService()
        
        latest_timestamp = metadata_service.get_latest_timestamp(repo_name)
        
        if latest_timestamp is None:
            print(f"[WorkerTask] Novo repositório detectado. Executando ingestão completa.")
            metadata_service.delete_documents_by_repo(repo_name)
            raw_data = github_service.get_repo_data(
                repo_name, issues_limit, prs_limit, commits_limit, since=None
            )
        else:
            print(f"[WorkerTask] Repositório existente. Executando ingestão incremental desde {latest_timestamp}.")
            raw_data = github_service.get_repo_data(
                repo_name, issues_limit, prs_limit, commits_limit, since=latest_timestamp
            )

        documentos_para_salvar = ingest_service.format_data_for_ingestion(repo_name, raw_data)
        
        if not documentos_para_salvar:
            mensagem_vazia = "Nenhum dado novo encontrado para ingestão."
            print(f"[WorkerTask] {mensagem_vazia}")
            return {"status": "concluído", "mensagem": mensagem_vazia}
            
        metadata_service.save_documents_batch(documentos_para_salvar)
        
        mensagem_final = f"Ingestão de {repo_name} concluída. {len(documentos_para_salvar)} novos documentos salvos."
        print(f"[WorkerTask] {mensagem_final}")
        return {"status": "concluído", "mensagem": mensagem_final}
        
    except Exception as e:
        print(f"[WorkerTask] ERRO na ingestão de {repo_name}: {e}")
        # --- CORREÇÃO (Bug 1) ---
        # Propaga o erro para o RQ
        raise e

def save_instruction(repo_name: str, instruction_text: str) -> str:
    """
    Tarefa do Worker (RQ) para salvar uma instrução de relatório.
    """
    print(f"[WorkerTask] Salvando instrução para: {repo_name}")
    try:
        metadata_service = MetadataService()
        print("[WorkerTask] Gerando embedding para a instrução...")
        instruction_embedding = get_embedding(instruction_text)
        
        new_instruction = {
            "repositorio": repo_name,
            "instrucao_texto": instruction_text,
            "embedding": instruction_embedding
        }
        
        response = metadata_service.supabase.table("instrucoes_relatorio").insert(new_instruction).execute()
        
        if response.data:
            print("[WorkerTask] Instrução salva com sucesso.")
            return "Instrução de relatório salva com sucesso."
        else:
            raise Exception("Falha ao salvar instrução no Supabase (sem dados retornados).")

    except Exception as e:
        print(f"[WorkerTask] ERRO ao salvar instrução: {e}")
        # --- CORREÇÃO (Bug 1) ---
        raise e


# -------------------------------------------------------------------
# TAREFA (do Marco 4, 7): Relatório para Download
# -------------------------------------------------------------------

def processar_e_salvar_relatorio(repo_name: str, user_prompt: str, format: str = "html"):
    """
    Tarefa do Worker (RQ) que gera um relatório para DOWNLOAD.
    """
    SUPABASE_BUCKET_NAME = "reports" 
    print(f"[WorkerTask] Iniciando relatório (com RAG) para: {repo_name}")
    try:
        # 1. Instancia os serviços
        metadata_service = MetadataService()
        llm_service = LLMService()
        report_service = ReportService()
        storage_service = SupabaseStorageService()
        
        # 2. Busca uma instrução salva (RAG)
        retrieved_instruction = metadata_service.find_similar_instruction(repo_name, user_prompt)
        
        if retrieved_instruction:
            print(f"[WorkerTask] Instrução RAG encontrada. Combinando prompts...")
            combined_prompt = f"Instrução Base: '{user_prompt}'\nContexto Salvo: '{retrieved_instruction}'\nGere o relatório."
        else:
            print(f"[WorkerTask] Nenhuma instrução RAG encontrada. Usando prompt padrão.")
            combined_prompt = user_prompt
            
        # 3. Busca os dados brutos para a análise
        dados_brutos = metadata_service.get_all_documents_by_repo(repo_name)
        if not dados_brutos:
            print("[WorkerTask] Nenhum dado encontrado no SQL.")

        print(f"[WorkerTask] {len(dados_brutos)} registos encontrados. Enviando para LLM...")

        # 4. Gera o JSON do relatório (usando o prompt combinado)
        report_json_string = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=combined_prompt,
            raw_data=dados_brutos
        )
        
        print("[WorkerTask] Relatório JSON gerado pela LLM.")

        # 5. Gera o CONTEÚDO (HTML) e o NOME DO ARQUIVO
        (content_to_upload, filename, content_type) = report_service.generate_report_content(
            repo_name, report_json_string, format
        )
        
        print(f"[WorkerTask] Conteúdo HTML gerado. Fazendo upload de {filename}...")
        
        # 6. Fazer UPLOAD do conteúdo
        storage_service.upload_file_content(
            content_string=content_to_upload,
            filename=filename,
            bucket_name=SUPABASE_BUCKET_NAME,
            content_type=content_type
        )
        
        print(f"[WorkerTask] Upload com sucesso! Retornando filename: {filename}")
        
        # 7. Retornar o nome do arquivo (para o App.js baixar)
        return filename
        
    except Exception as e:
        error_message = repr(e) # Pega a mensagem de erro (ex: TypeError)
        print(f"[WorkerTask] Erro detalhado during geração do relatório: {error_message}")
        # --- CORREÇÃO (Bug 1) ---
        # Relança a exceção para o RQ marcar como 'failed'
        raise e

# -------------------------------------------------------------------
# TAREFA (do Marco 5): Relatório Agendado por Email
# -------------------------------------------------------------------

def enviar_relatorio_agendado(
    agendamento_id: Optional[str], # <-- ATUALIZAÇÃO: De str para Optional[str]
    user_email: str, 
    repo_name: str, 
    user_prompt: str
):
    """
    Tarefa do Worker (RQ) que gera um relatório e o ENVIA POR EMAIL.
    Se 'agendamento_id' for None, é um envio imediato e a DB não é atualizada.
    """
    if agendamento_id:
        print(f"[WorkerTask] Iniciando relatório agendado {agendamento_id} para {user_email}")
    else:
        print(f"[WorkerTask] Iniciando relatório imediato (once) para {user_email}")
    
    try:
        # 1. Instancia os serviços
        llm_service = LLMService()
        report_service = ReportService()
        metadata_service = MetadataService()
        
        print(f"[WorkerTask] Buscando dados de {repo_name}...")
        
        # 2. Busca os dados
        dados_brutos = metadata_service.get_all_documents_by_repo(repo_name)
        if not dados_brutos:
            print(f"[WorkerTask] Nenhum dado encontrado para {repo_name}.")
            
        print(f"[WorkerTask] Gerando JSON da LLM...")
        
        # 3. Gera o JSON
        report_json_string = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=user_prompt,
            raw_data=dados_brutos
        )
        
        print(f"[WorkerTask] Gerando HTML do relatório...")
        
        # --- INÍCIO DA ATUALIZAÇÃO (QuickChart) ---
        
        chart_image_url = None
        try:
            # Tenta parsear o JSON para extrair os dados do gráfico
            report_data = json.loads(report_json_string)
            chart_json = report_data.get("chart_json")
            
            if chart_json:
                print("[WorkerTask] Gerando imagem estática do gráfico via QuickChart...")
                qc_response = requests.post(
                    'https://quickchart.io/chart/create',
                    json={
                        "chart": chart_json,
                        "backgroundColor": "#ffffff", # Fundo branco
                        "format": "png",
                        "width": 600,
                        "height": 400
                    }
                )
                qc_response.raise_for_status()
                chart_image_url = qc_response.json().get('url')
                print(f"[WorkerTask] URL do gráfico gerada: {chart_image_url}")

        except Exception as e:
            print(f"[WorkerTask] AVISO: Falha ao gerar gráfico estático: {e}")
            chart_image_url = None # Continua sem o gráfico se falhar

        # 4. Gera o HTML (agora passando a URL da imagem)
        (html_content, _, _) = report_service.generate_report_content(
            repo_name,
            report_json_string,
            "html",
            chart_image_url # <-- Passa a nova URL
        )
        
        print(f"[WorkerTask] Enviando email para {user_email}...")
        subject = f"Seu Relatório Solicitado: {repo_name}" # Ajustado para "Solicitado"
        send_report_email(user_email, subject, html_content)
        
        # --- INÍCIO DA ATUALIZAÇÃO ---
        # 6. Atualiza o 'ultimo_envio' (APENAS se for um job agendado)
        if agendamento_id:
            url: str = os.getenv("SUPABASE_URL")
            key: str = os.getenv("SUPABASE_KEY")
            supabase: Client = create_client(url, key)
            
            supabase.table("agendamentos").update({
                "ultimo_envio": datetime.now(pytz.utc).isoformat()
            }).eq("id", agendamento_id).execute()
            
            print(f"[WorkerTask] Relatório agendado {agendamento_id} concluído com sucesso.")
        else:
            print(f"[WorkerTask] Relatório imediato para {user_email} concluído.")
        # --- FIM DA ATUALIZAÇÃO ---

    except Exception as e:
        print(f"[WorkerTask] ERRO CRÍTICO no job de {user_email}: {e}")
        raise e

# -------------------------------------------------------------------
# TAREFA (do Marco 6): Ingestão por Webhook
# -------------------------------------------------------------------

# (Funções helper _parse_issue_payload e _parse_push_payload não mudam)
def _parse_issue_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    action = payload.get("action");
    if action not in ["opened", "edited"]: return []
    issue = payload.get("issue", {}); repo_name = payload.get("repository", {}).get("full_name")
    if not issue or not repo_name: return []
    conteudo = f"Issue #{issue.get('number')}: {issue.get('title')}\n{issue.get('body')}"
    return [{
        "repositorio": repo_name, "tipo": "issue",
        "metadados": {"id": issue.get('number'), "autor": issue.get('user', {}).get('login'),
                      "data": issue.get('created_at'), "url": issue.get('html_url'), "titulo": issue.get('title')},
        "conteudo": conteudo
    }]

def _parse_push_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    repo_name = payload.get("repository", {}).get("full_name"); commits = payload.get("commits", [])
    if not commits or not repo_name: return []
    documentos_para_salvar = []
    for commit in commits:
        if commit.get("message", "").startswith("Merge pull request"): continue
        conteudo = f"Commit de {commit.get('author', {}).get('name')}: {commit.get('message')}"
        documentos_para_salvar.append({
            "repositorio": repo_name, "tipo": "commit",
            "metadados": {"sha": commit.get('id'), "autor": commit.get('author', {}).get('name'),
                          "data": commit.get('timestamp'), "url": commit.get('url')},
            "conteudo": conteudo
        })
    return documentos_para_salvar

def process_webhook_payload(event_type: str, payload: Dict[str, Any]):
    """
    Tarefa do Worker (RQ) que processa um webhook do GitHub (Ingestão Delta).
    """
    print(f"[WebhookWorker] Processando evento: {event_type}")
    try:
        metadata_service = MetadataService()
        
        documentos_para_salvar = []
        if event_type == "issues":
            documentos_para_salvar = _parse_issue_payload(payload)
        elif event_type == "push":
            documentos_para_salvar = _parse_push_payload(payload)
        
        if not documentos_para_salvar:
            print("[WebhookWorker] Nenhum documento novo para salvar.")
            return

        print(f"[WebhookWorker] Salvando {len(documentos_para_salvar)} novos documentos no Supabase...")
        metadata_service.save_documents_batch(documentos_para_salvar)
        print(f"[WebhookWorker] Evento {event_type} processado com sucesso.")

    except Exception as e:
        print(f"[WebhookWorker] ERRO CRÍTICO ao processar webhook {event_type}: {e}")
        # --- CORREÇÃO (Bug 1) ---
        raise e