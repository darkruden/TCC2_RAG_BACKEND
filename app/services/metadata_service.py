# CÓDIGO COMPLETO PARA: app/services/metadata_service.py
# (Adicionada a função 'find_similar_instruction')

import os
from supabase import create_client, Client
from typing import List, Dict, Any, Optional
from app.services.embedding_service import get_embedding, get_embeddings_batch
from datetime import datetime

# Inicializa o cliente Supabase (Sem alterações)
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
    Salva um lote de documentos na tabela 'documentos'.
    (Sem alterações do Marco 1)
    """
    if not supabase: raise Exception("Serviço Supabase não está inicializado.")
    if not documents: return
    try:
        textos_para_embedding = [doc["conteudo"] for doc in documents]
        print(f"[MetadataService] Gerando {len(textos_para_embedding)} embeddings em lote...")
        embeddings = get_embeddings_batch(textos_para_embedding)
        
        documentos_para_salvar = []
        for i, doc in enumerate(documents):
            doc["embedding"] = embeddings[i]
            documentos_para_salvar.append(doc)
        
        print(f"[MetadataService] Salvando {len(documentos_para_salvar)} documentos no Supabase...")
        response = supabase.table("documentos").insert(documentos_para_salvar).execute()
        
        if response.data:
            print(f"[MetadataService] Lote salvo com sucesso. {len(response.data)} registros inseridos.")
        else:
            print(f"[MetadataService] Supabase salvou o lote, mas não retornou dados.")
    except Exception as e:
        print(f"[MetadataService] Erro CRÍTICO ao salvar lote no Supabase: {e}")
        raise

def delete_documents_by_repo(repo_name: str):
    """
    Deleta TODOS os documentos de um repositório.
    (Sem alterações do Marco 6)
    """
    if not supabase: raise Exception("Serviço Supabase não está inicializado.")
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
    Encontra os 'k' documentos mais similares (RAG).
    (Sem alterações do Marco 1)
    """
    if not supabase: raise Exception("Serviço Supabase não está inicializado.")
    try:
        print(f"[MetadataService] Gerando embedding para a consulta RAG...")
        query_embedding = get_embedding(query_text)
        
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

def get_latest_timestamp(repo_name: str) -> Optional[datetime]:
    """
    Busca o timestamp mais recente de um repositório.
    (Sem alterações do Marco 6)
    """
    if not supabase: raise Exception("Serviço Supabase não está inicializado.")
    print(f"[MetadataService] Verificando timestamp mais recente para: {repo_name}")
    try:
        response = supabase.rpc('get_latest_repo_timestamp', {
            'repo_name': repo_name
        }).execute()
        latest_timestamp_str = response.data
        if latest_timestamp_str:
            latest_timestamp = datetime.fromisoformat(latest_timestamp_str)
            print(f"[MetadataService] Timestamp mais recente encontrado: {latest_timestamp}")
            return latest_timestamp
        else:
            print(f"[MetadataService] Nenhum timestamp encontrado (novo repositório).")
            return None
    except Exception as e:
        print(f"[MetadataService] ERRO ao buscar timestamp: {e}")
        return None

def get_all_documents_by_repo(repo_name: str) -> List[Dict[str, Any]]:
    """
    Busca TODOS os documentos de um repositório para relatórios.
    (Sem alterações do Marco 4)
    """
    if not supabase: raise Exception("Serviço Supabase não está inicializado.")
    print(f"[MetadataService] Buscando todos os documentos de: {repo_name}")
    try:
        response = supabase.table("documentos").select("metadados, conteudo, tipo").eq("repositorio", repo_name).execute()
        if response.data:
            print(f"[MetadataService] Encontrados {len(response.data)} documentos para o relatório.")
            return response.data
        else:
            print(f"[MetadataService] Nenhum documento encontrado para {repo_name}.")
            return []
    except Exception as e:
        print(f"[MetadataService] Erro ao buscar todos os documentos: {e}")
        return []

# --- NOVA FUNÇÃO (Marco 7) ---
def find_similar_instruction(repo_name: str, query_text: str) -> Optional[str]:
    """
    Encontra a instrução de relatório mais relevante (RAG)
    para um repositório e um prompt.
    """
    if not supabase:
        raise Exception("Serviço Supabase não está inicializado.")
        
    try:
        print(f"[MetadataService] Buscando instrução de relatório RAG para: {repo_name}")
        
        # 1. Gera o embedding para a consulta (ex: "relatório de hoje")
        query_embedding = get_embedding(query_text)
        
        # 2. Chama a nova função 'match_instructions' do Supabase
        response = supabase.rpc('match_instructions', {
            'query_embedding': query_embedding,
            'match_repositorio': repo_name,
            'match_count': 1 # Queremos apenas a instrução MAIS relevante
        }).execute()

        if response.data:
            # Retorna o texto da instrução
            retrieved_instruction = response.data[0].get("instrucao_texto")
            print(f"[MetadataService] Instrução RAG encontrada: {retrieved_instruction[:50]}...")
            return retrieved_instruction
        else:
            print("[MetadataService] Nenhuma instrução de relatório salva encontrada.")
            return None

    except Exception as e:
        print(f"[MetadataService] Erro na busca vetorial de instruções: {e}")
        return None # Não quebra, apenas não retorna nenhuma instrução