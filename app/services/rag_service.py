# CÓDIGO COMPLETO PARA: app/services/rag_service.py
# (Refatorado para usar Classes)

from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from typing import Dict, Any

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
        """
        Formata os documentos recuperados do Supabase em um contexto
        de texto claro para a LLM e em um formato de objeto para a API.
        """
        if not context_docs:
            return "Nenhum contexto encontrado.", []
        
        formatted_context_text = ""
        context_for_llm_api = []
        
        for doc in context_docs:
            tipo = doc.get('tipo')
            meta = doc.get('metadados', {})
            conteudo = doc.get('conteudo', '')
            
            # 1. Para o texto de depuração/retorno
            formatted_context_text += f"--- Fonte (Tipo: {tipo}) ---\n"
            if tipo == 'commit':
                formatted_context_text += f"URL: {meta.get('url')}\nAutor: {meta.get('autor')}\n"
            else:
                formatted_context_text += f"URL: {meta.get('url')}\nTítulo: {meta.get('titulo')}\n"
            formatted_context_text += f"Conteúdo: {conteudo}\n\n"
            
            # 2. Para a API da LLM (formato do llm_service.py)
            context_for_llm_api.append({
                "text": conteudo,
                "metadata": {**meta, "type": tipo}
            })
            
        return formatted_context_text, context_for_llm_api

    def gerar_resposta_rag(self, query: str, repo_name: str) -> Dict[str, Any]:
        """
        Função principal do RAG (chamada pelo main.py).
        """
        if not self.llm_service or not self.metadata_service:
            raise Exception("RAGService não pode operar; serviços dependentes falharam.")
            
        print(f"[RAGService] Recebida consulta para {repo_name}: '{query}'")
        
        try:
            # 1. Buscar contexto (Busca Vetorial Híbrida)
            documentos_similares = self.metadata_service.find_similar_documents(
                query_text=query,
                repo_name=repo_name,
                k=5 # Pega os 5 resultados mais relevantes
            )
            
            # 2. Formatar o contexto
            contexto_formatado, contexto_para_llm = self._format_context_for_llm(documentos_similares)
            
            # 3. Gerar a resposta com a LLM
            print("[RAGService] Contexto enviado para LLMService...")
            resposta_llm = self.llm_service.generate_response(
                query=query,
                context=contexto_para_llm
            )
            
            print("[RAGService] Resposta recebida da LLM.")
            
            return {
                "texto": resposta_llm["response"],
                "contexto": contexto_formatado
            }

        except Exception as e:
            print(f"[RAGService] ERRO CRÍTICO ao gerar resposta RAG: {e}")
            raise

# --- Instância Singleton para o Worker ---
try:
    _rag_service_instance = RAGService()
    gerar_resposta_rag = _rag_service_instance.gerar_resposta_rag
    print("[RAGService] Instância de serviço criada e função exportada.")
except Exception as e:
    print(f"[RAGService] Falha ao criar instância de serviço: {e}")
    gerar_resposta_rag = None