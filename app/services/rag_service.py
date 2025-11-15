# app/services/rag_service.py
from app.services.metadata_service import find_similar_documents
from app.services.llm_service import LLMService
from typing import Dict, Any

# Inicializa o LLMService uma vez
try:
    llm_service = LLMService() # Usa o modelo padrão gpt-4o-mini
    print("[RAGService] LLMService inicializado.")
except Exception as e:
    print(f"[RAGService] Erro ao inicializar LLMService: {e}")
    llm_service = None

def _format_context_for_llm(context_docs: list) -> str:
    """
    Formata os documentos recuperados do Supabase em um contexto
    de texto claro para a LLM.
    """
    if not context_docs:
        return "Nenhum contexto encontrado."
    
    formatted_context = ""
    for doc in context_docs:
        # 'doc' é o resultado da nossa consulta SQL
        tipo = doc.get('tipo')
        meta = doc.get('metadados', {})
        conteudo = doc.get('conteudo', '')
        
        formatted_context += f"--- Fonte (Tipo: {tipo}) ---\n"
        if tipo == 'commit':
            formatted_context += f"URL: {meta.get('url')}\nAutor: {meta.get('autor')}\n"
        else:
            formatted_context += f"URL: {meta.get('url')}\nTítulo: {meta.get('titulo')}\n"
        
        formatted_context += f"Conteúdo: {conteudo}\n\n"
        
    return formatted_context

def gerar_resposta_rag(query: str, repo_name: str) -> Dict[str, Any]:
    """
    Função principal do RAG (chamada pelo main.py).
    Coordena a busca vetorial e a geração de resposta da LLM.
    """
    if not llm_service:
        raise Exception("RAGService não pode operar; LLMService falhou ao inicializar.")
        
    print(f"[RAGService] Recebida consulta para {repo_name}: '{query}'")
    
    try:
        # 1. Buscar contexto (Busca Vetorial Híbrida)
        # O MetadataService agora faz a busca vetorial
        documentos_similares = find_similar_documents(
            query_text=query,
            repo_name=repo_name,
            k=5 # Pega os 5 resultados mais relevantes
        )
        
        # 2. Formatar o contexto para a LLM
        contexto_formatado = _format_context_for_llm(documentos_similares)
        
        # 3. Gerar a resposta com a LLM
        print("[RAGService] Contexto enviado para LLMService...")
        # (Esta função 'generate_response' é do seu llm_service.py
        #  e pode precisar ser ajustada se o formato do contexto mudou)
        
        # O llm_service.py espera um contexto diferente, vamos adaptar
        # (Adaptação para o formato esperado pelo seu llm_service.py)
        contexto_para_llm = [
            {
                "text": doc.get('conteudo'),
                "metadata": {**doc.get('metadados'), "type": doc.get('tipo')}
            } 
            for doc in documentos_similares
        ]
        
        # Chama a função do seu llm_service.py
        resposta_llm = llm_service.generate_response(
            query=query,
            context=contexto_para_llm
        )
        
        print("[RAGService] Resposta recebida da LLM.")
        
        return {
            "texto": resposta_llm["response"],
            "contexto": contexto_formatado # Retorna o contexto que usamos
        }

    except Exception as e:
        print(f"[RAGService] ERRO CRÍTICO ao gerar resposta RAG: {e}")
        raise