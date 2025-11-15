# CÓDIGO COMPLETO PARA: app/services/report_service.py
# (Refatorado para usar Classes)

import os
import markdown
import uuid
import requests
import json
from supabase import create_client, Client
from typing import Dict, Any, Tuple
from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService

# (SupabaseStorageService não muda, mas precisa ser parte da classe)
class SupabaseStorageService:
    def __init__(self):
        self.url: str = os.getenv('SUPABASE_URL')
        self.key: str = os.getenv('SUPABASE_KEY')
        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
        self.client: Client = create_client(self.url, self.key)

    def upload_file_content(self, content_string: str, filename: str, bucket_name: str, content_type: str = 'text/html'):
        try:
            endpoint = f"{self.url}/storage/v1/object/{bucket_name}/{filename}"
            headers = {
                "Authorization": f"Bearer {self.key}", "Content-Type": content_type,
                "x-upsert": "true", "Content-Disposition": f'attachment; filename="{filename}"' 
            }
            content_bytes = content_string.encode('utf-8')
            response = requests.post(endpoint, data=content_bytes, headers=headers)
            response.raise_for_status()
            public_url = self.client.storage.from_(bucket_name).get_public_url(filename)
            return public_url
        except requests.exceptions.HTTPError as e:
            print(f"[SUPABASE_SERVICE] Erro HTTP no upload manual: {e.response.text}")
            raise
        except Exception as e:
            print(f"[SUPABASE_SERVICE] Erro ao fazer upload manual para o Supabase: {e}")
            raise      

