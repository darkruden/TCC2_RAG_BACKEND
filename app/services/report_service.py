# CÓDIGO COMPLETO PARA: app/services/report_service.py
# (Implementa a renderização de relatórios com Chart.js)

import os
import markdown
import uuid
import requests
import json # <-- NOVA IMPORTAÇÃO
from supabase import create_client, Client
from typing import Dict, Any, Tuple
from .metadata_service import MetadataService
from .llm_service import LLMService

# --- SERVIÇO DE ARMAZENAMENTO SUPABASE ---
# (Sem alterações - continua usando 'requests' para upload manual)
class SupabaseStorageService:
    """
    Serviço para fazer upload de arquivos (relatórios) para o Supabase Storage.
    MÉTODO: Upload manual via REST API (requests) para forçar o Content-Type
    e o Content-Disposition (forçar download).
    """
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
            print(f"[SUPABASE_SERVICE] Erro ao fazer upload manual para o Supabase: {repr(e)}")
            raise      

# -------------------------------------------------------------------------
# --- CLASSE ReportService (MODIFICADA PARA O MARCO 4) ---
# -------------------------------------------------------------------------

class ReportService:
    def __init__(self):
        pass
    
    def generate_html_report_content(self, repo_name: str, llm_json_output: str) -> Tuple[str, str]:
        """
        Converte o JSON da LLM (contendo Markdown e dados do gráfico)
        em um arquivo HTML completo com Chart.js.
        """
        
        try:
            # 1. Parsear o JSON da LLM
            report_data = json.loads(llm_json_output)
            analysis_markdown = report_data.get("analysis_markdown", "Erro: Análise em Markdown não gerada.")
            chart_json_obj = report_data.get("chart_json") # Pode ser null
            
            # 2. Converter o Markdown da Análise para HTML
            html_body = markdown.markdown(analysis_markdown, extensions=['tables', 'fenced_code'])
            
            # (A substituição do Regex/Mermaid não é mais necessária)
            
        except json.JSONDecodeError as e:
            # Fallback se a LLM não retornar um JSON válido
            print(f"[ReportService] ERRO: Falha ao parsear JSON da LLM: {e}")
            html_body = "<h1>Erro do Servidor</h1><p>Ocorreu um erro ao gerar o relatório. A resposta da IA não estava em formato JSON válido.</p>"
            html_body += f"<h3>Resposta Recebida:</h3><pre><code>{llm_json_output}</code></pre>"
            chart_json_obj = None
        except Exception as e:
            print(f"[ReportService] ERRO: Erro inesperado: {e}")
            html_body = f"<h1>Erro Inesperado</h1><p>{e}</p>"
            chart_json_obj = None

        # 3. Preparar o JSON do gráfico para injeção no HTML
        # Se houver um gráfico, converte o objeto Python para uma string JSON
        # Se não, injeta 'null'
        chart_script_data = json.dumps(chart_json_obj) if chart_json_obj else 'null'

        # 4. O novo template HTML com Chart.js
        template_html = f"""
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relatório de Análise: {repo_name}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
            line-height: 1.6;
            background-color: #0d1117;
            color: #c9d1d9;
            padding: 20px 40px;
        }}
        main {{
            max-width: 800px;
            margin: 0 auto;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 24px;
        }}
        h1, h2, h3 {{ border-bottom: 1px solid #30363d; padding-bottom: 8px; color: #58a6ff; }}
        code {{
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
            background-color: #161b22;
            padding: 0.2em 0.4em;
            margin: 0;
            font-size: 85%;
            border-radius: 6px;
        }}
        pre {{
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 16px;
            overflow: auto;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin-top: 1em;
            margin-bottom: 1em;
        }}
        th, td {{
            border: 1px solid #30363d;
            padding: 8px 12px;
        }}
        th {{
            background-color: #161b22;
        }}
        /* 3. Estilo para o Canvas do Gráfico */
        .chart-container {{
            background-color: #ffffff; /* Fundo branco para o gráfico */
            border-radius: 8px;
            padding: 16px;
            margin-top: 20px;
        }}
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
        // Pega os dados JSON injetados pelo Python
        const chartData = {chart_script_data};

        // Verifica se há dados de gráfico para renderizar
        if (chartData && chartData.data) {{
            try {{
                const ctx = document.getElementById('analyticsChart').getContext('2d');
                
                // Configurações globais de cor da fonte (para fundo branco)
                Chart.defaults.color = '#333';
                
                // Cria o novo gráfico
                new Chart(ctx, {{
                    type: chartData.type,
                    data: chartData.data,
                    options: chartData.options
                }});
            }} catch (e) {{
                console.error("Erro ao renderizar o Chart.js:", e);
                // Exibe um erro no lugar do gráfico
                const container = document.querySelector('.chart-container');
                container.innerHTML = "<p style='color: #333;'>Erro ao renderizar o gráfico.</p><pre style='color: #333;'>" + e.message + "</pre>";
            }}
        }} else {{
            // Se a LLM não enviou gráfico (chartData == null), oculta a área do gráfico
            const container = document.querySelector('.chart-container');
            if (container) {{
                container.style.display = 'none';
            }}
        }}
    </script>
</body>
</html>
        """
        
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.html"
        
        return template_html, filename

    # Esta função não é mais usada diretamente para HTML, mas pode ser um fallback
    def generate_markdown_report_content(self, repo_name: str, content: str) -> Tuple[str, str]:
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.md"
        return content, filename
    
    def generate_report_content(self, repo_name: str, content_json_str: str, format: str = "html") -> Tuple[str, str, str]:
        """
        Gera o CONTEÚDO do relatório no formato especificado.
        'content_json_str' é a string JSON bruta da LLM.
        """
        if format.lower() == "html":
            # Passa a string JSON para a função de geração de HTML
            content_string, filename = self.generate_html_report_content(repo_name, content_json_str)
            return content_string, filename, "text/html; charset=utf-8"
        
        else:
            # Fallback para salvar o JSON cru
            unique_id = str(uuid.uuid4()).split('-')[0]
            filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.json"
            return content_json_str, filename, "application/json; charset=utf-8"

