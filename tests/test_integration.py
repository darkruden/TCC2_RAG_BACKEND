import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os
import json

from app.main import app

# Cliente de teste
client = TestClient(app)

# Configuração de fixtures para testes
@pytest.fixture
def mock_token():
    # Configurar token de teste
    os.environ["API_TOKEN"] = "test_token"
    yield "test_token"
    # Limpar após o teste
    os.environ.pop("API_TOKEN", None)

@pytest.fixture
def mock_github_service():
    with patch('app.main.GitHubService') as mock_service:
        # Configurar o mock para retornar valores específicos
        mock_instance = MagicMock()
        mock_service.return_value = mock_instance
        
        # Configurar métodos simulados
        mock_instance.get_issues.return_value = [
            {"id": 1, "title": "Issue 1", "state": "open"}
        ]
        mock_instance.get_pull_requests.return_value = [
            {"id": 2, "title": "PR 1", "state": "open"}
        ]
        mock_instance.get_commits.return_value = [
            {"sha": "abc123", "message": "Fix bug"}
        ]
        
        yield mock_instance

@pytest.fixture
def mock_embedding_service():
    with patch('app.main.EmbeddingService') as mock_service:
        # Configurar o mock para retornar valores específicos
        mock_instance = MagicMock()
        mock_service.return_value = mock_instance
        
        # Configurar métodos simulados
        mock_instance.process_github_data.return_value = {
            "collection_name": "github_test_repo",
            "documents_count": 3
        }
        mock_instance.query_collection.return_value = {
            "ids": [["doc1", "doc2"]],
            "documents": [["Texto 1", "Texto 2"]],
            "metadatas": [[{"type": "issue"}, {"type": "commit"}]],
            "distances": [[0.1, 0.2]]
        }
        
        yield mock_instance

@pytest.fixture
def mock_llm_service():
    with patch('app.main.LLMService') as mock_service:
        # Configurar o mock para retornar valores específicos
        mock_instance = MagicMock()
        mock_service.return_value = mock_instance
        
        # Configurar métodos simulados
        mock_instance.generate_response.return_value = {
            "response": "Resposta gerada pelo modelo",
            "usage": {"total_tokens": 150}
        }
        mock_instance.generate_report.return_value = "# Relatório\nConteúdo do relatório"
        
        yield mock_instance

@pytest.fixture
def mock_report_service():
    with patch('app.main.ReportService') as mock_service:
        # Configurar o mock para retornar valores específicos
        mock_instance = MagicMock()
        mock_service.return_value = mock_instance
        
        # Configurar métodos simulados
        mock_instance.generate_report.return_value = {
            "format": "markdown",
            "filepath": "/path/to/report.md",
            "filename": "report.md"
        }
        
        yield mock_instance

# Testes de integração
class TestAPI:
    
    def test_health_check(self):
        """Testa o endpoint de health check"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "online"
    
    def test_test_route(self):
        """Testa o endpoint de teste"""
        response = client.get("/test")
        assert response.status_code == 200
        assert "Conexão com o backend estabelecida" in response.json()["message"]
    
    def test_consultar_unauthorized(self, mock_token):
        """Testa o endpoint de consulta sem token"""
        response = client.post(
            "/api/consultar",
            json={"query": "Como funciona?", "repositorio": "user/repo"}
        )
        assert response.status_code == 401
    
    def test_consultar_authorized(self, mock_token, mock_github_service, mock_embedding_service, mock_llm_service):
        """Testa o endpoint de consulta com token válido"""
        response = client.post(
            "/api/consultar",
            headers={"X-API-Key": "test_token"},
            json={"query": "Como funciona?", "repositorio": "user/repo"}
        )
        
        assert response.status_code == 200
        assert "resposta" in response.json()
        assert "fontes" in response.json()
    
    def test_relatorio_unauthorized(self, mock_token):
        """Testa o endpoint de relatório sem token"""
        response = client.post(
            "/api/relatorio",
            json={"repositorio": "user/repo", "formato": "markdown"}
        )
        assert response.status_code == 401
    
    def test_relatorio_authorized(self, mock_token, mock_github_service, mock_embedding_service, mock_llm_service, mock_report_service):
        """Testa o endpoint de relatório com token válido"""
        response = client.post(
            "/api/relatorio",
            headers={"X-API-Key": "test_token"},
            json={"repositorio": "user/repo", "formato": "markdown"}
        )
        
        assert response.status_code == 200
        assert "url" in response.json()
        assert "formato" in response.json()
