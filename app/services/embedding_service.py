# app/services/embedding_service.py
import os
import time
from openai import OpenAI
from typing import List

# Inicializa o cliente OpenAI
# (Ele lê a OPENAI_API_KEY automaticamente das variáveis de ambiente [cite: 8])
try:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception as e:
    print(f"[EmbeddingService] Erro ao inicializar cliente OpenAI: {e}")
    client = None

# O modelo de embedding que usaremos.
# 'text-embedding-3-small' é rápido, barato e poderoso.
EMBEDDING_MODEL = "text-embedding-3-small"
# A dimensão que este modelo gera (deve bater com o SQL: VECTOR(1536))
EMBEDDING_DIMENSION = 1536 

def get_embedding(text: str) -> List[float]:
    """
    Gera o embedding para um único bloco de texto.
    """
    if not client:
        raise Exception("Cliente OpenAI não inicializado. Verifique a API_TOKEN.")

    if not text or not text.strip():
        print("[EmbeddingService] Aviso: Texto vazio recebido, retornando vetor nulo.")
        return [0.0] * EMBEDDING_DIMENSION

    try:
        # Substitui caracteres nulos que podem quebrar a API da OpenAI
        text = text.replace("\0", "\n") 
        
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[text] # A API espera uma lista
        )
        
        embedding = response.data[0].embedding
        return embedding

    except Exception as e:
        print(f"[EmbeddingService] Erro ao gerar embedding: {e}")
        # Retorna um vetor nulo em caso de erro
        return [0.0] * EMBEDDING_DIMENSION

def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Gera embeddings para um lote de textos (mais eficiente).
    """
    if not client:
        raise Exception("Cliente OpenAI não inicializado.")

    if not texts:
        return []

    try:
        # Limpa os textos
        texts = [t.replace("\0", "\n") if t else "" for t in texts]
        
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts
        )
        
        # Retorna a lista de embeddings na ordem correta
        return [data.embedding for data in response.data]

    except Exception as e:
        print(f"[EmbeddingService] Erro ao gerar embeddings em lote: {e}")
        # Retorna uma lista de vetores nulos
        return [[0.0] * EMBEDDING_DIMENSION for _ in texts]