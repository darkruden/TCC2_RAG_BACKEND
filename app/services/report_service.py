# CÓDIGO FINAL (usando /tmp para salvar) PARA: app/services/report_service.py

import os
import markdown
import uuid
import requests
from supabase import create_client, Client
from typing import Dict, Any, Tuple
from .metadata_service import MetadataService
from .llm_service import LLMService
# Não precisamos mais de 'io'

# --- SERVIÇO DE ARMAZENAMENTO SUPABASE (MÉTODO CORRIGIDO) ---

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
            
        # Ainda precisamos do cliente para o .get_public_url()
        self.client: Client = create_client(self.url, self.key)

    def upload_file_content(self, content_string: str, filename: str, bucket_name: str, content_type: str = 'text/html'):
        
        try:
            # 1. Constrói o endpoint da API de Storage
            endpoint = f"{self.url}/storage/v1/object/{bucket_name}/{filename}"

            # 2. Define os cabeçalhos manualmente (aqui está o controle total)
            headers = {
                "Authorization": f"Bearer {self.key}", # Chave de serviço
                "Content-Type": content_type,      # Ex: "text/html; charset=utf-8"
                "x-upsert": "true",                # Sobrescreve
                # O cabeçalho crucial para forçar o download
                "Content-Disposition": f'attachment; filename="{filename}"' 
            }

            # 3. Codifica o conteúdo
            content_bytes = content_string.encode('utf-8')
            
            # 4. Faz o upload via POST
            response = requests.post(
                endpoint, 
                data=content_bytes, 
                headers=headers
            )
            
            # 5. Verifica se houve erro
            response.raise_for_status() # Lança um erro se o status for 4xx ou 5xx
            
            # 6. Pega a URL pública
            public_url = self.client.storage.from_(bucket_name).get_public_url(filename)
            return public_url
            
        except requests.exceptions.HTTPError as e:
            # Erro mais detalhado se o upload falhar
            print(f"[SUPABASE_SERVICE] Erro HTTP no upload manual: {e.response.text}")
            raise
        except Exception as e:
            print(f"[SUPABASE_SERVICE] Erro ao fazer upload manual para o Supabase: {repr(e)}")
            raise      
        finally:
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)

# -------------------------------------------------------------------------
# O RESTANTE DO ARQUIVO ESTÁ CORRETO E NÃO MUDOU
# -------------------------------------------------------------------------

class ReportService:
    def __init__(self):
        pass
    
    def generate_html_report_content(self, repo_name: str, markdown_content: str) -> Tuple[str, str]:
        html_body = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])
        template_html = f"""
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relatório de Análise: {repo_name}</title>
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
        .mermaid {{
            background-color: #f6f8fa; /* Fundo claro para o gráfico */
            border-radius: 6px;
            padding: 16px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <main>
        <h1>Relatório de Análise</h1>
        <h2>Repositório: {repo_name}</h2>
        
        {html_body}
        
    </main>
    
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{ startOnLoad: true, theme: 'neutral' }});
    </script>
</body>
</html>
        """
        
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.html"
        
        return template_html, filename

    def generate_markdown_report_content(self, repo_name: str, content: str) -> Tuple[str, str]:
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.md"
        return content, filename
    
    def generate_report_content(self, repo_name: str, content: str, format: str = "html") -> Tuple[str, str, str]:
        if format.lower() == "html":
            content_string, filename = self.generate_html_report_content(repo_name, content)
            return content_string, filename, "text/html; charset=utf-8"
        
        elif format.lower() == "markdown":
            content_string, filename = self.generate_markdown_report_content(repo_name, content)
            return content_string, filename, "text/markdown; charset=utf-8"
        
        else:
            raise ValueError(f"Formato não suportado: {format}. Use 'html' ou 'markdown'.")

# --- FUNÇÃO DO WORKER (NÃO MUDA) ---
        
def processar_e_salvar_relatorio(repo_name: str, user_prompt: str, format: str = "html"):
    SUPABASE_BUCKET_NAME = "reports" 
    
    try:
        metadata_service = MetadataService()
        llm_service = LLMService()
        report_service = ReportService()
        supabase_service = SupabaseStorageService()
        
    except Exception as e:
        print(f"[WORKER-REPORTS] Erro ao inicializar serviços: {repr(e)}")
        return f"Erro ao inicializar serviços: {repr(e)}"

    try:
        print(f"[WORKER-REPORTS] Iniciando relatório para: {repo_name}")
        
        dados_brutos = metadata_service.get_full_repo_analysis_data(repo_name)
        
        if not dados_brutos:
            print("[WORKER-REPORTS] Nenhum dado encontrado no SQL.")
            raise ValueError("Nenhum dado de metadados encontrado para este repositório.")

        print(f"[WORKER-REPORTS] {len(dados_brutos)} registos encontrados. Enviando para LLM...")

        report_content_md = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=user_prompt,
            raw_data=dados_brutos
        )
        
        print("[WORKER-REPORTS] Relatório gerado pela LLM. Preparando para upload...")

        (content_to_upload, filename, content_type) = report_service.generate_report_content(
            repo_name, 
            report_content_md, 
            format
        )
        
        print(f"[WORKER-REPORTS] Conteúdo gerado. Fazendo upload de {filename} para Supabase...")
        
        public_url = supabase_service.upload_file_content(
            content_string=content_to_upload,
            filename=filename,
            bucket_name=SUPABASE_BUCKET_NAME,
            content_type=content_type
        )
        
        print(f"[WORKER-REPORTS] Upload com sucesso! URL: {public_url}")
        
        return public_url
        
    except Exception as e:
        error_message = repr(e)
        print(f"[WORKER-REPORTS] Erro detalhado durante geração de relatório: {error_message}")
        return f"Erro durante a geração do relatório: {error_message}"