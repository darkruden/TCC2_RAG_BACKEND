# CÓDIGO COMPLETO PARA: app/services/metadata_service.py

import os
from supabase import create_client, Client
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.services.embedding_service import EmbeddingService

class MetadataService:
    def __init__(self, embedding_service: EmbeddingService):
        try:
            url: str = os.getenv("SUPABASE_URL")
            key: str = os.getenv("SUPABASE_KEY")
            if not url or not key:
                raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
            
            self.supabase: Client = create_client(url, key)
            if not embedding_service:
                raise ValueError("EmbeddingService é obrigatório.")
            self.embedding_service = embedding_service
        except Exception as e:
            print(f"[MetadataService] Erro ao inicializar: {e}")
            self.supabase = None
            raise

    # --- NOVOS MÉTODOS PARA LÓGICA CIRÚRGICA ---

    def update_user_last_repo(self, user_id: str, repo_name: str):
        """Salva qual foi o último repo que o usuário mexeu (Contexto Implícito)."""
        try:
            self.supabase.table("usuarios").update({"last_ingested_repo": repo_name}).eq("id", user_id).execute()
        except Exception as e:
            print(f"[MetadataService] Erro ao atualizar last_repo: {e}")

    def get_existing_file_shas(self, user_id: str, repo_name: str, branch: str) -> Dict[str, str]:
        """
        Retorna um dicionário {file_path: file_sha} de todos os arquivos JÁ salvos.
        Usado para comparar com o GitHub e evitar download inútil.
        """
        if not self.supabase: return {}
        try:
            # Buscamos apenas caminho e sha para ser leve
            response = self.supabase.table("documentos") \
                .select("file_path, file_sha") \
                .eq("user_id", user_id) \
                .eq("repositorio", repo_name) \
                .eq("branch", branch) \
                .eq("tipo", "file") \
                .execute()
            
            # Converte lista para dict {path: sha}
            return {doc['file_path']: doc['file_sha'] for doc in response.data if doc['file_path']}
        except Exception as e:
            print(f"[MetadataService] Erro ao buscar SHAs existentes: {e}")
            return {}

    def delete_files_by_paths(self, user_id: str, repo_name: str, branch: str, paths: List[str]):
        """Deleta arquivos específicos que foram removidos do GitHub."""
        if not self.supabase or not paths: return
        try:
            # O Supabase tem limites de filtro, para muitos arquivos o ideal seria batch
            print(f"[MetadataService] Deletando {len(paths)} arquivos obsoletos...")
            self.supabase.table("documentos").delete() \
                .eq("user_id", user_id) \
                .eq("repositorio", repo_name) \
                .eq("branch", branch) \
                .in_("file_path", paths) \
                .execute()
        except Exception as e:
            print(f"[MetadataService] Erro ao deletar arquivos: {e}")

    def save_documents_batch(self, user_id: str, documents: List[Dict[str, Any]]):
        """
        Salva documentos (agora com SHA e Visibility).
        """
        if not self.supabase or not self.embedding_service: return
        if not documents: return
        
        try:
            textos_para_embedding = [doc["conteudo"] for doc in documents]
            embeddings = self.embedding_service.get_embeddings_batch(textos_para_embedding)
            
            documentos_para_salvar = []
            for i, doc in enumerate(documents):
                doc["embedding"] = embeddings[i]
                doc["user_id"] = user_id
                if "branch" not in doc: doc["branch"] = "main"
                # Garante campos novos
                if "visibility" not in doc: doc["visibility"] = "private"
                if "file_sha" not in doc: doc["file_sha"] = None
                
                documentos_para_salvar.append(doc)
            
            self.supabase.table("documentos").insert(documentos_para_salvar).execute()
        except Exception as e:
            print(f"[MetadataService] Erro CRÍTICO ao salvar lote: {e}")
            raise

    # --- MÉTODOS DE CONSULTA (Mantidos/Atualizados) ---

    def check_repo_exists(self, user_id: str, repo_name: str, branch: str) -> bool:
        if not self.supabase: return False
        try:
            response = self.supabase.table("documentos") \
                .select("id").eq("user_id", user_id).eq("repositorio", repo_name).eq("branch", branch).limit(1).execute()
            return len(response.data) > 0
        except Exception: return False

    def delete_file_documents_only(self, user_id: str, repo_name: str, branch: str):
        # Este método será usado menos agora, mas mantemos por segurança
        if not self.supabase: return
        try:
            self.supabase.table("documentos").delete().eq("user_id", user_id).eq("repositorio", repo_name).eq("branch", branch).eq("tipo", "file").execute()
        except Exception: pass

    def delete_documents_by_repo(self, user_id: str, repo_name: str, branch: str = None):
        if not self.supabase: return
        try:
            query = self.supabase.table("documentos").delete().eq("user_id", user_id).eq("repositorio", repo_name)
            if branch: query = query.eq("branch", branch)
            query.execute()
        except Exception: pass

    def get_latest_timestamp(self, user_id: str, repo_name: str, branch: str) -> Optional[datetime]:
        if not self.supabase: return None
        try:
            response = self.supabase.rpc('get_latest_repo_timestamp_user', {
                'repo_name_filter': repo_name, 'user_id_filter': user_id, 'branch_filter': branch
            }).execute()
            if response.data: return datetime.fromisoformat(response.data)
            return None
        except Exception: return None

    def find_similar_documents(self, user_id: str, query_text: str, repo_name: str, branch: str = None, k: int = 5) -> List[Dict[str, Any]]:
        if not self.supabase: return []
        try:
            embedding = self.embedding_service.get_embedding(query_text)
            # A RPC agora cuida da lógica de 'public' vs 'private'
            params = {
                'query_embedding': embedding,
                'match_repositorio': repo_name,
                'match_user_id': user_id,
                'match_count': k,
                'match_branch': branch
            }
            response = self.supabase.rpc('match_documents_user', params).execute()
            return response.data or []
        except Exception as e:
            print(f"[MetadataService] Erro na busca: {e}")
            return []
            
    def get_all_documents_for_repository(self, user_id: str, repo_name: str, branch: str = "main") -> List[Dict[str, Any]]:
        if not self.supabase: return []
        try:
            query = self.supabase.table("documentos").select("file_path, conteudo, metadados, tipo") \
                .eq("repositorio", repo_name)
            
            if branch: query = query.eq("branch", branch)
            
            # Para relatório, precisamos garantir que pegamos o do usuário OU publico.
            # Como o relatório é uma operação pesada, vamos simplificar e pegar apenas o do usuário por enquanto
            query = query.eq("user_id", user_id)
            
            response = query.execute()
            return response.data or []
        except Exception: return []

    def find_similar_instruction(self, user_id: str, repo_name: str, query_text: str) -> Optional[str]:
        if not self.supabase or not self.embedding_service:
            raise Exception("Serviços Supabase ou Embedding não estão inicializados.")
        try:
            emb = self.embedding_service.get_embedding(query_text)
            res = self.supabase.rpc('match_instructions_user', {
                'query_embedding': emb, 
                'match_repositorio': repo_name, 
                'match_user_id': user_id, 
                'match_count': 1
            }).execute()
            
            # CORREÇÃO AQUI: 'if res.data' em vez de 'ifXR res.data'
            return res.data[0].get("instrucao_texto") if res.data else None
            
        except Exception: return None
        
    def get_distinct_users_for_repo(self, repo_name: str) -> List[str]:
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
        try:
            res = self.supabase.rpc('get_distinct_users_for_repo', {'repo_name_filter': repo_name}).execute()
            return [row['user_id'] for row in res.data] if res.data else []
        except Exception: return []

    def get_recent_commits(self, user_id: str, repo_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.supabase: return []
        try:
            params = {
                'match_user_id': user_id,
                'match_repo': repo_name,
                'limit_count': limit
            }
            # Chama a "consulta salva" (RPC) no banco
            response = self.supabase.rpc('get_recent_commits_user', params).execute()
            
            results = []
            for row in (response.data or []):
                results.append({
                    "conteudo": row['conteudo'],
                    "metadados": row['metadados'],
                    "tipo": "commit",
                    "file_path": "Contexto Temporal (Recente)",
                    "branch": "main" 
                })
            return results
        except Exception as e:
            print(f"[MetadataService] Erro ao buscar commits recentes: {e}")
            return []