class ReportService:
    """
    Serviço que coordena a geração de relatórios.
    """
    def __init__(self):
        try:
            self.metadata_service = MetadataService()
            self.llm_service = LLMService()
            self.storage_service = SupabaseStorageService()
            print("[ReportService] Serviços LLM, Metadata e Storage inicializados.")
        except Exception as e:
            print(f"[ReportService] Erro crítico ao inicializar serviços dependentes: {e}")
            raise
    
    def _generate_html_report_content(self, repo_name: str, llm_json_output: str) -> Tuple[str, str]:
        # (Esta é a função 'generate_html_report_content' anterior, agora privada)
        try:
            report_data = json.loads(llm_json_output)
            analysis_markdown = report_data.get("analysis_markdown", "Erro: Análise em Markdown não gerada.")
            chart_json_obj = report_data.get("chart_json")
        except json.JSONDecodeError as e:
            print(f"[ReportService] ERRO: Falha ao parsear JSON da LLM: {e}")
            html_body = f"<h1>Erro do Servidor</h1><p>Ocorreu um erro ao gerar o relatório...</p>"
            chart_json_obj = None
        else:
            html_body = markdown.markdown(analysis_markdown, extensions=['tables', 'fenced_code'])
        
        chart_script_data = json.dumps(chart_json_obj) if chart_json_obj else 'null'
        
        # (Template HTML não muda)
        template_html = f"""
<!DOCTYPE html><html lang="pt-br"><head><meta charset="UTF-8"><title>Relatório: {repo_name}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script><style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.6; background-color: #0d1117; color: #c9d1d9; padding: 20px 40px; }}
main {{ max-width: 800px; margin: 0 auto; border: 1px solid #30363d; border-radius: 8px; padding: 24px; }}
h1, h2, h3 {{ border-bottom: 1px solid #30363d; padding-bottom: 8px; color: #58a6ff; }}
code {{ font-family: "SFMono-Regular", Consolas, monospace; background-color: #161b22; padding: 0.2em 0.4em; font-size: 85%; border-radius: 6px; }}
pre {{ background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; overflow: auto; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1em; margin-bottom: 1em; }}
th, td {{ border: 1px solid #30363d; padding: 8px 12px; }}
th {{ background-color: #161b22; }}
.chart-container {{ background-color: #ffffff; border-radius: 8px; padding: 16px; margin-top: 20px; }}
</style></head><body><main>
<h1>Relatório de Análise</h1><h2>Repositório: {repo_name}</h2>
{html_body}
<div class="chart-container"><canvas id="analyticsChart"></canvas></div>
</main><script>
const chartData = {chart_script_data};
if (chartData && chartData.data) {{
    try {{
        const ctx = document.getElementById('analyticsChart').getContext('2d');
        Chart.defaults.color = '#333';
        new Chart(ctx, {{ type: chartData.type, data: chartData.data, options: chartData.options }});
    }} catch (e) {{ console.error("Erro Chart.js:", e); }}
}} else {{
    const container = document.querySelector('.chart-container');
    if (container) {{ container.style.display = 'none'; }}
}}
</script></body></html>
"""
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.html"
        return template_html, filename

    def _generate_report_content(self, repo_name: str, content_json_str: str, format: str = "html") -> Tuple[str, str, str]:
        # (Esta é a função 'generate_report_content' anterior, agora privada)
        if format.lower() == "html":
            content_string, filename = self._generate_html_report_content(repo_name, content_json_str)
            return content_string, filename, "text/html; charset=utf-8"
        else:
            unique_id = str(uuid.uuid4()).split('-')[0]
            filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.json"
            return content_json_str, filename, "application/json; charset=utf-8"

    def processar_e_salvar_relatorio(self, repo_name: str, user_prompt: str, format: str = "html"):
        """
        Tarefa do Worker (RQ) que gera um relatório para DOWNLOAD.
        """
        SUPABASE_BUCKET_NAME = "reports" 
        print(f"[WORKER-REPORTS] Iniciando relatório (com RAG) para: {repo_name}")
        try:
            # 1. Busca uma instrução salva (RAG)
            retrieved_instruction = self.metadata_service.find_similar_instruction(repo_name, user_prompt)
            
            if retrieved_instruction:
                print(f"[WORKER-REPORTS] Instrução RAG encontrada. Combinando prompts...")
                combined_prompt = f"Instrução Base: '{user_prompt}'\nContexto Salvo: '{retrieved_instruction}'\nGere o relatório."
            else:
                print(f"[WORKER-REPORTS] Nenhuma instrução RAG encontrada. Usando prompt padrão.")
                combined_prompt = user_prompt
                
            # 2. Busca os dados brutos para a análise
            try:
                dados_brutos = self.metadata_service.get_all_documents_by_repo(repo_name)
            except Exception as e:
                 print(f"[WORKER-REPORTS] AVISO: Falha ao buscar documentos: {e}")
                 dados_brutos = []
            
            if not dados_brutos:
                print("[WORKER-REPORTS] Nenhum dado encontrado no SQL.")

            print(f"[WORKER-REPORTS] {len(dados_brutos)} registos encontrados. Enviando para LLM...")

            # 3. Gera o JSON do relatório (usando o prompt combinado)
            report_json_string = self.llm_service.generate_analytics_report(
                repo_name=repo_name,
                user_prompt=combined_prompt,
                raw_data=dados_brutos
            )
            
            print("[WORKER-REPORTS] Relatório JSON gerado pela LLM.")

            # 4. Gera o CONTEÚDO (HTML) e o NOME DO ARQUIVO
            (content_to_upload, filename, content_type) = self._generate_report_content(
                repo_name, report_json_string, format
            )
            
            print(f"[WORKER-REPORTS] Conteúdo HTML gerado. Fazendo upload de {filename}...")
            
            # 5. Fazer UPLOAD do conteúdo
            self.storage_service.upload_file_content(
                content_string=content_to_upload,
                filename=filename,
                bucket_name=SUPABASE_BUCKET_NAME,
                content_type=content_type
            )
            
            print(f"[WORKER-REPORTS] Upload com sucesso! Retornando filename: {filename}")
            
            # 6. Retornar o nome do arquivo (para o App.js baixar)
            return filename
            
        except Exception as e:
            error_message = repr(e)
            print(f"[WORKER-REPORTS] Erro detalhado durante geração de relatório: {error_message}")
            return f"Erro during a geração do relatório: {error_message}"

# --- Instância Singleton para o Worker ---
try:
    _report_service_instance = ReportService()
    processar_e_salvar_relatorio = _report_service_instance.processar_e_salvar_relatorio
    print("[ReportService] Instância de serviço criada e função exportada.")
except Exception as e:
    print(f"[ReportService] Falha ao criar instância de serviço: {e}")
    processar_e_salvar_relatorio = None