# CÓDIGO ATUALIZADO PARA: app/services/report_service.py

import os
import markdown # Usado para converter .md para .html
from typing import Dict, Any
from .metadata_service import MetadataService
from .llm_service import LLMService
class ReportService:
    """
    Serviço para geração de relatórios em Markdown e HTML (com gráficos Mermaid).
    """
    
    def __init__(self, output_dir: str = "./reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_markdown_report(self, repo_name: str, content: str) -> str:
        """
        Gera um relatório em formato Markdown (útil para debug).
        """
        filename = f"{repo_name.replace('/', '_')}_report.md"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return filepath

    # --- INÍCIO DA NOVA FUNÇÃO (HTML) ---
    def generate_html_report(self, repo_name: str, markdown_content: str) -> str:
        """
        Converte o relatório Markdown (com Mermaid) em um arquivo HTML
        autocontido e interativo.
        """
        
        # 1. Converter o Markdown da LLM para HTML
        # Usamos extensões para tabelas e blocos de código
        html_body = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])

        # 2. Definir um template HTML que:
        #    a) Inclui um CSS para ficar bonito (estilo GitHub Dark)
        #    b) Inclui o script do Mermaid.js para renderizar os gráficos
        
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
        /* Estilo para os gráficos Mermaid renderizados */
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
        
        # 4. Salvar o arquivo HTML final
        filename = f"{repo_name.replace('/', '_')}_report.html"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(template_html)
        
        return filepath
    # --- FIM DA NOVA FUNÇÃO (HTML) ---
    
    def generate_report(self, repo_name: str, content: str, format: str = "html") -> Dict[str, Any]:
        """
        Gera um relatório no formato especificado.
        Agora o padrão é HTML.
        """
        if format.lower() == "html":
            filepath = self.generate_html_report(repo_name, content)
            return {
                "format": "html",
                "filepath": filepath,
                "filename": os.path.basename(filepath)
            }
        elif format.lower() == "markdown":
            filepath = self.generate_markdown_report(repo_name, content)
            return {
                "format": "markdown",
                "filepath": filepath,
                "filename": os.path.basename(filepath)
            }
        else:
            raise ValueError(f"Formato não suportado: {format}. Use 'html' ou 'markdown'.")
        
def processar_e_salvar_relatorio(repo_name: str, user_prompt: str, format: str = "html"):
    """
    Função de tarefa (Task Function) para o worker.
    Busca os dados, chama a LLM para análise e salva o arquivo final.
    """
    
    # Inicializa os serviços DENTRO da função do worker.
    # Isso é uma melhor prática para o RQ, pois garante que
    # não há conexões de BD (como a do Supabase) partilhadas entre processos.
    try:
        metadata_service = MetadataService()
        llm_service = LLMService()
        report_service = ReportService()
    except Exception as e:
        print(f"[WORKER-REPORTS] Erro ao inicializar serviços: {repr(e)}")
        return f"Erro ao inicializar serviços: {repr(e)}"

    try:
        print(f"[WORKER-REPORTS] Iniciando relatório para: {repo_name}")
        
        # 1. Buscar TODOS os dados brutos
        dados_brutos = metadata_service.get_full_repo_analysis_data(repo_name)
        
        if not dados_brutos:
            print("[WORKER-REPORTS] Nenhum dado encontrado no SQL.")
            raise ValueError("Nenhum dado de metadados encontrado para este repositório.")

        print(f"[WORKER-REPORTS] {len(dados_brutos)} registos encontrados. Enviando para LLM...")

        # 2. Gerar o conteúdo do relatório (Markdown + Gráficos)
        report_content = llm_service.generate_analytics_report(
            repo_name=repo_name,
            user_prompt=user_prompt,
            raw_data=dados_brutos
        )
        
        print("[WORKER-REPORTS] Relatório gerado pela LLM. Salvando arquivo...")

        # 3. Salvar o arquivo (HTML por defeito)
        resultado = report_service.generate_report(
            repo_name, 
            report_content, 
            format
        )
        
        print(f"[WORKER-REPORTS] Relatório salvo com sucesso: {resultado['filename']}")
        # Retorna o dicionário de resultado, que será salvo no Job
        return resultado
        
    except Exception as e:
        print(f"Erro detalhado durante geração de relatório: {repr(e)}")
        # Retorna a string de erro, que será salva no Job
        return f"Erro durante a geração do relatório: {repr(e)}"
        