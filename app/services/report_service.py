# CÓDIGO COMPLETO PARA: app/services/report_service.py
# (Implementa o RAG de Instruções no processamento do relatório)

import os
import markdown
import uuid
import requests
import json
from supabase import create_client, Client
from typing import Dict, Any, Tuple
from .metadata_service import MetadataService, find_similar_instruction # <-- IMPORTAÇÃO ATUALIZADA
from .llm_service import LLMService

# --- SERVIÇO DE ARMAZENAMENTO SUPABASE ---
# (Sem alterações - continua usando 'requests' para upload manual)
class SupabaseStorageService:
    def __init__(self):
        self.url: str = os.getenv('SUPABASE_URL')
        self.key: str = os.getenv('SUPABASE_KEY')
        if not self.url or not self.key:
            raise ValueError("Variáveis de ambiente 'SUPABASE_URL' e 'SUPABASE_KEY' não definidas.")
        self.client: Client = create_client(self.url, self.key)

    def upload_file_content(self, content_string: str, filename: str, bucket_name: str, content_type: str = 'text/html'):
        try:
            endpoint = f"{self.url}/storage/v1/object/{bucket_name}/{filename}"
            headers = {
                "Authorization": f"Bearer {self.key}",
                "Content-Type": content_type,
                "x-upsert": "true",
                "Content-Disposition": f'attachment; filename="{filename}"' 
            }
            content_bytes = content_string.encode('utf-8')
            response = requests.post(
                endpoint, 
                data=content_bytes, 
                headers=headers
            )
            response.raise_for_status()
            public_url = self.client.storage.from_(bucket_name).get_public_url(filename)
            return public_url
        except requests.exceptions.HTTPError as e:
            print(f"[SUPABASE_SERVICE] Erro HTTP no upload manual: {e.response.text}")
            raise
        except Exception as e:
            print(f"[SUPABASE_SERVICE] Erro ao fazer upload manual para o Supabase: {e}")
            raise      

# --- CLASSE ReportService ---
# (Sem alterações - continua gerando o HTML do Chart.js)
class ReportService:
    def __init__(self):
        pass
    
    def generate_html_report_content(self, repo_name: str, llm_json_output: str) -> Tuple[str, str]:
        try:
            report_data = json.loads(llm_json_output)
            analysis_markdown = report_data.get("analysis_markdown", "Erro: Análise em Markdown não gerada.")
            chart_json_obj = report_data.get("chart_json")
        except json.JSONDecodeError as e:
            print(f"[ReportService] ERRO: Falha ao parsear JSON da LLM: {e}")
            html_body = f"<h1>Erro do Servidor</h1><p>Ocorreu um erro ao gerar o relatório. A resposta da IA não estava em formato JSON válido.</p><h3>Resposta Recebida:</h3><pre><code>{llm_json_output}</code></pre>"
            chart_json_obj = None
        else:
            html_body = markdown.markdown(analysis_markdown, extensions=['tables', 'fenced_code'])

        chart_script_data = json.dumps(chart_json_obj) if chart_json_obj else 'null'

        template_html = f"""
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relatório de Análise: {repo_name}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; line-height: 1.6; background-color: #0d1117; color: #c9d1d9; padding: 20px 40px; }}
        main {{ max-width: 800px; margin: 0 auto; border: 1px solid #30363d; border-radius: 8px; padding: 24px; }}
        h1, h2, h3 {{ border-bottom: 1px solid #30363d; padding-bottom: 8px; color: #58a6ff; }}
        code {{ font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; background-color: #161b22; padding: 0.2em 0.4em; font-size: 85%; border-radius: 6px; }}
        pre {{ background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; overflow: auto; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 1em; margin-bottom: 1em; }}
        th, td {{ border: 1px solid #30363d; padding: 8px 12px; }}
        th {{ background-color: #161b22; }}
        .chart-container {{ background-color: #ffffff; border-radius: 8px; padding: 16px; margin-top: 20px; }}
    </style>
</head>
<body>
    <main>
        <h1>Relatório de Análise</h1>
        <h2>Repositório: {repo_name}</h2>
        {html_body}
        <div class="chart-container">
            <canvas id="analyticsChart"></canvas>
        </div>
    </main>
    <script>
        const chartData = {chart_script_data};
        if (chartData && chartData.data) {{
            try {{
                const ctx = document.getElementById('analyticsChart').getContext('2d');
                Chart.defaults.color = '#333';
                new Chart(ctx, {{
                    type: chartData.type,
                    data: chartData.data,
                    options: chartData.options
                }});
            }} catch (e) {{
                console.error("Erro ao renderizar o Chart.js:", e);
                const container = document.querySelector('.chart-container');
                container.innerHTML = "<p style='color: #333;'>Erro ao renderizar o gráfico.</p>";
            }}
        }} else {{
            const container = document.querySelector('.chart-container');
            if (container) {{ container.style.display = 'none'; }}
        }}
    </script>
</body>
</html>
        """
        
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.html"
        return template_html, filename

    def generate_report_content(self, repo_name: str, content_json_str: str, format: str = "html") -> Tuple[str, str, str]:
        if format.lower() == "html":
            content_string, filename = self.generate_html_report_content(repo_name, content_json_str)
            return content_string, filename, "text/html; charset=utf-8"
        else:
            unique_id = str(uuid.uuid4()).split('-')[0]
            filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.json"
            return content_json_str, filename, "application/json; charset=utf-8"

