# app/services/metadata_service.py
import os
from supabase import create_client, Client
from typing import List, Dict, Any
from app.services.embedding_service import get_embedding, get_embeddings_batch

# Inicializa o cliente Supabase
# (Ele usará as vars SUPABASE_URL e SUPABASE_KEY do Heroku [cite: 8])
try:
    url: str = os.getenv("SUPABASE_URL")
    key: str = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
    
    supabase: Client = create_client(url, key)
    print("[MetadataService] Cliente Supabase inicializado.")
    
except Exception as e:
    print(f"[MetadataService] Erro ao inicializar Supabase: {e}")
    supabase = None

def save_documents_batch(documents: List[Dict[str, Any]]):
    """
    Recebe uma lista de documentos, gera seus embeddings e os
    salva na tabela 'documentos' do Supabase.
    
    'documents' deve ser uma lista de:
    {
        "repositorio": "user/repo",
        "tipo": "commit",
        "metadados": {"sha": "...", "autor": "...", "url": "..."},
        "conteudo": "Mensagem do commit"
    }
    """
    if not supabase:
        raise Exception("Serviço Supabase não está inicializado.")
    
    if not documents:
        print("[MetadataService] Nenhum documento para salvar.")
        return
        
    try:
        # 1. Extrai o texto de cada documento para o batch
        textos_para_embedding = [doc["conteudo"] for doc in documents]
        
        print(f"[MetadataService] Gerando {len(textos_para_embedding)} embeddings em lote...")
        
        # 2. Gera os embeddings em lote
        embeddings = get_embeddings_batch(textos_para_embedding)
        
        # 3. Adiciona o embedding a cada documento
        documentos_para_salvar = []
        for i, doc in enumerate(documents):
            doc["embedding"] = embeddings[i]
            documentos_para_salvar.append(doc)
        
        print(f"[MetadataService] Salvando {len(documentos_para_salvar)} documentos no Supabase...")
        
        # 4. Salva tudo no Supabase de uma vez
        response = supabase.table("documentos").insert(documentos_para_salvar).execute()
        
        if response.data:
            print(f"[MetadataService] Lote salvo com sucesso. {len(response.data)} registros inseridos.")
        else:
            # (Nota: 'response.error' não é padrão, mas é bom verificar)
            print(f"[MetadataService] Supabase salvou o lote, mas não retornou dados.")

    except Exception as e:
        print(f"[MetadataService] Erro CRÍTICO ao salvar lote no Supabase: {e}")
        # Dependendo da política, você pode querer lançar o erro
        raise

def delete_documents_by_repo(repo_name: str):
    """
    Deleta TODOS os documentos (vetores e metadados) de um repositório
    antes de uma nova ingestão.
    """
    if not supabase:
        raise Exception("Serviço Supabase não está inicializado.")
        
    print(f"[MetadataService] Deletando dados antigos de: {repo_name}")
    
    try:
        response = supabase.table("documentos").delete().eq("repositorio", repo_name).execute()
        
        if response.data:
            print(f"[MetadataService] Dados antigos de {repo_name} deletados. ({len(response.data)} registros)")
        else:
            print(f"[MetadataService] Nenhum dado antigo encontrado para {repo_name}.")
            
    except Exception as e:
        print(f"[MetadataService] Erro ao deletar dados antigos: {e}")
        raise

def find_similar_documents(query_text: str, repo_name: str, k: int = 5) -> List[Dict[str, Any]]:
    """
    Encontra os 'k' documentos mais similares a uma consulta
    dentro de um repositório específico.
    """
    if not supabase:
        raise Exception("Serviço Supabase não está inicializado.")
        
    try:
        # 1. Gera o embedding para a consulta do usuário
        print(f"[MetadataService] Gerando embedding para a consulta RAG...")
        query_embedding = get_embedding(query_text)
        
        # 2. Chama a 'procedure' (função) do Supabase para busca vetorial
        # Esta é a consulta SQL híbrida!
        print(f"[MetadataService] Executando busca vetorial (match_documents)...")
        response = supabase.rpc('match_documents', {
            'query_embedding': query_embedding,
            'match_repositorio': repo_name,
            'match_count': k
        }).execute()

        if response.data:
            print(f"[MetadataService] {len(response.data)} documentos similares encontrados.")
            return response.data
        else:
            print("[MetadataService] Nenhum documento similar encontrado.")
            return []

    except Exception as e:
        print(f"[MetadataService] Erro na busca vetorial: {e}")
        raise