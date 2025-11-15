# CÓDIGO COMPLETO PARA: worker_tasks.py
# (Novo arquivo - Coloque na pasta RAIZ do seu backend)
# Este arquivo define as funções que o worker.py irá executar.

from app.services.metadata_service import get_all_documents_by_repo
from app.services.llm_service import LLMService
from app.services.report_service import ReportService
from app.services.email_service import send_report_email
from supabase import create_client
import os
from datetime import datetime
import pytz

def enviar_relatorio_agendado(agendamento_id: str, user_email: str, repo_name: str, user_prompt: str):
    """
    Tarefa do Worker (RQ) que gera um relatório e o ENVIA POR EMAIL.
    """
    print(f"[WorkerTask] Iniciando relatório agendado {agendamento_id} para {user_email}")
    
    try:
        # 1. Inicializa os serviços (dentro da tarefa)
        llm_service = LLMService()
        report_service = ReportService()
        
        # 2. Busca os dados para a análise (igual ao Marco 4)
        print(f"[WorkerTask] Buscando dados de {repo_name}...")
        dados_brutos = get_all_documents_by_repo(repo_name)
        if not dados_brutos:
            print(f"[WorkerTask] Nenhum dado encontrado para {repo_name}.")
            # (Podemos optar por enviar um email vazio ou pular)
            
        # 3. Gera o JSON da LLM (igual ao Marco 4)
        print(f"[WorkerTask] Gerando JSON da LLM...")
        report_json_string = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=user_prompt,
            raw_data=dados_brutos
        )
        
        # 4. Gera o CONTEÚDO HTML (igual ao Marco 4)
        print(f"[WorkerTask] Gerando HTML do relatório...")
        (html_content, _, _) = report_service.generate_report_content(
            repo_name,
            report_json_string,
            "html"
        )
        
        # 5. ENVIA O EMAIL (Novo!)
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
        # O RQ irá capturar este erro e marcar o job como 'failed'
        raise