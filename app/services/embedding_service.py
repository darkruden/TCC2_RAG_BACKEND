# CÓDIGO COMPLETO PARA: app/services/embedding_service.py
# (Note as adições de 'chunking', 'batching' e a chamada ao MetadataService)

import os
import traceback
from openai import OpenAI
from pinecone import Pinecone
from typing import List, Dict, Any, Optional
import time
from .metadata_service import MetadataService # <-- 1. IMPORTAR O NOVO SERVIÇO

PINECONE_INDEX_NAME = "tcc-rag-index" 

class EmbeddingService:
    
    def __init__(self, persistence_dir: str = None):
        print("[EmbeddingService] INICIANDO VERSÃO HÍBRIDA (V12)")
        
        try:
            self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.embedding_model_api = "text-embedding-3-small"
        except Exception as e:
            self.openai_client = None
            print(f"[EmbeddingService] ERRO: Falha ao inicializar cliente OpenAI: {e}")
            
        try:
            api_key = os.getenv("PINECONE_API_KEY")
            env = os.getenv("PINECONE_ENVIRONMENT")
            if not api_key or not env:
                raise ValueError("PINECONE_API_KEY ou PINECONE_ENVIRONMENT não definidos.")
            self.pc = Pinecone(api_key=api_key, environment=env)
            self.index = self.pc.Index(PINECONE_INDEX_NAME)
            print(f"[EmbeddingService] Conectado ao índice Pinecone '{PINECONE_INDEX_NAME}'.")
        except Exception as e:
            self.pc = None
            self.index = None
            print(f"[EmbeddingService] ERRO: Falha ao conectar com Pinecone: {e}")

        # <-- 2. INICIALIZAR O NOVO SERVIÇO
        self.metadata_service = MetadataService()

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not self.openai_client:
            raise ValueError("Cliente OpenAI não inicializado.")
        BATCH_SIZE = 10  
        all_embeddings = []
        print(f"[EmbeddingService] Iniciando geração de embeddings em {len(texts)} textos (lotes de {BATCH_SIZE})...")
        start_time = time.time()
        try:
            for i in range(0, len(texts), BATCH_SIZE):
                batch_texts = texts[i:i + BATCH_SIZE]
                print(f"[EmbeddingService] Processando lote OpenAI {i//BATCH_SIZE + 1}...")
                response = self.openai_client.embeddings.create(
                    model=self.embedding_model_api,
                    input=batch_texts
                )
                all_embeddings.extend([embedding.embedding for embedding in response.data])
            total_time = time.time() - start_time
            print(f"[EmbeddingService] Todos os embeddings gerados pela OpenAI em {total_time:.2f}s")
            return all_embeddings
        except Exception as e:
            print(f"[EmbeddingService] Erro ao chamar API de Embeddings da OpenAI: {e}")
            raise

    def add_documents_to_pinecone(self, documents: List[Dict[str, Any]], embeddings: List[List[float]]):
        """(Refatorado) Adiciona documentos ao Pinecone em lotes."""
        if not self.index:
            raise ValueError("Cliente Pinecone não inicializado.")

        PINECONE_BATCH_SIZE = 100
        start_time = time.time()
        
        vectors_to_upsert = []
        for doc, embedding in zip(documents, embeddings):
            doc_metadata = doc.get("metadata", {}).copy()
            doc_metadata["text"] = doc.get("text", "")
            vectors_to_upsert.append({
                "id": str(doc["id"]), 
                "values": embedding, 
                "metadata": doc_metadata
            })
        
        print(f"[EmbeddingService] {len(vectors_to_upsert)} vetores para salvar no Pinecone. Enviando em lotes de {PINECONE_BATCH_SIZE}...")
        try:
            for i in range(0, len(vectors_to_upsert), PINECONE_BATCH_SIZE):
                batch_vectors = vectors_to_upsert[i:i + PINECONE_BATCH_SIZE]
                print(f"[EmbeddingService] Enviando lote Pinecone {i//PINECONE_BATCH_SIZE + 1}...")
                self.index.upsert(vectors=batch_vectors)
            print(f"[EmbeddingService] Vetores salvos no Pinecone em {time.time() - start_time:.2f}s")
        except Exception as e:
            print(f"Erro ao salvar vetores no Pinecone (no lote {i//PINECONE_BATCH_SIZE + 1}): {e}")
            raise

    def query_collection_pinecone(self, query_text: str, n_results: int = 5, repo_name: Optional[str] = None) -> Dict[str, Any]:
        """(Refatorado) Consulta apenas o Pinecone (busca semântica)."""
        if not self.index:
             print("[EmbeddingService] Cliente Pinecone não inicializado para consulta.")
             return {"matches": []}
        try:
            query_embedding = self.generate_embeddings([query_text])[0]
            query_filter = {}
            if repo_name:
                query_filter = {"repo_name": {"$eq": repo_name}}
            
            results = self.index.query(
                vector=query_embedding,
                top_k=n_results,
                include_metadata=True,
                filter=query_filter
            )
            return results
        except Exception as e:
            print(f"Erro ao consultar o Pinecone: {e}")
            traceback.print_exc()
            return {"matches": []}

    def process_github_data(self, repo_name: str, issues: List[Dict], prs: List[Dict], commits: List[Dict]):
        """
        (ATUALIZADO) Processa dados, divide em chunks e salva em AMBOS os bancos.
        """
        MAX_TEXT_LENGTH = 7000
        all_documents = [] # Lista de chunks

        # --- Lógica de Chunking (Issues) ---
        for issue in issues:
            body = (issue['body'] or "")
            base_metadata = {
                "repo_name": repo_name, "type": "issue", "id": issue["id"], "title": issue["title"], 
                "state": issue["state"], "url": issue["url"], "created_at": issue["created_at"], 
                "labels": ",".join(issue.get("labels", []))
            }
            if len(body) <= MAX_TEXT_LENGTH:
                all_documents.append({
                    "id": f"issue_{issue['id']}_chunk_0",
                    "text": f"Issue #{issue['id']}: {issue['title']}\n\n{body}",
                    "metadata": {**base_metadata, "chunk_num": 0, "total_chunks": 1}
                })
            else:
                body_chunks = [body[i:i + MAX_TEXT_LENGTH] for i in range(0, len(body), MAX_TEXT_LENGTH)]
                total_chunks = len(body_chunks)
                for i, chunk_text in enumerate(body_chunks):
                    all_documents.append({
                        "id": f"issue_{issue['id']}_chunk_{i}",
                        "text": f"Issue #{issue['id']}: {issue['title']} (Parte {i+1}/{total_chunks})\n\n{chunk_text}",
                        "metadata": {**base_metadata, "chunk_num": i, "total_chunks": total_chunks}
                    })

        # --- Lógica de Chunking (PRs) ---
        for pr in prs:
            body = (pr['body'] or "")
            base_metadata = {
                "repo_name": repo_name, "type": "pull_request", "id": pr["id"], "title": pr["title"], 
                "state": pr["state"], "url": pr["url"], "created_at": pr["created_at"], 
                "merged": pr.get("merged", False)
            }
            if len(body) <= MAX_TEXT_LENGTH:
                all_documents.append({
                    "id": f"pr_{pr['id']}_chunk_0",
                    "text": f"Pull Request #{pr['id']}: {pr['title']}\n\n{body}",
                    "metadata": {**base_metadata, "chunk_num": 0, "total_chunks": 1}
                })
            else:
                body_chunks = [body[i:i + MAX_TEXT_LENGTH] for i in range(0, len(body), MAX_TEXT_LENGTH)]
                total_chunks = len(body_chunks)
                for i, chunk_text in enumerate(body_chunks):
                    all_documents.append({
                        "id": f"pr_{pr['id']}_chunk_{i}",
                        "text": f"Pull Request #{pr['id']}: {pr['title']} (Parte {i+1}/{total_chunks})\n\n{chunk_text}",
                        "metadata": {**base_metadata, "chunk_num": i, "total_chunks": total_chunks}
                    })

        # --- Lógica de Chunking (Commits) ---
        for commit in commits:
            message = (commit['message'] or "")[:MAX_TEXT_LENGTH]
            all_documents.append({
                "id": f"commit_{commit['sha']}",
                "text": f"Commit {commit['sha'][:7]}: {message}",
                "metadata": {
                    "repo_name": repo_name, "type": "commit", "sha": commit["sha"], "id": commit["sha"], 
                    "author": commit["author"], "date": commit["date"], "url": commit["url"], 
                    "created_at": commit["date"], # SQL usará 'created_at' para tudo
                    "chunk_num": 0, "total_chunks": 1
                }
            })
        
        if not all_documents:
            print("[EmbeddingService] Nenhum documento para processar.")
            return { "documents_count": 0 }

        print(f"[EmbeddingService] {len(all_documents)} documentos (chunks) formatados.")

        # --- 1. Gerar Embeddings (só para o Pinecone) ---
        print("Gerando embeddings via API...")
        texts_to_embed = [doc["text"] for doc in all_documents]
        embeddings_list = self.generate_embeddings(texts_to_embed)
        
        # --- 2. Salvar no Pinecone (VETORES) ---
        print("Salvando no Pinecone...")
        self.add_documents_to_pinecone(
            documents=all_documents,
            embeddings=embeddings_list
        )
            
        # --- 3. SALVAR NO SQL (METADADOS) ---
        print("Salvando metadados no SQL DB...")
        self.metadata_service.add_documents(all_documents)
        
        print("[EmbeddingService] Ingestão dupla concluída.")
        return {
            "documents_count": len(all_documents)
        }