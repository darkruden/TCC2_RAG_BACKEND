# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/ingest_service.py

import os
import traceback
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.github_service import GithubService
from app.services.metadata_service import MetadataService
from app.services.embedding_service import EmbeddingService

class TCC_TextSplitter:
    def __init__(self, chunk_size: int = 3000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> List[str]:
        if not text: return []
        chunks = []
        start = 0
        text_len = len(text)
        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            chunks.append(text[start:end])
            step = self.chunk_size - self.chunk_overlap
            if step < 1: step = 1
            start += step
        return chunks

class IngestService:
    def __init__(self, github_service: GithubService, metadata_service: MetadataService, embedding_service: EmbeddingService):
        self.github = github_service
        self.metadata = metadata_service
        self.splitter = TCC_TextSplitter()
        print("[IngestService] Inicializado com lógica cirúrgica e PARALELISMO.")

    def _download_file_content(self, repo_name: str, path: str, branch: str) -> Tuple[str, str]:
        """Helper para ser executado em thread separada."""
        content = self.github.get_file_content(repo_name, path, branch)
        return path, content

    def ingest_repository(self, user_id: str, repo_url: str, issues_limit: int, prs_limit: int, commits_limit: int, max_depth: int) -> Dict[str, Any]:
        print(f"[TRACER] Início Ingestão: {repo_url} (User: {user_id})")
        
        # --- 1. INTELIGÊNCIA ELÁSTICA (Calcula Workers Dinamicamente) ---
        limits = self.github.check_rate_limit()
        remaining = limits.get("remaining", 5000)
        
        # Lógica de Decisão baseada no saldo da API
        if remaining > 4000:
            current_max_workers = 10 # Modo Turbo
            print(f"[IngestService] MODO TURBO: {remaining} créditos. Usando {current_max_workers} threads.")
        elif remaining > 2000:
            current_max_workers = 5  # Modo Padrão
            print(f"[IngestService] MODO PADRÃO: {remaining} créditos. Usando {current_max_workers} threads.")
        elif remaining > 500:
            current_max_workers = 2  # Modo Economia
            print(f"[IngestService] MODO ECONOMIA: {remaining} créditos. Usando {current_max_workers} threads.")
        else:
            current_max_workers = 1  # Modo Sobrevivência
            print(f"[IngestService] MODO SOBREVIVÊNCIA: {remaining} créditos. Ingestão sequencial.")
        # ----------------------------------------------------------------

        try:
            # 2. Identificação e Metadados (Correção da Branch)
            repo_name, parsed_branch = self.github.parse_repo_url(repo_url)
            
            # Busca metadados para confirmar branch real
            repo_meta = self.github.get_repo_metadata(repo_name)
            default_branch = repo_meta.get("default_branch", "main")
            visibility = repo_meta.get("visibility", "private")
            
            # Decide a branch final
            branch = parsed_branch if parsed_branch else default_branch
            
            print(f"[TRACER] Repo: {repo_name} | Branch Detectada: {branch} | Visibilidade: {visibility}")
            
            self.metadata.update_user_last_repo(user_id, f"{repo_name}/tree/{branch}")

            # 3. Ingestão de Metadados (Commits/Issues)
            latest_ts = self.metadata.get_latest_timestamp(user_id, repo_name, branch)
            github_data = self.github.get_repo_data_batch(
                repo_url, issues_limit, prs_limit, commits_limit, since=latest_ts, branch=branch
            )
            
            meta_docs = self._create_metadata_docs(user_id, repo_name, branch, github_data, visibility)
            if meta_docs:
                print(f"[TRACER] Salvando {len(meta_docs)} novos metadados...")
                self._save_batch(user_id, meta_docs)
            else:
                print("[TRACER] Nenhum metadado novo.")

            # 4. ARQUIVOS - Lógica com Paralelismo Dinâmico
            print(f"[TRACER] Iniciando sincronização de arquivos na branch {branch}...")
            
            github_files_map = self.github.get_repo_file_structure(repo_name, branch)
            db_files_map = self.metadata.get_existing_file_shas(user_id, repo_name, branch)

            files_to_add_update = []
            files_to_delete = []
            unchanged_count = 0

            for path, sha in github_files_map.items():
                if path not in db_files_map:
                    files_to_add_update.append(path) 
                elif db_files_map[path] != sha:
                    files_to_add_update.append(path)
                else:
                    unchanged_count += 1

            for path in db_files_map.keys():
                if path not in github_files_map:
                    files_to_delete.append(path)

            print(f"[TRACER] Arquivos: {len(files_to_add_update)} baixar, {len(files_to_delete)} deletar.")

            # D1. Deleta obsoletos
            if files_to_delete:
                self.metadata.delete_files_by_paths(user_id, repo_name, branch, files_to_delete)

            # D2. Download Paralelo (Usando current_max_workers calculado acima)
            new_docs = []
            successful_updates = 0
            
            if files_to_add_update:
                print(f"[IngestService] Iniciando download com {current_max_workers} workers...")
                
                with ThreadPoolExecutor(max_workers=current_max_workers) as executor:
                    future_to_path = {
                        executor.submit(self._download_file_content, repo_name, path, branch): path 
                        for path in files_to_add_update
                    }

                    for future in as_completed(future_to_path):
                        path = future_to_path[future]
                        try:
                            _, content = future.result()
                            
                            if content is None: 
                                print(f"[IngestService] AVISO: Conteúdo vazio para {path}.")
                                continue

                            if path in db_files_map:
                                self.metadata.delete_files_by_paths(user_id, repo_name, branch, [path])

                            chunks = self.splitter.split_text(content)
                            file_sha = github_files_map[path]

                            for chunk in chunks:
                                if not chunk.strip(): continue
                                doc = {
                                    "user_id": user_id,
                                    "repositorio": repo_name,
                                    "branch": branch,
                                    "file_path": path,
                                    "file_sha": file_sha,
                                    "visibility": visibility,
                                    "conteudo": chunk,
                                    "tipo": "file"
                                }
                                new_docs.append(doc)
                            
                            successful_updates += 1
                            
                            if len(new_docs) >= 50:
                                self._save_batch(user_id, new_docs)
                                new_docs = []
                                
                        except Exception as exc:
                            print(f"[IngestService] Erro ao processar arquivo {path}: {exc}")

            if new_docs:
                self._save_batch(user_id, new_docs)

            total_changes = successful_updates + len(files_to_delete)
            
            if total_changes == 0 and not meta_docs:
                 status_msg = f"O repositório {repo_name} já é o mais atualizado (Branch: {branch})."
            else:
                 status_msg = f"Sincronização concluída. {successful_updates} arquivos atualizados, {len(files_to_delete)} deletados."

            return {
                "status": "sucesso",
                "repo": repo_name,
                "branch": branch,
                "updated": successful_updates,
                "deleted": len(files_to_delete),
                "unchanged": unchanged_count,
                "mensagem": status_msg
            }

        except Exception as e:
            print(f"[IngestService] ERRO FATAL: {e}")
            traceback.print_exc()
            raise

    def _create_metadata_docs(self, user_id, repo, branch, data, visibility):
        docs = []
        def add(item, tipo):
            docs.append({
                "user_id": user_id, "repositorio": repo, "branch": branch, "tipo": tipo,
                "visibility": visibility, "file_sha": None,
                "metadados": item, 
                "conteudo": f"{tipo.capitalize()}: {item.get('title') or item.get('message', '')}"
            })

        for c in data.get("commits", []): add(c, "commit")
        for i in data.get("issues", []): add(i, "issue")
        for p in data.get("prs", []): add(p, "pr")
        return docs

    def _save_batch(self, user_id, docs):
        self.metadata.save_documents_batch(user_id, docs)

    def save_instruction_document(self, user_id: str, repo_url: str, instrucao_texto: str):
         return self.metadata.save_documents_batch(user_id, [{
             "user_id": user_id, "repositorio": repo_url, "instrucao_texto": instrucao_texto, 
             "conteudo": instrucao_texto, "tipo": "instruction", "visibility": "private"
         }])
         
    def handle_webhook(self, event_type, payload):
        return {"status": "webhook_received"}