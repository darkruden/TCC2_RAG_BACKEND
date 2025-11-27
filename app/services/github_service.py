# CÓDIGO COMPLETO PARA: app/services/github_service.py

import os
import base64
import requests
from github import Github, Auth, GithubException
import re
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor # <--- OTIMIZAÇÃO

# Constantes de Extensões (Mantidas)
TEXT_EXTENSIONS = {
    ".py", ".js", ".mjs", ".ts", ".tsx", ".html", ".css", ".scss", ".json", ".md",
    ".txt", ".rst", ".java", ".c", ".h", ".cpp", ".go", ".php", ".rb", ".swift",
    ".kt", ".kts", ".sql", ".xml", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".sh", ".bat", ".ps1", ".dockerfile", ".gitignore", ".npmignore", ".env",
    ".example", "procfile", ".conf", ".properties", ".log",
    "requirements.txt", "package.json", "pom.xml", "build.gradle", "gemfile",
}
IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico", ".tif", ".tiff",
    ".webp", ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".ogg",
    ".zip", ".tar", ".gz", ".rar", ".7z", ".pkg",
    ".exe", ".dll", ".so", ".a", ".o", ".lib",
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".eot", ".ttf", ".woff", ".woff2",
    ".DS_Store",
}

class GithubService:
    def __init__(self, token: Optional[str] = None):
        if not token:
            token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise ValueError("Token do GitHub não fornecido. Defina GITHUB_TOKEN.")
        
        auth = Auth.Token(token)
        self.g = Github(auth=auth)
        try:
            self.g.get_user().login
            print("[GitHubService] Autenticação no GitHub bem-sucedida.")
        except Exception as e:
            print(f"[GitHubService] ERRO: Falha ao autenticar no GitHub. {e}")
            raise ValueError("Token do GitHub inválido ou expirado.")

    def parse_repo_url(self, repo_url: str) -> Tuple[str, Optional[str]]:
        branch = None
        clean_url = repo_url

        if "/tree/" in repo_url:
            parts = repo_url.split("/tree/")
            clean_url = parts[0]
            if len(parts) > 1:
                branch = parts[1].strip("/")
        
        match = re.search(r"github\.com/([\w\-\.]+)/([\w\-\.]+)", clean_url)
        if match:
            return f"{match.group(1)}/{match.group(2)}", branch
        
        if "/" in clean_url and "github.com" not in clean_url:
            return clean_url, branch
            
        raise ValueError(f"URL de repositório inválida: {repo_url}")

    def get_repo_metadata(self, repo_name: str) -> Dict[str, Any]:
        """Retorna metadados gerais do repositório, incluindo visibilidade."""
        repo = self.g.get_repo(repo_name)
        return {
            "full_name": repo.full_name,
            "private": repo.private,
            "visibility": "private" if repo.private else "public",
            "default_branch": repo.default_branch
        }

    def get_repo_file_structure(self, repo_name: str, branch: str) -> Dict[str, str]:
        """
        Retorna um mapa {path: sha} de todos os arquivos de texto do repositório.
        """
        print(f"[GitHubService] Mapeando estrutura de arquivos para {repo_name} (Branch: {branch})...")
        repo = self.g.get_repo(repo_name)
        
        try:
            tree = repo.get_git_tree(sha=branch, recursive=True)
        except GithubException as e:
            print(f"[GitHubService] Erro ao buscar árvore git: {e}")
            raise

        file_map = {}
        for element in tree.tree:
            if element.type == "blob": # É um arquivo
                if self._is_text_file(element.path):
                     file_map[element.path] = element.sha
        
        print(f"[GitHubService] Mapa construído: {len(file_map)} arquivos rastreáveis encontrados.")
        return file_map

    def get_file_content(self, repo_name: str, file_path: str, branch: str) -> Optional[str]:
        """Baixa o conteúdo de um único arquivo."""
        try:
            repo = self.g.get_repo(repo_name)
            content_file = repo.get_contents(file_path, ref=branch)
            if content_file.size == 0 or content_file.size > 1_000_000:
                return None
            
            return base64.b64decode(content_file.content).decode("utf-8")
        except Exception as e:
            print(f"[GitHubService] Erro ao baixar {file_path}: {e}")
            return None

    def get_repo_data_batch(
            self,
            repo_url: str,
            issues_limit: int, 
            prs_limit: int, 
            commits_limit: int,
            since: Optional[datetime] = None,
            branch: Optional[str] = None
        ) -> Dict[str, List[Dict[str, Any]]]:
            
            repo_name, _ = self.parse_repo_url(repo_url)
            repo = self.g.get_repo(repo_name)

            print(f"[GitHubService] Iniciando busca PARALELA de metadados (Commits={commits_limit}, Issues={issues_limit})...")

            # --- OTIMIZAÇÃO: Paralelismo na busca de metadados ---
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_commits = executor.submit(self._get_repo_commits, repo, commits_limit, since, branch)
                future_issues = executor.submit(self._get_repo_issues, repo, issues_limit, since)
                future_prs = executor.submit(self._get_repo_prs, repo, prs_limit, since)
                
                # O .result() bloqueia até que a thread termine, mas elas rodam juntas
                commits_data = future_commits.result()
                issues_data = future_issues.result()
                prs_data = future_prs.result()

            print(f"[GitHubService] Busca finalizada. Commits: {len(commits_data)}, Issues: {len(issues_data)}, PRs: {len(prs_data)}")

            return {
                "commits": commits_data,
                "issues": issues_data,
                "prs": prs_data
            }

    # --- Helpers Internos (Mantidos) ---
    def _get_repo_commits(self, repo: Any, max_items: int, since: Optional[datetime], sha: Optional[str] = None) -> List[Dict[str, Any]]:
            commits_data = []
            api_args = {}
            if since: api_args['since'] = since
            if sha: api_args['sha'] = sha 
            
            try:
                commits_paginator = repo.get_commits(**api_args)
                count = 0
                for commit in commits_paginator:
                    if count >= max_items: break
                    commits_data.append({
                        "sha": commit.sha, "message": commit.commit.message,
                        "author": commit.commit.author.name or "N/A",
                        "date": commit.commit.author.date.isoformat(),
                        "url": commit.html_url, "tipo": "commit"
                    })
                    count += 1
                return commits_data
            except Exception as e:
                print(f"[GitHubService] AVISO: Erro ao buscar commits (possivelmente branch vazia ou nova): {e}")
                return []

    def _get_repo_issues(self, repo: Any, max_items: int, since: Optional[datetime]) -> List[Dict[str, Any]]:
        issues_data = []
        api_args = {'state': 'all', 'sort': 'updated', 'direction': 'desc'}
        if since: api_args['since'] = since
        try:
            for issue in repo.get_issues(**api_args):
                if len(issues_data) >= max_items: break
                if issue.pull_request: continue
                issues_data.append({
                    "id": issue.number, "title": issue.title,
                    "author": issue.user.login, "date": issue.created_at.isoformat(),
                    "url": issue.html_url, "body": issue.body or "", "tipo": "issue"
                })
            return issues_data
        except Exception:
            return []

    def _get_repo_prs(self, repo: Any, max_items: int, since: Optional[datetime]) -> List[Dict[str, Any]]:
        prs_data = []
        api_args = {'state': 'all', 'sort': 'updated', 'direction': 'desc'}
        if since: api_args['since'] = since
        try:
            for pr in repo.get_pulls(**api_args):
                if len(prs_data) >= max_items: break
                prs_data.append({
                    "id": pr.number, "title": pr.title,
                    "author": pr.user.login, "date": pr.created_at.isoformat(),
                    "url": pr.html_url, "body": pr.body or "", "tipo": "pr"
                })
            return prs_data
        except Exception:
            return []

    def _is_text_file(self, file_path: str) -> bool:
        try:
            filename = os.path.basename(file_path).lower()
            if filename in TEXT_EXTENSIONS: return True
            ext = Path(file_path).suffix.lower()
            if not ext:
                if Path(file_path).name.lower() in ["readme", "contributing", "license", "makefile"]: return True
                return False
            if ext in TEXT_EXTENSIONS: return True
            return False
        except Exception:
            return False
        
    # Adicione este método dentro da classe GithubService
    def check_rate_limit(self) -> Dict[str, Any]:
        """
        Consulta o 'saldo' da API do GitHub.
        """
        try:
            # Tenta obter o objeto geral
            rate_limit_obj = self.g.get_rate_limit()
            
            # Tenta acessar 'core' (API REST) ou usa o objeto direto se for GraphQL/Outro
            # Em algumas versões do PyGithub, o objeto raiz já contém os dados ou usa 'rate'
            core_limit = getattr(rate_limit_obj, 'core', rate_limit_obj)
            
            # Se ainda falhar, tenta acessar atributos diretos (fallback genérico)
            limit = getattr(core_limit, 'limit', 5000)
            remaining = getattr(core_limit, 'remaining', 5000)
            reset = getattr(core_limit, 'reset', datetime.now())

            status = {
                "limit": limit,
                "remaining": remaining,
                "reset": reset.isoformat() if isinstance(reset, datetime) else str(reset)
            }
            print(f"[GitHubService] Rate Limit: {status['remaining']}/{status['limit']} restantes.")
            return status
        except Exception as e:
            print(f"[GitHubService] Aviso: Erro não-fatal ao checar limites ({e}). Usando valores padrão.")
            # Fallback seguro: assume que tem 5000 para não travar
            return {"limit": 5000, "remaining": 5000}