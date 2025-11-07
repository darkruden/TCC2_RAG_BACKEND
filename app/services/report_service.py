import os
import markdown
import pdfkit
from typing import Dict, Any, Optional

class ReportService:
    """
    Serviço para geração de relatórios em Markdown e PDF.
    """
    
    def __init__(self, output_dir: str = "./reports"):
        """
        Inicializa o serviço de relatórios.
        
        Args:
            output_dir: Diretório para salvar os relatórios gerados
        """
        self.output_dir = output_dir
        
        # Criar diretório de saída se não existir
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_markdown_report(self, repo_name: str, content: str) -> str:
        """
        Gera um relatório em formato Markdown.
        
        Args:
            repo_name: Nome do repositório
            content: Conteúdo do relatório em Markdown
            
        Returns:
            Caminho do arquivo gerado
        """
        # Formatar nome do arquivo
        filename = f"{repo_name.replace('/', '_')}_report.md"
        filepath = os.path.join(self.output_dir, filename)
        
        # Escrever conteúdo no arquivo
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return filepath
    
    def generate_pdf_report(self, repo_name: str, markdown_content: str) -> str:
        """
        Gera um relatório em formato PDF a partir de conteúdo Markdown.
        
        Args:
            repo_name: Nome do repositório
            markdown_content: Conteúdo do relatório em Markdown
            
        Returns:
            Caminho do arquivo gerado
        """
        # Converter Markdown para HTML
        html_content = markdown.markdown(markdown_content, extensions=['tables', 'fenced_code'])
        
        # Adicionar estilos CSS para melhorar a aparência
        styled_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Relatório de Requisitos - {repo_name}</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    margin: 40px;
                    color: #333;
                }}
                h1 {{
                    color: #2c3e50;
                    border-bottom: 2px solid #3498db;
                    padding-bottom: 10px;
                }}
                h2 {{
                    color: #2980b9;
                    margin-top: 30px;
                }}
                h3 {{
                    color: #3498db;
                }}
                a {{
                    color: #3498db;
                    text-decoration: none;
                }}
                a:hover {{
                    text-decoration: underline;
                }}
                pre, code {{
                    background-color: #f8f8f8;
                    border: 1px solid #ddd;
                    border-radius: 3px;
                    padding: 10px;
                    overflow-x: auto;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 20px 0;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 8px 12px;
                    text-align: left;
                }}
                th {{
                    background-color: #f2f2f2;
                }}
                tr:nth-child(even) {{
                    background-color: #f9f9f9;
                }}
                .footer {{
                    margin-top: 50px;
                    text-align: center;
                    font-size: 0.8em;
                    color: #7f8c8d;
                }}
            </style>
        </head>
        <body>
            <h1>Relatório de Requisitos - {repo_name}</h1>
            {html_content}
            <div class="footer">
                <p>Gerado automaticamente pela extensão RAG para análise de requisitos</p>
                <p>Data: {os.popen('date').read().strip()}</p>
            </div>
        </body>
        </html>
        """
        
        # Formatar nome do arquivo
        filename = f"{repo_name.replace('/', '_')}_report.pdf"
        filepath = os.path.join(self.output_dir, filename)
        
        # Gerar PDF a partir do HTML
        pdfkit.from_string(styled_html, filepath)
        
        return filepath
    
    def generate_report(self, repo_name: str, content: str, format: str = "markdown") -> Dict[str, Any]:
        """
        Gera um relatório no formato especificado.
        
        Args:
            repo_name: Nome do repositório
            content: Conteúdo do relatório em Markdown
            format: Formato do relatório ("markdown" ou "pdf")
            
        Returns:
            Dicionário com informações do relatório gerado
        """
        if format.lower() == "markdown":
            filepath = self.generate_markdown_report(repo_name, content)
            return {
                "format": "markdown",
                "filepath": filepath,
                "filename": os.path.basename(filepath)
            }
        # elif format.lower() == "pdf":
        #     filepath = self.generate_pdf_report(repo_name, content)
        #     return {
        #         "format": "pdf",
        #         "filepath": filepath,
        #         "filename": os.path.basename(filepath)
        #     }
        else:
            raise ValueError(f"Formato não suportado: {format}. Use 'markdown' ou 'pdf'.")
