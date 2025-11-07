import os
from sentence_transformers import SentenceTransformer
import chromadb
from typing import List, Dict, Any, Optional

class EmbeddingService:
    """
    Serviço para processamento de embeddings e armazenamento vetorial.
    Utiliza sentence-transformers para vetorização e ChromaDB para armazenamento.
    """
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", persistence_dir: str = None):
        """
        Inicializa o serviço de embeddings.
        
        Args:
            model_name: Nome do modelo sentence-transformers a ser utilizado
            persistence_dir: Diretório para persistência do ChromaDB
        """
        self.model_name = model_name
        
        # --- INÍCIO DA CORREÇÃO ---
        # 1. Pega o caminho relativo do .env ou o padrão
        raw_path = persistence_dir or os.getenv("CHROMA_PERSISTENCE_DIRECTORY", "./chroma_db")
        
        # 2. Converte para um caminho absoluto
        self.persistence_dir = os.path.abspath(raw_path)
        
        # 3. Garante que o diretório exista (CRUCIAL!)
        os.makedirs(self.persistence_dir, exist_ok=True)
        
        print(f"[EmbeddingService] Diretório de persistência configurado em: {self.persistence_dir}")
        # --- FIM DA CORREÇÃO ---

        # Inicializar modelo de embeddings
        self.model = SentenceTransformer(self.model_name) # Corrigi para usar self.model_name
        
        # Inicializar ChromaDB
        self.client = chromadb.PersistentClient(path=self.persistence_dir)
        """
        Inicializa o serviço de embeddings.
        
        Args:
            model_name: Nome do modelo sentence-transformers a ser utilizado
            persistence_dir: Diretório para persistência do ChromaDB
        """
        self.model_name = model_name
        self.persistence_dir = persistence_dir or os.getenv("CHROMA_PERSISTENCE_DIRECTORY", "./chroma_db")
        
        # Inicializar modelo de embeddings
        self.model = SentenceTransformer(model_name)
        
        # Inicializar ChromaDB
        self.client = chromadb.PersistentClient(path=self.persistence_dir)
    
    def get_or_create_collection(self, collection_name: str):
        """
        Obtém ou cria uma coleção no ChromaDB.
        
        Args:
            collection_name: Nome da coleção
            
        Returns:
            Objeto de coleção do ChromaDB
        """
        try:
            return self.client.get_collection(collection_name)
        except:
            return self.client.create_collection(collection_name)
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Gera embeddings para uma lista de textos.
        
        Args:
            texts: Lista de textos para gerar embeddings
            
        Returns:
            Lista de vetores de embeddings
        """
        return self.model.encode(texts).tolist()
    
    def add_documents(self, collection_name: str, documents: List[Dict[str, Any]]):
        """
        Adiciona documentos a uma coleção do ChromaDB.
        
        Args:
            collection_name: Nome da coleção
            documents: Lista de documentos com campos 'id', 'text' e 'metadata'
        """
        collection = self.get_or_create_collection(collection_name)
        
        ids = [str(doc["id"]) for doc in documents]
        texts = [doc["text"] for doc in documents]
        metadatas = [doc.get("metadata", {}) for doc in documents]
        
        # Gerar embeddings e adicionar à coleção
        collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas
        )
    
    def query_collection(self, collection_name: str, query_text: str, n_results: int = 5) -> Dict[str, Any]:
        """
        Consulta uma coleção do ChromaDB usando texto de consulta.
        
        Args:
            collection_name: Nome da coleção
            query_text: Texto da consulta
            n_results: Número de resultados a retornar
            
        Returns:
            Resultados da consulta
        """
        collection = self.get_or_create_collection(collection_name)
        
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        
        return results
    
    def delete_collection(self, collection_name: str):
        """
        Exclui uma coleção do ChromaDB.
        
        Args:
            collection_name: Nome da coleção a ser excluída
        """
        self.client.delete_collection(collection_name)
    
    def process_github_data(self, repo_name: str, issues: List[Dict], prs: List[Dict], commits: List[Dict]):
        """
        Processa dados do GitHub e armazena no ChromaDB.
        
        Args:
            repo_name: Nome do repositório
            issues: Lista de issues
            prs: Lista de pull requests
            commits: Lista de commits
        """
        collection_name = f"github_{repo_name.replace('/', '_')}"
        
        # Processar issues
        issue_documents = []
        for issue in issues:
            issue_documents.append({
                "id": f"issue_{issue['id']}",
                "text": f"Issue #{issue['id']}: {issue['title']}\n\n{issue['body']}",
                "metadata": {
                    "type": "issue",
                    "id": issue["id"],
                    "title": issue["title"],
                    "state": issue["state"],
                    "url": issue["url"],
                    "created_at": issue["created_at"],
                    "labels": ",".join(issue.get("labels", []))
                }
            })
        #comentando algo para fazer novo deploy
        # Processar pull requests
        pr_documents = []
        for pr in prs:
            pr_documents.append({
                "id": f"pr_{pr['id']}",
                "text": f"Pull Request #{pr['id']}: {pr['title']}\n\n{pr['body']}",
                "metadata": {
                    "type": "pull_request",
                    "id": pr["id"],
                    "title": pr["title"],
                    "state": pr["state"],
                    "url": pr["url"],
                    "created_at": pr["created_at"],
                    "merged": pr.get("merged", False)
                }
            })
        
        # Processar commits
        commit_documents = []
        for commit in commits:
            commit_documents.append({
                "id": f"commit_{commit['sha']}",
                "text": f"Commit {commit['sha'][:7]}: {commit['message']}",
                "metadata": {
                    "type": "commit",
                    "sha": commit["sha"],
                    "author": commit["author"],
                    "date": commit["date"],
                    "url": commit["url"]
                }
            })
        
        # Adicionar todos os documentos à coleção
        all_documents = issue_documents + pr_documents + commit_documents
        if all_documents:
            self.add_documents(collection_name, all_documents)
            
        return {
            "collection_name": collection_name,
            "documents_count": len(all_documents),
            "issues_count": len(issue_documents),
            "prs_count": len(pr_documents),
            "commits_count": len(commit_documents)
        }
