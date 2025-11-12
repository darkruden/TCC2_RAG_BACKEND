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

    def query_collection(self, query_text: str, n_results: int = 5, repo_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Consulta o índice Pinecone.
        
        [CORREÇÃO]: Adicionado 'repo_name' para filtrar a consulta
        e evitar vazamento de contexto.
        """
        try:
            # 1. Criar o embedding da consulta
            query_embedding = self.create_embeddings([query_text])[0]

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
        (FUNÇÃO OTIMIZADA COM TRUNCAMENTO) Processa dados do GitHub e armazena no Pinecone.
        """
        
        # --- INÍCIO DA CORREÇÃO ---
        # Define um limite MÁXIMO de caracteres por documento.
        # 8192 tokens é o limite da API. 7000 caracteres é uma
        # margem de segurança excelente (aprox. 1 char = 1 token, mas varia)
        MAX_TEXT_LENGTH = 7000
        # --- FIM DA CORREÇÃO ---

        collection_name = f"github_{repo_name.replace('/', '_')}"
        
        # --- 1. Preparar Documentos (COM TRUNCAMENTO) ---
        issue_documents = []
        for issue in issues:
            # Pega o corpo da issue e TRUNCA em MAX_TEXT_LENGTH
            body = (issue['body'] or "")[:MAX_TEXT_LENGTH] 
            
            issue_documents.append({
                "id": f"issue_{issue['id']}",
                "text": f"Issue #{issue['id']}: {issue['title']}\n\n{body}", # Usa o corpo truncado
                "metadata": { "repo_name": repo_name, "type": "issue", "id": issue["id"], "title": issue["title"], "state": issue["state"], "url": issue["url"], "created_at": issue["created_at"], "labels": ",".join(issue.get("labels", [])) }
            })
            
        pr_documents = []
        for pr in prs:
            # Pega o corpo do PR e TRUNCA em MAX_TEXT_LENGTH
            body = (pr['body'] or "")[:MAX_TEXT_LENGTH]
            
            pr_documents.append({
                "id": f"pr_{pr['id']}",
                "text": f"Pull Request #{pr['id']}: {pr['title']}\n\n{body}", # Usa o corpo truncado
                "metadata": { "repo_name": repo_name, "type": "pull_request", "id": pr["id"], "title": pr["title"], "state": pr["state"], "url": pr["url"], "created_at": pr["created_at"], "merged": pr.get("merged", False) }
            })
            
        commit_documents = []
        for commit in commits:
            # Commits são pequenos, mas vamos truncar por segurança
            message = (commit['message'] or "")[:MAX_TEXT_LENGTH]
            
            commit_documents.append({
                "id": f"commit_{commit['sha']}",
                "text": f"Commit {commit['sha'][:7]}: {message}", # Usa a mensagem truncada
                "metadata": { "repo_name": repo_name, "type": "commit", "sha": commit["sha"], "author": commit["author"], "date": commit["date"], "url": commit["url"] }
            })
        
        all_documents = issue_documents + pr_documents + commit_documents
        
        if not all_documents:
            print("[EmbeddingService] Nenhum documento para processar.")
            return { "documents_count": 0, "issues_count": 0, "prs_count": 0, "commits_count": 0 }

        print(f"[EmbeddingService] {len(all_documents)} documentos formatados. Gerando embeddings via API...")

        # --- 2. Gerar Embeddings (RÁPIDO) ---
        texts_to_embed = [doc["text"] for doc in all_documents]
        
        # O generate_embeddings já está com o BATCH_SIZE=10 e o input=batch_texts
        # (Se você quiser, pode remover os prints de DEBUG 'V9' e 'DEBUG' agora)
        embeddings_list = self.generate_embeddings(texts_to_embed)
        
        print(f"[EmbeddingService] Embeddings recebidos. Salvando no Pinecone...")

        # --- 3. Salvar no Pinecone (RÁPIDO) ---
        self.add_documents(
            documents=all_documents,
            embeddings=embeddings_list
        )
            
        # --- 4. CORREÇÃO DO KEYERROR (que vimos antes) ---
        # Retorna o dicionário sem o 'collection_name'
        return {
            "documents_count": len(all_documents),
            "issues_count": len(issue_documents),
            "prs_count": len(pr_documents),
            "commits_count": len(commit_documents)
        }