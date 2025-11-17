# CÓDIGO COMPLETO E ATUALIZADO PARA: worker_tasks.py
# (Refatorado para Multi-Tenancy com 'user_id' e prompts de relatório mais robustos)

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
import requests  # QuickChart
import json      # QuickChart e prompts


# -------------------------------------------------------------------
# TAREFA: Ingestão de Repositório (Delta Pull)
# -------------------------------------------------------------------

def ingest_repo(
    user_id: str,
    repo_name: str,
    issues_limit: int,
    prs_limit: int,
    commits_limit: int,
) -> Dict[str, Any]:
    """
    Tarefa do Worker (RQ) para ingestão (Delta Pull).
    Agora vinculada a um user_id.

    Fluxo:
    - Descobre o último timestamp ingerido para (user_id, repo_name).
    - Se não houver, faz ingestão completa.
    - Se houver, faz ingestão incremental a partir desse timestamp.
    - Salva documentos no índice (SQL + vetores) usando MetadataService.
    """
    print(f"[WorkerTask] INICIANDO INGESTÃO (User: {user_id}) para {repo_name}...")
    try:
        metadata_service = MetadataService()
        github_service = GithubService()
        ingest_service = IngestService()

        latest_timestamp = metadata_service.get_latest_timestamp(user_id, repo_name)

        if latest_timestamp is None:
            print("[WorkerTask] Novo repositório detectado. Executando ingestão completa.")
            metadata_service.delete_documents_by_repo(user_id, repo_name)
            raw_data = github_service.get_repo_data(
                repo_name, issues_limit, prs_limit, commits_limit, since=None
            )
        else:
            print(
                f"[WorkerTask] Repositório existente. Executando ingestão incremental desde {latest_timestamp}."
            )
            raw_data = github_service.get_repo_data(
                repo_name, issues_limit, prs_limit, commits_limit, since=latest_timestamp
            )

        documentos_para_salvar = ingest_service.format_data_for_ingestion(repo_name, raw_data)

        if not documentos_para_salvar:
            mensagem_vazia = "Nenhum dado novo encontrado para ingestão."
            print(f"[WorkerTask] {mensagem_vazia}")
            return {"status": "concluído", "mensagem": mensagem_vazia}

        metadata_service.save_documents_batch(user_id, documentos_para_salvar)

        mensagem_final = (
            f"Ingestão de {repo_name} concluída. {len(documentos_para_salvar)} novos documentos salvos."
        )
        print(f"[WorkerTask] {mensagem_final}")
        return {"status": "concluído", "mensagem": mensagem_final}

    except Exception as e:
        print(f"[WorkerTask] ERRO na ingestão de {repo_name}: {e}")
        raise e


def save_instruction(user_id: str, repo_name: str, instruction_text: str) -> str:
    """
    Tarefa do Worker (RQ) para salvar uma instrução de relatório.
    Agora vinculada a um user_id.

    Essa instrução é usada como "contexto base" para futuros relatórios analíticos
    daquele repositório.
    """
    print(f"[WorkerTask] Salvando instrução (User: {user_id}) para: {repo_name}")
    try:
        metadata_service = MetadataService()
        print("[WorkerTask] Gerando embedding para a instrução...")
        instruction_embedding = get_embedding(instruction_text)

        new_instruction = {
            "user_id": user_id,
            "repositorio": repo_name,
            "instrucao_texto": instruction_text,
            "embedding": instruction_embedding,
        }

        response = (
            metadata_service.supabase.table("instrucoes_relatorio")
            .insert(new_instruction)
            .execute()
        )

        if response.data:
            print("[WorkerTask] Instrução salva com sucesso.")
            return "Instrução de relatório salva com sucesso."
        else:
            raise Exception("Falha ao salvar instrução no Supabase (sem dados retornados).")

    except Exception as e:
        print(f"[WorkerTask] ERRO ao salvar instrução: {e}")
        raise e


# -------------------------------------------------------------------
# TAREFA: Relatório para Download (HTML armazenado em Supabase)
# -------------------------------------------------------------------

