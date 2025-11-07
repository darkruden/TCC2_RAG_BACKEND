import pytest
import os
from unittest.mock import patch, MagicMock
import numpy as np
from app.services.embedding_service import EmbeddingService

# Configuração de fixtures para testes
@pytest.fixture
def mock_sentence_transformer():
    with patch('app.services.embedding_service.SentenceTransformer') as mock_transformer:
        # Configurar o mock para retornar valores específicos
        mock_instance = MagicMock()
        mock_transformer.return_value = mock_instance
        
        # Configurar o método encode para retornar embeddings simulados
        mock_instance.encode.return_value = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        
        yield mock_instance

@pytest.fixture
def mock_chromadb():
    with patch('app.services.embedding_service.chromadb') as mock_chromadb:
        # Configurar o mock para retornar valores específicos
        mock_client = MagicMock()
        mock_collection = MagicMock()
        
        mock_chromadb.PersistentClient.return_value = mock_client
        mock_client.get_collection.return_value = mock_collection
        mock_client.create_collection.return_value = mock_collection
        
        # Configurar o método query para retornar resultados simulados
        mock_collection.query.return_value = {
            "ids": [["doc1", "doc2"]],
            "documents": [["Texto do documento 1", "Texto do documento 2"]],
            "metadatas": [[{"type": "issue"}, {"type": "commit"}]],
            "distances": [[0.1, 0.2]]
        }
        
        yield {
            "client": mock_client,
            "collection": mock_collection
        }

@pytest.fixture
def embedding_service(mock_sentence_transformer, mock_chromadb):
    # Configurar serviço para teste
    service = EmbeddingService(model_name="test-model", persistence_dir="./test_chroma")
    yield service

# Testes unitários
class TestEmbeddingService:
    
    def test_init(self, mock_sentence_transformer, mock_chromadb):
        """Testa a inicialização do serviço"""
        service = EmbeddingService(model_name="test-model", persistence_dir="./test_dir")
        
        assert service.model_name == "test-model"
        assert service.persistence_dir == "./test_dir"
        assert service.model == mock_sentence_transformer
        assert service.client == mock_chromadb["client"]
    
    def test_get_or_create_collection_existing(self, embedding_service, mock_chromadb):
        """Testa a obtenção de uma coleção existente"""
        # Configurar mock
        mock_client = mock_chromadb["client"]
        mock_collection = mock_chromadb["collection"]
        
        # Chamar método
        collection = embedding_service.get_or_create_collection("test_collection")
        
        # Verificar chamadas e resultado
        mock_client.get_collection.assert_called_once_with("test_collection")
        assert collection == mock_collection
    
    def test_get_or_create_collection_new(self, embedding_service, mock_chromadb):
        """Testa a criação de uma nova coleção"""
        # Configurar mock para lançar exceção ao tentar obter coleção
        mock_client = mock_chromadb["client"]
        mock_collection = mock_chromadb["collection"]
        mock_client.get_collection.side_effect = Exception("Collection not found")
        
        # Chamar método
        collection = embedding_service.get_or_create_collection("new_collection")
        
        # Verificar chamadas e resultado
        mock_client.get_collection.assert_called_once_with("new_collection")
        mock_client.create_collection.assert_called_once_with("new_collection")
        assert collection == mock_collection
    
    def test_generate_embeddings(self, embedding_service, mock_sentence_transformer):
        """Testa a geração de embeddings"""
        # Configurar mock
        texts = ["Texto 1", "Texto 2"]
        
        # Chamar método
        embeddings = embedding_service.generate_embeddings(texts)
        
        # Verificar chamadas e resultado
        mock_sentence_transformer.encode.assert_called_once_with(texts)
        assert len(embeddings) == 2
        assert len(embeddings[0]) == 3  # Dimensão do embedding simulado
    
    def test_add_documents(self, embedding_service, mock_chromadb):
        """Testa a adição de documentos a uma coleção"""
        # Configurar mock
        mock_collection = mock_chromadb["collection"]
        
        # Dados de teste
        documents = [
            {"id": "doc1", "text": "Texto 1", "metadata": {"type": "issue"}},
            {"id": "doc2", "text": "Texto 2", "metadata": {"type": "commit"}}
        ]
        
        # Chamar método
        embedding_service.add_documents("test_collection", documents)
        
        # Verificar chamadas
        mock_collection.add.assert_called_once_with(
            ids=["doc1", "doc2"],
            documents=["Texto 1", "Texto 2"],
            metadatas=[{"type": "issue"}, {"type": "commit"}]
        )
    
    def test_query_collection(self, embedding_service, mock_chromadb):
        """Testa a consulta a uma coleção"""
        # Configurar mock
        mock_collection = mock_chromadb["collection"]
        
        # Chamar método
        results = embedding_service.query_collection("test_collection", "consulta de teste", n_results=2)
        
        # Verificar chamadas e resultado
        mock_collection.query.assert_called_once_with(
            query_texts=["consulta de teste"],
            n_results=2
        )
        
        assert "ids" in results
        assert "documents" in results
        assert "metadatas" in results
        assert "distances" in results
    
    def test_delete_collection(self, embedding_service, mock_chromadb):
        """Testa a exclusão de uma coleção"""
        # Configurar mock
        mock_client = mock_chromadb["client"]
        
        # Chamar método
        embedding_service.delete_collection("test_collection")
        
        # Verificar chamadas
        mock_client.delete_collection.assert_called_once_with("test_collection")
    
    def test_process_github_data(self, embedding_service, mock_chromadb):
        """Testa o processamento de dados do GitHub"""
        # Configurar mock
        mock_collection = mock_chromadb["collection"]
        
        # Dados de teste
        repo_name = "user/repo"
        issues = [
            {"id": 1, "title": "Issue 1", "body": "Descrição 1", "state": "open", "url": "url1", "created_at": "2025-01-01", "labels": ["bug"]}
        ]
        prs = [
            {"id": 2, "title": "PR 1", "body": "Descrição 2", "state": "open", "url": "url2", "created_at": "2025-01-02", "merged": False}
        ]
        commits = [
            {"sha": "abc123", "message": "Fix bug", "author": "Dev", "date": "2025-01-03", "url": "url3"}
        ]
        
        # Chamar método
        result = embedding_service.process_github_data(repo_name, issues, prs, commits)
        
        # Verificar chamadas
        assert mock_collection.add.called
        
        # Verificar resultado
        assert result["collection_name"] == "github_user_repo"
        assert result["documents_count"] == 3
        assert result["issues_count"] == 1
        assert result["prs_count"] == 1
        assert result["commits_count"] == 1
