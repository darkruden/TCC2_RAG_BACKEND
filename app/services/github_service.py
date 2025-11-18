# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/github_service.py
# (Converte o arquivo de funções para a Classe que o worker_tasks espera)

import os
import base64
import requests
from github import Github, Auth, GithubException
import re
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime

# Constantes
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
            """
            Retorna (nome_repo, branch_name).
            Ex: "https://github.com/user/repo/tree/dev" -> ("user/repo", "dev")
            Ex: "https://github.com/user/repo" -> ("user/repo", None)
            """
            branch = None
            clean_url = repo_url

            # Detecta padrão de branch na URL
            if "/tree/" in repo_url:
                parts = repo_url.split("/tree/")
                clean_url = parts[0] # Pega a parte antes do /tree/
                if len(parts) > 1:
                    branch = parts[1].strip("/")
            
            match = re.search(r"github\.com/([\w\-\.]+)/([\w\-\.]+)", clean_url)
            if match:
                return f"{match.group(1)}/{match.group(2)}", branch
            
            if "/" in clean_url and "github.com" not in clean_url:
                return clean_url, branch
                
            raise ValueError(f"URL de repositório inválida: {repo_url}")

    def get_repo_data_batch(
            self,
            repo_url: str,
            issues_limit: int, 
            prs_limit: int, 
            commits_limit: int,
            since: Optional[datetime] = None,
            branch: Optional[str] = None # <--- Novo parametro
        ) -> Dict[str, List[Dict[str, Any]]]:
            # Parseamos apenas para pegar o nome limpo, a branch já vem passada ou detectada antes
            repo_name, _ = self.parse_repo_url(repo_url)
            
            # ... prints mantidos ...
            repo = self.g.get_repo(repo_name)

            # Para commits, passamos o SHA (branch) se existir
            commits = self._get_repo_commits(repo, commits_limit, since, sha=branch)
            
            # Issues e PRs são globais do repo, não dependem tanto de branch, mantemos padrão
            return {
                "commits": commits,
                "issues": self._get_repo_issues(repo, issues_limit, since),
                "prs": self._get_repo_prs(repo, prs_limit, since)
            }

    def _get_repo_commits(self, repo: Any, max_items: int, since: Optional[datetime], sha: Optional[str] = None) -> List[Dict[str, Any]]:
            # ... logs ...
            commits_data = []
            api_args = {}
            if since: api_args['since'] = since
            if sha: api_args['sha'] = sha # <--- Usa a branch aqui
            
            try:
                commits_paginator = repo.get_commits(**api_args)
                # ... loop mantido ...
                # (Certifique-se de copiar o loop do seu arquivo original aqui)
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
                print(f"[GitHubService] ERRO ao buscar commits: {e}")
                return []

    def _get_repo_issues(self, repo: Any, max_items: int, since: Optional[datetime]) -> List[Dict[str, Any]]:
        print(f"[GitHubService] Buscando {max_items} issues...")
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
        except Exception as e:
            print(f"[GitHubService] ERRO ao buscar issues: {e}")
            return []

    def _get_repo_prs(self, repo: Any, max_items: int, since: Optional[datetime]) -> List[Dict[str, Any]]:
        print(f"[GitHubService] Buscando {max_items} PRs...")
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
        except Exception as e:
            print(f"[GitHubService] ERRO ao buscar PRs: {e}")
            return []

    def get_repo_files_batch(
            self, repo_url: str, max_depth: int = 10, branch: Optional[str] = None
        ) -> List[Dict[str, str]]:
            repo_name, _ = self.parse_repo_url(repo_url) # Ignora branch da URL pois já foi passado ou processado
            print(f"[GitHubService] Buscando arquivos de: {repo_name} (Branch: {branch or 'Default'})")
            
            try:
                repo = self.g.get_repo(repo_name)
            except GithubException:
                raise ValueError(f"Repositório não encontrado: {repo_name}")

            # AQUI É A MÁGICA: Passamos 'ref' para pegar conteúdo de outra branch
            contents_args = {}
            if branch: contents_args["ref"] = branch
            
            try:
                contents = repo.get_contents("", **contents_args)
            except Exception as e:
                 print(f"[GitHubService] Erro ao acessar branch '{branch}': {e}")
                 raise

            files_data = []
            queue = [(contents, 0)]
            
            while queue:
                current_contents, current_depth = queue.pop(0)
                if current_depth > max_depth: continue
                for content in current_contents:
                    if content.type == "dir":
                        try:
                            # Recursão também precisa do ref/branch
                            queue.append((repo.get_contents(content.path, **contents_args), current_depth + 1))
                        except GithubException as e:
                            pass
                    elif content.type == "file":
                        if self._is_text_file(content.path):
                            # ... lógica de download e decode mantida ...
                            # Copie a lógica do seu arquivo original (checagem de tamanho, base64, etc)
                            if content.size == 0 or content.size > 1_000_000: continue
                            try:
                                decoded_content = base64.b64decode(content.content).decode("utf-8")
                                files_data.append({"file_path": content.path, "content": decoded_content})
                            except Exception:
                                pass
            return files_data

    def _is_text_file(self, file_path: str) -> bool:
        try:
            filename = os.path.basename(file_path).lower()
            if filename in TEXT_EXTENSIONS: return True
            ext = Path(file_path).suffix.lower()
            if not ext:
                if Path(file_path).name.lower() in ["readme", "contributing", "license", "makefile"]: return True
                return False
            if ext in TEXT_EXTENSIONS: return True
            if ext in IMAGE_EXTENSIONS: return False
            return False
        except Exception:
            return False