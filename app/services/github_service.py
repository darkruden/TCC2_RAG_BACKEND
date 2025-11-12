import os
from github import Github, GithubObject
from typing import List, Dict, Any, Optional
import traceback    
# [CORREÇÃO 1]: Removida a importação 'from sympy import limit'
# (Ela estava causando um conflito de nomes com o parâmetro 'limit')

class GitHubService:
    """
    Serviço para interação com a API do GitHub.
    Responsável por coletar dados de repositórios, issues, pull requests e commits.
    """
    
    def __init__(self, token: str = None):
        """
        Inicializa o serviço GitHub com um token de autenticação.
        
        Args:
            token: Token de acesso à API do GitHub
        """
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("Token do GitHub não fornecido")
        
        self.github = Github(self.token)
    
    def get_repository(self, repo_name: str):
        """
        Obtém um repositório do GitHub.
        """
        try:
            return self.github.get_repo(repo_name)
        except Exception as e:
            raise Exception(f"Erro ao acessar repositório {repo_name}: {str(e)}")
    

    # [CORREÇÃO 2]: Lógica de iteração corrigida
    def get_issues(self, repo_name: str, state: str = "all", labels: List[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Obtém issues de um repositório.
        Lida com o caso de 'Issues' estarem desabilitadas.
        """
        print(f"[GitHubService] Buscando issues para {repo_name} (limite: {limit})...")
        try:
            repo = self.get_repository(repo_name)
            issues = []
            labels_list = labels if labels is not None else []
            issues_query = repo.get_issues(state=state, labels=labels_list)
            
            # Itera sobre a consulta e aplica o limite manualmente
            # Isso corrige o bug de fatiar (slice) antes de filtrar
            for issue in issues_query:
                # Pula pull requests
                if issue.pull_request:
                    continue
                    
                issues.append({
                    "id": issue.number,
                    "title": issue.title,
                    "body": issue.body or "",
                    "state": issue.state,
                    "created_at": issue.created_at.isoformat(),
                    "updated_at": issue.updated_at.isoformat(),
                    "labels": [label.name for label in issue.labels],
                    "url": issue.html_url,
                    "author": issue.user.login if issue.user else None,
                    "comments_count": issue.comments
                })
                
                # Para de iterar quando atingimos o limite
                if limit and len(issues) >= limit:
                    print(f"[GitHubService] Limite de {limit} issues atingido.")
                    break
            
            print(f"[GitHubService] Encontradas {len(issues)} issues reais.")
            return issues

        except AssertionError as e:
            print(f"[GitHubService] CAPTURADO ASSERTIONERROR EM GET_ISSUES para {repo_name}.")
            print(f"Erro detalhado: {repr(e)}")
            traceback.print_exc()  # <--- Isso imprimirá o traceback completo no log
            return []
        
        except Exception as e:
            print(f"[GitHubService] Erro inesperado em get_issues para {repo_name}: {repr(e)}")
            raise e

    
    # app/services/github_service.py 

    def get_pull_requests(self, repo_name: str, state: str = "all", limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Obtém pull requests de um repositório.
        [CORREÇÃO]: Itera manualmente para evitar 'IndexError' em repositórios vazios.
        """
        print(f"[GitHubService] Buscando PRs para {repo_name} (limite: {limit})...")
        repo = self.get_repository(repo_name)
        pull_requests = []
        
        pr_query = repo.get_pulls(state=state)
        
        # --- INÍCIO DA CORREÇÃO ---
        # Itera sobre a consulta e aplica o limite manualmente
        for pr in pr_query:
            pull_requests.append({
                "id": pr.number,
                "title": pr.title,
                "body": pr.body or "",
                "state": pr.state,
                "created_at": pr.created_at.isoformat(),
                "updated_at": pr.updated_at.isoformat(),
                "merged": pr.merged,
                "url": pr.html_url,
                "author": pr.user.login if pr.user else None,
                "comments_count": pr.comments
            })
            
            # Para de iterar quando atingimos o limite
            if limit and len(pull_requests) >= limit:
                print(f"[GitHubService] Limite de {limit} PRs atingido.")
                break
        # --- FIM DA CORREÇÃO ---
        
        print(f"[GitHubService] Encontrados {len(pull_requests)} PRs.")
        return pull_requests
    

    # [CORREÇÃO 3]: Lógica de iteração aplicada para robustez
    def get_commits(self, repo_name: str, branch: str = None, path: str = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Obtém commits de um repositório.
        Lida com o caso de 'Commits' não estarem acessíveis ou repositório vazio.
        """
        print(f"[GitHubService] Buscando commits para {repo_name} (limite: {limit})...")
        try:
            repo = self.get_repository(repo_name)
            commits = []
            branch_sha = branch if branch is not None else GithubObject.NotSet
            path_str = path if path is not None else GithubObject.NotSet
            commits_query = repo.get_commits(sha=branch_sha, path=path_str)
            
            # Itera sobre a consulta e aplica o limite manualmente
            # (Mais robusto do que fatiar, que era a fonte do Bug 1)
            count = 0
            for commit in commits_query:
                if limit and count >= limit:
                    print(f"[GitHubService] Limite de {limit} commits atingido.")
                    break
                
                author_name = commit.commit.author.name if commit.commit.author else "N/A"
                author_email = commit.commit.author.email if commit.commit.author else "N/A"
                author_date = commit.commit.author.date.isoformat() if commit.commit.author else "N/A"

                commits.append({
                    "sha": commit.sha,
                    "message": commit.commit.message,
                    "author": author_name,
                    "author_email": author_email,
                    "date": author_date,
                    "url": commit.html_url
                })
                count += 1
            
            print(f"[GitHubService] Encontrados {len(commits)} commits.")
            return commits

        except AssertionError:
            print(f"[GitHubService] Capturado 'AssertionError' ao buscar commits para {repo_name}. "
                  "Provavelmente problema de acesso ou repositório vazio. Pulando a coleta de commits.")
            return []
        
        except Exception as e:
            print(f"[GitHubService] Erro inesperado em get_commits para {repo_name}: {repr(e)}")
            raise e
    
    
    def get_repository_info(self, repo_name: str) -> Dict[str, Any]:
        """
        Obtém informações gerais sobre um repositório.
        """
        repo = self.get_repository(repo_name)
        
        return {
            "name": repo.name,
            "full_name": repo.full_name,
            "description": repo.description,
            "url": repo.html_url,
            "stars": repo.stargazers_count,
            "forks": repo.forks_count,
            "open_issues": repo.open_issues_count,
            "created_at": repo.created_at.isoformat(),
            "updated_at": repo.updated_at.isoformat(),
            "language": repo.language,
            "topics": repo.get_topics()
        }
    
    
    def search_code(self, repo_name: str, query: str) -> List[Dict[str, Any]]:
        """
        Pesquisa código em um repositório.
        """
        results = []
        search_query = f"repo:{repo_name} {query}"
        
        for code_result in self.github.search_code(search_query):
            results.append({
                "name": code_result.name,
                "path": code_result.path,
                "url": code_result.html_url,
                "repository": code_result.repository.full_name
            })
        
        return results