def processar_e_salvar_relatorio(
    user_id: str, repo_name: str, user_prompt: str, format: str = "html"
):
    """
    Tarefa do Worker (RQ) que gera um relatório para DOWNLOAD.
    Agora vinculada a um user_id.

    Fluxo:
    - Busca instruções salvas (RAG) específicas para (user_id, repo_name).
    - Combina instrução + prompt atual para formar o "prompt analítico".
    - Busca todos os documentos do repositório (multi-tenant).
    - Chama a LLM para gerar JSON com análise + chart_json.
    - Gera o HTML (ou outro formato, se configurado) e salva em Supabase Storage.
    """
    SUPABASE_BUCKET_NAME = "reports"
    print(f"[WorkerTask] Iniciando relatório (User: {user_id}) para: {repo_name}")
    try:
        metadata_service = MetadataService()
        llm_service = LLMService()
        report_service = ReportService()
        storage_service = SupabaseStorageService()

        # 1. Busca uma instrução salva (RAG) - Passa user_id
        retrieved_instruction = metadata_service.find_similar_instruction(
            user_id, repo_name, user_prompt
        )

        if retrieved_instruction:
            print("[WorkerTask] Instrução RAG encontrada. Combinando prompts...")
            combined_prompt = (
                "Instrução de relatório pré-salva:\n"
                f"\"{retrieved_instruction}\"\n\n"
                "Pedido atual do usuário:\n"
                f"\"{user_prompt}\"\n\n"
                "Gere um relatório analítico estruturado para a equipe de engenharia de software, "
                "destacando métricas relevantes, hotspots, rastreabilidade de requisitos e recomendações."
            )
        else:
            print("[WorkerTask] Nenhuma instrução RAG encontrada. Usando prompt atual como base.")
            combined_prompt = (
                "Pedido do usuário para o relatório:\n"
                f"\"{user_prompt}\"\n\n"
                "Gere um relatório analítico estruturado para a equipe de engenharia de software, "
                "destacando métricas relevantes, hotspots, rastreabilidade de requisitos e recomendações."
            )

        # 2. Busca os dados brutos para a análise - Passa user_id
        dados_brutos = metadata_service.get_all_documents_by_repo(user_id, repo_name)
        if not dados_brutos:
            print("[WorkerTask] Nenhum dado encontrado no SQL para este repositório.")

        print(f"[WorkerTask] {len(dados_brutos)} registros encontrados. Enviando para LLM...")

        # 3. Gera o JSON do relatório
        report_json_string = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=combined_prompt,
            raw_data=dados_brutos,
        )

        print("[WorkerTask] Relatório JSON gerado pela LLM.")

        # 4. Gera o CONTEÚDO (HTML) e o NOME DO ARQUIVO
        content_to_upload, filename, content_type = report_service.generate_report_content(
            repo_name, report_json_string, format, chart_image_url=None
        )

        print(f"[WorkerTask] Conteúdo '{format}' gerado. Fazendo upload de {filename}...")

        # 5. Fazer UPLOAD do conteúdo
        storage_service.upload_file_content(
            content_string=content_to_upload,
            filename=filename,
            bucket_name=SUPABASE_BUCKET_NAME,
            content_type=content_type,
        )

        print(f"[WorkerTask] Upload com sucesso! Retornando filename: {filename}")

        return filename

    except Exception as e:
        error_message = repr(e)
        print(f"[WorkerTask] ERRO detalhado durante geração do relatório: {error_message}")
        raise e


# -------------------------------------------------------------------
# TAREFA: Relatório Agendado por Email
# -------------------------------------------------------------------

