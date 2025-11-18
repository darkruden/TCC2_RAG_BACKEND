# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/report_service.py
# (Adiciona GithubService na injeção de dependência)

import os
import markdown
import uuid
import requests
import json
from supabase import create_client, Client
from typing import Dict, Any, Tuple, Optional, List
import traceback

# Importa os serviços que serão INJETADOS
from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from app.services.github_service import GithubService # <--- NOVO IMPORT

class SupabaseStorageService:
    """
    Serviço para fazer upload de arquivos (relatórios) para o Supabase Storage.
    """
    def __init__(self):
        self.url: str = os.getenv('SUPABASE_URL')
        self.key: str = os.getenv('SUPABASE_KEY')
        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
        self.client: Client = create_client(self.url, self.key)
        self.bucket_name = "reports" 

    def upload_file_content(self, content_string: str, filename: str, content_type: str = 'text/html'):
        try:
            endpoint = f"{self.url}/storage/v1/object/{self.bucket_name}/{filename}"
            headers = {
                "Authorization": f"Bearer {self.key}", "Content-Type": content_type,
                "x-upsert": "true", "Content-Disposition": f'attachment; filename="{filename}"' 
            }
            content_bytes = content_string.encode('utf-8')
            response = requests.post(endpoint, data=content_bytes, headers=headers)
            response.raise_for_status()
            public_url = self.client.storage.from_(self.bucket_name).get_public_url(filename)
            print(f"[SupabaseStorageService] Upload bem-sucedido: {public_url}")
            return public_url
        except requests.exceptions.HTTPError as e:
            print(f"[SupabaseStorageService] Erro HTTP no upload manual: {e.response.text}")
            raise
        except Exception as e:
            print(f"[SupabaseStorageService] Erro ao fazer upload manual: {e}")
            raise      

