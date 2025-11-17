# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/embedding_service.py
# (Converte o arquivo de funções para a Classe que o worker_tasks espera)

import os
import time
from openai import OpenAI
from typing import List, Optional
import tiktoken # <-- Agora será importado corretamente

class EmbeddingService:
    def __init__(self, model_name: str, max_retries: int = 5, delay: int = 2):
        self.model_name = model_name
        self.max_retries = max_retries
        self.delay = delay
        self.client = None
        self.tokenizer = None
        self.embedding_dimension = 1536
        
        print(f"[EmbeddingService] Inicializando com modelo: {self.model_name}")
        try:
            if self.model_name.startswith("text-embedding"):
                self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                self.tokenizer = tiktoken.get_encoding("cl100k_base")
                self.embedding_type = "openai"
                if self.model_name == "text-embedding-3-small":
                    self.embedding_dimension = 1536
                elif self.model_name == "text-embedding-3-large":
                    self.embedding_dimension = 3072
                print(f"[EmbeddingService] Modo OpenAI configurado. Dimensão: {self.embedding_dimension}")
            else:
                raise ValueError(f"Modelo de embedding não suportado: {self.model_name}")
        except Exception as e:
            print(f"[EmbeddingService] ERRO CRÍTICO ao inicializar o cliente: {e}")
            raise

    def get_embedding(self, text: str) -> List[float]:
        if not self.client:
            raise RuntimeError("Cliente OpenAI não inicializado.")
        if not text or not text.strip():
            return [0.0] * self.embedding_dimension
        text = text.replace("\n", " ").replace("\0", "\n")
        
        for i in range(self.max_retries):
            try:
                response = self.client.embeddings.create(input=[text], model=self.model_name)
                return response.data[0].embedding
            except Exception as e:
                print(f"[EmbeddingService] OpenAI API error (tentativa {i+1}): {e}. Tentando novamente em {self.delay}s...")
                time.sleep(self.delay)
        raise RuntimeError(f"Falha ao gerar embedding após {self.max_retries} tentativas.")

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not self.client:
            raise RuntimeError("Cliente OpenAI não inicializado.")
        if not texts:
            return []
        texts = [t.replace("\n", " ").replace("\0", "\n") if t else "" for t in texts]
        for i in range(self.max_retries):
            try:
                response = self.client.embeddings.create(input=texts, model=self.model_name)
                sorted_embeddings = sorted(response.data, key=lambda e: e.index)
                return [item.embedding for item in sorted_embeddings]
            except Exception as e:
                print(f"[EmbeddingService] OpenAI API error (lote, tentativa {i+1}): {e}. Tentando novamente em {self.delay}s...")
                time.sleep(self.delay)
        raise RuntimeError(f"Falha ao gerar embeddings em lote após {self.max_retries} tentativas.")