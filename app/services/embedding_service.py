import os
import traceback
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from typing import List, Dict, Any, Optional
import time # Usado para logs de tempo
# Comentario
# --- PONTO CRÍTICO ---
# Certifique-se de que o nome do seu índice no Pinecone seja este.
# Se for diferente, mude aqui.
PINECONE_INDEX_NAME = "tcc-rag-index" 
# BUILD V3 - CORRIGINDO BATCHING 

class EmbeddingService:
    """
    Serviço para processamento de embeddings e armazenamento vetorial.
    Utiliza API da OpenAI para vetorização e Pinecone (DaaS) para armazenamento.
    """
    
    def __init__(self, persistence_dir: str = None):
        """
        Inicializa os clientes da OpenAI e Pinecone.
        """
        print("[EmbeddingService] INICIANDO VERSÃO V10 - BATCH CORRIGIDO") # <-- ADICIONE ESTA LINHA
        # 1. (REMOVIDO) Não precisamos mais do diretório do Chroma
        print("[EmbeddingService] Inicializando...")

        # 2. Inicializa o cliente da OpenAI (como antes)
        try:
            self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.embedding_model_api = "text-embedding-3-small"
        except Exception as e:
            print(f"[EmbeddingService] ERRO: Falha ao inicializar cliente OpenAI: {e}")
            self.openai_client = None
            
        # 3. (NOVO) Inicializa o cliente Pinecone
        try:
            api_key = os.getenv("PINECONE_API_KEY")
            env = os.getenv("PINECONE_ENVIRONMENT")
            if not api_key or not env:
                raise ValueError("PINECONE_API_KEY ou PINECONE_ENVIRONMENT não definidos.")
                
            self.pc = Pinecone(api_key=api_key, environment=env)
            
            # Conecta ao índice. 
            # (Você deve tê-lo criado no painel do Pinecone com 1536 dimensões)
            self.index = self.pc.Index(PINECONE_INDEX_NAME)
            print(f"[EmbeddingService] Conectado ao índice Pinecone '{PINECONE_INDEX_NAME}'.")
            
        except Exception as e:
            print(f"[EmbeddingService] ERRO: Falha ao conectar com Pinecone: {e}")
            self.pc = None
            self.index = None

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        (FUNÇÃO OTIMIZADA COM BATCHING - V9 DEBUG) Gera embeddings usando a API da OpenAI em lotes.
        """
        if not self.openai_client:
            raise ValueError("Cliente OpenAI não inicializado.")

        BATCH_SIZE = 10  
        all_embeddings = []
        
        print(f"[EmbeddingService] Iniciando geração de embeddings em {len(texts)} textos (lotes de {BATCH_SIZE})...")
        
        start_time = time.time()
        
        try:
            for i in range(0, len(texts), BATCH_SIZE):
                batch_texts = texts[i:i + BATCH_SIZE]
                
                print(f"[EmbeddingService] Processando lote {i//BATCH_SIZE + 1} de { (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE } ({len(batch_texts)} documentos)...")
                
                # --- O DEBUG DEFINITIVO ESTÁ AQUI ---
                # Vamos provar qual variável está sendo usada.
                
                input_data_to_send = batch_texts  # <--- Definimos a variável correta
                
                print(f"[EmbeddingService-DEBUG] Enviando {len(input_data_to_send)} textos para a OpenAI.")

                response = self.openai_client.embeddings.create(
                    model=self.embedding_model_api,
                    input=input_data_to_send  # <-- Usamos a variável de debug
                )
                # --- FIM DO DEBUG ---
                
                all_embeddings.extend([embedding.embedding for embedding in response.data])

            total_time = time.time() - start_time
            print(f"[EmbeddingService] Todos os embeddings gerados pela OpenAI em {total_time:.2f}s")
            return all_embeddings
            
        except Exception as e:
            print(f"[EmbeddingService] Erro ao chamar API de Embeddings da OpenAI (no lote {i//BATCH_SIZE + 1}): {e}")
            raise
    
    def add_documents(self, documents: List[Dict[str, Any]], embeddings: List[List[float]]):
        """
        (MODIFICADO V2) Adiciona documentos e seus embeddings pré-calculados ao Pinecone
        em LOTES (Batches) para evitar o limite de tamanho da requisição (2MB).
        """
        if not self.index:
            raise ValueError("Cliente Pinecone não inicializado.")

        start_time = time.time()
        
        # --- INÍCIO DA CORREÇÃO ---
        # Define um tamanho de lote seguro para o Pinecone
        PINECONE_BATCH_SIZE = 100
        # --- FIM DA CORREÇÃO ---
        
        # 1. Formata todos os vetores primeiro (como antes)
        vectors_to_upsert = []
        for doc, embedding in zip(documents, embeddings):
            # Copia os metadados e ADICIONA o texto neles
            doc_metadata = doc.get("metadata", {}).copy()
            doc_metadata["text"] = doc.get("text", "") # Salva o texto nos metadados
            
            vectors_to_upsert.append({
                "id": str(doc["id"]), 
                "values": embedding, 
                "metadata": doc_metadata
            })
        
        # 2. (NOVO) Envia os vetores para o Pinecone em lotes
        print(f"[EmbeddingService] {len(vectors_to_upsert)} vetores para salvar. Enviando em lotes de {PINECONE_BATCH_SIZE}...")
        
        try:
            # Itera sobre a lista 'vectors_to_upsert' em "pedaços" (chunks)
            for i in range(0, len(vectors_to_upsert), PINECONE_BATCH_SIZE):
                
                # Pega o lote atual (ex: 0 a 100, 100 a 200, ...)
                batch_vectors = vectors_to_upsert[i:i + PINECONE_BATCH_SIZE]
                
                print(f"[EmbeddingService] Enviando lote {i//PINECONE_BATCH_SIZE + 1} de {(len(vectors_to_upsert) + PINECONE_BATCH_SIZE - 1) // PINECONE_BATCH_SIZE}...")
                
                # A chamada de 'upsert' agora está DENTRO do loop
                self.index.upsert(vectors=batch_vectors)

            print(f"[EmbeddingService] Vetores salvos no Pinecone em {time.time() - start_time:.2f}s")
        
        except Exception as e:
            # Se der erro, saberemos qual lote falhou
            print(f"Erro ao salvar vetores no Pinecone (no lote {i//PINECONE_BATCH_SIZE + 1}): {e}")
            raise

    def query_collection(self, query_text: str, n_results: int = 5, repo_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Consulta o índice Pinecone.
        
        [CORREÇÃO]: Adicionado 'repo_name' para filtrar a consulta
        e evitar vazamento de contexto.
        """
        try:
            # 1. Criar o embedding da consulta
            query_embedding = self.generate_embeddings([query_text])[0]

            # --- INÍCIO DA CORREÇÃO ---
            
            # 2. Criar o dicionário de filtro (metadata filter)
            query_filter = {}
            if repo_name:
                query_filter = {"repo_name": {"$eq": repo_name}}
                print(f"[EmbeddingService] Aplicando filtro de consulta para repo_name: {repo_name}")
            else:
                print("[EmbeddingService] ATENÇÃO: Consultando sem filtro de repositório.")

            # 3. Consultar o Pinecone (AGORA COM FILTRO)
            results = self.index.query(
                vector=query_embedding,
                top_k=n_results,
                include_metadata=True,
                filter=query_filter # <-- FILTRO APLICADO AQUI
            )
            # --- FIM DA CORREÇÃO ---
            
            return results
        
        except Exception as e:
            print(f"Erro ao consultar o Pinecone: {e}")
            traceback.print_exc()
            return {"matches": []}
    
    def process_github_data(self, repo_name: str, issues: List[Dict], prs: List[Dict], commits: List[Dict]):
        """
        (FUNÇÃO ATUALIZADA COM CHUNKING) 
        Processa dados do GitHub e armazena no Pinecone.
        Divide documentos grandes (issues/PRs) em múltiplos "chunks" 
        para garantir que nenhuma informação seja perdida (evita o truncamento).
        """
        
        # --- INÍCIO DA CORREÇÃO ---
        # Limite de caracteres por "chunk" (pedaço)
        # (Isso é baseado no limite de tokens do modelo de embedding)
        MAX_TEXT_LENGTH = 7000
        # --- FIM DA CORREÇÃO ---

        collection_name = f"github_{repo_name.replace('/', '_')}"
        
        # --- 1. Preparar Documentos (COM LÓGICA DE CHUNKING) ---
        
        issue_documents = []
        for issue in issues:
            body = (issue['body'] or "")
            
            # --- INÍCIO DA LÓGICA DE CHUNKING (ISSUES) ---
            if len(body) <= MAX_TEXT_LENGTH:
                # 1. Documento é pequeno: Salva como um único chunk (pedaço)
                issue_documents.append({
                    "id": f"issue_{issue['id']}_chunk_0", # ID de chunk único
                    "text": f"Issue #{issue['id']}: {issue['title']}\n\n{body}",
                    "metadata": { 
                        "repo_name": repo_name, 
                        "type": "issue", "id": issue["id"], "title": issue["title"], 
                        "state": issue["state"], "url": issue["url"], "created_at": issue["created_at"], 
                        "labels": ",".join(issue.get("labels", [])),
                        "chunk_num": 0, # Metadado para o chunk
                        "total_chunks": 1
                    }
                })
            else:
                # 2. Documento é grande: Divide o 'body' em múltiplos chunks
                body_chunks = [body[i:i + MAX_TEXT_LENGTH] for i in range(0, len(body), MAX_TEXT_LENGTH)]
                total_chunks = len(body_chunks)
                
                for i, chunk_text in enumerate(body_chunks):
                    # Cria um documento separado no Pinecone para CADA chunk
                    issue_documents.append({
                        "id": f"issue_{issue['id']}_chunk_{i}", # ID de chunk único
                        "text": f"Issue #{issue['id']}: {issue['title']} (Parte {i+1}/{total_chunks})\n\n{chunk_text}", # Adiciona contexto de "Parte X de Y"
                        "metadata": { 
                            "repo_name": repo_name, 
                            "type": "issue", "id": issue["id"], "title": issue["title"], 
                            "state": issue["state"], "url": issue["url"], "created_at": issue["created_at"], 
                            "labels": ",".join(issue.get("labels", [])),
                            "chunk_num": i, # Metadado para o chunk
                            "total_chunks": total_chunks
                        }
                    })
            # --- FIM DA LÓGICA DE CHUNKING (ISSUES) ---
            
        pr_documents = []
        for pr in prs:
            body = (pr['body'] or "")

            # --- INÍCIO DA LÓGICA DE CHUNKING (PRS) ---
            if len(body) <= MAX_TEXT_LENGTH:
                # 1. Documento é pequeno
                pr_documents.append({
                    "id": f"pr_{pr['id']}_chunk_0",
                    "text": f"Pull Request #{pr['id']}: {pr['title']}\n\n{body}",
                    "metadata": { 
                        "repo_name": repo_name, 
                        "type": "pull_request", "id": pr["id"], "title": pr["title"], 
                        "state": pr["state"], "url": pr["url"], "created_at": pr["created_at"], 
                        "merged": pr.get("merged", False),
                        "chunk_num": 0,
                        "total_chunks": 1
                    }
                })
            else:
                # 2. Documento é grande: Divide o 'body' em múltiplos chunks
                body_chunks = [body[i:i + MAX_TEXT_LENGTH] for i in range(0, len(body), MAX_TEXT_LENGTH)]
                total_chunks = len(body_chunks)

                for i, chunk_text in enumerate(body_chunks):
                    pr_documents.append({
                        "id": f"pr_{pr['id']}_chunk_{i}",
                        "text": f"Pull Request #{pr['id']}: {pr['title']} (Parte {i+1}/{total_chunks})\n\n{chunk_text}",
                        "metadata": { 
                            "repo_name": repo_name, 
                            "type": "pull_request", "id": pr["id"], "title": pr["title"], 
                            "state": pr["state"], "url": pr["url"], "created_at": pr["created_at"], 
                            "merged": pr.get("merged", False),
                            "chunk_num": i,
                            "total_chunks": total_chunks
                        }
                    })
            # --- FIM DA LÓGICA DE CHUNKING (PRS) ---
            
        commit_documents = []
        for commit in commits:
            # Commits são pequenos, o truncamento de segurança é aceitável
            # Mas adicionamos metadados de chunk para consistência
            message = (commit['message'] or "")[:MAX_TEXT_LENGTH]
            
            commit_documents.append({
                "id": f"commit_{commit['sha']}",
                "text": f"Commit {commit['sha'][:7]}: {message}",
                "metadata": { 
                    "repo_name": repo_name, 
                    "type": "commit", "sha": commit["sha"], "author": commit["author"], 
                    "date": commit["date"], "url": commit["url"],
                    "chunk_num": 0,
                    "total_chunks": 1
                }
            })
        
        all_documents = issue_documents + pr_documents + commit_documents
        
        if not all_documents:
            print("[EmbeddingService] Nenhum documento para processar.")
            return { "documents_count": 0, "issues_count": 0, "prs_count": 0, "commits_count": 0 }

        print(f"[EmbeddingService] {len(all_documents)} documentos (chunks) formatados. Gerando embeddings via API...")

        # --- 2. Gerar Embeddings (RÁPIDO) ---
        texts_to_embed = [doc["text"] for doc in all_documents]
        
        embeddings_list = self.generate_embeddings(texts_to_embed)
        
        print(f"[EmbeddingService] Embeddings recebidos. Salvando no Pinecone...")

        # --- 3. Salvar no Pinecone (RÁPIDO) ---
        # (Esta função já está com o batching de 100 que fizemos)
        self.add_documents(
            documents=all_documents,
            embeddings=embeddings_list
        )
            
        # --- 4. CORREÇÃO DO KEYERROR (que vimos antes) ---
        return {
            "documents_count": len(all_documents),
            "issues_count": len(issue_documents), # Agora conta "chunks" de issues
            "prs_count": len(pr_documents),       # Agora conta "chunks" de PRs
            "commits_count": len(commit_documents)
        }