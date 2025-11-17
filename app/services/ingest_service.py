# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/ingest_service.py
# (Refatorado para Injeção de Dependência)

import os
from app.services.github_service import GithubService
from app.services.metadata_service import MetadataService
from app.services.embedding_service import EmbeddingService
from app.utils.text_splitter import TCC_TextSplitter # (Certifique-se que este arquivo existe)
from typing import List, Dict, Any, Optional
from datetime import datetime
import traceback

class IngestService:
    """
    Serviço de orquestração para o processo de ingestão de repositórios.
    """
    def __init__(
        self,
        github_service: GithubService,
        metadata_service: MetadataService,
        embedding_service: EmbeddingService,
    ):
        """
        Inicializa o IngestService com as dependências injetadas.
        """
        self.github_service = github_service
        self.metadata_service = metadata_service
        self.embedding_service = embedding_service
        
        # (Presumindo que você tem este utilitário)
        # Se 'TCC_TextSplitter' não existir, esta linha pode precisar ser ajustada
        self.text_splitter = TCC_TextSplitter(chunk_size=1000, chunk_overlap=100)
        
        print("[IngestService] Serviço de Ingestão inicializado.")

    def ingest_repository(
        self,
        user_id: str,
        repo_url: str,
        issues_limit: int = 50,
        prs_limit: int = 20,
        commits_limit: int = 30,
        max_depth: int = 10,
    ) -> Dict[str, Any]:
        """
        Orquestra o processo completo de ingestão.
        """
        print(f"[IngestService] Iniciando ingestão (User: {user_id}) de: {repo_url}")
        try:
            repo_name = self.github_service.parse_repo_url(repo_url)
            
            # 1. Buscar timestamp da última ingestão
            latest_timestamp = self.metadata_service.get_latest_timestamp(user_id, repo_name)
            
            # 2. Buscar dados do GitHub (arquivos e metadados)
            # A. Arquivos de Código
            files = self.github_service.get_repo_files_batch(repo_url, max_depth)
            
            # B. Metadados (Issues, PRs, Commits) - com 'since'
            metadata = self.github_service.get_repo_data_batch(
                repo_url, issues_limit, prs_limit, commits_limit, since=latest_timestamp
            )
            
            if not files and not metadata["commits"] and not metadata["issues"] and not metadata["prs"]:
                print("[IngestService] Nenhum dado novo encontrado. Ingestão concluída.")
                return {"status": "sucesso", "repo": repo_name, "arquivos": 0, "chunks": 0}

            # 3. Se for incremental, deletar dados antigos
            if latest_timestamp:
                print(f"[IngestService] Ingestão incremental. Deletando dados de metadados antigos...")
                # (Aqui você precisará de uma lógica mais granular, mas por enquanto vamos deletar tudo)
                self.metadata_service.delete_documents_by_repo(user_id, repo_name)
            else:
                 print(f"[IngestService] Ingestão completa. Deletando dados antigos (se existirem)...")
                 self.metadata_service.delete_documents_by_repo(user_id, repo_name)

            # 4. Processar e "chunkear" os arquivos
            all_documents = []
            
            # Processa arquivos de código
            for file_data in files:
                chunks = self.text_splitter.split_text(file_data["content"])
                for chunk in chunks:
                    doc = self._create_document_chunk(
                        user_id=user_id,
                        repo_name=repo_name,
                        file_path=file_data["file_path"],
                        chunk_content=chunk
                    )
                    all_documents.append(doc)
            
            # Processa metadados (Issues, PRs, Commits)
            metadata_docs = self._create_metadata_documents(repo_name, metadata)
            all_documents.extend(metadata_docs)

            # 5. Salvar os chunks em lotes
            total_chunks = len(all_documents)
            print(f"[IngestService] {len(files)} arquivos e {len(metadata_docs)} metadados processados. {total_chunks} chunks gerados.")
            
            batch_size = 50 # Definir um tamanho de lote
            for i in range(0, total_chunks, batch_size):
                batch = all_documents[i : i + batch_size]
                self.metadata_service.save_documents_batch(user_id, batch)
                print(f"[IngestService] Lote {i//batch_size + 1} salvo. ({len(batch)} chunks)")

            print(f"[IngestService] Ingestão (User: {user_id}) de {repo_name} concluída com sucesso.")
            return {
                "status": "sucesso",
                "repo": repo_name,
                "arquivos": len(files),
                "chunks": total_chunks,
            }

        except Exception as e:
            print(f"[IngestService] ERRO (Geral): {e}")
            traceback.print_exc()
            raise

    def _create_document_chunk(
        self, user_id: str, repo_name: str, file_path: str, chunk_content: str
    ) -> Dict[str, Any]:
        """
        Cria a estrutura de dicionário para um chunk de ARQUIVO (sem embedding).
        """
        return {
            "user_id": user_id,
            "repositorio": repo_name,
            "file_path": file_path,
            "conteudo": chunk_content,
            "tipo": "file" # Adiciona o tipo
        }

    def _create_metadata_documents(self, repo_name: str, raw_data: Dict[str, List]) -> List[Dict[str, Any]]:
        """
        Converte os dados brutos de metadados em documentos para salvar.
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

    def save_instruction_document(self, user_id: str, repo_url: str, instrucao_texto: str):
        """
        Cria e salva um documento especial para a instrução de relatório.
        """
        print(f"[IngestService] Criando documento de instrução para {repo_url}...")
        repo_name = self.github_service.parse_repo_url(repo_url)
        
        embedding = self.embedding_service.get_embedding(instrucao_texto)
        
        doc = {
            "user_id": user_id,
            "repositorio": repo_name,
            "instrucao_texto": instrucao_texto,
            "embedding": embedding,
            "tipo": "instruction"
        }
        
        try:
            self.supabase.table("instrucoes").insert(doc).execute()
            print(f"[IngestService] Instrução salva com sucesso para {repo_name}.")
            return {"status": "instrucao_salva", "repo": repo_name}
        except Exception as e:
            print(f"[IngestService] ERRO ao salvar instrução: {e}")
            raise
            
    def handle_webhook(self, event_type: str, payload: dict):
        """
        Processa um webhook do GitHub para ingestão incremental.
        """
        print(f"[IngestService] Processando webhook '{event_type}'...")
        repo_full_name = payload.get("repository", {}).get("full_name")
        if not repo_full_name:
            return {"status": "ignored", "reason": "Nome do repositório não encontrado no payload."}

        # 1. Encontra todos os usuários que rastreiam este repositório
        user_ids = self.metadata_service.get_distinct_users_for_repo(repo_full_name)
        if not user_ids:
            print(f"[IngestService] Webhook ignorado. Nenhum usuário está rastreando {repo_full_name}.")
            return {"status": "ignored", "reason": f"Ninguém rastreia {repo_full_name}"}

        print(f"[IngestService] Webhook relevante. {len(user_ids)} usuários rastreiam {repo_full_name}.")

        # 2. Para cada usuário, busca os dados incrementais
        for user_id in user_ids:
            latest_timestamp = self.metadata_service.get_latest_timestamp(user_id, repo_full_name)
            if not latest_timestamp:
                print(f"[IngestService] AVISO: Usuário {user_id} não tem ingestão prévia. Pulando webhook.")
                continue

            print(f"[IngestService] Processando webhook para User: {user_id}...")
            
            # (Simplificação: Estamos buscando todos os tipos, mesmo que seja só um evento de 'push')
            metadata_novos = self.github_service.get_repo_data_batch(
                repo_full_name,
                issues_limit=20,
                prs_limit=20,
                commits_limit=20,
                since=latest_timestamp
            )
            
            documentos_novos = self._create_metadata_documents(repo_full_name, metadata_novos)
            
            if documentos_novos:
                print(f"[IngestService] {len(documentos_novos)} novos itens de metadados encontrados. Salvando...")
                self.metadata_service.save_documents_batch(user_id, documentos_novos)
            else:
                print(f"[IngestService] Nenhum item novo de metadados encontrado para {user_id}.")

        return {"status": "processed", "event": event_type, "users_notified": len(user_ids)}