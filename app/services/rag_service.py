import os
from .embedding_service import EmbeddingService
from .llm_service import LLMService
from typing import List, Dict, Any

# 1. Inicializar os serviços (como antes)
try:
    embedding_service = EmbeddingService()
    llm_service = LLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("LLM_MODEL", "gpt-4")
    )
except ValueError as e:
    print(f"Erro ao inicializar serviços (verifique .env): {e}")
    llm_service = None
    embedding_service = None

def _formatar_resultados_query(resultados: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    (MODIFICADO) Converte a saída do PINECONE para o formato que o LLMService espera.
    
    Pinecone retorna: {'matches': [{'id': '...', 'metadata': {...}, 'score': ...}]}
    LLMService espera: [{'text': '...', 'metadata': {...}}, ...]
    """
    contexto_formatado = []
    
    if "matches" not in resultados:
        return []

    for match in resultados["matches"]:
        metadata = match.get("metadata", {})
        
        # Recuperamos o texto de dentro dos metadados (onde salvamos)
        doc_text = metadata.get("text", "") 
        
        contexto_formatado.append({
            "text": doc_text,
            "metadata": metadata
        })
        
    return contexto_formatado


def gerar_resposta_rag(pergunta: str, repositorio: str):
    """
    Gera resposta contextualizada via RAG.
    (Esta função não precisa de NENHUMA MUDANÇA, 
     pois só _formatar_resultados_query mudou)
    """
    if not embedding_service or not llm_service:
        msg = "Serviços de Embedding ou LLM não foram inicializados."
        print(f"[ERRO] {msg}")
        return {"texto": f"Erro: {msg}", "contexto": "N/A"}

    try:
        # 1. (REMOVIDO) Não precisamos mais do nome da coleção, 
        #    pois o embedding_service já sabe o índice
        print(f"[RAG] Consultando índice Pinecone para: {repositorio}")

        # 2. Buscar contexto no Pinecone via EmbeddingService
        resultados_query = embedding_service.query_collection(
            query_text=pergunta,
            n_results=5, # Pega os 5 resultados mais relevantes
            repo_name=repositorio # <-- ESTA LINHA CORRIGE O VAZAMENTO DE DADOS
        )

        # 3. Formatar o contexto para o LLMService
        contexto_formatado = _formatar_resultados_query(resultados_query)

        if not contexto_formatado:
            print("[RAG] Nenhum contexto encontrado no banco vetorial.")
            sem_contexto = "Nenhum contexto encontrado no banco vetorial para esta consulta."
            return {"texto": sem_contexto, "contexto": sem_contexto}
            
        print(f"[RAG] Contexto encontrado: {len(contexto_formatado)} documentos.")

        # 4. Gerar resposta no LLMService
        resposta_llm = llm_service.generate_response(
            query=pergunta,
            context=contexto_formatado
        )

        # 5. Retornar resposta
        contexto_texto_bruto = "\n\n".join([doc['text'] for doc in contexto_formatado])
        
        return {
            "texto": resposta_llm["response"],
            "contexto": contexto_texto_bruto
        }

    except Exception as e:
        print(f"Erro ao gerar resposta RAG: {e}")
        return {"texto": f"Erro ao processar sua consulta: {e}", "contexto": "Erro"}