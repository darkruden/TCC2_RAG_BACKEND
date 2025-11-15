# app/services/github_service.py
import os
from github import Github, Auth
from typing import List, Dict, Any

# Pega o token do GitHub das variáveis de ambiente [cite: 7]
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
        g = Github() # Fallback para não autenticado

def get_repo_data(repo_name: str, issues_limit: int, prs_limit: int, commits_limit: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    Busca commits, issues e PRs de um repositório do GitHub.
    """
    print(f"[GitHubService] Iniciando busca para: {repo_name}")
    
    try:
        repo = g.get_repo(repo_name)
    except Exception as e:
        print(f"[GitHubService] Erro: Não foi possível encontrar o repositório '{repo_name}'. {e}")
        raise ValueError(f"Repositório '{repo_name}' não encontrado ou inacessível.") from e

    # Dicionário para armazenar os dados
    data = {
        "commits": [],
        "issues": [],
        "prs": []
    }

    # 1. Buscar Commits
    try:
        print(f"[GitHubService] Buscando {commits_limit} commits...")
        commits = repo.get_commits()
        for i, commit in enumerate(commits):
            if i >= commits_limit:
                break
            
            commit_data = {
                "sha": commit.sha,
                "message": commit.commit.message,
                "author": commit.commit.author.name,
                "date": commit.commit.author.date.isoformat(),
                "url": commit.html_url
            }
            data["commits"].append(commit_data)
            
    except Exception as e:
        print(f"[GitHubService] Erro ao buscar commits: {e}")
        # Continua mesmo se os commits falharem

    # 2. Buscar Issues
    try:
        print(f"[GitHubService] Buscando {issues_limit} issues...")
        issues = repo.get_issues(state="all") # Pega abertas e fechadas
        for i, issue in enumerate(issues):
            if i >= issues_limit:
                break
            
            # Ignora Pull Requests (que também são "issues")
            if issue.pull_request:
                continue
                
            issue_data = {
                "id": issue.number,
                "title": issue.title,
                "author": issue.user.login,
                "date": issue.created_at.isoformat(),
                "url": issue.html_url,
                "body": issue.body or "" # Garante que não é nulo
            }
            data["issues"].append(issue_data)
            
    except Exception as e:
        print(f"[GitHubService] Erro ao buscar issues: {e}")

    # 3. Buscar Pull Requests
    try:
        print(f"[GitHubService] Buscando {prs_limit} PRs...")
        prs = repo.get_pulls(state="all")
        for i, pr in enumerate(prs):
            if i >= prs_limit:
                break
                
            pr_data = {
                "id": pr.number,
                "title": pr.title,
                "author": pr.user.login,
                "date": pr.created_at.isoformat(),
                "url": pr.html_url,
                "body": pr.body or ""
            }
            data["prs"].append(pr_data)
            
    except Exception as e:
        print(f"[GitHubService] Erro ao buscar PRs: {e}")

    print(f"[GitHubService] Busca concluída para {repo_name}:")
    print(f"  {len(data['commits'])} commits, {len(data['issues'])} issues, {len(data['prs'])} PRs")
    
    return data