# app/services/ingest_service.py
from app.services.github_service import get_repo_data
from app.services.metadata_service import save_documents_batch, delete_documents_by_repo
from typing import List, Dict, Any

def _format_data_for_ingestion(repo_name: str, raw_data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Formata os dados brutos do GitHub no formato que a tabela
    'documentos' do Supabase espera.
    """
    documentos = []
    
    # Formata Commits
    for item in raw_data["commits"]:
        conteudo = f"Commit de {item['author']}: {item['message']}"
        documentos.append({
            "repositorio": repo_name,
            "tipo": "commit",
            "metadados": {"sha": item['sha'], "autor": item['author'], "data": item['date'], "url": item['url']},
            "conteudo": conteudo
        })
        
    # Formata Issues
    for item in raw_data["issues"]:
        conteudo = f"Issue #{item['id']} por {item['author']}: {item['title']}\n{item['body']}"
        documentos.append({
            "repositorio": repo_name,
            "tipo": "issue",
            "metadados": {"id": item['id'], "autor": item['author'], "data": item['date'], "url": item['url'], "titulo": item['title']},
            "conteudo": conteudo
        })
        
    # Formata PRs
    for item in raw_data["prs"]:
        conteudo = f"PR #{item['id']} por {item['author']}: {item['title']}\n{item['body']}"
        documentos.append({
            "repositorio": repo_name,
            "tipo": "pr",
            "metadados": {"id": item['id'], "autor": item['author'], "data": item['date'], "url": item['url'], "titulo": item['title']},
            "conteudo": conteudo
        })
    
    return documentos

def ingest_repo(repo_name: str, issues_limit: int, prs_limit: int, commits_limit: int) -> Dict[str, Any]:
    """
    Função principal de ingestão (chamada pelo worker do RQ).
    Coordena a busca no GitHub, formatação e salvamento no Supabase.
    """
    print(f"[IngestService] INICIANDO INGESTÃO para {repo_name}...")
    
    try:
        # 1. Deletar dados antigos do repositório
        # (Isso garante que não haja duplicatas)
        delete_documents_by_repo(repo_name)
        
        # 2. Buscar novos dados do GitHub
        raw_data = get_repo_data(repo_name, issues_limit, prs_limit, commits_limit)
        
        # 3. Formatar os dados para o formato do banco
        documentos_para_salvar = _format_data_for_ingestion(repo_name, raw_data)
        
        if not documentos_para_salvar:
            print(f"[IngestService] Nenhum documento formatado para salvar.")
            return {"status": "concluído", "mensagem": "Nenhum dado encontrado para ingestão."}
            
        # 4. Salvar os novos documentos e embeddings no Supabase
        save_documents_batch(documentos_para_salvar)
        
        mensagem_final = f"Ingestão de {repo_name} concluída. {len(documentos_para_salvar)} documentos salvos."
        print(f"[IngestService] {mensagem_final}")
        
        return {"status": "concluído", "mensagem": mensagem_final}
        
    except Exception as e:
        print(f"[IngestService] ERRO na ingestão de {repo_name}: {e}")
        # Propaga o erro para o worker do RQ
        raise