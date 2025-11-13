# CÓDIGO COMPLETO PARA: app/services/rag_service.py
# (Versão HÍBRIDA com Roteador)

import os
from .embedding_service import EmbeddingService
from .llm_service import LLMService
from .router_service import RouterService # <-- Importa o Roteador
from .metadata_service import MetadataService # <-- Importa o Serviço SQL
from typing import List, Dict, Any

try:
    embedding_service = EmbeddingService() # Nosso serviço Pinecone
    llm_service = LLMService()
    router_service = RouterService()       # Nosso novo Roteador
    metadata_service = MetadataService()   # Nosso novo serviço SQL
except ValueError as e:
    print(f"Erro ao inicializar serviços (verifique .env): {e}")
    llm_service = None
    embedding_service = None
    router_service = None
    metadata_service = None

def _formatar_resultados_query_pinecone(resultados: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Converte a saída do PINECONE para o formato que o LLMService espera."""
    contexto_formatado = []
    if "matches" not in resultados:
        return []
    for match in resultados["matches"]:
        metadata = match.get("metadata", {})
        doc_text = metadata.get("text", "") 
        contexto_formatado.append({
            "text": doc_text,
            "metadata": metadata
        })
    return contexto_formatado

def gerar_resposta_rag(pergunta: str, repositorio: str):
    """
    (Versão Híbrida) Gera resposta contextualizada via RAG.
    1. Roteia a consulta para descobrir a intenção.
    2. Busca no banco de dados apropriado (SQL para fatos, Pinecone para semântica).
    3. Gera a resposta com a LLM.
    """
    if not all([embedding_service, llm_service, router_service, metadata_service]):
        msg = "Serviços essenciais (RAG, LLM, Roteador ou Metadados) não foram inicializados."
        print(f"[ERRO] {msg}")
        return {"texto": f"Erro: {msg}", "contexto": "N/A"}

    try:
        # --- ETAPA 1: ROTEAMENTO ---
        rota = router_service.route_query(pergunta)
        categoria = rota.get("categoria", "semantica")
        
        contexto_formatado = []

        # --- ETAPA 2: BUSCA HÍBRIDA ---
        if categoria == "cronologica":
            print("[RAG] Rota: CRONOLÓGICA. Buscando no SQL...")
            entidade = rota.get("entidade", "commit") # Padrão para commit
            ordem = rota.get("ordem", "desc")         # Padrão para "último"
            limite = int(rota.get("limite", 1))
            # Busca no Postgres (rápido, factual)
            contexto_formatado = metadata_service.find_document_by_date(
                repo_name=repositorio,
                doc_type=entidade,
                order=ordem
            )

        # Se não for cronológica, ou se a busca SQL falhar, usamos a busca semântica
        if categoria == "semantica" or not contexto_formatado:
            if not contexto_formatado:
                print("[RAG] Rota: Fallback para SEMÂNTICA (busca cronológica não retornou dados).")
            else:
                print("[RAG] Rota: SEMÂNTICA. Buscando no Pinecone...")

            # Busca no Pinecone (semântica)
            # (Note que voltamos para n_results=5, pois não precisamos mais do "hack")
            resultados_query = embedding_service.query_collection_pinecone(
                query_text=pergunta,
                n_results=5, 
                repo_name=repositorio
            )
            contexto_formatado = _formatar_resultados_query_pinecone(resultados_query)

        # --- ETAPA 3: GERAÇÃO DE RESPOSTA ---
        if not contexto_formatado:
            print("[RAG] Nenhum contexto encontrado em NENHUM banco de dados.")
            sem_contexto = "Nenhum contexto encontrado no banco vetorial ou de metadados para esta consulta."
            return {"texto": sem_contexto, "contexto": sem_contexto}
            
        print(f"[RAG] Contexto final encontrado: {len(contexto_formatado)} documentos.")

        resposta_llm = llm_service.generate_response(
            query=pergunta,
            context=contexto_formatado
        )

        contexto_texto_bruto = "\n\n".join([doc['text'] for doc in contexto_formatado])
        
        return {
            "texto": resposta_llm["response"],
            "contexto": contexto_texto_bruto
        }

    except Exception as e:
        print(f"Erro ao gerar resposta RAG: {e}")
        traceback.print_exc()
        return {"texto": f"Erro ao processar sua consulta: {e}", "contexto": "Erro"}