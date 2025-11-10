import os
import markdown
# import pdfkit  # <--- COMENTE ESTA LINHA (Passo 1)
from typing import Dict, Any, Optional

class ReportService:
    """
    Serviço para geração de relatórios em Markdown e PDF.
    """
    
    def __init__(self, output_dir: str = "./reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_markdown_report(self, repo_name: str, content: str) -> str:
        """
        Gera um relatório em formato Markdown.
        """
        filename = f"{repo_name.replace('/', '_')}_report.md"
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return filepath
    
    # --- PASSO 2: COMENTE TODA A FUNÇÃO PDF ---
    """
    def generate_pdf_report(self, repo_name: str, markdown_content: str) -> str:
        html_content = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])
        
        styled_html = f\"\"\"
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Relatório de Requisitos - {repo_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                h1 {{ color: #2c3e50; }}
                h2 {{ color: #2980b9; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h1>Relatório de Requisitos - {repo_name}</h1>
            {html_content}
        </body>
        </html>
        \"\"\"
        
        filename = f"{repo_name.replace('/', '_')}_report.pdf"
        filepath = os.path.join(self.output_dir, filename)
        
        pdfkit.from_string(styled_html, filepath)
        
        return filepath
    """
    
    def generate_report(self, repo_name: str, content: str, format: str = "markdown") -> Dict[str, Any]:
        """
        Gera um relatório no formato especificado.
        """
        if format.lower() == "markdown":
            filepath = self.generate_markdown_report(repo_name, content)
            return {
                "format": "markdown",
                "filepath": filepath,
                "filename": os.path.basename(filepath)
            }
        # --- PASSO 3: COMENTE O BLOCO ELIF DO PDF ---
        # elif format.lower() == "pdf":
        #     filepath = self.generate_pdf_report(repo_name, content)
        #     return {
        #         "format": "pdf",
        #         "filepath": filepath,
        #         "filename": os.path.basename(filepath)
        #     }
        else:
            raise ValueError(f"Formato não suportado: {format}. Use 'markdown' ou 'pdf'.")