# --- FUNÇÃO DO WORKER (ATUALIZADA - Marco 7) ---
        
def processar_e_salvar_relatorio(repo_name: str, user_prompt: str, format: str = "html"):
    """
    Tarefa do Worker (RQ) que gera um relatório para DOWNLOAD.
    AGORA usa RAG para buscar instruções salvas.
    """
    SUPABASE_BUCKET_NAME = "reports" 
    
    try:
        # 1. Inicializa os serviços
        metadata_service = MetadataService()
        llm_service = LLMService()
        report_service = ReportService()
        supabase_service = SupabaseStorageService()
        
    except Exception as e:
        print(f"[WORKER-REPORTS] Erro ao inicializar serviços: {repr(e)}")
        return f"Erro ao inicializar serviços: {repr(e)}"

    try:
        print(f"[WORKER-REPORTS] Iniciando relatório (com RAG) para: {repo_name}")
        
        # --- INÍCIO DA LÓGICA RAG (Marco 7) ---
        
        # 2. Busca uma instrução salva (RAG)
        # (Usa o prompt do usuário para encontrar a instrução mais relevante)
        retrieved_instruction = find_similar_instruction(repo_name, user_prompt)
        
        if retrieved_instruction:
            print(f"[WORKER-REPORTS] Instrução RAG encontrada. Combinando prompts...")
            combined_prompt = f"""
            Instrução Base do Usuário:
            '{user_prompt}'
            
            Contexto/Instrução Salva (Siga esta regra):
            '{retrieved_instruction}'
            
            Gere o relatório combinando as duas instruções.
            """
        else:
            print(f"[WORKER-REPORTS] Nenhuma instrução RAG encontrada. Usando prompt padrão.")
            combined_prompt = user_prompt
            
        # --- FIM DA LÓGICA RAG ---

        # 3. Busca os dados brutos para a análise (do Marco 4)
        try:
            dados_brutos = metadata_service.get_all_documents_by_repo(repo_name)
        except AttributeError:
             print("[WORKER-REPORTS] AVISO: metadata_service.get_all_documents_by_repo() não encontrada.")
             dados_brutos = [] 
        
        if not dados_brutos:
            print("[WORKER-REPORTS] Nenhum dado encontrado no SQL. A LLM usará apenas o prompt.")

        print(f"[WORKER-REPORTS] {len(dados_brutos)} registos encontrados. Enviando para LLM...")

        # 4. Gera o JSON do relatório (usando o prompt combinado)
        report_json_string = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=combined_prompt, # <-- Usa o prompt combinado
            raw_data=dados_brutos
        )
        
        print("[WORKER-REPORTS] Relatório JSON gerado pela LLM. Preparando para upload...")

        # 5. Gera o CONTEÚDO (HTML) e o NOME DO ARQUIVO
        (content_to_upload, filename, content_type) = report_service.generate_report_content(
            repo_name, 
            report_json_string,
            format
        )
        
        print(f"[WORKER-REPORTS] Conteúdo HTML gerado. Fazendo upload de {filename} para Supabase...")
        
        # 6. Fazer UPLOAD do conteúdo
        supabase_service.upload_file_content(
            content_string=content_to_upload,
            filename=filename,
            bucket_name=SUPABASE_BUCKET_NAME,
            content_type=content_type
        )
        
        print(f"[WORKER-REPORTS] Upload com sucesso! Retornando filename: {filename}")
        
        # 7. Retornar o nome do arquivo (para o App.js baixar)
        return filename
        
    except Exception as e:
        error_message = repr(e)
        print(f"[WORKER-REPORTS] Erro detalhado durante geração de relatório: {error_message}")
        return f"Erro durante a geração do relatório: {error_message}"