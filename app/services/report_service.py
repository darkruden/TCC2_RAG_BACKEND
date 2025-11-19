# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/report_service.py

import os
import markdown
import uuid
import requests
import json
import urllib.parse
from supabase import create_client, Client
from typing import Dict, Any, Tuple, Optional, List
import traceback

# Importa os serviços que serão INJETADOS
from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from app.services.github_service import GithubService

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
                "Authorization": f"Bearer {self.key}",
                "Content-Type": content_type,
                "x-upsert": "true",
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
            # Garante utf-8 para não quebrar acentos
            response = requests.post(endpoint, data=content_string.encode('utf-8'), headers=headers)
            if response.status_code not in (200, 201):
                print(f"[StorageService] Erro upload: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"[StorageService] Exceção no upload: {e}")

class ReportService:
    """
    Serviço que coordena a geração de relatórios.
    """
    def __init__(
        self, 
        llm_service: LLMService, 
        metadata_service: MetadataService,
        github_service: GithubService
    ):
        try:
            if not llm_service or not metadata_service or not github_service:
                raise ValueError("LLMService, MetadataService e GithubService são obrigatórios.")
                
            self.llm_service = llm_service
            self.metadata_service = metadata_service
            self.github_service = github_service
            self.storage_service = SupabaseStorageService()
            print("[ReportService] Serviços inicializados.")
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
        print(f"[ReportService] Iniciando relatório (User: {user_id}) para: {repo_url}")
        
        repo_name, branch = self.github_service.parse_repo_url(repo_url)
        if not branch: branch = "main"
        
        try:
            # Busca documentos filtrando pela branch correta
            raw_data = self.metadata_service.get_all_documents_for_repository(
                user_id, repo_name, branch=branch
            )
            
            if not raw_data:
                print(f"[ReportService] AVISO: Nenhum documento encontrado para {repo_name}.")
                return "error_report.html"
            
            llm_json_output = self.llm_service.generate_analytics_report(repo_name, prompt, raw_data)
            content_string, filename, content_type = self.generate_report_content(repo_name, llm_json_output, formato)
            
            self.storage_service.upload_file_content(content_string, filename, content_type)
            return filename
            
        except Exception as e:
            print(f"[ReportService] ERRO CRÍTICO: {e}")
            traceback.print_exc()
            return "error_report.html"

    def gerar_relatorio_html(self, user_id: str, repo_url: str, prompt: str) -> Tuple[str, str]:
        """
        Gera o HTML do relatório para EMAIL (usa imagem estática).
        """
        repo_name, branch = self.github_service.parse_repo_url(repo_url)
        if not branch: branch = "main"

        try:
            raw_data = self.metadata_service.get_all_documents_for_repository(
                user_id, repo_name, branch=branch
            )
            
            llm_output_str = self.llm_service.generate_analytics_report(repo_name, prompt, raw_data)
            
            try:
                llm_data = json.loads(llm_output_str)
            except json.JSONDecodeError:
                llm_data = {"analysis_markdown": llm_output_str, "chart_json": None}

            # Usa o método estático (QuickChart) para o email
            html_content, filename = self.generate_static_html_report(repo_name, llm_data)
            
            return html_content, filename

        except Exception as e:
            print(f"[ReportService] Erro: {e}")
            traceback.print_exc()
            return "<html><body><h1>Erro ao gerar relatório</h1></body></html>", "error_report.html"

    def generate_static_html_report(self, repo_name: str, llm_data: Dict[str, Any]) -> Tuple[str, str]:
        """
        Cria um HTML onde o gráfico é uma IMAGEM (<img>) gerada pelo QuickChart.io.
        """
        markdown_text = llm_data.get("analysis_markdown", "Sem análise.")
        chart_config = llm_data.get("chart_json")
        
        html_body = markdown.markdown(markdown_text, extensions=['tables'])
        
        # --- LÓGICA DO GRÁFICO ESTÁTICO (CORRIGIDA) ---
        chart_img_tag = ""
        if chart_config and isinstance(chart_config, dict):
            try:
                # 1. Validação e Correção do JSON
                # Se a IA esqueceu o tipo, assumimos barra
                if 'type' not in chart_config: 
                    chart_config['type'] = 'bar'
                # Se não tem data, criamos estrutura vazia para não quebrar
                if 'data' not in chart_config: 
                    chart_config['data'] = {'labels': [], 'datasets': []}

                # 2. Configuração QuickChart
                # backgroundColor 'white' é crucial para emails (muitos têm fundo escuro ou cinza)
                qc_config = {
                    "backgroundColor": "white",
                    "width": 600,
                    "height": 350,
                    "format": "png",
                    "chart": chart_config
                }
                
                config_str = json.dumps(qc_config)
                # Codifica caracteres especiais para URL
                encoded_config = urllib.parse.quote(config_str)
                chart_url = f"https://quickchart.io/chart?c={encoded_config}"
                
                # Cria a tag de imagem
                chart_img_tag = f"""
                <div style="margin-top: 40px; padding: 20px; background-color: #ffffff; border: 1px solid #e1e4e8; border-radius: 8px; text-align: center;">
                    <h3 style="color: #24292f; margin-bottom: 15px; font-family: Arial, sans-serif;">Visualização de Dados</h3>
                    <img src="{chart_url}" alt="Gráfico de Análise" style="max-width: 100%; height: auto;" />
                </div>
                """
            except Exception as e:
                print(f"[ReportService] Erro ao gerar gráfico estático: {e}")

        # --- TEMPLATE HTML PARA EMAIL ---
        # CORREÇÃO DE POSIÇÃO: {html_body} vem PRIMEIRO, {chart_img_tag} vem DEPOIS.
        template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Relatório GitRAG</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #24292f; max-width: 800px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #f6f8fa; padding: 20px; border-bottom: 1px solid #d0d7de; border-radius: 6px 6px 0 0;">
                <h1 style="margin: 0; color: #0969da; font-size: 24px;">Relatório de Análise</h1>
                <p style="margin: 5px 0 0; color: #57606a;">Repositório: <strong>{repo_name}</strong></p>
            </div>
            
            <div style="padding: 30px; background-color: #fff; border: 1px solid #d0d7de; border-top: none; border-radius: 0 0 6px 6px;">
                
                <div style="margin-bottom: 30px;">
                    {html_body}
                </div>

                {chart_img_tag}
                
            </div>
            
            <div style="text-align: center; margin-top: 20px; font-size: 12px; color: #888;">
                Gerado automaticamente por GitRAG AI
            </div>
        </body>
        </html>
        """
        
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.html"
        
        return template, filename

    def generate_report_content(
        self, 
        repo_name: str, 
        content_json_str: str, 
        format: str = "html",
        chart_image_url: Optional[str] = None
    ) -> Tuple[str, str, str]:
        """
        Gera o conteúdo para DOWNLOAD (Mantém Chart.js interativo se for HTML).
        """
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

    def generate_html_report_content(self, repo_name: str, llm_json_output: str, chart_image_url: Optional[str] = None) -> Tuple[str, str]:
        try:
            report_data = json.loads(llm_json_output)
            analysis_markdown = report_data.get("analysis_markdown", "Erro: Análise não gerada.")
            chart_json_obj = report_data.get("chart_json")
        except json.JSONDecodeError:
            analysis_markdown = "Erro ao processar resposta da IA."
            chart_json_obj = None
        
        html_body = markdown.markdown(analysis_markdown, extensions=['tables'])
        
        # Chart.js para versão interativa (Download)
        chart_html = ""
        if chart_json_obj:
             chart_script_data = json.dumps(chart_json_obj)
             chart_html = f"""
             <div class="chart-container" style="background-color: #fff; padding: 20px; border-radius: 8px; margin-top: 30px; border: 1px solid #eee;">
                <h3 style="text-align:center; margin-bottom: 10px;">Visualização Interativa</h3>
                <canvas id="analyticsChart"></canvas>
             </div>
             <script>
                const chartData = {chart_script_data};
                if (chartData && window.Chart) {{
                    new Chart(document.getElementById('analyticsChart'), {{
                        type: chartData.type || 'bar',
                        data: chartData.data,
                        options: chartData.options || {{}}
                    }});
                }}
             </script>
             """

        template_html = f"""
<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<title>Relatório: {repo_name}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
    body {{ font-family: sans-serif; line-height: 1.6; background: #f4f4f4; padding: 20px; }}
    main {{ max-width: 800px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
    h1 {{ color: #0366d6; border-bottom: 1px solid #eee; padding-bottom: 10px; }}
    img {{ max-width: 100%; }}
    table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f2f2f2; }}
</style>
</head>
<body>
<main>
    <h1>Relatório: {repo_name}</h1>
    {html_body}
    {chart_html}
</main>
</body>
</html>
"""
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.html"
        return template_html, filename