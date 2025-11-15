# CÓDIGO COMPLETO PARA: app/services/ingest_service.py
# (Refatorado para usar Classes)

# (Primeiro, o GithubService que deveria estar em seu próprio arquivo)
import os
from github import Github, Auth
from typing import List, Dict, Any, Optional
from datetime import datetime

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
            print(f"[GitHubService] Buscando commits...")
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
            print(f"[GitHubService] Buscando issues...")
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
            print(f"[GitHubService] Buscando PRs...")
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

# --- Fim do GithubService (que deveria estar em github_service.py) ---
# (Se você já tem 'github_service.py' separado, ignore o código acima e 
#  apenas adicione a importação abaixo)

from app.services.metadata_service import MetadataService
# from app.services.github_service import GithubService # (Descomente se estiver separado)
from app.services.embedding_service import get_embedding
from typing import List, Dict, Any

class IngestService:
    """
    Serviço que coordena a ingestão de dados.
    """
    def __init__(self):
        try:
            self.metadata_service = MetadataService()
            self.github_service = GithubService() # Assegura que estamos usando a classe
        except Exception as e:
            print(f"[IngestService] Erro crítico ao inicializar serviços dependentes: {e}")
            raise
    
    def _format_data_for_ingestion(self, repo_name: str, raw_data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        # (Função helper interna, sem alterações)
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

    def ingest_repo(self, repo_name: str, issues_limit: int, prs_limit: int, commits_limit: int) -> Dict[str, Any]:
        """
        Função principal de ingestão (Delta Pull).
        """
        print(f"[IngestService] INICIANDO INGESTÃO para {repo_name}...")
        try:
            # Chama o MÉTODO da classe
            latest_timestamp = self.metadata_service.get_latest_timestamp(repo_name)
            
            if latest_timestamp is None:
                print(f"[IngestService] Novo repositório detectado. Executando ingestão completa.")
                self.metadata_service.delete_documents_by_repo(repo_name)
                raw_data = self.github_service.get_repo_data(
                    repo_name, issues_limit, prs_limit, commits_limit, since=None
                )
            else:
                print(f"[IngestService] Repositório existente. Executando ingestão incremental desde {latest_timestamp}.")
                raw_data = self.github_service.get_repo_data(
                    repo_name, issues_limit, prs_limit, commits_limit, since=latest_timestamp
                )

            documentos_para_salvar = self._format_data_for_ingestion(repo_name, raw_data)
            
            if not documentos_para_salvar:
                mensagem_vazia = "Nenhum dado novo encontrado para ingestão."
                print(f"[IngestService] {mensagem_vazia}")
                return {"status": "concluído", "mensagem": mensagem_vazia}
                
            self.metadata_service.save_documents_batch(documentos_para_salvar)
            
            mensagem_final = f"Ingestão de {repo_name} concluída. {len(documentos_para_salvar)} novos documentos salvos."
            print(f"[IngestService] {mensagem_final}")
            return {"status": "concluído", "mensagem": mensagem_final}
            
        except Exception as e:
            print(f"[IngestService] ERRO na ingestão de {repo_name}: {e}")
            raise

    def save_instruction(self, repo_name: str, instruction_text: str) -> str:
        """
        Salva uma instrução de relatório persistente.
        """
        if not self.metadata_service.supabase:
            raise Exception("Serviço Supabase não está inicializado.")
            
        print(f"[IngestService] Salvando instrução para: {repo_name}")
        try:
            print("[IngestService] Gerando embedding para a instrução...")
            instruction_embedding = get_embedding(instruction_text)
            
            new_instruction = {
                "repositorio": repo_name,
                "instrucao_texto": instruction_text,
                "embedding": instruction_embedding
            }
            
            response = self.metadata_service.supabase.table("instrucoes_relatorio").insert(new_instruction).execute()
            
            if response.data:
                print("[IngestService] Instrução salva com sucesso.")
                return "Instrução de relatório salva com sucesso."
            else:
                raise Exception("Falha ao salvar instrução no Supabase (sem dados retornados).")

        except Exception as e:
            print(f"[IngestService] ERRO ao salvar instrução: {e}")
            raise Exception(f"Falha ao salvar instrução: {e}")

# --- Instância Singleton para o Worker ---
# (Isso permite que o main.py e o worker.py importem as funções)
try:
    _ingest_service_instance = IngestService()
    ingest_repo = _ingest_service_instance.ingest_repo
    save_instruction = _ingest_service_instance.save_instruction
    print("[IngestService] Instância de serviço criada e funções exportadas.")
except Exception as e:
    print(f"[IngestService] Falha ao criar instância de serviço: {e}")
    ingest_repo = None
    save_instruction = None