import os
from openai import OpenAI  # Importa o cliente da OpenAI
import chromadb
from typing import List, Dict, Any, Optional

class EmbeddingService:
    """
    Serviço para processamento de embeddings e armazenamento vetorial.
    Utiliza a API da OpenAI para vetorização (rápido) e ChromaDB para armazenamento.
    """
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", persistence_dir: str = None):
        """
        Inicializa o serviço de embeddings.
        
        Args:
            model_name: (Não mais usado para o modelo local, mas mantido por consistência)
            persistence_dir: Diretório para persistência do ChromaDB
        """
        
        # 1. Configura o diretório de persistência do Chroma (seu código original está correto)
        raw_path = persistence_dir or os.getenv("CHROMA_PERSISTENCE_DIRECTORY", "./chroma_db")
        self.persistence_dir = os.path.abspath(raw_path)
        os.makedirs(self.persistence_dir, exist_ok=True)
        print(f"[EmbeddingService] Diretório de persistência configurado em: {self.persistence_dir}")

        # 2. (REMOVIDO) Não precisamos mais do modelo local de SentenceTransformer
        # self.model = SentenceTransformer(model_name)
        
        # 3. (NOVO) Inicializa o cliente da OpenAI
        # Ele vai ler a chave 'OPENAI_API_KEY' que já configuramos no Heroku
        try:
            self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        except Exception as e:
            print(f"[EmbeddingService] ERRO: Falha ao inicializar cliente OpenAI. Verifique a OPENAI_API_KEY. Erro: {e}")
            self.openai_client = None
            
        # Usamos o modelo de embedding mais novo, rápido e barato da OpenAI
        self.embedding_model_api = "text-embedding-3-small"

        # 4. Inicializar ChromaDB (como antes)
        self.client = chromadb.PersistentClient(path=self.persistence_dir)
    
    def get_or_create_collection(self, collection_name: str):
        """ Obtém ou cria uma coleção no ChromaDB. """
        try:
            return self.client.get_collection(collection_name)
        except Exception:
            return self.client.create_collection(collection_name)
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        (FUNÇÃO OTIMIZADA) Gera embeddings usando a API da OpenAI.
        """
        if not self.openai_client:
            raise ValueError("Cliente OpenAI não inicializado.")
            
        try:
            response = self.openai_client.embeddings.create(
                model=self.embedding_model_api,
                input=texts
            )
            # Extrai os vetores da resposta da API
            return [embedding.embedding for embedding in response.data]
        except Exception as e:
            print(f"Erro ao chamar API de Embeddings da OpenAI: {e}")
            raise
    
    def add_documents(self, collection_name: str, documents: List[Dict[str, Any]], embeddings: List[List[float]]):
        """
        Adiciona documentos E seus embeddings pré-calculados a uma coleção.
        """
        collection = self.get_or_create_collection(collection_name)
        
        ids = [str(doc["id"]) for doc in documents]
        texts = [doc["text"] for doc in documents]
        metadatas = [doc.get("metadata", {}) for doc in documents]
        
        # Adiciona tudo, incluindo os embeddings que já geramos via API
        collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings  # A grande mudança está aqui!
        )
    
    def query_collection(self, collection_name: str, query_text: str, n_results: int = 5) -> Dict[str, Any]:
        """
        Consulta uma coleção do ChromaDB.
        (Esta função não muda, mas agora ela vai consultar usando os embeddings da OpenAI)
        """
        collection = self.get_or_create_collection(collection_name)
        
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        
        return results
    
    def delete_collection(self, collection_name: str):
        """ Exclui uma coleção do ChromaDB. """
        self.client.delete_collection(collection_name)
    
    def process_github_data(self, repo_name: str, issues: List[Dict], prs: List[Dict], commits: List[Dict]):
        """
        (FUNÇÃO OTIMIZADA) Processa dados do GitHub e armazena no ChromaDB.
        """
        collection_name = f"github_{repo_name.replace('/', '_')}"
        
        # --- 1. Preparar Documentos (Igual antes) ---
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
            return { "collection_name": collection_name, "documents_count": 0, "issues_count": 0, "prs_count": 0, "commits_count": 0 }

        print(f"[EmbeddingService] {len(all_documents)} documentos formatados. Gerando embeddings via API...")

        # --- 2. Gerar Embeddings (RÁPIDO) ---
        # Pega todos os textos para enviar para a API de uma vez
        texts_to_embed = [doc["text"] for doc in all_documents]
        
        # Chama a API da OpenAI (rápido!)
        embeddings_list = self.generate_embeddings(texts_to_embed)
        
        print(f"[EmbeddingService] Embeddings recebidos da API. Salvando no ChromaDB...")

        # --- 3. Salvar no ChromaDB (RÁPIDO) ---
        # Passa os documentos e os embeddings pré-calculados
        self.add_documents(
            collection_name=collection_name,
            documents=all_documents,
            embeddings=embeddings_list
        )
            
        return {
            "collection_name": collection_name,
            "documents_count": len(all_documents),
            "issues_count": len(issue_documents),
            "prs_count": len(pr_documents),
            "commits_count": len(commit_documents)
        }