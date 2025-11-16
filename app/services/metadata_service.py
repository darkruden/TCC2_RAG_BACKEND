# CÓDIGO COMPLETO E ATUALIZADO PARA: app/services/metadata_service.py
# (Refatorado para Multi-Tenancy com 'user_id')

import os
from supabase import create_client, Client
from typing import List, Dict, Any, Optional
from app.services.embedding_service import get_embedding, get_embeddings_batch
from datetime import datetime

class MetadataService:
    """
    Serviço para gerenciar a interação com o banco de dados Supabase,
    incluindo metadados e vetores (pg_vector).
    Refatorado para Multi-Tenancy (tudo é filtrado por user_id).
    """
    
    def __init__(self):
        """
        Inicializa o cliente Supabase.
        """
        try:
            url: str = os.getenv("SUPABASE_URL")
            key: str = os.getenv("SUPABASE_KEY")
            if not url or not key:
                raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
            
            self.supabase: Client = create_client(url, key)
            print("[MetadataService] Cliente Supabase inicializado com sucesso.")
            
        except Exception as e:
            print(f"[MetadataService] Erro ao inicializar Supabase: {e}")
            self.supabase = None
            raise

    def save_documents_batch(self, user_id: str, documents: List[Dict[str, Any]]):
        """
        Salva um lote de documentos na tabela 'documentos' para um usuário.
        """
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
        if not documents:
            print("[MetadataService] Nenhum documento para salvar.")
            return
            
        try:
            textos_para_embedding = [doc["conteudo"] for doc in documents]
            print(f"[MetadataService] Gerando {len(textos_para_embedding)} embeddings em lote...")
            embeddings = get_embeddings_batch(textos_para_embedding)
            
            documentos_para_salvar = []
            for i, doc in enumerate(documents):
                doc["embedding"] = embeddings[i]
                doc["user_id"] = user_id # <-- Vincula o documento ao usuário
                documentos_para_salvar.append(doc)
            
            print(f"[MetadataService] Salvando {len(documentos_para_salvar)} documentos (User: {user_id})...")
            response = self.supabase.table("documentos").insert(documentos_para_salvar).execute()
            
            if response.data:
                print(f"[MetadataService] Lote salvo com sucesso. {len(response.data)} registros inseridos.")
            else:
                print(f"[MetadataService] Supabase salvou o lote, mas não retornou dados.")

        except Exception as e:
            print(f"[MetadataService] Erro CRÍTICO ao salvar lote no Supabase: {e}")
            raise

    def delete_documents_by_repo(self, user_id: str, repo_name: str):
        """
        Deleta TODOS os documentos de um repositório PARA UM USUÁRIO.
        """
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
            
        print(f"[MetadataService] Deletando dados antigos (User: {user_id}) de: {repo_name}")
        try:
            response = self.supabase.table("documentos").delete() \
                .eq("user_id", user_id) \
                .eq("repositorio", repo_name) \
                .execute()
            if response.data:
                print(f"[MetadataService] Dados antigos de {repo_name} deletados. ({len(response.data)} registros)")
            else:
                print(f"[MetadataService] Nenhum dado antigo encontrado para {repo_name}.")
        except Exception as e:
            print(f"[MetadataService] Erro ao deletar dados antigos: {e}")
            raise

    def find_similar_documents(self, user_id: str, query_text: str, repo_name: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Encontra os 'k' documentos mais similares (RAG) PARA UM USUÁRIO.
        """
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
            
        try:
            print(f"[MetadataService] Gerando embedding para a consulta RAG (User: {user_id})...")
            query_embedding = get_embedding(query_text)
            
            print(f"[MetadataService] Executando busca vetorial (match_documents_user)...")
            
            # --- ATUALIZAÇÃO IMPORTANTE ---
            # Precisamos de uma nova função RPC no Supabase que filtre por user_id.
            # O 'match_documents' antigo não filtrava por usuário.
            # Você precisará criar 'match_documents_user' no seu Supabase SQL Editor.
            response = self.supabase.rpc('match_documents_user', {
                'query_embedding': query_embedding,
                'match_repositorio': repo_name,
                'match_user_id': user_id, # <-- NOVO FILTRO
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

    def get_latest_timestamp(self, user_id: str, repo_name: str) -> Optional[datetime]:
        """
        Busca o timestamp mais recente de um repositório PARA UM USUÁRIO.
        """
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
            
        print(f"[MetadataService] Verificando timestamp (User: {user_id}) para: {repo_name}")
        try:
            # --- ATUALIZAÇÃO IMPORTANTE ---
            # Precisamos de uma nova função RPC no Supabase.
            # Você precisará criar 'get_latest_repo_timestamp_user' no seu Supabase SQL Editor.
            response = self.supabase.rpc('get_latest_repo_timestamp_user', {
                'repo_name_filter': repo_name,
                'user_id_filter': user_id # <-- NOVO FILTRO
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

    def get_all_documents_by_repo(self, user_id: str, repo_name: str) -> List[Dict[str, Any]]:
        """
        Busca TODOS os documentos de um repositório PARA UM USUÁRIO.
        """
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
            
        print(f"[MetadataService] Buscando todos os documentos (User: {user_id}) de: {repo_name}")
        try:
            response = self.supabase.table("documentos").select("metadados, conteudo, tipo") \
                .eq("user_id", user_id) \
                .eq("repositorio", repo_name) \
                .execute()
                
            if response.data:
                print(f"[MetadataService] Encontrados {len(response.data)} documentos para o relatório.")
                return response.data
            else:
                print(f"[MetadataService] Nenhum documento encontrado para {repo_name}.")
                return []
        except Exception as e:
            print(f"[MetadataService] Erro ao buscar todos os documentos: {e}")
            return []

    def find_similar_instruction(self, user_id: str, repo_name: str, query_text: str) -> Optional[str]:
        """
        Encontra a instrução de relatório mais relevante (RAG) PARA UM USUÁRIO.
        """
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
            
        try:
            print(f"[MetadataService] Buscando instrução RAG (User: {user_id}) para: {repo_name}")
            query_embedding = get_embedding(query_text)
            
            # --- ATUALIZAÇÃO IMPORTANTE ---
            # Precisamos de uma nova função RPC no Supabase.
            # Você precisará criar 'match_instructions_user' no seu Supabase SQL Editor.
            response = self.supabase.rpc('match_instructions_user', {
                'query_embedding': query_embedding,
                'match_repositorio': repo_name,
                'match_user_id': user_id, # <-- NOVO FILTRO
                'match_count': 1
            }).execute()

            if response.data:
                retrieved_instruction = response.data[0].get("instrucao_texto")
                print(f"[MetadataService] Instrução RAG encontrada: {retrieved_instruction[:50]}...")
                return retrieved_instruction
            else:
                print("[MetadataService] Nenhuma instrução de relatório salva encontrada.")
                return None
        except Exception as e:
            print(f"[MetadataService] Erro na busca vetorial de instruções: {e}")
            return None

    def get_user_ids_for_repo(self, repo_name: str) -> List[str]:
        """
        (NOVA FUNÇÃO PARA WEBHOOKS)
        Encontra todos os user_ids únicos que ingeriram um repositório.
        """
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
        
        try:
            print(f"[MetadataService] Buscando usuários que rastreiam: {repo_name}")
            # Esta função RPC precisa ser criada no Supabase
            response = self.supabase.rpc('get_distinct_users_for_repo', {
                'repo_name_filter': repo_name
            }).execute()
            
            if response.data:
                user_ids = [row['user_id'] for row in response.data]
                return user_ids
            else:
                return []
        except Exception as e:
            print(f"[MetadataService] Erro ao buscar usuários para webhook: {e}")
            return []