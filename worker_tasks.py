# CÓDIGO COMPLETO E ATUALIZADO PARA: worker_tasks.py
# (Refatorado para Multi-Tenancy com 'user_id')

# --- Importações de Serviços (Classes) ---
from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from app.services.report_service import ReportService, SupabaseStorageService
from app.services.ingest_service import IngestService, GithubService
from app.services.email_service import send_report_email
from app.services.embedding_service import get_embedding

from supabase import create_client, Client
import os
from datetime import datetime
import pytz
from typing import List, Dict, Any, Optional
import requests # Adicionado para QuickChart
import json     # Adicionado para QuickChart

# -------------------------------------------------------------------
# TAREFA (do Marco 1, 6, 7): Ingestão
# -------------------------------------------------------------------

def ingest_repo(user_id: str, repo_name: str, issues_limit: int, prs_limit: int, commits_limit: int) -> Dict[str, Any]:
    """
    Tarefa do Worker (RQ) para ingestão (Delta Pull).
    Agora vinculada a um user_id.
    """
    print(f"[WorkerTask] INICIANDO INGESTÃO (User: {user_id}) para {repo_name}...")
    try:
        metadata_service = MetadataService()
        github_service = GithubService()
        ingest_service = IngestService()
        
        # Passa o user_id para o serviço de metadados
        latest_timestamp = metadata_service.get_latest_timestamp(user_id, repo_name)
        
        if latest_timestamp is None:
            print(f"[WorkerTask] Novo repositório detectado. Executando ingestão completa.")
            # Passa o user_id para deletar documentos
            metadata_service.delete_documents_by_repo(user_id, repo_name)
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
            
        # Passa o user_id para salvar os documentos
        metadata_service.save_documents_batch(user_id, documentos_para_salvar)
        
        mensagem_final = f"Ingestão de {repo_name} concluída. {len(documentos_para_salvar)} novos documentos salvos."
        print(f"[WorkerTask] {mensagem_final}")
        return {"status": "concluído", "mensagem": mensagem_final}
        
    except Exception as e:
        print(f"[WorkerTask] ERRO na ingestão de {repo_name}: {e}")
        raise e

