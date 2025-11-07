# [COLE ESSE NOVO CÓDIGO NO LUGAR DO CONTEÚDO ANTIGO DE ingest_service.py]

# O que você deve colar
import os
from .github_service import GitHubService
from .embedding_service import EmbeddingService

# 1. Inicializar os serviços que vamos usar
# Eles pegam as configurações (tokens, paths) das variáveis de ambiente
try:
    github_service = GitHubService()
    embedding_service = EmbeddingService()
except ValueError as e:
    print(f"Erro ao inicializar serviços (verifique .env): {e}")
    # Se não pudermos inicializar, definimos como None para falhar graciosamente
    github_service = None
    embedding_service = None

def ingest_repo(owner_repo: str):
    """
    Orquestra a ingestão de dados do GitHub para o ChromaDB.
    
    1. Busca dados do GitHubService.
    2. Processa e salva os dados no ChromaDB via EmbeddingService.
    """
    if not github_service or not embedding_service:
        msg = "Serviços de GitHub ou Embedding não foram inicializados."
        print(f"[ERRO] {msg}")
        return f"Erro: {msg}"

    print(f"Iniciando ingestão para o repositório: {owner_repo}")

    try:
       # [COLE ESSA NOVA VERSÃO]

        # 1. Buscar dados do GitHub (COM LIMITES)
        print(f"Buscando issues para {owner_repo} (limite: 20)...")
        issues = github_service.get_issues(owner_repo, state="all", limit=20)
        print(f"Encontradas {len(issues)} issues.")

        print(f"Buscando Pull Requests para {owner_repo} (limite: 10)...")
        prs = github_service.get_pull_requests(owner_repo, state="all", limit=10)
        print(f"Encontrados {len(prs)} Pull Requests.")

        print(f"Buscando Commits para {owner_repo} (limite: 15)...")
        commits = github_service.get_commits(owner_repo, limit=15)
        print(f"Encontrados {len(commits)} commits.")

        # 2. Processar e salvar no ChromaDB
        # Usamos o método do EmbeddingService que já faz tudo:
        # cria embeddings e salva no ChromaDB
        print("Processando e salvando dados no banco vetorial...")
        resultado = embedding_service.process_github_data(
            repo_name=owner_repo,
            issues=issues,
            prs=prs,
            commits=commits
        )

        msg = f"Ingestão concluída para {resultado['collection_name']}: {resultado['documents_count']} documentos."
        print(f"[SUCESSO] {msg}")
        return msg

    # O que você deve colar
    except Exception as e:
        # Usar repr(e) é muito melhor para debug
        error_message = repr(e) 
        print(f"Erro DETALHADO durante a ingestão de {owner_repo}: {error_message}")
        # Retorna a mensagem de erro detalhada na API
        return f"Erro durante a ingestão: {error_message}"