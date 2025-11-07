import pytest
import os
from unittest.mock import patch, MagicMock
from app.services.llm_service import LLMService

# Configuração de fixtures para testes
@pytest.fixture
def mock_openai():
    with patch('app.services.llm_service.OpenAI') as mock_openai:
        # Configurar o mock para retornar valores específicos
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # Configurar resposta simulada
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Resposta gerada pelo modelo"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150
        
        mock_client.chat.completions.create.return_value = mock_response
        
        yield mock_client

@pytest.fixture
def llm_service(mock_openai):
    # Configurar variável de ambiente para teste
    os.environ["OPENAI_API_KEY"] = "test_key"
    service = LLMService()
    yield service
    # Limpar após o teste
    os.environ.pop("OPENAI_API_KEY", None)

# Testes unitários
class TestLLMService:
    
    def test_init_with_api_key(self):
        """Testa a inicialização do serviço com API key fornecida"""
        service = LLMService(api_key="custom_key")
        assert service.api_key == "custom_key"
    
    def test_init_with_env_api_key(self, llm_service):
        """Testa a inicialização do serviço com API key do ambiente"""
        assert llm_service.api_key == "test_key"
    
    def test_init_without_api_key(self):
        """Testa a inicialização do serviço sem API key"""
        os.environ.pop("OPENAI_API_KEY", None)
        with pytest.raises(ValueError):
            LLMService()
    
    def test_init_with_custom_model(self):
        """Testa a inicialização do serviço com modelo personalizado"""
        service = LLMService(api_key="test_key", model="gpt-3.5-turbo")
        assert service.model == "gpt-3.5-turbo"
    
    def test_generate_response(self, llm_service, mock_openai):
        """Testa a geração de resposta"""
        # Dados de teste
        query = "Como funciona o sistema?"
        context = [
            {
                "text": "O sistema utiliza RAG para análise de requisitos.",
                "metadata": {
                    "type": "issue",
                    "id": 1,
                    "title": "Documentação do Sistema",
                    "url": "https://github.com/user/repo/issues/1"
                }
            }
        ]
        
        # Chamar método
        response = llm_service.generate_response(query, context)
        
        # Verificar chamadas
        mock_openai.chat.completions.create.assert_called_once()
        call_args = mock_openai.chat.completions.create.call_args[1]
        assert call_args["model"] == "gpt-4"
        assert len(call_args["messages"]) == 2
        assert call_args["messages"][0]["role"] == "system"
        assert call_args["messages"][1]["role"] == "user"
        assert query in call_args["messages"][1]["content"]
        
        # Verificar resultado
        assert response["response"] == "Resposta gerada pelo modelo"
        assert response["usage"]["prompt_tokens"] == 100
        assert response["usage"]["completion_tokens"] == 50
        assert response["usage"]["total_tokens"] == 150
    
    def test_generate_report(self, llm_service, mock_openai):
        """Testa a geração de relatório"""
        # Dados de teste
        repo_name = "user/repo"
        requirements_data = [
            {
                "title": "Requisito 1",
                "description": "Descrição do requisito 1",
                "issues": [{"id": 1, "title": "Issue relacionada"}],
                "pull_requests": [{"id": 2, "title": "PR relacionado"}],
                "commits": [{"sha": "abc123", "message": "Implementação do requisito 1"}]
            }
        ]
        
        # Chamar método
        report = llm_service.generate_report(repo_name, requirements_data)
        
        # Verificar chamadas
        mock_openai.chat.completions.create.assert_called_once()
        call_args = mock_openai.chat.completions.create.call_args[1]
        assert call_args["model"] == "gpt-4"
        assert len(call_args["messages"]) == 2
        assert call_args["messages"][0]["role"] == "system"
        assert call_args["messages"][1]["role"] == "user"
        assert repo_name in call_args["messages"][1]["content"]
        
        # Verificar resultado
        assert report == "Resposta gerada pelo modelo"
    
    def test_get_token_usage(self, llm_service, mock_openai):
        """Testa a obtenção de estatísticas de uso de tokens"""
        # Configurar estado inicial
        llm_service.token_usage = {
            "prompt_tokens": 200,
            "completion_tokens": 100,
            "total_tokens": 300
        }
        
        # Chamar método
        usage = llm_service.get_token_usage()
        
        # Verificar resultado
        assert usage["prompt_tokens"] == 200
        assert usage["completion_tokens"] == 100
        assert usage["total_tokens"] == 300
    
    def test_format_context(self, llm_service):
        """Testa a formatação de contexto para o prompt"""
        # Dados de teste
        context = [
            {
                "text": "Descrição da issue",
                "metadata": {
                    "type": "issue",
                    "id": 1,
                    "title": "Issue 1",
                    "url": "https://github.com/user/repo/issues/1"
                }
            },
            {
                "text": "Mensagem do commit",
                "metadata": {
                    "type": "commit",
                    "sha": "abc123",
                    "author": "Developer"
                }
            },
            {
                "text": "Conteúdo do PR",
                "metadata": {
                    "type": "pull_request",
                    "id": 2,
                    "title": "PR 1",
                    "url": "https://github.com/user/repo/pull/2"
                }
            },
            {
                "text": "Documento genérico"
            }
        ]
        
        # Chamar método
        formatted = llm_service._format_context(context)
        
        # Verificar resultado
        assert "Issue #1: Issue 1" in formatted
        assert "https://github.com/user/repo/issues/1" in formatted
        assert "Descrição da issue" in formatted
        
        assert "Commit abc123" in formatted
        assert "Developer" in formatted
        assert "Mensagem do commit" in formatted
        
        assert "Pull Request #2: PR 1" in formatted
        assert "https://github.com/user/repo/pull/2" in formatted
        assert "Conteúdo do PR" in formatted
        
        assert "Documento 4" in formatted
        assert "Documento genérico" in formatted
    
    def test_format_requirements_data(self, llm_service):
        """Testa a formatação de dados de requisitos para o prompt"""
        # Dados de teste
        requirements_data = [
            {
                "title": "Requisito 1",
                "description": "Descrição do requisito 1",
                "issues": [
                    {"id": 1, "title": "Issue relacionada"}
                ],
                "pull_requests": [
                    {"id": 2, "title": "PR relacionado"}
                ],
                "commits": [
                    {"sha": "abc123", "message": "Implementação do requisito 1"}
                ]
            },
            {
                "title": "Requisito 2",
                "description": "Descrição do requisito 2"
            }
        ]
        
        # Chamar método
        formatted = llm_service._format_requirements_data(requirements_data)
        
        # Verificar resultado
        assert "Requisito 1: Requisito 1" in formatted
        assert "Descrição: Descrição do requisito 1" in formatted
        assert "Issue #1: Issue relacionada" in formatted
        assert "PR #2: PR relacionado" in formatted
        assert "abc123: Implementação do requisito 1" in formatted
        
        assert "Requisito 2: Requisito 2" in formatted
        assert "Descrição: Descrição do requisito 2" in formatted
