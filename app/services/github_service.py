# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/github_service.py
# (Esta é a versão moderna, com a CLASSE, que seu 'worker_tasks' precisa)

import os
import base64
import requests
from github import Github, Auth, GithubException
import re
from pathlib import Path
# import magic  <--- REMOVIDO
from typing import List, Dict, Optional, Any
from datetime import datetime # Importação necessária

# Constantes para tipos de arquivos
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
        
        # Fallback para o caso de já ser 'owner/repo'
        if "/" in repo_url and not "github.com" in repo_url:
            return repo_url
            
        raise ValueError(f"URL de repositório inválida: {repo_url}")

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
                        # Evita recursão infinita em links simbólicos de diretório
                        if content.path in [c[0].path for q in queue for c in q[0] if c.type == "dir"]:
                            continue
                        queue.append((repo.get_contents(content.path), current_depth + 1))
                    except GithubException as e:
                        print(f"[GitHubService] AVISO: Não foi possível acessar o diretório {content.path}. {e}")
                
                elif content.type == "file":
                    # Usa a função _is_text_file simplificada
                    if self._is_text_file(content.path):
                        if content.size == 0:
                            print(f"[GitHubService] AVISO: Pulando arquivo vazio: {content.path}")
                            continue
                        
                        # Limite de tamanho de arquivo (ex: 1MB)
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

    # --- FUNÇÃO CORRIGIDA ---
    def _is_text_file(self, file_path: str) -> bool:
        """
        Verifica se um arquivo é provável de ser texto com base na extensão.
        """
        try:
            # 1. Normaliza o nome do arquivo para checagem
            filename = os.path.basename(file_path).lower()
            
            # 2. Checa por nomes de arquivo exatos (ex: 'Procfile')
            if filename in TEXT_EXTENSIONS:
                return True
                
            # 3. Pega a extensão
            ext = Path(file_path).suffix.lower()
            if not ext:
                # Se não tiver extensão, mas for um nome conhecido (ex: 'README')
                if Path(file_path).name.lower() in ["readme", "contributing", "license", "makefile"]:
                    return True
                return False # Assume que arquivos sem extensão não são texto

            # 4. Checa se a extensão está na lista de permissão
            if ext in TEXT_EXTENSIONS:
                return True
                
            # 5. Checa se a extensão está na lista de negação (binários)
            if ext in IMAGE_EXTENSIONS:
                return False
                
            # 6. Regra padrão
            return False

        except Exception as e:
            print(f"[GitHubService] Erro ao verificar _is_text_file para {file_path}: {e}")
            return False

    # (Funções restantes que você já tinha)
    def get_repo_issues(self, repo_url: str, max_items: int = 50, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        print(f"[GitHubService] Buscando {max_items} issues de: {repo_url}")
        repo_name = self.parse_repo_url(repo_url)
        repo = self.g.get_repo(repo_name)
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
                    
                comments = []
                for comment in issue.get_comments():
                    comments.append(comment.body)
                
                issues_data.append({
                    "id": issue.id,
                    "number": issue.number,
                    "title": issue.title,
                    "body": issue.body or "",
                    "state": issue.state,
                    "created_at": issue.created_at.isoformat(),
                    "updated_at": issue.updated_at.isoformat(),
                    "user_login": issue.user.login,
                    "labels": [label.name for label in issue.labels],
                    "comments": "\n".join(comments),
                    "url": issue.html_url,
                    "tipo": "issue" # Adiciona o tipo
                })
            print(f"[GitHubService] {len(issues_data)} issues encontradas.")
            return issues_data
        except Exception as e:
            print(f"[GitHubService] ERRO ao buscar issues: {e}")
            return []

    def get_repo_prs(self, repo_url: str, max_items: int = 20, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        print(f"[GitHubService] Buscando {max_items} PRs de: {repo_url}")
        repo_name = self.parse_repo_url(repo_url)
        repo = self.g.get_repo(repo_name)
        prs_data = []
        
        api_args = {'state': 'all', 'sort': 'updated', 'direction': 'desc'}
        if since:
            api_args['since'] = since

        try:
            for pr in repo.get_pulls(**api_args):
                if len(prs_data) >= max_items:
                    break
                
                comments = []
                for comment in pr.get_issue_comments():
                    comments.append(comment.body)
                    
                review_comments = []
                for comment in pr.get_review_comments():
                    review_comments.append(comment.body)
                
                prs_data.append({
                    "id": pr.id,
                    "number": pr.number,
                    "title": pr.title,
                    "body": pr.body or "",
                    "state": pr.state,
                    "created_at": pr.created_at.isoformat(),
                    "updated_at": pr.updated_at.isoformat(),
                    "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                    "user_login": pr.user.login,
                    "labels": [label.name for label in pr.labels],
                    "comments": "\n".join(comments),
                    "review_comments": "\n".join(review_comments),
                    "url": pr.html_url,
                    "tipo": "pull_request" # Adiciona o tipo
                })
            print(f"[GitHubService] {len(prs_data)} PRs encontrados.")
            return prs_data
        except Exception as e:
            print(f"[GitHubService] ERRO ao buscar PRs: {e}")
            return []

    def get_repo_commits(self, repo_url: str, max_items: int = 30, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        print(f"[GitHubService] Buscando {max_items} commits de: {repo_url} (Since: {since})")
        repo_name = self.parse_repo_url(repo_url)
        repo = self.g.get_repo(repo_name)
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
                
                files_changed = []
                try:
                    commit_details = repo.get_commit(commit.sha)
                    if commit_details.files:
                        files_changed = [f.filename for f in commit_details.files]
                except Exception as e:
                    print(f"[GitHubService] AVISO: Não foi possível obter arquivos do commit {commit.sha[:7]}. {e}")

                commits_data.append({
                    "sha": commit.sha,
                    "message": commit.commit.message,
                    "author": commit.commit.author.name or "N/A",
                    "date": commit.commit.author.date.isoformat(),
                    "files": files_changed,
                    "url": commit.html_url,
                    "tipo": "commit" # Adiciona o tipo
                })
                count += 1
                
            print(f"[GitHubService] {len(commits_data)} commits encontrados.")
            return commits_data
        except Exception as e:
            print(f"[GitHubService] ERRO ao buscar commits: {e}")
            return []