# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/ingest_service.py
# (Correção: Força ingestão completa para evitar perda de histórico ao deletar dados antigos)

import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import traceback

from app.services.github_service import GithubService
from app.services.metadata_service import MetadataService
from app.services.embedding_service import EmbeddingService

# --- CLASSE DE SPLITTER REAL (Embutida para evitar ImportError) ---
class TCC_TextSplitter:
    """
    Divisor de texto simples baseado em caracteres para garantir que 
    os chunks nunca excedam o limite de tokens da OpenAI.
    """
    def __init__(self, chunk_size: int = 3000, chunk_overlap: int = 200):
        # 3000 caracteres é aprox. 750-1000 tokens, muito seguro para o limite de 8192.
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> List[str]:
        if not text:
            return []
        
        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            # Define o fim do chunk
            end = min(start + self.chunk_size, text_len)
            
            # Extrai o pedaço
            chunk = text[start:end]
            chunks.append(chunk)
            
            # Avança o ponteiro, recuando pelo overlap (mas garante que avance)
            step = self.chunk_size - self.chunk_overlap
            if step < 1: step = 1
            start += step
        
        return chunks

class IngestService:
    def __init__(
        self,
        github_service: GithubService,
        metadata_service: MetadataService,
        embedding_service: EmbeddingService,
    ):
        self.github_service = github_service
        self.metadata_service = metadata_service
        self.embedding_service = embedding_service
        # Instancia o splitter seguro definido acima
        self.text_splitter = TCC_TextSplitter(chunk_size=3000, chunk_overlap=200)
        print("[IngestService] Serviço de Ingestão inicializado com Splitter Seguro.")

    def ingest_repository(
        self,
        user_id: str,
        repo_url: str,
        issues_limit: int = 50,
        prs_limit: int = 20,
        commits_limit: int = 30,
        max_depth: int = 10,
    ) -> Dict[str, Any]:
        print(f"[IngestService] Iniciando ingestão (User: {user_id}) de: {repo_url}")
        try:
            repo_name = self.github_service.parse_repo_url(repo_url)
            
            # --- LÓGICA DE INGESTÃO INTELIGENTE ---
            
            # 1. Verifica se o repositório já existe no banco
            exists = self.metadata_service.check_repo_exists(user_id, repo_name)
            latest_timestamp = None
            tipo_ingestao = "COMPLETA"

            if exists:
                print(f"[IngestService] Repositório {repo_name} encontrado. Verificando atualizações...")
                # Tenta pegar a data do último item salvo para fazer o delta
                latest_timestamp = self.metadata_service.get_latest_timestamp(user_id, repo_name)
                
                if latest_timestamp:
                    tipo_ingestao = "INCREMENTAL"
                    print(f"[IngestService] Modo INCREMENTAL ativado. Buscando dados desde: {latest_timestamp}")
                else:
                    print("[IngestService] AVISO: Repositório existe mas sem data válida. Forçando ingestão completa.")

                # Na atualização, deletamos APENAS o código antigo ('file') para substituir pelo novo.
                # O histórico (commits, issues, PRs) é mantido e apenas adicionamos os novos.
                self.metadata_service.delete_file_documents_only(user_id, repo_name)
            
            else:
                print(f"[IngestService] Primeira vez ingerindo {repo_name}. Modo COMPLETO.")
                # Se é a primeira vez (ou estava corrompido), limpa TUDO para garantir.
                self.metadata_service.delete_documents_by_repo(user_id, repo_name)

            # 2. Busca Arquivos (Sempre pega o snapshot atual do código)
            files = self.github_service.get_repo_files_batch(repo_url, max_depth)
            
            # 3. Busca Metadados (Se incremental, usa 'since' para trazer só os novos)
            metadata = self.github_service.get_repo_data_batch(
                repo_url, issues_limit, prs_limit, commits_limit, since=latest_timestamp
            )
            
            if not files and not metadata["commits"] and not metadata["issues"] and not metadata["prs"]:
                print("[IngestService] Nenhum dado novo encontrado no GitHub.")
                return {"status": "atualizado_sem_mudancas", "repo": repo_name, "arquivos": 0, "chunks": 0}

            all_documents = []
            
            # 4. Processamento de Arquivos
            print(f"[IngestService] Processando {len(files)} arquivos de código atuais...")
            for file_data in files:
                file_content = file_data.get("content", "")
                chunks = self.text_splitter.split_text(file_content)
                
                for chunk in chunks:
                    if not chunk.strip(): continue
                    
                    doc = self._create_document_chunk(
                        user_id=user_id,
                        repo_name=repo_name,
                        file_path=file_data["file_path"],
                        chunk_content=chunk
                    )
                    all_documents.append(doc)
            
            # 5. Processamento de Metadados
            # Se for incremental, 'metadata' contém apenas os itens novos retornados pelo GitHub
            count_commits = len(metadata.get('commits', []))
            count_issues = len(metadata.get('issues', []))
            print(f"[IngestService] Processando {count_commits} commits e {count_issues} issues novos...")
            
            metadata_docs = self._create_metadata_documents(user_id, repo_name, metadata)
            all_documents.extend(metadata_docs)

            total_chunks = len(all_documents)
            print(f"[IngestService] Total de {total_chunks} chunks para salvar.")
            
            # 6. Salva em lotes
            batch_size = 50 
            for i in range(0, total_chunks, batch_size):
                batch = all_documents[i : i + batch_size]
                self.metadata_service.save_documents_batch(user_id, batch)
                print(f"[IngestService] Lote {i//batch_size + 1} salvo.")

            print(f"[IngestService] Ingestão {tipo_ingestao} de {repo_name} concluída.")
            return {
                "status": "sucesso",
                "tipo": tipo_ingestao,
                "repo": repo_name,
                "arquivos_processados": len(files),
                "novos_metadados": len(metadata_docs),
                "chunks_gerados": total_chunks,
            }

        except Exception as e:
            print(f"[IngestService] ERRO (Geral): {e}")
            traceback.print_exc()
            raise

    def _create_document_chunk(
        self, user_id: str, repo_name: str, file_path: str, chunk_content: str
    ) -> Dict[str, Any]:
        return {
            "user_id": user_id, "repositorio": repo_name,
            "file_path": file_path, "conteudo": chunk_content, "tipo": "file"
        }

    def _create_metadata_documents(self, user_id: str, repo_name: str, raw_data: Dict[str, List]) -> List[Dict[str, Any]]:
        documentos = []
        for item in raw_data.get("commits", []):
            conteudo = f"Commit de {item.get('author', 'N/A')}: {item.get('message', '')}"
            documentos.append({
                "user_id": user_id, "repositorio": repo_name, "tipo": "commit",
                "metadados": {"sha": item['sha'], "autor": item['author'], "data": item['date'], "url": item['url']},
                "conteudo": conteudo
            })
        for item in raw_data.get("issues", []):
            conteudo = f"Issue #{item['id']} por {item['author']}: {item['title']}\n{item.get('body', '')}"
            documentos.append({
                "user_id": user_id, "repositorio": repo_name, "tipo": "issue",
                "metadados": {"id": item['id'], "autor": item['author'], "data": item['date'], "url": item['url'], "titulo": item['title']},
                "conteudo": conteudo
            })
        for item in raw_data.get("prs", []):
            conteudo = f"PR #{item['id']} por {item['author']}: {item['title']}\n{item.get('body', '')}"
            documentos.append({
                "user_id": user_id, "repositorio": repo_name, "tipo": "pr",
                "metadados": {"id": item['id'], "autor": item['author'], "data": item['date'], "url": item['url'], "titulo": item['title']},
                "conteudo": conteudo
            })
        return documentos

    def save_instruction_document(self, user_id: str, repo_url: str, instrucao_texto: str):
        print(f"[IngestService] Criando documento de instrução para {repo_url}...")
        repo_name = self.github_service.parse_repo_url(repo_url)
        embedding = self.embedding_service.get_embedding(instrucao_texto)
        doc = {
            "user_id": user_id, "repositorio": repo_name,
            "instrucao_texto": instrucao_texto,
            "embedding": embedding, "tipo": "instruction"
        }
        try:
            self.metadata_service.supabase.table("instrucoes").insert(doc).execute()
            print(f"[IngestService] Instrução salva com sucesso para {repo_name}.")
            return {"status": "instrucao_salva", "repo": repo_name}
        except Exception as e:
            print(f"[IngestService] ERRO ao salvar instrução: {e}")
            raise
            
    def handle_webhook(self, event_type: str, payload: dict):
        print(f"[IngestService] Processando webhook '{event_type}'...")
        repo_full_name = payload.get("repository", {}).get("full_name")
        if not repo_full_name:
            return {"status": "ignored", "reason": "Nome do repositório não encontrado."}

        user_ids = self.metadata_service.get_distinct_users_for_repo(repo_full_name)
        if not user_ids:
            return {"status": "ignored", "reason": f"Ninguém rastreia {repo_full_name}"}

        print(f"[IngestService] Webhook relevante. {len(user_ids)} usuários rastreiam {repo_full_name}.")
        for user_id in user_ids:
            # Para webhook, mantemos a lógica de buscar apenas o novo, pois webhook é um evento incremental por natureza
            latest_timestamp = self.metadata_service.get_latest_timestamp(user_id, repo_full_name)
            if not latest_timestamp:
                continue
            
            print(f"[IngestService] Processando webhook para User: {user_id}...")
            metadata_novos = self.github_service.get_repo_data_batch(
                repo_full_name, 20, 20, 20, since=latest_timestamp
            )
            documentos_novos = self._create_metadata_documents(user_id, repo_full_name, metadata_novos)
            
            if documentos_novos:
                print(f"[IngestService] {len(documentos_novos)} novos itens de metadados encontrados. Salvando...")
                self.metadata_service.save_documents_batch(user_id, documentos_novos)
            else:
                print(f"[IngestService] Nenhum item novo de metadados encontrado para {user_id}.")
        return {"status": "processed", "event": event_type, "users_notified": len(user_ids)}
    