def save_instruction(user_id: str, repo_name: str, instruction_text: str) -> str:
    """
    Tarefa do Worker (RQ) para salvar uma instrução de relatório.
    Agora vinculada a um user_id.
    """
    print(f"[WorkerTask] Salvando instrução (User: {user_id}) para: {repo_name}")
    try:
        metadata_service = MetadataService()
        print("[WorkerTask] Gerando embedding para a instrução...")
        instruction_embedding = get_embedding(instruction_text)
        
        new_instruction = {
            "user_id": user_id, # <-- ADICIONADO
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
        raise e


# -------------------------------------------------------------------
# TAREFA (do Marco 4, 7): Relatório para Download
# -------------------------------------------------------------------

def processar_e_salvar_relatorio(user_id: str, repo_name: str, user_prompt: str, format: str = "html"):
    """
    Tarefa do Worker (RQ) que gera um relatório para DOWNLOAD.
    Agora vinculada a um user_id.
    """
    SUPABASE_BUCKET_NAME = "reports" 
    print(f"[WorkerTask] Iniciando relatório (User: {user_id}) para: {repo_name}")
    try:
        # 1. Instancia os serviços
        metadata_service = MetadataService()
        llm_service = LLMService()
        report_service = ReportService()
        storage_service = SupabaseStorageService()
        
        # 2. Busca uma instrução salva (RAG) - Passa user_id
        retrieved_instruction = metadata_service.find_similar_instruction(user_id, repo_name, user_prompt)
        
        if retrieved_instruction:
            print(f"[WorkerTask] Instrução RAG encontrada. Combinando prompts...")
            combined_prompt = f"Instrução Base: '{user_prompt}'\nContexto Salvo: '{retrieved_instruction}'\nGere o relatório."
        else:
            print(f"[WorkerTask] Nenhuma instrução RAG encontrada. Usando prompt padrão.")
            combined_prompt = user_prompt
            
        # 3. Busca os dados brutos para a análise - Passa user_id
        dados_brutos = metadata_service.get_all_documents_by_repo(user_id, repo_name)
        if not dados_brutos:
            print("[WorkerTask] Nenhum dado encontrado no SQL.")

        print(f"[WorkerTask] {len(dados_brutos)} registos encontrados. Enviando para LLM...")

        # 4. Gera o JSON do relatório
        report_json_string = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=combined_prompt,
            raw_data=dados_brutos
        )
        
        print("[WorkerTask] Relatório JSON gerado pela LLM.")

        # 5. Gera o CONTEÚDO (HTML) e o NOME DO ARQUIVO
        # (Nenhuma mudança aqui, o chart_image_url é None por padrão)
        (content_to_upload, filename, content_type) = report_service.generate_report_content(
            repo_name, report_json_string, format, chart_image_url=None
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
        error_message = repr(e)
        print(f"[WorkerTask] Erro detalhado during geração do relatório: {error_message}")
        raise e

# -------------------------------------------------------------------
# TAREFA (do Marco 5): Relatório Agendado por Email
# -------------------------------------------------------------------

def enviar_relatorio_agendado(
    agendamento_id: Optional[str],
    user_email: str, 
    repo_name: str, 
    user_prompt: str,
    user_id: str # <-- NOVO
):
    """
    Tarefa do Worker (RQ) que gera um relatório e o ENVIA POR EMAIL.
    Se 'agendamento_id' for None, é um envio imediato.
    Agora vinculada a um user_id.
    """
    if agendamento_id:
        print(f"[WorkerTask] Iniciando relatório agendado {agendamento_id} (User: {user_id}) para {user_email}")
    else:
        print(f"[WorkerTask] Iniciando relatório imediato (User: {user_id}) para {user_email}")
    
    try:
        # 1. Instancia os serviços
        llm_service = LLMService()
        report_service = ReportService()
        metadata_service = MetadataService()
        
        print(f"[WorkerTask] Buscando dados de {repo_name}...")
        
        # 2. Busca os dados - Passa user_id
        dados_brutos = metadata_service.get_all_documents_by_repo(user_id, repo_name)
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
        
        # --- Lógica do Gráfico Estático (QuickChart) ---
        chart_image_url = None
        try:
            report_data = json.loads(report_json_string)
            chart_json = report_data.get("chart_json")
            
            if chart_json:
                print("[WorkerTask] Gerando imagem estática do gráfico via QuickChart...")
                qc_response = requests.post(
                    'https://quickchart.io/chart/create',
                    json={
                        "chart": chart_json,
                        "backgroundColor": "#ffffff",
                        "format": "png", "width": 600, "height": 400
                    }
                )
                qc_response.raise_for_status()
                chart_image_url = qc_response.json().get('url')
                print(f"[WorkerTask] URL do gráfico gerada: {chart_image_url}")

        except Exception as e:
            print(f"[WorkerTask] AVISO: Falha ao gerar gráfico estático: {e}")
            chart_image_url = None
        # --- Fim da Lógica QuickChart ---
        
        # 4. Gera o HTML (passando a URL da imagem)
        (html_content, _, _) = report_service.generate_report_content(
            repo_name,
            report_json_string,
            "html",
            chart_image_url # <-- Passa a nova URL
        )
        
        print(f"[WorkerTask] Enviando email para {user_email}...")
        subject = f"Seu Relatório Solicitado: {repo_name}"
        send_report_email(user_email, subject, html_content)
        
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

    except Exception as e:
        print(f"[WorkerTask] ERRO CRÍTICO no job de {user_email}: {e}")
        raise e

# -------------------------------------------------------------------
# TAREFA (do Marco 6): Ingestão por Webhook
# -------------------------------------------------------------------
# (Funções helper _parse_issue_payload e _parse_push_payload não mudam)
def _parse_issue_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    # ... (sem mudanças) ...
    pass

def _parse_push_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    # ... (sem mudanças) ...
    pass

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
            
        # --- Lógica Multi-Tenancy para Webhook ---
        # 1. Pega o repositório
        repo_name = documentos_para_salvar[0].get("repositorio")
        if not repo_name:
            raise Exception("Não foi possível extrair repo_name do payload do webhook.")
            
        # 2. Descobre qual usuário(s) ingeriu esse repositório
        user_ids = metadata_service.get_user_ids_for_repo(repo_name)
        if not user_ids:
            print(f"[WebhookWorker] Nenhum usuário está rastreando o repositório {repo_name}. Ignorando.")
            return

        print(f"[WebhookWorker] Webhook para {repo_name}. Inserindo dados para {len(user_ids)} usuário(s).")

        # 3. Salva os documentos para CADA usuário
        for user_id in user_ids:
            print(f"[WebhookWorker] Salvando {len(documentos_para_salvar)} documentos para User: {user_id}...")
            # Passa o user_id para o save_batch
            metadata_service.save_documents_batch(user_id, documentos_para_salvar)
            
        print(f"[WebhookWorker] Evento {event_type} processado com sucesso para todos os usuários.")

    except Exception as e:
        print(f"[WebhookWorker] ERRO CRÍTICO ao processar webhook {event_type}: {e}")
        raise e