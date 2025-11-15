# CÓDIGO COMPLETO PARA: app/services/ingest_service.py
# (Refatorado - Funções de tarefa movidas para worker_tasks.py)

import os
from github import Github, Auth
from typing import List, Dict, Any, Optional
from datetime import datetime

# --- CLASSE GithubService ---
# (Esta classe não é uma tarefa, é um serviço, então está correta aqui)
class GithubService:
    """
    Serviço para buscar dados da API do GitHub.
    """
    def __init__(self):
        GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
        if not GITHUB_TOKEN:
            print("[GitHubService] AVISO: GITHUB_TOKEN não definido.")
            self.g = Github()
        else:
            try:
                auth = Auth.Token(GITHUB_TOKEN)
                self.g = Github(auth=auth)
            except Exception as e:
                print(f"[GitHubService] Erro ao autenticar com GitHub: {e}")
                self.g = Github()

    def get_repo_data(self, repo_name: str, issues_limit: int, prs_limit: int, commits_limit: int, since: Optional[datetime] = None) -> Dict[str, List[Dict[str, Any]]]:
        if since:
            print(f"[GitHubService] Iniciando busca INCREMENTAL para: {repo_name} (desde {since})")
        else:
            print(f"[GitHubService] Iniciando busca COMPLETA para: {repo_name}")
        
        try:
            repo = self.g.get_repo(repo_name)
        except Exception as e:
            print(f"[GitHubService] Erro: Não foi possível encontrar o repositório '{repo_name}'. {e}")
            raise ValueError(f"Repositório '{repo_name}' não encontrado ou inacessível.") from e

        data = {"commits": [], "issues": [], "prs": []}
        api_args = {}
        if since:
            api_args['since'] = since

        # 1. Buscar Commits
        try:
            commits = repo.get_commits(**api_args) 
            count = 0
            for commit in commits:
                if count >= commits_limit: break
                commit_data = {
                    "sha": commit.sha, "message": commit.commit.message,
                    "author": commit.commit.author.name or "N/A",
                    "date": commit.commit.author.date.isoformat(), "url": commit.html_url
                }
                data["commits"].append(commit_data); count += 1
        except Exception as e: print(f"[GitHubService] Erro ao buscar commits: {e}")

        # 2. Buscar Issues
        try:
            issues = repo.get_issues(state="all", **api_args) 
            count = 0
            for issue in issues:
                if count >= issues_limit: break
                if issue.pull_request: continue
                issue_data = {
                    "id": issue.number, "title": issue.title, "author": issue.user.login,
                    "date": issue.created_at.isoformat(), "url": issue.html_url, "body": issue.body or ""
                }
                data["issues"].append(issue_data); count += 1
        except Exception as e: print(f"[GitHubService] Erro ao buscar issues: {e}")

        # 3. Buscar Pull Requests
        try:
            prs = repo.get_pulls(state="all", **api_args)
            count = 0
            for pr in prs:
                if count >= prs_limit: break
                pr_data = {
                    "id": pr.number, "title": pr.title, "author": pr.user.login,
                    "date": pr.created_at.isoformat(), "url": pr.html_url, "body": pr.body or ""
                }
                data["prs"].append(pr_data); count += 1
        except Exception as e: print(f"[GitHubService] Erro ao buscar PRs: {e}")

        print(f"[GitHubService] Busca concluída para {repo_name}:")
        print(f"  {len(data['commits'])} novos commits, {len(data['issues'])} novas issues, {len(data['prs'])} novos PRs")
        return data

# --- CLASSE IngestService ---
# (Esta classe também é apenas uma biblioteca de helpers, não uma tarefa)

from app.services.metadata_service import MetadataService
from app.services.embedding_service import get_embedding

class IngestService:
    """
    Serviço que coordena a ingestão de dados.
    """
    def __init__(self):
        try:
            self.metadata_service = MetadataService()
            self.github_service = GithubService()
        except Exception as e:
            print(f"[IngestService] Erro crítico ao inicializar serviços dependentes: {e}")
            raise
    
    def format_data_for_ingestion(self, repo_name: str, raw_data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        # (Função helper interna)
        documentos = []
        for item in raw_data.get("commits", []):
            conteudo = f"Commit de {item.get('author', 'N/A')}: {item.get('message', '')}"
            documentos.append({
                "repositorio": repo_name, "tipo": "commit",
                "metadados": {"sha": item['sha'], "autor": item['author'], "data": item['date'], "url": item['url']},
                "conteudo": conteudo
            })
        for item in raw_data.get("issues", []):
            conteudo = f"Issue #{item['id']} por {item['author']}: {item['title']}\n{item.get('body', '')}"
            documentos.append({
                "repositorio": repo_name, "tipo": "issue",
                "metadados": {"id": item['id'], "autor": item['author'], "data": item['date'], "url": item['url'], "titulo": item['title']},
                "conteudo": conteudo
            })
        for item in raw_data.get("prs", []):
            conteudo = f"PR #{item['id']} por {item['author']}: {item['title']}\n{item.get('body', '')}"
            documentos.append({
                "repositorio": repo_name, "tipo": "pr",
                "metadados": {"id": item['id'], "autor": item['author'], "data": item['date'], "url": item['url'], "titulo": item['title']},
                "conteudo": conteudo
            })
        return documentos

# (As funções 'ingest_repo' e 'save_instruction' foram movidas para worker_tasks.py)
# (O singleton no final foi removido)