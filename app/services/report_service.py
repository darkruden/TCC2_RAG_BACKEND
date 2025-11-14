# CÓDIGO CORRIGIDO PARA: app/services/report_service.py
# (Com a correção do Content-Type para text/html; charset=utf-8)

import os
import markdown
import uuid
from supabase import create_client, Client
from typing import Dict, Any, Tuple
from .metadata_service import MetadataService
from .llm_service import LLMService

# --- SERVIÇO DE ARMAZENAMENTO SUPABASE ---
# (Esta classe está correta e não precisa de mudanças)
class SupabaseStorageService:
    """
    Serviço para fazer upload de arquivos (relatórios) para o Supabase Storage.
    """
    def __init__(self):
        url: str = os.getenv('SUPABASE_URL')
        key: str = os.getenv('SUPABASE_KEY')
        
        if not url or not key:
            raise ValueError("Variáveis de ambiente 'SUPABASE_URL' e 'SUPABASE_KEY' não definidas.")
            
        self.client: Client = create_client(url, key)

    def upload_file_content(self, content_string: str, filename: str, bucket_name: str, content_type: str = 'text/html'):
        """
        Faz upload de um CONTEÚDO (string) para o Supabase Storage.
        """
        try:
            content_bytes = content_string.encode('utf-8')
            
            self.client.storage.from_(bucket_name).upload(
                path=filename,
                file=content_bytes,
                file_options={
                    "content-type": content_type, # <--- A mágica acontece aqui
                    "cache-control": "3600",
                    "upsert": "true"
                }
            )
            
            public_url = self.client.storage.from_(bucket_name).get_public_url(filename)
            return public_url
            
        except Exception as e:
            print(f"[SUPABASE_SERVICE] Erro ao fazer upload para o Supabase: {repr(e)}")
            raise


class ReportService:
    """
    Serviço para GERAÇÃO DE CONTEÚDO de relatórios.
    """
    
    def __init__(self):
        pass
    
    def generate_html_report_content(self, repo_name: str, markdown_content: str) -> Tuple[str, str]:
        """
        Converte o Markdown em um CONTEÚDO HTML (string) e gera um nome de arquivo.
        """
        
        html_body = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])

        # O template HTML (idêntico ao anterior)
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
        """
        Gera um nome de arquivo para o conteúdo Markdown.
        """
        unique_id = str(uuid.uuid4()).split('-')[0]
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.md"
        return content, filename
    
    def generate_report_content(self, repo_name: str, content: str, format: str = "html") -> Tuple[str, str, str]:
        """
        Gera o CONTEÚDO do relatório no formato especificado.
        
        :return: Tupla (content_string, filename, content_type)
        """
        if format.lower() == "html":
            content_string, filename = self.generate_html_report_content(repo_name, content)
            # --- AQUI ESTÁ A CORREÇÃO ---
            # Antes: "text/html"
            # Agora: "text/html; charset=utf-8"
            return content_string, filename, "text/html; charset=utf-8"
        
        elif format.lower() == "markdown":
            content_string, filename = self.generate_markdown_report_content(repo_name, content)
            # Boa prática adicionar aqui também
            return content_string, filename, "text/markdown; charset=utf-8"
        
        else:
            raise ValueError(f"Formato não suportado: {format}. Use 'html' ou 'markdown'.")

# --- FUNÇÃO DO WORKER ATUALIZADA ---
# (Esta função está correta e não precisa de mudanças, pois ela
# apenas repassa o content_type que a função acima gera)
        
def processar_e_salvar_relatorio(repo_name: str, user_prompt: str, format: str = "html"):
    """
    Função de tarefa (Task Function) para o worker.
    """
    
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
            content_type=content_type # <-- Passa o "text/html; charset=utf-8"
        )
        
        print(f"[WORKER-REPORTS] Upload com sucesso! URL: {public_url}")
        
        return public_url
        
    except Exception as e:
        error_message = repr(e)
        print(f"[WORKER-REPORTS] Erro detalhado durante geração de relatório: {error_message}")
        return f"Erro durante a geração do relatório: {error_message}"