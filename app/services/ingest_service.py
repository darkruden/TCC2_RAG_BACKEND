# CÓDIGO COMPLETO PARA: app/services/ingest_service.py
# (Implementa a lógica de Ingestão Incremental / Delta Pull)

from app.services.github_service import get_repo_data
from app.services.metadata_service import (
    save_documents_batch, 
    delete_documents_by_repo,
    get_latest_timestamp # <-- NOVA IMPORTAÇÃO
)
from typing import List, Dict, Any

def _format_data_for_ingestion(repo_name: str, raw_data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Formata os dados brutos do GitHub no formato que a tabela
    'documentos' do Supabase espera. (Função sem alterações)
    """
    documentos = []
    
    # Formata Commits
    for item in raw_data.get("commits", []):
        conteudo = f"Commit de {item.get('author', 'N/A')}: {item.get('message', '')}"
        documentos.append({
            "repositorio": repo_name,
            "tipo": "commit",
            "metadados": {"sha": item['sha'], "autor": item['author'], "data": item['date'], "url": item['url']},
            "conteudo": conteudo
        })
        
    # Formata Issues
    for item in raw_data.get("issues", []):
        conteudo = f"Issue #{item['id']} por {item['author']}: {item['title']}\n{item.get('body', '')}"
        documentos.append({
            "repositorio": repo_name,
            "tipo": "issue",
            "metadados": {"id": item['id'], "autor": item['author'], "data": item['date'], "url": item['url'], "titulo": item['title']},
            "conteudo": conteudo
        })
        
    # Formata PRs
    for item in raw_data.get("prs", []):
        conteudo = f"PR #{item['id']} por {item['author']}: {item['title']}\n{item.get('body', '')}"
        documentos.append({
            "repositorio": repo_name,
            "tipo": "pr",
            "metadados": {"id": item['id'], "autor": item['author'], "data": item['date'], "url": item['url'], "titulo": item['title']},
            "conteudo": conteudo
        })
    
    return documentos

# --- FUNÇÃO PRINCIPAL (MODIFICADA - Marco 6) ---
def ingest_repo(repo_name: str, issues_limit: int, prs_limit: int, commits_limit: int) -> Dict[str, Any]:
    """
    Função principal de ingestão (chamada pelo worker do RQ).
    IMPLEMENTA LÓGICA INCREMENTAL (DELTA PULL).
    """
    print(f"[IngestService] INICIANDO INGESTÃO para {repo_name}...")
    
    try:
        # 1. Verifica se é uma ingestão completa ou incremental
        latest_timestamp = get_latest_timestamp(repo_name)
        
        if latest_timestamp is None:
            # --- CASO 1: INGESTÃO COMPLETA (Novo Repositório) ---
            print(f"[IngestService] Novo repositório detectado. Executando ingestão completa.")
            
            # 1a. Deleta quaisquer dados parciais que possam existir
            delete_documents_by_repo(repo_name)
            
            # 1b. Busca dados do GitHub (sem filtro 'since')
            raw_data = get_repo_data(
                repo_name, issues_limit, prs_limit, commits_limit,
                since=None # Garante que está buscando tudo
            )
        
        else:
            # --- CASO 2: INGESTÃO INCREMENTAL (Delta) ---
            print(f"[IngestService] Repositório existente. Executando ingestão incremental desde {latest_timestamp}.")
            
            # 2a. NÃO deletamos dados antigos.
            
            # 2b. Busca dados do GitHub (APENAS o que for novo)
            raw_data = get_repo_data(
                repo_name, issues_limit, prs_limit, commits_limit,
                since=latest_timestamp # <-- Passa a data do último item
            )

        # 3. Formatar os dados para o formato do banco
        documentos_para_salvar = _format_data_for_ingestion(repo_name, raw_data)
        
        if not documentos_para_salvar:
            mensagem_vazia = "Nenhum dado novo encontrado para ingestão."
            print(f"[IngestService] {mensagem_vazia}")
            return {"status": "concluído", "mensagem": mensagem_vazia}
            
        # 4. Salvar os novos documentos (sejam eles todos ou apenas o delta)
        save_documents_batch(documentos_para_salvar)
        
        mensagem_final = f"Ingestão de {repo_name} concluída. {len(documentos_para_salvar)} novos documentos salvos."
        print(f"[IngestService] {mensagem_final}")
        
        return {"status": "concluído", "mensagem": mensagem_final}
        
    except Exception as e:
        print(f"[IngestService] ERRO na ingestão de {repo_name}: {e}")
        # Propaga o erro para o worker do RQ
        raise