def enviar_relatorio_agendado(
    agendamento_id: Optional[str],
    user_email: str,
    repo_name: str,
    user_prompt: str,
    user_id: str,
):
    """
    Tarefa do Worker (RQ) que gera um relatório e o ENVIA POR EMAIL.
    Se 'agendamento_id' for None, é um envio imediato.
    Agora vinculada a um user_id.

    O conteúdo é gerado em HTML e injetado diretamente no corpo do email.
    """
    if agendamento_id:
        print(
            f"[WorkerTask] Iniciando relatório agendado {agendamento_id} (User: {user_id}) para {user_email}"
        )
    else:
        print(
            f"[WorkerTask] Iniciando relatório imediato (User: {user_id}) para {user_email}"
        )

    try:
        llm_service = LLMService()
        report_service = ReportService()
        metadata_service = MetadataService()

        print(f"[WorkerTask] Buscando dados de {repo_name}...")

        dados_brutos = metadata_service.get_all_documents_by_repo(user_id, repo_name)
        if not dados_brutos:
            print(f"[WorkerTask] Nenhum dado encontrado para {repo_name}.")

        print("[WorkerTask] Gerando JSON da LLM para relatório de email...")

        # Prompt enriquecido para o contexto de email
        effective_prompt = (
            "Relatório solicitado para envio por email.\n\n"
            f"Pedido do usuário:\n\"{user_prompt}\"\n\n"
            "Gere um relatório claro, objetivo e visualmente organizado para ser lido no corpo do email, "
            "destacando informações-chave que ajudem a equipe a tomar decisões rápidas "
            "sobre o estado do repositório."
        )

        report_json_string = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=effective_prompt,
            raw_data=dados_brutos,
        )

        print("[WorkerTask] Gerando HTML do relatório...")

        # --- Lógica do Gráfico Estático (QuickChart) ---
        chart_image_url = None
        try:
            report_data = json.loads(report_json_string)
            chart_json = report_data.get("chart_json")

            if chart_json:
                print("[WorkerTask] Gerando imagem estática do gráfico via QuickChart...")
                qc_response = requests.post(
                    "https://quickchart.io/chart/create",
                    json={
                        "chart": chart_json,
                        "backgroundColor": "#ffffff",
                        "format": "png",
                        "width": 600,
                        "height": 400,
                    },
                )
                qc_response.raise_for_status()
                chart_image_url = qc_response.json().get("url")
                print(f"[WorkerTask] URL do gráfico gerada: {chart_image_url}")

        except Exception as e:
            print(f"[WorkerTask] AVISO: Falha ao gerar gráfico estático: {e}")
            chart_image_url = None
        # --- Fim da Lógica QuickChart ---

        html_content, _, _ = report_service.generate_report_content(
            repo_name,
            report_json_string,
            "html",
            chart_image_url,
        )

        print(f"[WorkerTask] Enviando email para {user_email}...")
        subject = f"Seu Relatório GitRAG: {repo_name}"
        send_report_email(user_email, subject, html_content)

        # Atualiza o 'ultimo_envio' (APENAS se for um job agendado)
        if agendamento_id:
            url: str = os.getenv("SUPABASE_URL")
            key: str = os.getenv("SUPABASE_KEY")
            supabase: Client = create_client(url, key)

            supabase.table("agendamentos").update(
                {"ultimo_envio": datetime.now(pytz.utc).isoformat()}
            ).eq("id", agendamento_id).execute()

            print(f"[WorkerTask] Relatório agendado {agendamento_id} concluído com sucesso.")
        else:
            print(f"[WorkerTask] Relatório imediato para {user_email} concluído.")

    except Exception as e:
        print(f"[WorkerTask] ERRO CRÍTICO no job de {user_email}: {e}")
        raise e


# -------------------------------------------------------------------
# TAREFA: Ingestão por Webhook (Delta) - Multi-Tenancy
# -------------------------------------------------------------------

def _parse_issue_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    TODO: Implementar parsing de payload de issues do GitHub
    para o formato de documentos esperado pelo MetadataService.
    """
    # Implementação real deve ir aqui.
    return []


def _parse_push_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    TODO: Implementar parsing de payload de push (commits) do GitHub
    para o formato de documentos esperado pelo MetadataService.
    """
    # Implementação real deve ir aqui.
    return []


def process_webhook_payload(event_type: str, payload: Dict[str, Any]):
    """
    Tarefa do Worker (RQ) que processa um webhook do GitHub (Ingestão Delta).

    Logicamente:
    - Converte o payload em documentos (issues, commits, etc.).
    - Descobre quais usuários estão rastreando aquele repositório.
    - Replica os documentos para cada user_id correspondente (multi-tenant).
    """
    print(f"[WebhookWorker] Processando evento: {event_type}")
    try:
        metadata_service = MetadataService()

        documentos_para_salvar: List[Dict[str, Any]] = []
        if event_type == "issues":
            documentos_para_salvar = _parse_issue_payload(payload)
        elif event_type == "push":
            documentos_para_salvar = _parse_push_payload(payload)
        else:
            print(f"[WebhookWorker] Evento {event_type} não possui parser implementado. Ignorando.")
            return

        if not documentos_para_salvar:
            print("[WebhookWorker] Nenhum documento novo para salvar.")
            return

        # --- Lógica Multi-Tenancy para Webhook ---
        repo_name = documentos_para_salvar[0].get("repositorio")
        if not repo_name:
            raise Exception("Não foi possível extrair repo_name do payload do webhook.")

        user_ids = metadata_service.get_user_ids_for_repo(repo_name)
        if not user_ids:
            print(
                f"[WebhookWorker] Nenhum usuário está rastreando o repositório {repo_name}. Ignorando."
            )
            return

        print(
            f"[WebhookWorker] Webhook para {repo_name}. Inserindo dados para {len(user_ids)} usuário(s)."
        )

        for user_id in user_ids:
            print(
                f"[WebhookWorker] Salvando {len(documentos_para_salvar)} documentos para User: {user_id}..."
            )
            metadata_service.save_documents_batch(user_id, documentos_para_salvar)

        print(f"[WebhookWorker] Evento {event_type} processado com sucesso para todos os usuários.")

    except Exception as e:
        print(f"[WebhookWorker] ERRO CRÍTICO ao processar webhook {event_type}: {e}")
        raise e
