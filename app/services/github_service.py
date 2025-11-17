# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/github_service.py
# (Converte o arquivo de funções para a Classe que o worker_tasks espera)

import os
import base64
import requests
from github import Github, Auth, GithubException
import re
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

# Constantes para tipos de arquivos (movidas para dentro da classe ou mantidas globais se necessário)
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

    def parse_repo_url(self, repo_url: str) -> str:
        """
        Extrai 'owner/repo_name' de URLs do GitHub (http, https, git).
        """
        match = re.search(r"github\.com/([\w\-\.]+)/([\w\-\.]+)", repo_url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        
        if "/" in repo_url and not "github.com" in repo_url:
            return repo_url
            
        raise ValueError(f"URL de repositório inválida: {repo_url}")

    def get_repo_data_batch(
        self,
        repo_url: str,
        issues_limit: int, 
        prs_limit: int, 
        commits_limit: int,
        since: Optional[datetime] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Busca commits, issues e PRs de um repositório do GitHub.
        """
        repo_name = self.parse_repo_url(repo_url)
        
        if since:
            print(f"[GitHubService] Iniciando busca INCREMENTAL para: {repo_name} (desde {since})")
        else:
            print(f"[GitHubService] Iniciando busca COMPLETA para: {repo_name}")
        
        try:
            repo = self.g.get_repo(repo_name)
        except Exception as e:
            print(f"[GitHubService] Erro: Não foi possível encontrar o repositório '{repo_name}'. {e}")
            raise ValueError(f"Repositório '{repo_name}' não encontrado ou inacessível.") from e

        data = {
            "commits": self._get_repo_commits(repo, commits_limit, since),
            "issues": self._get_repo_issues(repo, issues_limit, since),
            "prs": self._get_repo_prs(repo, prs_limit, since)
        }
        
        print(f"[GitHubService] Busca concluída para {repo_name}:")
        print(f"  {len(data['commits'])} commits, {len(data['issues'])} issues, {len(data['prs'])} PRs")
        return data

    def _get_repo_commits(self, repo: Any, max_items: int, since: Optional[datetime]) -> List[Dict[str, Any]]:
        print(f"[GitHubService] Buscando {max_items} commits...")
        commits_data = []
        api_args = {}
        if since:
            api_args['since'] = since
        try:
            commits_paginator = repo.get_commits(**api_args)
            count = 0
            for commit in commits_paginator:
                if count >= max_items:
                    break
                
                commits_data.append({
                    "sha": commit.sha,
                    "message": commit.commit.message,
                    "author": commit.commit.author.name or "N/A",
                    "date": commit.commit.author.date.isoformat(),
                    "url": commit.html_url,
                    "tipo": "commit"
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
        if since:
            api_args['since'] = since
        try:
            for issue in repo.get_issues(**api_args):
                if len(issues_data) >= max_items:
                    break
                if issue.pull_request: # Ignora PRs
                    continue
                    
                issues_data.append({
                    "id": issue.number,
                    "title": issue.title,
                    "author": issue.user.login,
                    "date": issue.created_at.isoformat(),
                    "url": issue.html_url,
                    "body": issue.body or "",
                    "tipo": "issue"
                })
            return issues_data
        except Exception as e:
            print(f"[GitHubService] ERRO ao buscar issues: {e}")
            return []

    def _get_repo_prs(self, repo: Any, max_items: int, since: Optional[datetime]) -> List[Dict[str, Any]]:
        print(f"[GitHubService] Buscando {max_items} PRs...")
        prs_data = []
        api_args = {'state': 'all', 'sort': 'updated', 'direction': 'desc'}
        if since:
            api_args['since'] = since
        try:
            for pr in repo.get_pulls(**api_args):
                if len(prs_data) >= max_items:
                    break
                
                prs_data.append({
                    "id": pr.number,
                    "title": pr.title,
                    "author": pr.user.login,
                    "date": pr.created_at.isoformat(),
                    "url": pr.html_url,
                    "body": pr.body or "",
                    "tipo": "pr"
                })
            return prs_data
        except Exception as e:
            print(f"[GitHubService] ERRO ao buscar PRs: {e}")
            return []

    def get_repo_files_batch(
        self,
        repo_url: str,
        max_depth: int = 10,
    ) -> List[Dict[str, str]]:
        """
        Busca o conteúdo de todos os arquivos de texto do repositório.
        Retorna uma lista de dicionários com file_path e content.
        """
        print(f"[GitHubService] Iniciando busca de arquivos para: {repo_url}")
        repo_name = self.parse_repo_url(repo_url)
        try:
            repo = self.g.get_repo(repo_name)
        except GithubException as e:
            print(f"[GitHubService] ERRO: Não foi possível encontrar o repositório {repo_name}. {e}")
            raise ValueError(f"Repositório não encontrado ou token sem permissão: {repo_name}")

        contents = repo.get_contents("")
        files_data = []
        queue = [(contents, 0)]

        while queue:
            current_contents, current_depth = queue.pop(0)
            if current_depth > max_depth:
                continue
            for content in current_contents:
                if content.type == "dir":
                    try:
                        if content.path in [c[0].path for q in queue for c in q[0] if c.type == "dir"]:
                            continue
                        queue.append((repo.get_contents(content.path), current_depth + 1))
                    except GithubException as e:
                        print(f"[GitHubService] AVISO: Não foi possível acessar o diretório {content.path}. {e}")
                elif content.type == "file":
                    if self._is_text_file(content.path):
                        if content.size == 0:
                            print(f"[GitHubService] AVISO: Pulando arquivo vazio: {content.path}")
                            continue
                        if content.size > 1_000_000:
                            print(f"[GitHubService] AVISO: Pulando arquivo muito grande: {content.path} ({content.size} bytes)")
                            continue
                        try:
                            decoded_content = base64.b64decode(content.content).decode("utf-8")
                            files_data.append({
                                "file_path": content.path,
                                "content": decoded_content
                            })
                        except UnicodeDecodeError:
                            print(f"[GitHubService] AVISO: Ignorando arquivo não-UTF8: {content.path}")
                        except Exception as e:
                             print(f"[GitHubService] AVISO: Falha ao decodificar {content.path}. {e}")

        print(f"[GitHubService] Busca concluída. {len(files_data)} arquivos de texto encontrados.")
        return files_data

    def _is_text_file(self, file_path: str) -> bool:
        """
        Verifica se um arquivo é provável de ser texto com base na extensão.
        """
        try:
            filename = os.path.basename(file_path).lower()
            if filename in TEXT_EXTENSIONS:
                return True
                
            ext = Path(file_path).suffix.lower()
            if not ext:
                if Path(file_path).name.lower() in ["readme", "contributing", "license", "makefile"]:
                    return True
                return False

            if ext in TEXT_EXTENSIONS:
                return True
                
            if ext in IMAGE_EXTENSIONS:
                return False
                
            return False
        except Exception as e:
            print(f"[GitHubService] Erro ao verificar _is_text_file para {file_path}: {e}")
            return False