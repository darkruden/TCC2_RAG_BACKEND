import pytest
import os
from unittest.mock import patch, MagicMock
from app.services.github_service import GitHubService

# Configuração de fixtures para testes
@pytest.fixture
def mock_github():
    with patch('app.services.github_service.Github') as mock_github:
        # Configurar o mock para retornar valores específicos
        mock_instance = MagicMock()
        mock_github.return_value = mock_instance
        yield mock_instance

@pytest.fixture
def github_service():
    # Configurar variável de ambiente para teste
    os.environ["GITHUB_TOKEN"] = "test_token"
    service = GitHubService()
    yield service
    # Limpar após o teste
    os.environ.pop("GITHUB_TOKEN", None)

# Testes unitários
class TestGitHubService:
    
    def test_init_with_token(self):
        """Testa a inicialização do serviço com token fornecido"""
        service = GitHubService(token="custom_token")
        assert service.token == "custom_token"
    
    def test_init_with_env_token(self, github_service):
        """Testa a inicialização do serviço com token do ambiente"""
        assert github_service.token == "test_token"
    
    def test_init_without_token(self):
        """Testa a inicialização do serviço sem token"""
        os.environ.pop("GITHUB_TOKEN", None)
        with pytest.raises(ValueError):
            GitHubService()
    
    def test_get_repository(self, github_service, mock_github):
        """Testa a obtenção de um repositório"""
        # Configurar mock
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        
        # Chamar método
        repo = github_service.get_repository("user/repo")
        
        # Verificar chamadas e resultado
        mock_github.get_repo.assert_called_once_with("user/repo")
        assert repo == mock_repo
    
    def test_get_repository_error(self, github_service, mock_github):
        """Testa erro na obtenção de um repositório"""
        # Configurar mock para lançar exceção
        mock_github.get_repo.side_effect = Exception("Repo not found")
        
        # Verificar se a exceção é propagada corretamente
        with pytest.raises(Exception) as excinfo:
            github_service.get_repository("user/nonexistent")
        
        assert "Erro ao acessar repositório" in str(excinfo.value)
    
    def test_get_issues(self, github_service, mock_github):
        """Testa a obtenção de issues de um repositório"""
        # Configurar mocks
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        
        mock_issue1 = MagicMock()
        mock_issue1.number = 1
        mock_issue1.title = "Issue 1"
        mock_issue1.body = "Description 1"
        mock_issue1.state = "open"
        mock_issue1.created_at.isoformat.return_value = "2025-01-01T00:00:00"
        mock_issue1.updated_at.isoformat.return_value = "2025-01-02T00:00:00"
        mock_issue1.labels = [MagicMock(name="bug")]
        mock_issue1.html_url = "https://github.com/user/repo/issues/1"
        mock_issue1.user.login = "user1"
        mock_issue1.comments = 5
        mock_issue1.pull_request = None
        
        mock_issue2 = MagicMock()
        mock_issue2.number = 2
        mock_issue2.title = "PR 1"
        mock_issue2.pull_request = MagicMock()  # Este é um PR, não uma issue
        
        mock_repo.get_issues.return_value = [mock_issue1, mock_issue2]
        
        # Chamar método
        issues = github_service.get_issues("user/repo")
        
        # Verificar resultado
        assert len(issues) == 1  # Apenas uma issue (não PR)
        assert issues[0]["id"] == 1
        assert issues[0]["title"] == "Issue 1"
        assert issues[0]["state"] == "open"
        assert issues[0]["labels"] == ["bug"]
        assert issues[0]["url"] == "https://github.com/user/repo/issues/1"
        assert issues[0]["author"] == "user1"
        assert issues[0]["comments_count"] == 5
    
    def test_get_pull_requests(self, github_service, mock_github):
        """Testa a obtenção de pull requests de um repositório"""
        # Configurar mocks
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        
        mock_pr = MagicMock()
        mock_pr.number = 1
        mock_pr.title = "PR 1"
        mock_pr.body = "Description 1"
        mock_pr.state = "open"
        mock_pr.created_at.isoformat.return_value = "2025-01-01T00:00:00"
        mock_pr.updated_at.isoformat.return_value = "2025-01-02T00:00:00"
        mock_pr.merged = False
        mock_pr.html_url = "https://github.com/user/repo/pull/1"
        mock_pr.user.login = "user1"
        mock_pr.comments = 3
        
        mock_repo.get_pulls.return_value = [mock_pr]
        
        # Chamar método
        prs = github_service.get_pull_requests("user/repo")
        
        # Verificar resultado
        assert len(prs) == 1
        assert prs[0]["id"] == 1
        assert prs[0]["title"] == "PR 1"
        assert prs[0]["state"] == "open"
        assert prs[0]["merged"] == False
        assert prs[0]["url"] == "https://github.com/user/repo/pull/1"
        assert prs[0]["author"] == "user1"
        assert prs[0]["comments_count"] == 3
    
    def test_get_commits(self, github_service, mock_github):
        """Testa a obtenção de commits de um repositório"""
        # Configurar mocks
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        
        mock_commit = MagicMock()
        mock_commit.sha = "abc123"
        mock_commit.commit.message = "Fix bug"
        mock_commit.commit.author.name = "Developer"
        mock_commit.commit.author.email = "dev@example.com"
        mock_commit.commit.author.date.isoformat.return_value = "2025-01-01T00:00:00"
        mock_commit.html_url = "https://github.com/user/repo/commit/abc123"
        
        mock_repo.get_commits.return_value = [mock_commit]
        
        # Chamar método
        commits = github_service.get_commits("user/repo")
        
        # Verificar resultado
        assert len(commits) == 1
        assert commits[0]["sha"] == "abc123"
        assert commits[0]["message"] == "Fix bug"
        assert commits[0]["author"] == "Developer"
        assert commits[0]["author_email"] == "dev@example.com"
        assert commits[0]["url"] == "https://github.com/user/repo/commit/abc123"
    
    def test_get_repository_info(self, github_service, mock_github):
        """Testa a obtenção de informações de um repositório"""
        # Configurar mocks
        mock_repo = MagicMock()
        mock_repo.name = "repo"
        mock_repo.full_name = "user/repo"
        mock_repo.description = "A test repository"
        mock_repo.html_url = "https://github.com/user/repo"
        mock_repo.stargazers_count = 10
        mock_repo.forks_count = 5
        mock_repo.open_issues_count = 3
        mock_repo.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_repo.updated_at.isoformat.return_value = "2025-01-01T00:00:00"
        mock_repo.language = "Python"
        mock_repo.get_topics.return_value = ["api", "testing"]
        
        mock_github.get_repo.return_value = mock_repo
        
        # Chamar método
        info = github_service.get_repository_info("user/repo")
        
        # Verificar resultado
        assert info["name"] == "repo"
        assert info["full_name"] == "user/repo"
        assert info["description"] == "A test repository"
        assert info["url"] == "https://github.com/user/repo"
        assert info["stars"] == 10
        assert info["forks"] == 5
        assert info["open_issues"] == 3
        assert info["language"] == "Python"
        assert info["topics"] == ["api", "testing"]
    
    def test_search_code(self, github_service, mock_github):
        """Testa a pesquisa de código em um repositório"""
        # Configurar mocks
        mock_result = MagicMock()
        mock_result.name = "file.py"
        mock_result.path = "src/file.py"
        mock_result.html_url = "https://github.com/user/repo/blob/main/src/file.py"
        mock_result.repository.full_name = "user/repo"
        
        mock_github.search_code.return_value = [mock_result]
        
        # Chamar método
        results = github_service.search_code("user/repo", "function")
        
        # Verificar chamadas e resultado
        mock_github.search_code.assert_called_once_with("repo:user/repo function")
        
        assert len(results) == 1
        assert results[0]["name"] == "file.py"
        assert results[0]["path"] == "src/file.py"
        assert results[0]["url"] == "https://github.com/user/repo/blob/main/src/file.py"
        assert results[0]["repository"] == "user/repo"
