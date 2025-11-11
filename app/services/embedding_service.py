import os
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
        print("[EmbeddingService] INICIANDO VERSÃO V6 - BATCH CORRIGIDO") # <-- ADICIONE ESTA LINHA
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
        (FUNÇÃO OTIMIZADA COM BATCHING) Gera embeddings usando a API da OpenAI em lotes.
        """
        if not self.openai_client:
            raise ValueError("Cliente OpenAI não inicializado.")

        # Define um tamanho de lote (batch size) seguro para não estourar o limite de tokens
        BATCH_SIZE = 20  
        all_embeddings = []
        
        print(f"[EmbeddingService] Iniciando geração de embeddings em {len(texts)} textos (lotes de {BATCH_SIZE})...")
        
        start_time = time.time()
        
        try:
            # Loop que "fatia" a lista de textos em pedaços de BATCH_SIZE
            for i in range(0, len(texts), BATCH_SIZE):
                batch_texts = texts[i:i + BATCH_SIZE]
                
                print(f"[EmbeddingService] Processando lote {i//BATCH_SIZE + 1} ({len(batch_texts)} documentos)...")
                
                # Chama a API da OpenAI para o lote atual
                response = self.openai_client.embeddings.create(
                    model=self.embedding_model_api,
                    input=batch_texts
                )
                
                # Adiciona os vetores resultantes à nossa lista principal
                all_embeddings.extend([embedding.embedding for embedding in response.data])
                
                # (Pequena pausa opcional para não sobrecarregar a API, mas geralmente não é necessário)
                # time.sleep(0.1) 

            total_time = time.time() - start_time
            print(f"[EmbeddingService] Todos os embeddings gerados pela OpenAI em {total_time:.2f}s")
            return all_embeddings
            
        except Exception as e:
            print(f"Erro ao chamar API de Embeddings da OpenAI (no lote {i//BATCH_SIZE + 1}): {e}")
            raise
    
    def add_documents(self, documents: List[Dict[str, Any]], embeddings: List[List[float]]):
        """
        (MODIFICADO) Adiciona documentos e seus embeddings pré-calculados ao Pinecone.
        """
        if not self.index:
            raise ValueError("Cliente Pinecone não inicializado.")

        start_time = time.time()
        
        # O Pinecone precisa que os vetores e metadados sejam formatados
        # NOTA: O Pinecone não armazena o "documento" de texto em si, 
        # apenas os metadados. Vamos salvar o texto nos metadados.
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
        
        # Envia os vetores para o Pinecone (operação de rede rápida)
        try:
            self.index.upsert(vectors=vectors_to_upsert)
            print(f"[EmbeddingService] Vetores salvos no Pinecone em {time.time() - start_time:.2f}s")
        except Exception as e:
            print(f"Erro ao salvar vetores no Pinecone: {e}")
            raise

    def query_collection(self, query_text: str, n_results: int = 5) -> Dict[str, Any]:
        """
        (MODIFICADO) Consulta o índice do Pinecone.
        """
        if not self.index or not self.openai_client:
            raise ValueError("Clientes não inicializados.")

        # 1. Gera o embedding (vetor) para a pergunta do usuário
        query_embedding = self.generate_embeddings([query_text])[0]
        
        # 2. Faz a busca no Pinecone
        results = self.index.query(
            vector=query_embedding,
            top_k=n_results,
            include_metadata=True
        )
        
        # Retorna o resultado bruto do Pinecone
        return results
    
    def process_github_data(self, repo_name: str, issues: List[Dict], prs: List[Dict], commits: List[Dict]):
        """
        (MODIFICADO) Orquestra a ingestão.
        """
        
        # --- 1. Preparar Documentos (Igual antes) ---
        # (Seu código de formatar issues/prs/commits estava aqui e continua o mesmo)
        issue_documents = []
        for issue in issues:
            issue_documents.append({
                "id": f"issue_{issue['id']}",
                "text": f"Issue #{issue['id']}: {issue['title']}\n\n{issue['body']}",
                "metadata": { "type": "issue", "id": issue["id"], "title": issue["title"], "state": issue["state"], "url": issue["url"], "created_at": issue["created_at"], "labels": ",".join(issue.get("labels", [])) }
            })
            
        pr_documents = []
        for pr in prs:
            pr_documents.append({
                "id": f"pr_{pr['id']}",
                "text": f"Pull Request #{pr['id']}: {pr['title']}\n\n{pr['body']}",
                "metadata": { "type": "pull_request", "id": pr["id"], "title": pr["title"], "state": pr["state"], "url": pr["url"], "created_at": pr["created_at"], "merged": pr.get("merged", False) }
            })
            
        commit_documents = []
        for commit in commits:
            commit_documents.append({
                "id": f"commit_{commit['sha']}",
                "text": f"Commit {commit['sha'][:7]}: {commit['message']}",
                "metadata": { "type": "commit", "sha": commit["sha"], "author": commit["author"], "date": commit["date"], "url": commit["url"] }
            })
        
        all_documents = issue_documents + pr_documents + commit_documents
        
        if not all_documents:
            print("[EmbeddingService] Nenhum documento para processar.")
            return { "documents_count": 0, "issues_count": 0, "prs_count": 0, "commits_count": 0 }

        print(f"[EmbeddingService] {len(all_documents)} documentos formatados. Gerando embeddings via API...")

        # --- 2. Gerar Embeddings (Rápido, 2s) ---
        texts_to_embed = [doc["text"] for doc in all_documents]
        embeddings_list = self.generate_embeddings(texts_to_embed)
        
        print(f"[EmbeddingService] Embeddings recebidos. Salvando no Pinecone...")

        # --- 3. Salvar no Pinecone (Rápido, 2s) ---
        self.add_documents(
            documents=all_documents,
            embeddings=embeddings_list
        )
            
        return {
            "documents_count": len(all_documents),
            "issues_count": len(issue_documents),
            "prs_count": len(pr_documents),
            "commits_count": len(commit_documents)
        }