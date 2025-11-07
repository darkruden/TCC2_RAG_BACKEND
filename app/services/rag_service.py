# [COLE ESSE NOVO CÓDIGO NO LUGAR DO CONTEÚDO ANTIGO DE rag_service.py]

# O que você deve colar
import os
from .embedding_service import EmbeddingService
from .llm_service import LLMService
from typing import List, Dict, Any
# 1. Inicializar os serviços que vamos usar
# Eles pegam as configurações (tokens, paths) das variáveis de ambiente
try:
    embedding_service = EmbeddingService()
    
    # O LLMService precisa da API_KEY
    llm_service = LLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("LLM_MODEL", "gpt-4")
    )
except ValueError as e:
    print(f"Erro ao inicializar serviços (verifique .env): {e}")
    llm_service = None
    embedding_service = None
except ImportError:
    print("Erro de importação. Verifique se os serviços estão no mesmo diretório.")
    llm_service = None
    embedding_service = None


def _formatar_resultados_query(resultados: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Converte a saída do ChromaDB para o formato que o LLMService espera.
    
    ChromaDB retorna: {'documents': [[]], 'metadatas': [[]]}
    LLMService espera: [{'text': '...', 'metadata': {...}}, ...]
    """
    contexto_formatado = []
    
    # Os resultados vêm em listas aninhadas, pegamos o primeiro (índice 0)
    docs = resultados.get('documents', [[]])[0]
    metadatas = resultados.get('metadatas', [[]])[0]

    if not docs:
        return []

    for doc_text, meta in zip(docs, metadatas):
        contexto_formatado.append({
            "text": doc_text,
            "metadata": meta
        })
        
    return contexto_formatado


def gerar_resposta_rag(pergunta: str, repositorio: str):
    """
    Gera resposta contextualizada via RAG.
    
    1. Define o nome da coleção.
    2. Busca o contexto no EmbeddingService.
    3. Formata o contexto.
    4. Gera a resposta no LLMService.
    """
    if not embedding_service or not llm_service:
        msg = "Serviços de Embedding ou LLM não foram inicializados."
        print(f"[ERRO] {msg}")
        return {"texto": f"Erro: {msg}", "contexto": "N/A"}

    try:
        # 1. Definir o nome da coleção (DEVE ser igual ao usado na ingestão)
        # O embedding_service.process_github_data usa este formato
        collection_name = f"github_{repositorio.replace('/', '_')}"
        print(f"[RAG] Consultando coleção: {collection_name}")

        # 2. Buscar contexto no ChromaDB via EmbeddingService
        resultados_query = embedding_service.query_collection(
            collection_name=collection_name,
            query_text=pergunta,
            n_results=2  # Pega os 5 resultados mais relevantes
        )

        # 3. Formatar o contexto para o LLMService
        contexto_formatado = _formatar_resultados_query(resultados_query)

        if not contexto_formatado:
            print("[RAG] Nenhum contexto encontrado no banco vetorial.")
            sem_contexto = "Nenhum contexto encontrado no banco vetorial para esta consulta."
            return {"texto": sem_contexto, "contexto": sem_contexto}
            
        print(f"[RAG] Contexto encontrado: {len(contexto_formatado)} documentos.")

        # 4. Gerar resposta no LLMService
        # Esta função já usa o prompt de sistema correto
        resposta_llm = llm_service.generate_response(
            query=pergunta,
            context=contexto_formatado
        )

        # 5. Retornar resposta no formato esperado pelo main.py
        # O "contexto" de retorno é apenas os trechos de texto para o frontend
        contexto_texto_bruto = "\n\n".join([doc['text'] for doc in contexto_formatado])
        
        return {
            "texto": resposta_llm["response"],
            "contexto": contexto_texto_bruto
        }

    except Exception as e:
        print(f"Erro ao gerar resposta RAG: {e}")
        return {"texto": f"Erro ao processar sua consulta: {e}", "contexto": "Erro"}