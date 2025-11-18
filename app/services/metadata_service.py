# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/metadata_service.py
# (Injeta a CLASSE EmbeddingService)

import os
from supabase import create_client, Client
from typing import List, Dict, Any, Optional
from datetime import datetime

# Importa a CLASSE, não as funções
from app.services.embedding_service import EmbeddingService

class MetadataService:
    def __init__(self, embedding_service: EmbeddingService):
        try:
            url: str = os.getenv("SUPABASE_URL")
            key: str = os.getenv("SUPABASE_KEY")
            if not url or not key:
                raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
            
            self.supabase: Client = create_client(url, key)
            print("[MetadataService] Cliente Supabase inicializado com sucesso.")
            
            if not embedding_service:
                raise ValueError("EmbeddingService é obrigatório para MetadataService.")
            self.embedding_service = embedding_service
            print("[MetadataService] Dependência (EmbeddingService) injetada.")
            
        except Exception as e:
            print(f"[MetadataService] Erro ao inicializar Supabase: {e}")
            self.supabase = None
            raise

    def save_documents_batch(self, user_id: str, documents: List[Dict[str, Any]]):
        # ... verificações iniciais ...
        try:
            textos_para_embedding = [doc["conteudo"] for doc in documents]
            embeddings = self.embedding_service.get_embeddings_batch(textos_para_embedding)
            
            documentos_para_salvar = []
            for i, doc in enumerate(documents):
                doc["embedding"] = embeddings[i]
                doc["user_id"] = user_id
                # Garante que tenha branch, se não tiver assume 'main'
                if "branch" not in doc:
                    doc["branch"] = "main"
                documentos_para_salvar.append(doc)
            
            self.supabase.table("documentos").insert(documentos_para_salvar).execute()
        except Exception as e:
            # ... log de erro ...
            raise

    def delete_documents_by_repo(self, user_id: str, repo_name: str, branch: str = None):
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
        try:
            query = self.supabase.table("documentos").delete() \
                .eq("user_id", user_id) \
                .eq("repositorio", repo_name)
            
            if branch:
                query = query.eq("branch", branch)
                
            query.execute()
        except Exception as e:
            # ... erro ...
            raise

    def find_similar_documents(self, user_id: str, query_text: str, repo_name: str, k: int = 5) -> List[Dict[str, Any]]:
        if not self.supabase or not self.embedding_service:
            raise Exception("Serviços Supabase ou Embedding não estão inicializados.")
        try:
            query_embedding = self.embedding_service.get_embedding(query_text)
            response = self.supabase.rpc('match_documents_user', {
                'query_embedding': query_embedding,
                'match_repositorio': repo_name,
                'match_user_id': user_id,
                'match_count': k
            }).execute()
            return response.data or []
        except Exception as e:
            print(f"[MetadataService] Erro na busca vetorial: {e}")
            raise

    def get_latest_timestamp(self, user_id: str, repo_name: str, branch: str) -> Optional[datetime]:
        if not self.supabase: return None
        try:
            # Chama a nova RPC com 3 argumentos
            response = self.supabase.rpc('get_latest_repo_timestamp_user', {
                'repo_name_filter': repo_name,
                'user_id_filter': user_id,
                'branch_filter': branch
            }).execute()
            latest_timestamp_str = response.data
            if latest_timestamp_str:
                return datetime.fromisoformat(latest_timestamp_str)
            return None
        except Exception as e:
            print(f"[MetadataService] ERRO ao buscar timestamp: {e}")
            return None

    def get_all_documents_for_repository(self, user_id: str, repo_name: str) -> List[Dict[str, Any]]:
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
        try:
            print(f"[MetadataService] Buscando todos os documentos (User: {user_id}) de: {repo_name}")
            response = self.supabase.table("documentos").select("file_path, conteudo") \
                .eq("user_id", user_id) \
                .eq("repositorio", repo_name) \
                .execute()
            return response.data or []
        except Exception as e:
            print(f"[MetadataService] Erro ao buscar todos os documentos: {e}")
            return []

    def find_similar_instruction(self, user_id: str, repo_name: str, query_text: str) -> Optional[str]:
        if not self.supabase or not self.embedding_service:
            raise Exception("Serviços Supabase ou Embedding não estão inicializados.")
        try:
            query_embedding = self.embedding_service.get_embedding(query_text)
            response = self.supabase.rpc('match_instructions_user', {
                'query_embedding': query_embedding,
                'match_repositorio': repo_name,
                'match_user_id': user_id,
                'match_count': 1
            }).execute()
            if response.data:
                return response.data[0].get("instrucao_texto")
            return None
        except Exception as e:
            print(f"[MetadataService] Erro na busca vetorial de instruções: {e}")
            return None

    def check_repo_exists(self, user_id: str, repo_name: str, branch: str) -> bool:
        if not self.supabase: return False
        try:
            response = self.supabase.table("documentos") \
                .select("id") \
                .eq("user_id", user_id) \
                .eq("repositorio", repo_name) \
                .eq("branch", branch) \
                .limit(1) \
                .execute()
            return len(response.data) > 0
        except Exception as e:
            return False

    def delete_file_documents_only(self, user_id: str, repo_name: str, branch: str):
        if not self.supabase: return
        try:
            self.supabase.table("documentos").delete() \
                .eq("user_id", user_id) \
                .eq("repositorio", repo_name) \
                .eq("branch", branch) \
                .eq("tipo", "file") \
                .execute()
        except Exception as e:
            raise

    def get_distinct_users_for_repo(self, repo_name: str) -> List[str]:
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
        try:
            response = self.supabase.rpc('get_distinct_users_for_repo', {
                'repo_name_filter': repo_name
            }).execute()
            if response.data:
                return [row['user_id'] for row in response.data]
            return []
        except Exception as e:
            print(f"[MetadataService] Erro ao buscar usuários para webhook: {e}")
            return []