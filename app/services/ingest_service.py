# CÓDIGO COMPLETO PARA: app/services/ingest_service.py
# (Adicionada a função 'save_instruction')

from app.services.github_service import get_repo_data
from app.services.metadata_service import (
    save_documents_batch, 
    delete_documents_by_repo,
    get_latest_timestamp,
    supabase # Importa o cliente supabase
)
# (Importamos 'get_embedding' para salvar a instrução)
from app.services.embedding_service import get_embedding
from typing import List, Dict, Any

def _format_data_for_ingestion(repo_name: str, raw_data: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Formata os dados brutos do GitHub no formato que a tabela
    'documentos' do Supabase espera. (Sem alterações)
    """
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

def ingest_repo(repo_name: str, issues_limit: int, prs_limit: int, commits_limit: int) -> Dict[str, Any]:
    """
    Função principal de ingestão (Delta Pull).
    (Sem alterações do Marco 6)
    """
    print(f"[IngestService] INICIANDO INGESTÃO para {repo_name}...")
    try:
        latest_timestamp = get_latest_timestamp(repo_name)
        if latest_timestamp is None:
            print(f"[IngestService] Novo repositório detectado. Executando ingestão completa.")
            delete_documents_by_repo(repo_name)
            raw_data = get_repo_data(
                repo_name, issues_limit, prs_limit, commits_limit,
                since=None
            )
        else:
            print(f"[IngestService] Repositório existente. Executando ingestão incremental desde {latest_timestamp}.")
            raw_data = get_repo_data(
                repo_name, issues_limit, prs_limit, commits_limit,
                since=latest_timestamp
            )

        documentos_para_salvar = _format_data_for_ingestion(repo_name, raw_data)
        if not documentos_para_salvar:
            mensagem_vazia = "Nenhum dado novo encontrado para ingestão."
            print(f"[IngestService] {mensagem_vazia}")
            return {"status": "concluído", "mensagem": mensagem_vazia}
            
        save_documents_batch(documentos_para_salvar)
        mensagem_final = f"Ingestão de {repo_name} concluída. {len(documentos_para_salvar)} novos documentos salvos."
        print(f"[IngestService] {mensagem_final}")
        return {"status": "concluído", "mensagem": mensagem_final}
    except Exception as e:
        print(f"[IngestService] ERRO na ingestão de {repo_name}: {e}")
        raise

# --- NOVA FUNÇÃO (Marco 7) ---
def save_instruction(repo_name: str, instruction_text: str) -> str:
    """
    Salva uma instrução de relatório persistente no banco de dados
    vetorial 'instrucoes_relatorio'.
    """
    if not supabase:
        raise Exception("Serviço Supabase não está inicializado.")
        
    print(f"[IngestService] Salvando instrução para: {repo_name}")
    
    try:
        # 1. Gera o embedding para o texto da instrução
        print("[IngestService] Gerando embedding para a instrução...")
        instruction_embedding = get_embedding(instruction_text)
        
        # 2. Cria o objeto para salvar
        new_instruction = {
            "repositorio": repo_name,
            "instrucao_texto": instruction_text,
            "embedding": instruction_embedding
        }
        
        # 3. Salva na nova tabela
        # (Nota: Isso adiciona uma nova instrução. Você pode querer
        #  deletar as antigas primeiro se quiser apenas uma por repo)
        response = supabase.table("instrucoes_relatorio").insert(new_instruction).execute()
        
        if response.data:
            print("[IngestService] Instrução salva com sucesso.")
            return "Instrução de relatório salva com sucesso."
        else:
            raise Exception("Falha ao salvar instrução no Supabase (sem dados retornados).")

    except Exception as e:
        print(f"[IngestService] ERRO ao salvar instrução: {e}")
        raise Exception(f"Falha ao salvar instrução: {e}")