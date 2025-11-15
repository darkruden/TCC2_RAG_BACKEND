# CÓDIGO COMPLETO PARA: app/services/github_service.py
# (Modificado para aceitar o parâmetro 'since' para ingestão delta)

import os
from github import Github, Auth
from typing import List, Dict, Any, Optional
from datetime import datetime # Importação necessária

# Configuração do cliente GitHub (sem alterações)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    print("[GitHubService] AVISO: GITHUB_TOKEN não definido. API pode ter limites de taxa.")
    g = Github()
else:
    try:
        auth = Auth.Token(GITHUB_TOKEN)
        g = Github(auth=auth)
    except Exception as e:
        print(f"[GitHubService] Erro ao autenticar com GitHub: {e}")
        g = Github()

# --- FUNÇÃO MODIFICADA (Marco 6) ---
def get_repo_data(
    repo_name: str, 
    issues_limit: int, 
    prs_limit: int, 
    commits_limit: int,
    since: Optional[datetime] = None # <-- NOVO PARÂMETRO
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Busca commits, issues e PRs de um repositório do GitHub.
    Se 'since' for fornecido, busca apenas itens criados/atualizados
    desde aquela data (ingestão incremental).
    """
    
    if since:
        print(f"[GitHubService] Iniciando busca INCREMENTAL para: {repo_name} (desde {since})")
    else:
        print(f"[GitHubService] Iniciando busca COMPLETA para: {repo_name}")
    
    try:
        repo = g.get_repo(repo_name)
    except Exception as e:
        print(f"[GitHubService] Erro: Não foi possível encontrar o repositório '{repo_name}'. {e}")
        raise ValueError(f"Repositório '{repo_name}' não encontrado ou inacessível.") from e

    data = {"commits": [], "issues": [], "prs": []}
    
    # Define os argumentos da API. Se 'since' existir, ele é adicionado.
    api_args = {}
    if since:
        api_args['since'] = since

    # 1. Buscar Commits
    try:
        print(f"[GitHubService] Buscando commits...")
        # Adiciona 'since' à chamada da API
        commits = repo.get_commits(**api_args) 
        
        # O limite é aplicado manualmente
        count = 0
        for commit in commits:
            if count >= commits_limit:
                break
            
            commit_data = {
                "sha": commit.sha,
                "message": commit.commit.message,
                "author": commit.commit.author.name or "N/A",
                "date": commit.commit.author.date.isoformat(),
                "url": commit.html_url
            }
            data["commits"].append(commit_data)
            count += 1
            
    except Exception as e:
        print(f"[GitHubService] Erro ao buscar commits: {e}")

    # 2. Buscar Issues
    try:
        print(f"[GitHubService] Buscando issues...")
        # 'state="all"' pega abertas e fechadas
        issues = repo.get_issues(state="all", **api_args) 
        
        count = 0
        for issue in issues:
            if count >= issues_limit:
                break
            if issue.pull_request: # Ignora PRs
                continue
                
            issue_data = {
                "id": issue.number,
                "title": issue.title,
                "author": issue.user.login,
                "date": issue.created_at.isoformat(), # Usa data de criação
                "url": issue.html_url,
                "body": issue.body or ""
            }
            data["issues"].append(issue_data)
            count += 1
            
    except Exception as e:
        print(f"[GitHubService] Erro ao buscar issues: {e}")

    # 3. Buscar Pull Requests
    try:
        print(f"[GitHubService] Buscando PRs...")
        prs = repo.get_pulls(state="all", **api_args)
        
        count = 0
        for pr in prs:
            if count >= prs_limit:
                break
                
            pr_data = {
                "id": pr.number,
                "title": pr.title,
                "author": pr.user.login,
                "date": pr.created_at.isoformat(), # Usa data de criação
                "url": pr.html_url,
                "body": pr.body or ""
            }
            data["prs"].append(pr_data)
            count += 1
            
    except Exception as e:
        print(f"[GitHubService] Erro ao buscar PRs: {e}")

    print(f"[GitHubService] Busca concluída para {repo_name}:")
    print(f"  {len(data['commits'])} novos commits, {len(data['issues'])} novas issues, {len(data['prs'])} novos PRs")
    
    return data