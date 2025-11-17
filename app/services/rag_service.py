# CÓDIGO COMPLETO E ATUALIZADO PARA: app/services/rag_service.py
# (Refatorado para Multi-Tenancy com 'user_id' e contexto melhor formatado)

from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from typing import Dict, Any, Iterator, List, Tuple


class RAGService:
    """
    Serviço que coordena o RAG (Retrieval-Augmented Generation).
    Refatorado para Multi-Tenancy (tudo é filtrado por user_id).

    Responsabilidades:
    - Buscar documentos semelhantes no índice vetorial (por usuário + repositório).
    - Formatar o contexto em duas formas:
      1) texto legível para exibir na interface (para o usuário ver "o que foi usado");
      2) estrutura leve para ser consumida pela LLM (texto + metadados).
    - Delegar a geração da resposta ao LLMService.
    """

    def __init__(self):
        try:
            self.llm_service = LLMService()
            self.metadata_service = MetadataService()
            print("[RAGService] Serviços LLM e Metadata inicializados.")
        except Exception as e:
            print(f"[RAGService] Erro crítico ao inicializar serviços dependentes: {e}")
            raise

    def _format_context_for_llm(self, context_docs: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Converte a lista de documentos (vindos do MetadataService) em:
        - um texto legível para exibir na UI;
        - uma lista de dicionários no formato esperado pelo LLMService.

        Cada item de saída para a LLM tem:
        {
          "text": <conteúdo>,
          "metadata": { ... , "type": <tipo_do_documento> }
        }
        """
        if not context_docs:
            return "Nenhum contexto encontrado para este repositório.", []

        formatted_context_text = ""
        context_for_llm_api: List[Dict[str, Any]] = []

        for doc in context_docs:
            tipo = doc.get("tipo", "documento")
            meta = doc.get("metadados", {}) or {}
            conteudo = doc.get("conteudo", "")

            formatted_context_text += f"--- Fonte (Tipo: {tipo}) ---\n"

            # Commits geralmente têm autor + URL
            if tipo == "commit":
                formatted_context_text += f"URL: {meta.get('url')}\n"
                if meta.get("autor"):
                    formatted_context_text += f"Autor: {meta.get('autor')}\n"
            else:
                # Issues / PRs / outros documentos
                formatted_context_text += f"URL: {meta.get('url')}\n"
                if meta.get("titulo"):
                    formatted_context_text += f"Título: {meta.get('titulo')}\n"

            formatted_context_text += f"Conteúdo: {conteudo}\n\n"

            # Estrutura enxuta para o LLMService (que irá reformatar para o prompt final)
            context_for_llm_api.append(
                {
                    "text": conteudo,
                    "metadata": {
                        **meta,
                        "type": tipo,
                    },
                }
            )

        return formatted_context_text, context_for_llm_api

    def gerar_resposta_rag(self, user_id: str, query: str, repo_name: str) -> Dict[str, Any]:
        """
        Rota principal do RAG (NÃO-STREAMING).
        - Filtra documentos pelo user_id + repo_name.
        - Passa o contexto formatado para a LLM.
        - Retorna o texto da resposta + o contexto legível para ser exibido no frontend.
        """
        if not self.llm_service or not self.metadata_service:
            raise Exception("RAGService não pode operar; serviços dependentes falharam.")

        print(f"[RAGService] Recebida consulta (User: {user_id}) para {repo_name}: '{query}'")

        try:
            documentos_similares = self.metadata_service.find_similar_documents(
                user_id=user_id,
                query_text=query,
                repo_name=repo_name,
                k=5,
            )

            contexto_formatado, contexto_para_llm = self._format_context_for_llm(documentos_similares)

            print("[RAGService] Contexto enviado para LLMService...")
            resposta_llm = self.llm_service.generate_response(query=query, context=contexto_para_llm)
            print("[RAGService] Resposta recebida da LLM.")

            return {"texto": resposta_llm["response"], "contexto": contexto_formatado}

        except Exception as e:
            print(f"[RAGService] ERRO CRÍTICO ao gerar resposta RAG: {e}")
            raise

    def gerar_resposta_rag_stream(self, user_id: str, query: str, repo_name: str) -> Iterator[str]:
        """
        Função RAG que faz a busca e cede (yields) a resposta da LLM em stream.
        Agora vinculada a um user_id.
        """
        if not self.llm_service or not self.metadata_service:
            print("[RAGService-Stream] Erro: Serviços dependentes falharam.")
            yield "Erro: Serviços dependentes falharam."
            return

        print(f"[RAGService-Stream] Recebida consulta (User: {user_id}) para {repo_name}: '{query}'")

        try:
            documentos_similares = self.metadata_service.find_similar_documents(
                user_id=user_id,
                query_text=query,
                repo_name=repo_name,
                k=5,
            )

            _, contexto_para_llm = self._format_context_for_llm(documentos_similares)

            print("[RAGService-Stream] Contexto enviado para LLMService (stream)...")

            for token in self.llm_service.generate_response_stream(query=query, context=contexto_para_llm):
                yield token

            print("[RAGService-Stream] Streaming concluído.")

        except Exception as e:
            print(f"[RAGService-Stream] ERRO CRÍTICO ao gerar resposta RAG: {e}")
            yield f"\n\n**Erro ao gerar resposta:** {e}"


# --- Instância Singleton (Atualizada) ---
try:
    _rag_service_instance = RAGService()
    gerar_resposta_rag = _rag_service_instance.gerar_resposta_rag
    gerar_resposta_rag_stream = _rag_service_instance.gerar_resposta_rag_stream
    print("[RAGService] Instância de serviço criada e funções exportadas.")
except Exception as e:
    print(f"[RAGService] Falha ao criar instância de serviço: {e}")
    gerar_resposta_rag = None
    gerar_resposta_rag_stream = None
