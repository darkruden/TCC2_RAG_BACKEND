# CÓDIGO COMPLETO PARA: app/services/rag_service.py
# (Adicionada a função 'gerar_resposta_rag_stream')

from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from typing import Dict, Any, Iterator

class RAGService:
    """
    Serviço que coordena o RAG (Retrieval-Augmented Generation).
    """
    def __init__(self):
        try:
            self.llm_service = LLMService()
            self.metadata_service = MetadataService()
            print("[RAGService] Serviços LLM e Metadata inicializados.")
        except Exception as e:
            print(f"[RAGService] Erro crítico ao inicializar serviços dependentes: {e}")
            raise

    def _format_context_for_llm(self, context_docs: list) -> (str, list):
        # (Sem alterações)
        if not context_docs: return "Nenhum contexto encontrado.", []
        formatted_context_text = ""
        context_for_llm_api = []
        for doc in context_docs:
            tipo = doc.get('tipo'); meta = doc.get('metadados', {}); conteudo = doc.get('conteudo', '')
            formatted_context_text += f"--- Fonte (Tipo: {tipo}) ---\n"
            if tipo == 'commit': formatted_context_text += f"URL: {meta.get('url')}\nAutor: {meta.get('autor')}\n"
            else: formatted_context_text += f"URL: {meta.get('url')}\nTítulo: {meta.get('titulo')}\n"
            formatted_context_text += f"Conteúdo: {conteudo}\n\n"
            context_for_llm_api.append({"text": conteudo, "metadata": {**meta, "type": tipo}})
        return formatted_context_text, context_for_llm_api

    def gerar_resposta_rag(self, query: str, repo_name: str) -> Dict[str, Any]:
        """
        Função RAG principal (NÃO-STREAMING).
        (Sem alterações)
        """
        if not self.llm_service or not self.metadata_service:
            raise Exception("RAGService não pode operar; serviços dependentes falharam.")
        print(f"[RAGService] Recebida consulta para {repo_name}: '{query}'")
        try:
            documentos_similares = self.metadata_service.find_similar_documents(query_text=query, repo_name=repo_name, k=5)
            contexto_formatado, contexto_para_llm = self._format_context_for_llm(documentos_similares)
            print("[RAGService] Contexto enviado para LLMService...")
            resposta_llm = self.llm_service.generate_response(query=query, context=contexto_para_llm)
            print("[RAGService] Resposta recebida da LLM.")
            return {"texto": resposta_llm["response"], "contexto": contexto_formatado}
        except Exception as e:
            print(f"[RAGService] ERRO CRÍTICO ao gerar resposta RAG: {e}")
            raise

    # --- NOVA FUNÇÃO (Marco 8 - Streaming) ---
    def gerar_resposta_rag_stream(self, query: str, repo_name: str) -> Iterator[str]:
        """
        Função RAG que faz a busca e cede (yields) a resposta da LLM em stream.
        """
        if not self.llm_service or not self.metadata_service:
            print("[RAGService-Stream] Erro: Serviços dependentes falharam.")
            yield "Erro: Serviços dependentes falharam."
            return

        print(f"[RAGService-Stream] Recebida consulta para {repo_name}: '{query}'")
        
        try:
            # 1. Buscar contexto (RAG) - (Isso ainda é rápido)
            documentos_similares = self.metadata_service.find_similar_documents(
                query_text=query,
                repo_name=repo_name,
                k=5
            )
            
            # 2. Formatar o contexto
            _, contexto_para_llm = self._format_context_for_llm(documentos_similares)
            
            print("[RAGService-Stream] Contexto enviado para LLMService (stream)...")
            
            # 3. Chama a função de streaming da LLM e "repete" os tokens
            for token in self.llm_service.generate_response_stream(query=query, context=contexto_para_llm):
                yield token
                
            print("[RAGService-Stream] Streaming concluído.")

        except Exception as e:
            print(f"[RAGService-Stream] ERRO CRÍTICO ao gerar resposta RAG: {e}")
            yield f"\n\n**Erro ao gerar resposta:** {e}"

# --- Instância Singleton (Atualizada) ---
try:
    _rag_service_instance = RAGService()
    # Exporta AMBAS as funções (normal e stream)
    gerar_resposta_rag = _rag_service_instance.gerar_resposta_rag
    gerar_resposta_rag_stream = _rag_service_instance.gerar_resposta_rag_stream
    print("[RAGService] Instância de serviço criada e funções exportadas.")
except Exception as e:
    print(f"[RAGService] Falha ao criar instância de serviço: {e}")
    gerar_resposta_rag = None
    gerar_resposta_rag_stream = None