class ReportService:
    """
    Serviço que coordena a geração de relatórios.
    """
    def __init__(
        self, 
        llm_service: LLMService, 
        metadata_service: MetadataService,
        github_service: GithubService # <--- NOVA DEPENDÊNCIA
    ):
        try:
            if not llm_service or not metadata_service or not github_service:
                raise ValueError("LLMService, MetadataService e GithubService são obrigatórios.")
                
            self.llm_service = llm_service
            self.metadata_service = metadata_service
            self.github_service = github_service # <--- GUARDANDO A REFERÊNCIA
            self.storage_service = SupabaseStorageService()
            print("[ReportService] Serviços (LLM, Metadata, GitHub, Storage) injetados/inicializados.")
        except Exception as e:
            print(f"[ReportService] Erro crítico ao inicializar: {e}")
            raise
    
    def gerar_e_salvar_relatorio(
        self, 
        user_id: str, 
        repo_url: str, 
        prompt: str, 
        formato: str = "html"
    ) -> str:
        print(f"[ReportService] 1. Iniciando 'gerar_e_salvar_relatorio' para User: {user_id}, Repo: {repo_url}")
        
        # CORREÇÃO: Usa self.github_service diretamente, não via metadata_service
        repo_name = self.github_service.parse_repo_url(repo_url)
        
        try:
            print(f"[ReportService] 2. Buscando todos os documentos para {repo_name}...")
            raw_data: List[Dict[str, Any]] = self.metadata_service.get_all_documents_for_repository(
                user_id, repo_name
            )
            if not raw_data:
                print(f"[ReportService] AVISO: Nenhum documento encontrado para {repo_name}.")
            
            print(f"[ReportService] 3. Enviando {len(raw_data)} documentos para generate_analytics_report...")
            llm_json_output: str = self.llm_service.generate_analytics_report(
                repo_name, prompt, raw_data
            )
            
            print(f"[ReportService] 4. Formatando saída da LLM para {formato}...")
            content_string, filename, content_type = self.generate_report_content(
                repo_name, llm_json_output, formato
            )
            
            print(f"[ReportService] 5. Fazendo upload de {filename} para o Storage...")
            self.storage_service.upload_file_content(content_string, filename, content_type)
            
            print(f"[ReportService] 6. Relatório salvo com sucesso: {filename}")
            return filename
            
        except Exception as e:
            print(f"[ReportService] ERRO CRÍTICO em 'gerar_e_salvar_relatorio': {e}")
            traceback.print_exc()
            return "error_report.html"

    def gerar_relatorio_html(
        self, 
        user_id: str, 
        repo_url: str, 
        prompt: str
    ) -> Tuple[str, str]:
        print(f"[ReportService] 1. Iniciando 'gerar_relatorio_html' (para email) para User: {user_id}, Repo: {repo_url}")
        
        # CORREÇÃO: Usa self.github_service diretamente
        repo_name = self.github_service.parse_repo_url(repo_url)

        try:
            print(f"[ReportService] 2. Buscando todos os documentos para {repo_name}...")
            raw_data = self.metadata_service.get_all_documents_for_repository(user_id, repo_name)
            
            print(f"[ReportService] 3. Enviando {len(raw_data)} documentos para LLM...")
            llm_json_output = self.llm_service.generate_analytics_report(
                repo_name, prompt, raw_data
            )
            
            print(f"[ReportService] 4. Formatando saída da LLM para HTML...")
            html_content, filename = self.generate_html_report_content(
                repo_name, llm_json_output, chart_image_url=None
            )
            
            print(f"[ReportService] 5. Geração de HTML concluída: {filename}")
            return html_content, filename

        except Exception as e:
            print(f"[ReportService] ERRO CRÍTICO em 'gerar_relatorio_html': {e}")
            traceback.print_exc()
            return "<html><body><h1>Erro ao gerar relatório</h1></body></html>", "error_report.html"

    
    def generate_html_report_content(
        self, 
        repo_name: str, 
        llm_json_output: str, 
        chart_image_url: Optional[str] = None
    ) -> Tuple[str, str]:
        try:
            report_data = json.loads(llm_json_output)
            analysis_markdown = report_data.get("analysis_markdown", "Erro: Análise em Markdown não gerada.")
            chart_json_obj = report_data.get("chart_json")
        except json.JSONDecodeError as e:
            print(f"[ReportService] ERRO: Falha ao parsear JSON da LLM: {e}")
            analysis_markdown = "<h1>Erro do Servidor</h1><p>Ocorreu um erro ao gerar o relatório...</p>"
            chart_json_obj = None
        
        html_body = markdown.markdown(analysis_markdown, extensions=['tables', 'fenced_code'])
        
        chart_html = ""
        if chart_image_url:
            chart_html = f'<div class="chart-container"><img src="{chart_image_url}" alt="Gráfico de Análise" style="width:100%; max-width:600px;"></div>'
        else:
            chart_script_data = json.dumps(chart_json_obj) if chart_json_obj else 'null'
            chart_html = f"""
<div class="chart-container" style="background-color: #ffffff; border-radius: 8px; padding: 16px; margin-top: 20px;">
    <canvas id="analyticsChart"></canvas>
</div>
<script>
    const chartData = {chart_script_data};
    if (chartData && chartData.data && window.Chart) {{
        try {{
            const ctx = document.getElementById('analyticsChart').getContext('2d');
            Chart.defaults.color = '#333';
            new Chart(ctx, {{ type: chartData.type, data: chartData.data, options: chartData.options }});
        }} catch (e) {{ console.error("Erro Chart.js:", e); }}
    }} else if (!window.Chart) {{
        console.log("Chart.js não carregado.");
    }} else {{
        const container = document.querySelector('.chart-container');
        if (container) {{ container.style.display = 'none'; }}
    }}
</script>
"""
        template_html = f"""
<!DOCTYPE html><html lang="pt-br"><head><meta charset="UTF-8"><title>Relatório: {repo_name}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.6; background-color: #f6f8fa; color: #24292e; padding: 20px 40px; margin: 0; }}
main {{ max-width: 800px; margin: 0 auto; border: 1px solid #d0d7de; border-radius: 8px; padding: 24px; background-color: #ffffff; }}
h1, h2, h3 {{ border-bottom: 1px solid #d8dee4; padding-bottom: 8px; color: #0969da; }}
code {{ font-family: "SFMono-Regular", Consolas, monospace; background-color: #f6f8fa; padding: 0.2em 0.4em; font-size: 85%; border-radius: 6px; }}
pre {{ background-color: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; padding: 16px; overflow: auto; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1em; margin-bottom: 1em; }}
th, td {{ border: 1px solid #d0d7de; padding: 8px 12px; }}
th {{ background-color: #f6f8fa; }}
@media (prefers-color-scheme: dark) {{
    body {{ background-color: #0d1117; color: #c9d1d9; }}
    main {{ background-color: #161b22; border-color: #30363d; }}
    h1, h2, h3 {{ color: #58a6ff; border-color: #30363d; }}
    code {{ background-color: #2b3036; }}
    pre {{ background-color: #161b22; border-color: #30363d; }}
    th, td {{ border-color: #30363d; }}
    th {{ background-color: #2b3036; }}
    .chart-container {{ background-color: #ffffff !important; }} 
}}
</style></head><body><main>
<h1>Relatório de Análise</h1><h2>Repositório: {repo_name}</h2>
{html_body}
{chart_html}
</main>
</body></html>
"""
        
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.html"
        return template_html, filename

    def generate_report_content(
        self, 
        repo_name: str, 
        content_json_str: str, 
        format: str = "html",
        chart_image_url: Optional[str] = None
    ) -> Tuple[str, str, str]:
        if format.lower() == "html":
            content_string, filename = self.generate_html_report_content(
                repo_name, 
                content_json_str, 
                chart_image_url
            )
            return content_string, filename, "text/html; charset=utf-8"
        else:
            unique_id = str(uuid.uuid4()).split('-')[0]
            filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.json"
            return content_json_str, filename, "application/json; charset=utf-8"