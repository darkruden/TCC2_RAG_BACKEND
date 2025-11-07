import pytest
import os
from unittest.mock import patch, MagicMock, mock_open
from app.services.report_service import ReportService

# Configuração de fixtures para testes
@pytest.fixture
def mock_markdown():
    with patch('app.services.report_service.markdown') as mock_markdown:
        # Configurar o mock para retornar valores específicos
        mock_markdown.markdown.return_value = "<h1>Título</h1><p>Conteúdo convertido</p>"
        yield mock_markdown

@pytest.fixture
def mock_pdfkit():
    with patch('app.services.report_service.pdfkit') as mock_pdfkit:
        yield mock_pdfkit

@pytest.fixture
def mock_os():
    with patch('app.services.report_service.os') as mock_os:
        # Configurar o mock para retornar valores específicos
        mock_os.path.join.side_effect = lambda *args: '/'.join(args)
        mock_os.makedirs.return_value = None
        mock_os.popen.return_value.read.return_value = "2025-05-21"
        yield mock_os

@pytest.fixture
def report_service(mock_os):
    service = ReportService(output_dir="./test_reports")
    yield service

# Testes unitários
class TestReportService:
    
    def test_init(self, mock_os):
        """Testa a inicialização do serviço"""
        service = ReportService(output_dir="./custom_dir")
        
        assert service.output_dir == "./custom_dir"
        mock_os.makedirs.assert_called_once_with("./custom_dir", exist_ok=True)
    
    def test_generate_markdown_report(self, report_service, mock_os):
        """Testa a geração de relatório em Markdown"""
        # Configurar mock para open
        mock_file = mock_open()
        with patch('builtins.open', mock_file):
            # Chamar método
            filepath = report_service.generate_markdown_report("user/repo", "# Relatório\nConteúdo do relatório")
        
        # Verificar chamadas e resultado
        expected_path = "./test_reports/user_repo_report.md"
        mock_os.path.join.assert_called_with("./test_reports", "user_repo_report.md")
        mock_file.assert_called_once_with(expected_path, 'w', encoding='utf-8')
        mock_file().write.assert_called_once_with("# Relatório\nConteúdo do relatório")
        assert filepath == expected_path
    
    def test_generate_pdf_report(self, report_service, mock_os, mock_markdown, mock_pdfkit):
        """Testa a geração de relatório em PDF"""
        # Configurar mock
        markdown_content = "# Relatório\nConteúdo do relatório"
        
        # Chamar método
        filepath = report_service.generate_pdf_report("user/repo", markdown_content)
        
        # Verificar chamadas e resultado
        expected_path = "./test_reports/user_repo_report.pdf"
        mock_os.path.join.assert_called_with("./test_reports", "user_repo_report.pdf")
        mock_markdown.markdown.assert_called_once_with(markdown_content, extensions=['tables', 'fenced_code'])
        mock_pdfkit.from_string.assert_called_once()
        
        # Verificar conteúdo HTML gerado
        html_content = mock_pdfkit.from_string.call_args[0][0]
        assert "<h1>Relatório de Requisitos - user/repo</h1>" in html_content
        assert "<h1>Título</h1><p>Conteúdo convertido</p>" in html_content
        assert "Gerado automaticamente pela extensão RAG" in html_content
        
        assert filepath == expected_path
    
    def test_generate_report_markdown(self, report_service):
        """Testa a geração de relatório no formato Markdown"""
        # Configurar mock
        with patch.object(report_service, 'generate_markdown_report') as mock_markdown_report:
            mock_markdown_report.return_value = "./test_reports/user_repo_report.md"
            
            # Chamar método
            result = report_service.generate_report("user/repo", "Conteúdo", format="markdown")
        
        # Verificar chamadas e resultado
        mock_markdown_report.assert_called_once_with("user/repo", "Conteúdo")
        assert result["format"] == "markdown"
        assert result["filepath"] == "./test_reports/user_repo_report.md"
        assert result["filename"] == "user_repo_report.md"
    
    def test_generate_report_pdf(self, report_service):
        """Testa a geração de relatório no formato PDF"""
        # Configurar mock
        with patch.object(report_service, 'generate_pdf_report') as mock_pdf_report:
            mock_pdf_report.return_value = "./test_reports/user_repo_report.pdf"
            
            # Chamar método
            result = report_service.generate_report("user/repo", "Conteúdo", format="pdf")
        
        # Verificar chamadas e resultado
        mock_pdf_report.assert_called_once_with("user/repo", "Conteúdo")
        assert result["format"] == "pdf"
        assert result["filepath"] == "./test_reports/user_repo_report.pdf"
        assert result["filename"] == "user_repo_report.pdf"
    
    def test_generate_report_invalid_format(self, report_service):
        """Testa a geração de relatório com formato inválido"""
        # Chamar método e verificar exceção
        with pytest.raises(ValueError) as excinfo:
            report_service.generate_report("user/repo", "Conteúdo", format="invalid")
        
        assert "Formato não suportado" in str(excinfo.value)
