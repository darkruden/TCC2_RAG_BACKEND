# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/metadata_service.py

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
            response = self.supabase.table("documentos") \
                .select("file_path, file_sha") \
                .eq("user_id", user_id) \
                .eq("repositorio", repo_name) \
                .eq("branch", branch) \
                .eq("tipo", "file") \
                .execute()
            
            return {doc['file_path']: doc['file_sha'] for doc in response.data if doc['file_path']}
        except Exception as e:
            print(f"[MetadataService] Erro ao buscar SHAs existentes: {e}")
            return {}

    def delete_files_by_paths(self, user_id: str, repo_name: str, branch: str, paths: List[str]):
        """Deleta arquivos específicos que foram removidos do GitHub."""
        if not self.supabase or not paths: return
        try:
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
        Salva documentos com otimização seletiva de embeddings.
        Arquivos -> Embedding Real (OpenAI)
        Metadados -> Embedding Dummy (Zeros) para performance extrema.
        """
        if not self.supabase or not self.embedding_service: return
        if not documents: return
        
        try:
            # Separa o que precisa de IA do que não precisa
            docs_com_embedding = []
            docs_sem_embedding = []
            
            indices_com_embedding = []
            indices_sem_embedding = []

            for i, doc in enumerate(documents):
                # --- REGRA DE NEGÓCIO: Só gera inteligência para CÓDIGO e INSTRUÇÕES ---
                if doc.get("tipo") in ["file", "instruction"]:
                    docs_com_embedding.append(doc["conteudo"])
                    indices_com_embedding.append(i)
                else:
                    # Commits, Issues e PRs vão sem custo de IA
                    docs_sem_embedding.append(doc)
                    indices_sem_embedding.append(i)

            # 1. Gera Embeddings Reais apenas para os arquivos (Lento, mas necessário)
            embeddings_reais = []
            if docs_com_embedding:
                # print(f"[MetadataService] Gerando {len(docs_com_embedding)} embeddings reais (Arquivos)...")
                embeddings_reais = self.embedding_service.get_embeddings_batch(docs_com_embedding)

            # 2. Gera Vetores Zerados (Dummy) para metadados (Instantâneo)
            # Cria um vetor de 1536 zeros (dimensão do text-embedding-3-small)
            dummy_vector = [0.0] * 1536 

            # 3. Remonta a lista original com os vetores certos
            documentos_para_salvar = [None] * len(documents)

            # Preenche os reais
            for local_idx, original_idx in enumerate(indices_com_embedding):
                doc = documents[original_idx]
                doc["embedding"] = embeddings_reais[local_idx]
                doc["user_id"] = user_id
                if "branch" not in doc: doc["branch"] = "main"
                if "visibility" not in doc: doc["visibility"] = "private"
                if "file_sha" not in doc: doc["file_sha"] = None
                documentos_para_salvar[original_idx] = doc

            # Preenche os dummies (Commits/Issues)
            for original_idx in indices_sem_embedding:
                doc = documents[original_idx]
                doc["embedding"] = dummy_vector # Vetor nulo
                doc["user_id"] = user_id
                if "branch" not in doc: doc["branch"] = "main"
                if "visibility" not in doc: doc["visibility"] = "private"
                if "file_sha" not in doc: doc["file_sha"] = None
                documentos_para_salvar[original_idx] = doc
            
            # --- LÓGICA DE FALLBACK PARA DUPLICATAS (MANTIDA) ---
            try:
                self.supabase.table("documentos").insert(documentos_para_salvar).execute()
            
            except Exception as e:
                error_str = str(e)
                if "23505" in error_str or "duplicate key" in error_str:
                    # print("[MetadataService] AVISO: Duplicatas no lote. Inserindo individualmente...")
                    for doc in documentos_para_salvar:
                        try:
                            self.supabase.table("documentos").insert(doc).execute()
                        except Exception as inner_e:
                            if "23505" in str(inner_e) or "duplicate key" in str(inner_e): pass
                            else: print(f"[MetadataService] Erro individual: {inner_e}")
                else:
                    raise e

        except Exception as e:
            print(f"[MetadataService] Erro CRÍTICO ao salvar lote: {e}")
            raise

    # --- MÉTODOS DE CONSULTA ---

    def check_repo_exists(self, user_id: str, repo_name: str, branch: str) -> bool:
        if not self.supabase: return False
        try:
            response = self.supabase.table("documentos") \
                .select("id").eq("user_id", user_id).eq("repositorio", repo_name).eq("branch", branch).limit(1).execute()
            return len(response.data) > 0
        except Exception: return False

    def delete_file_documents_only(self, user_id: str, repo_name: str, branch: str):
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
            
            return res.data[0].get("instrucao_texto") if res.data else None
            
        except Exception: return None
        
    def get_distinct_users_for_repo(self, repo_name: str) -> List[str]:
        if not self.supabase: raise Exception("Serviço Supabase não está inicializado.")
        try:
            res = self.supabase.rpc('get_distinct_users_for_repo', {'repo_name_filter': repo_name}).execute()
            return [row['user_id'] for row in res.data] if res.data else []
        except Exception: return []

    def get_recent_commits(self, user_id: str, repo_name: str, branch: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.supabase: return []
        try:
            # --- CORREÇÃO: Voltamos para a lógica de "Default Main" ---
            # Se branch for None (URL raiz), assumimos "main".
            # Se branch tiver valor (ex: feature/x), usamos ela.
            target_branch = branch if branch else "main"
            
            print(f"\n[DEBUG TEMPORAL] ------------------------------------------------")
            print(f"[DEBUG TEMPORAL] Buscando commits no DB.")
            print(f"[DEBUG TEMPORAL] Repo: {repo_name} | Branch Alvo: {target_branch}")

            params = {
                'match_user_id': user_id,
                'match_repo': repo_name,
                'match_branch': target_branch, 
                'limit_count': limit
            }
            
            # Executa a RPC
            response = self.supabase.rpc('get_recent_commits_user', params).execute()
            data = response.data or []

            print(f"[DEBUG TEMPORAL] O Banco retornou {len(data)} commits.")
            
            results = []
            for i, row in enumerate(data):
                meta = row.get('metadados', {})
                data_commit = meta.get('date', 'N/A')
                sha = meta.get('sha', 'N/A')
                msg = meta.get('message', '')[:50]
                
                print(f"[DEBUG TEMPORAL] #{i+1} - SHA: {sha[:7]} | Data: {data_commit} | Branch: {row.get('branch')} | Msg: {msg}...")
                
                results.append({
                    "conteudo": f"[DATA: {data_commit}] [SHA: {sha[:7]}] {row['conteudo']}",
                    "metadados": meta,
                    "tipo": "commit",
                    "file_path": "Contexto Temporal (Recente)", 
                    "branch": row.get('branch') or target_branch
                })
            
            print(f"[DEBUG TEMPORAL] ------------------------------------------------\n")
            return results

        except Exception as e:
            print(f"[MetadataService] Erro CRÍTICO ao buscar commits: {e}")
            import traceback
            traceback.print_exc()
            return []