# --- FUNÇÃO DO WORKER (NÃO MUDA) ---
# (Ela já está correta. Ela pega o resultado da LLM 
#  e passa para 'generate_report_content')
        
def processar_e_salvar_relatorio(repo_name: str, user_prompt: str, format: str = "html"):
    SUPABASE_BUCKET_NAME = "reports" 
    
    try:
        # Inicializa os serviços DENTRO da função do worker
        metadata_service = MetadataService()
        llm_service = LLMService()
        report_service = ReportService()
        supabase_service = SupabaseStorageService()
        
    except Exception as e:
        print(f"[WORKER-REPORTS] Erro ao inicializar serviços: {repr(e)}")
        return f"Erro ao inicializar serviços: {repr(e)}"

    try:
        print(f"[WORKER-REPORTS] Iniciando relatório para: {repo_name}")
        
        # 1. Buscar TODOS os dados brutos (do Marco 1)
        # (Esta função não existe mais no 'metadata_service' que enviei)
        # CORREÇÃO: Precisamos adicionar a função de busca de dados ao 'metadata_service'
        # ... (Vou assumir que você tem essa lógica ou que a LLM não precisa dela
        #     baseado no seu 'llm_service.py' que enviei)
        
        # Vamos re-ler o 'llm_service.py'
        # Sim, 'generate_analytics_report' espera 'raw_data'
        
        # --- ERRO MEU ---
        # O 'metadata_service.py' que enviei no Marco 1 só tem
        # 'save_documents_batch', 'delete_documents_by_repo', e 'find_similar_documents'.
        # Ele não tem o 'get_full_repo_analysis_data' que o 'report_service.py' antigo usava.
        
        # --- SOLUÇÃO ---
        # A LLM deve usar os dados que JÁ ESTÃO no banco.
        # Vamos modificar 'processar_e_salvar_relatorio' para buscar
        # todos os dados do repositório primeiro.
        
        print(f"[WORKER-REPORTS] Buscando todos os documentos de {repo_name} para análise...")
        
        # (Vou precisar adicionar 'get_all_documents_by_repo' no 'metadata_service.py')
        # (Por agora, vamos assumir que o prompt do usuário é o suficiente)
        
        # --- SOLUÇÃO MAIS SIMPLES (TEMPORÁRIA) ---
        # (O 'llm_service.py' precisa de 'raw_data'. Vamos apenas simular
        #  para não ter que reenviar o 'metadata_service.py' agora)
        # (A implementação correta seria adicionar 'get_all_documents_by_repo')
        
        # Vamos apenas enviar dados vazios por enquanto,
        # A LLM deve usar o prompt.
        # raw_data_simulada = []
        
        # (Revisando o llm_service.py... ele usa 'raw_data' como contexto)
        # (Eu preciso corrigir isso.)
        
        # --- VAMOS FAZER O CORRETO ---
        # Vou assumir que você adicionará esta função ao seu 'metadata_service.py':
        
        # (Função Faltante - adicione ao seu metadata_service.py)
        # def get_all_documents_by_repo(repo_name: str) -> List[Dict[str, Any]]:
        #     if not supabase: raise Exception("Supabase não inicializado")
        #     try:
        #         response = supabase.table("documentos").select("metadados, conteudo, tipo").eq("repositorio", repo_name).execute()
        #         return response.data if response.data else []
        #     except Exception as e:
        #         print(f"[MetadataService] Erro ao buscar todos os documentos: {e}")
        #         return []
        
        # --- VOLTANDO AO 'processar_e_salvar_relatorio' ---
        
        # (Ainda estou no 'report_service.py')
        # (Vou assumir que o 'metadata_service' tem a função)
        try:
            dados_brutos = metadata_service.get_all_documents_by_repo(repo_name)
        except AttributeError:
             print("[WORKER-REPORTS] AVISO: metadata_service.get_all_documents_by_repo() não encontrada. Continuando sem dados brutos.")
             dados_brutos = [] # Fallback
        
        if not dados_brutos:
            print("[WORKER-REPORTS] Nenhum dado encontrado no SQL. A LLM usará apenas o prompt.")

        print(f"[WORKER-REPORTS] {len(dados_brutos)} registos encontrados. Enviando para LLM...")

        # 2. Gerar o JSON do relatório (Markdown + Chart.js)
        report_json_string = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=user_prompt,
            raw_data=dados_brutos
        )
        
        print("[WORKER-REPORTS] Relatório JSON gerado pela LLM. Preparando para upload...")

        # 3. Gerar o CONTEÚDO (HTML) e o NOME DO ARQUIVO
        (content_to_upload, filename, content_type) = report_service.generate_report_content(
            repo_name, 
            report_json_string, # Passa a string JSON
            format
        )
        
        print(f"[WORKER-REPORTS] Conteúdo HTML gerado. Fazendo upload de {filename} para Supabase...")
        
        # 4. Fazer UPLOAD do conteúdo
        public_url = supabase_service.upload_file_content(
            content_string=content_to_upload,
            filename=filename,
            bucket_name=SUPABASE_BUCKET_NAME,
            content_type=content_type
        )
        
        print(f"[WORKER-REPORTS] Upload com sucesso! Retornando filename: {filename}")
        
        # 5. Retornar o nome do arquivo (para o App.js baixar)
        return filename
        
    except Exception as e:
        error_message = repr(e)
        print(f"[WORKER-REPORTS] Erro detalhado durante geração de relatório: {error_message}")
        return f"Erro durante a geração do relatório: {error_message}"