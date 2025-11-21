# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/report_service.py

import os
import markdown
import uuid
import requests
import json # <--- Importação essencial
import traceback
from typing import Dict, Any, Tuple, Optional, List

# Template Engine
from jinja2 import Environment, FileSystemLoader, select_autoescape
from premailer import transform

from supabase import create_client, Client
from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from app.services.github_service import GithubService

class SupabaseStorageService:
    """
    Serviço para fazer upload de arquivos para o Supabase Storage.
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
            response = requests.post(endpoint, data=content_string.encode('utf-8'), headers=headers)
            if response.status_code not in (200, 201):
                print(f"[StorageService] Erro upload: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"[StorageService] Exceção no upload: {e}")

class ReportService:
    """
    Serviço de Relatórios Moderno (Jinja2 + Premailer).
    """
    def __init__(
        self, 
        llm_service: LLMService, 
        metadata_service: MetadataService,
        github_service: GithubService
    ):
        try:
            if not llm_service or not metadata_service or not github_service:
                raise ValueError("Dependências obrigatórias não fornecidas.")
                
            self.llm_service = llm_service
            self.metadata_service = metadata_service
            self.github_service = github_service
            self.storage_service = SupabaseStorageService()
            
            # --- CONFIGURAÇÃO DO JINJA2 ---
            template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
            self.env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=select_autoescape(['html', 'xml'])
            )
            
            # --- CORREÇÃO CRÍTICA: ADICIONA O FILTRO 'tojson' ---
            # Como não estamos usando Flask, precisamos ensinar o Jinja2 a fazer dump de JSON
            def tojson_filter(value):
                return json.dumps(value)
                
            self.env.filters['tojson'] = tojson_filter
            # ----------------------------------------------------
            
            print(f"[ReportService] Inicializado. Templates em: {template_dir}")
            
        except Exception as e:
            print(f"[ReportService] Erro crítico ao inicializar: {e}")
            raise
    
    def _prepare_data(self, repo_url: str, prompt: str, user_id: str, branch_default="main"):
        repo_name, branch = self.github_service.parse_repo_url(repo_url)
        if not branch: branch = branch_default
        
        raw_data = self.metadata_service.get_all_documents_for_repository(
            user_id, repo_name, branch=branch
        )
        
        # --- CORREÇÃO: Lidar com repositório vazio ou não indexado ---
        if not raw_data:
            print(f"[ReportService] Nenhum dado encontrado para {repo_name}. Gerando relatório de inatividade.")
            return repo_name, {
                "analysis_markdown": f"## Relatório de Status\n\nNão foram encontrados dados indexados para o repositório **{repo_name}** neste momento.\n\nIsso pode indicar que:\n1. O repositório ainda não foi ingerido.\n2. O repositório está vazio.\n3. Não houve atividade recente registrada no banco de dados.",
                "chart_json": None
            }
            
        llm_output_str = self.llm_service.generate_analytics_report(repo_name, prompt, raw_data)
        
        try:
            llm_data = json.loads(llm_output_str)
        except json.JSONDecodeError:
            llm_data = {"analysis_markdown": llm_output_str, "chart_json": None}
            
        # --- NOVA CAMADA DE SANITIZAÇÃO ---
        if llm_data.get("analysis_markdown"):
            clean_text = llm_data["analysis_markdown"]
            # Remove alucinações comuns de 'null'
            clean_text = clean_text.replace("json null", "")
            clean_text = clean_text.replace("`null`", "")
            clean_text = clean_text.replace("```json\nnull\n```", "")
            llm_data["analysis_markdown"] = clean_text.strip()    
        return repo_name, llm_data

    # --- DOWNLOAD (WEB) ---
    def gerar_e_salvar_relatorio(self, user_id: str, repo_url: str, prompt: str, formato: str = "html") -> str:
        print(f"[ReportService] Gerando relatório Web para: {repo_url}")
        try:
            repo_name, llm_data = self._prepare_data(repo_url, prompt, user_id)
            
            if formato.lower() == "html":
                markdown_text = llm_data.get("analysis_markdown", "")
                html_body = markdown.markdown(markdown_text, extensions=['tables', 'fenced_code'])
                chart_config = llm_data.get("chart_json")

                template = self.env.get_template("web.html")
                final_html = template.render(
                    repo_name=repo_name,
                    html_body=html_body,
                    chart_config=chart_config
                )
                
                content_string = final_html
                content_type = "text/html; charset=utf-8"
                ext = "html"
            else:
                content_string = json.dumps(llm_data)
                content_type = "application/json; charset=utf-8"
                ext = "json"
            
            unique_id = str(uuid.uuid4()).split('-')[0]
            filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.{ext}"
            self.storage_service.upload_file_content(content_string, filename, content_type)
            
            return filename

        except Exception as e:
            print(f"[ReportService] Erro Download: {e}")
            traceback.print_exc()
            return "error_report.html"

    # --- EMAIL ---
    def gerar_relatorio_html(self, user_id: str, repo_url: str, prompt: str) -> Tuple[str, str]:
        print(f"[ReportService] Gerando relatório Email para: {repo_url}")
        try:
            repo_name, llm_data = self._prepare_data(repo_url, prompt, user_id)
            
            markdown_text = llm_data.get("analysis_markdown", "")
            html_body = markdown.markdown(markdown_text, extensions=['tables'])
            chart_config = llm_data.get("chart_json")
            
            short_chart_url = None
            if chart_config:
                short_chart_url = self._get_short_chart_url(chart_config)

            template = self.env.get_template("email.html")
            rendered_html = template.render(
                repo_name=repo_name,
                html_body=html_body,
                chart_url=short_chart_url
            )
            
            final_email_html = transform(rendered_html)
            unique_id = str(uuid.uuid4()).split('-')[0]
            filename = f"{repo_name.replace('/', '_')}_email_{unique_id}.html"
            
            return final_email_html, filename

        except Exception as e:
            print(f"[ReportService] Erro Email: {e}")
            traceback.print_exc()
            return "<html><body><h1>Erro ao gerar relatório</h1></body></html>", "error.html"

    def _get_short_chart_url(self, chart_config: Dict[str, Any]) -> Optional[str]:
        try:
            if not isinstance(chart_config, dict): return None
            
            # Garante estrutura básica
            if 'type' not in chart_config: chart_config['type'] = 'bar'
            if 'data' not in chart_config: chart_config['data'] = {'labels': [], 'datasets': []}
            if 'options' not in chart_config: chart_config['options'] = {}
            
            # --- TEMA DARK PARA O GRÁFICO (Imagem Estática) ---
            TEXT_COLOR = '#c9d1d9'
            GRID_COLOR = '#30363d'
            
            # Injeta configurações de estilo no JSON do Chart.js
            # Isso simula o que fizemos via JavaScript no web.html
            
            # 1. Legendas e Títulos
            chart_config['options'].update({
                "plugins": {
                    "legend": {
                        "labels": {
                            "color": TEXT_COLOR, 
                            "font": {"size": 14}
                        }
                    },
                    "title": {
                        "display": True, 
                        "text": "Análise Visual", 
                        "color": TEXT_COLOR,
                        "font": {"size": 16}
                    }
                }
            })
            
            # 2. Eixos (Scales)
            # Precisamos garantir que 'scales' exista para injetar as cores
            if 'scales' not in chart_config['options']:
                chart_config['options']['scales'] = {}
                
            scales = chart_config['options']['scales']
            
            # Configuração padrão para eixos X e Y
            axis_style = {
                "grid": {"color": GRID_COLOR},
                "ticks": {"color": "#8b949e"}
            }
            
            scales['x'] = {**scales.get('x', {}), **axis_style}
            scales['y'] = {**scales.get('y', {}), **axis_style}

            # 3. Payload para QuickChart
            qc_payload = {
                "chart": chart_config,
                "width": 600, 
                "height": 350, 
                "backgroundColor": "#161b22", # Fundo Dark (igual ao .chart-box)
                "format": "png"
            }
            
            response = requests.post('https://quickchart.io/chart/create', json=qc_payload, timeout=5)
            if response.status_code == 200 and response.json().get('success'):
                return response.json()['url']
            return None
        except Exception as e: 
            print(f"[ReportService] Erro ao gerar gráfico: {e}")
            return None