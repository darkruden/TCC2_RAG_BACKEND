# CÓDIGO FINAL PARA: app/services/report_service.py
# (Usa Supabase Storage para salvar os relatórios)

import os
import markdown # Usado para converter .md para .html
import uuid     # Para nomes de arquivos únicos
from supabase import create_client, Client # Cliente do Supabase
from typing import Dict, Any, Tuple
from .metadata_service import MetadataService
from .llm_service import LLMService

# --- SERVIÇO DE ARMAZENAMENTO SUPABASE ---

class SupabaseStorageService:
    """
    Serviço para fazer upload de arquivos (relatórios) para o Supabase Storage.
    """
    def __init__(self):
        # Lê as variáveis de ambiente (do Heroku Config Vars)
        url: str = os.getenv('SUPABASE_URL')
        key: str = os.getenv('SUPABASE_KEY')
        
        if not url or not key:
            raise ValueError("Variáveis de ambiente 'SUPABASE_URL' e 'SUPABASE_KEY' não definidas.")
            
        self.client: Client = create_client(url, key)

    def upload_file_content(self, content_string: str, filename: str, bucket_name: str, content_type: str = 'text/html'):
        """
        Faz upload de um CONTEÚDO (string) para o Supabase Storage.
        
        :param content_string: O conteúdo HTML ou Markdown como uma string.
        :param filename: O nome do arquivo a ser salvo no bucket (ex: "meu_relatorio.html").
        :param bucket_name: O nome do bucket no Supabase (ex: "reports").
        :param content_type: O MimeType (ex: 'text/html' ou 'text/markdown').
        :return: A URL pública do arquivo no Supabase.
        """
        try:
            # Converte a string de conteúdo para bytes
            content_bytes = content_string.encode('utf-8')
            
            # Faz o upload
            self.client.storage.from_(bucket_name).upload(
                path=filename,
                file=content_bytes,
                file_options={
                    "content-type": content_type,
                    "cache-control": "3600", # Cache de 1 hora
                    "upsert": "true" # Sobrescreve se o arquivo já existir
                }
            )
            
            # Obtém a URL pública do arquivo recém-enviado
            public_url = self.client.storage.from_(bucket_name).get_public_url(filename)
            return public_url
            
        except Exception as e:
            print(f"[SUPABASE_SERVICE] Erro ao fazer upload para o Supabase: {repr(e)}")
            raise


class ReportService:
    """
    Serviço para GERAÇÃO DE CONTEÚDO de relatórios.
    Esta classe não salva mais arquivos localmente.
    """
    
    def __init__(self):
        pass # Não precisamos mais do output_dir
    
    def generate_html_report_content(self, repo_name: str, markdown_content: str) -> Tuple[str, str]:
        """
        Converte o Markdown em um CONTEÚDO HTML (string) e gera um nome de arquivo.
        NÃO SALVA MAIS O ARQUIVO LOCALMENTE.
        
        :return: Uma tupla (string_do_html, nome_do_arquivo)
        """
        
        # 1. Converter o Markdown da LLM para HTML
        html_body = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])

        # 2. Definir o template HTML (o mesmo de antes)
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
        
        # 3. Gerar um nome de arquivo único
        unique_id = str(uuid.uuid4()).split('-')[0] # Pega os 8 primeiros chars
        filename = f"{repo_name.replace('/', '_')}_report_{unique_id}.html"
        
        return template_html, filename

    def generate_markdown_report_content(self, repo_name: str, content: str) -> Tuple[str, str]:
        """
        Gera um nome de arquivo para o conteúdo Markdown.
        NÃO SALVA MAIS O ARQUIVO LOCALMENTE.

        :return: Uma tupla (string_do_markdown, nome_do_arquivo)
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
            return content_string, filename, "text/html"
        
        elif format.lower() == "markdown":
            content_string, filename = self.generate_markdown_report_content(repo_name, content)
            return content_string, filename, "text/markdown"
        
        else:
            raise ValueError(f"Formato não suportado: {format}. Use 'html' ou 'markdown'.")

# --- FUNÇÃO DO WORKER ATUALIZADA ---
        
def processar_e_salvar_relatorio(repo_name: str, user_prompt: str, format: str = "html"):
    """
    Função de tarefa (Task Function) para o worker.
    Busca os dados, chama a LLM, GERA o conteúdo e FAZ UPLOAD para o Supabase.
    """
    
    # IMPORTANTE: Certifique-se que este bucket existe no seu painel Supabase!
    SUPABASE_BUCKET_NAME = "reports" 
    
    try:
        # Inicializa os serviços DENTRO da função do worker
        metadata_service = MetadataService()
        llm_service = LLMService()
        report_service = ReportService()
        supabase_service = SupabaseStorageService() # <--- Serviço Supabase
        
    except Exception as e:
        print(f"[WORKER-REPORTS] Erro ao inicializar serviços: {repr(e)}")
        # Retorna a string de erro, que será salva no Job e vista pelo frontend
        return f"Erro ao inicializar serviços: {repr(e)}"

    try:
        print(f"[WORKK-REPORTS] Iniciando relatório para: {repo_name}")
        
        # 1. Buscar TODOS os dados brutos
        dados_brutos = metadata_service.get_full_repo_analysis_data(repo_name)
        
        if not dados_brutos:
            print("[WORKER-REPORTS] Nenhum dado encontrado no SQL.")
            raise ValueError("Nenhum dado de metadados encontrado para este repositório.")

        print(f"[WORKER-REPORTS] {len(dados_brutos)} registos encontrados. Enviando para LLM...")

        # 2. Gerar o conteúdo do relatório (Markdown + Gráficos)
        report_content_md = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=user_prompt,
            raw_data=dados_brutos
        )
        
        print("[WORKER-REPORTS] Relatório gerado pela LLM. Preparando para upload...")

        # 3. Gerar o CONTEÚDO (HTML) e o NOME DO ARQUIVO
        (content_to_upload, filename, content_type) = report_service.generate_report_content(
            repo_name, 
            report_content_md, 
            format
        )
        
        print(f"[WORKER-REPORTS] Conteúdo gerado. Fazendo upload de {filename} para Supabase...")
        
        # 4. Fazer UPLOAD do conteúdo para o Supabase Storage
        public_url = supabase_service.upload_file_content(
            content_string=content_to_upload,
            filename=filename,
            bucket_name=SUPABASE_BUCKET_NAME,
            content_type=content_type
        )
        
        print(f"[WORKET-REPORTS] Upload com sucesso! URL: {public_url}")
        
        # 5. Retornar a URL pública
        # O frontend (App.js) receberá esta URL como 'job.result'
        return public_url
        
    except Exception as e:
        error_message = repr(e)
        print(f"[WORKER-REPORTS] Erro detalhado durante geração de relatório: {error_message}")
        # Retorna a string de erro, que será salva no Job
        return f"Erro durante a geração do relatório: {error_message}"