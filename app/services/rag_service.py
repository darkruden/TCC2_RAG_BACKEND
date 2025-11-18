# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/rag_service.py
# (Refatorado para Injeção de Dependência e Multi-Tenancy)

import os
import json
from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from app.services.embedding_service import EmbeddingService # Importa a CLASSE
from typing import Dict, Any, Iterator, List, Tuple

class RAGService:
    def __init__(self):
        try:
            self.llm_service = LLMService()
            # Cria as instâncias de dependência
            self.embedding_service = EmbeddingService(
                model_name=os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
            )
            self.metadata_service = MetadataService(embedding_service=self.embedding_service)
            
            print("[RAGService] Serviços (LLM, Embedding, Metadata) inicializados.")
        except Exception as e:
            print(f"[RAGService] Erro crítico ao inicializar serviços dependentes: {e}")
            self.llm_service = None
            self.metadata_service = None

    def _format_context_for_llm(self, context_docs: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Formata os documentos de contexto do RAG em uma string legível para a LLM,
        e retorna uma lista de fontes para ser exibida na UI.
        """
        if not context_docs:
            return "", []
            
        context_parts = []
        sources_ui = []

        for i, doc in enumerate(context_docs):
            # Obtém file_path e conteudo (o que vem do metadata_service)
            file_path = doc.get('file_path', 'N/A')
            content = doc.get('conteudo', 'N/A')
            
            # Limita o conteúdo para evitar prompts muito longos
            content_snippet = content[:5000] 
            
            # Cria a string do contexto para ser injetada no prompt do LLM
            context_parts.append(
                f"--- Documento de Contexto RAG {i+1} ---\n"
                f"Caminho do Arquivo: {file_path}\n"
                f"Conteúdo:\n{content_snippet}\n"
                f"--- Fim do Documento {i+1} ---"
            )
            
            # Cria a lista de fontes para o front-end
            sources_ui.append({
                "source_id": i + 1,
                "file_path": file_path
            })
            
        # O LLMService receberá o contexto como uma única string.
        return "\n\n".join(context_parts), sources_ui


    def gerar_resposta_rag(self, user_id: str, prompt_usuario: str, repo_name: str) -> Dict[str, Any]:
        if not self.metadata_service or not self.llm_service:
            raise Exception("Serviços de RAG não inicializados.")

        print(f"[RAGService] Recebida consulta (User: {user_id}) para {repo_name}: '{prompt_usuario}'")
        try:
            documentos_similares = self.metadata_service.find_similar_documents(
                user_id=user_id,
                query_text=prompt_usuario,
                repo_name=repo_name,
                k=5,
            )
            instrucao = self.metadata_service.find_similar_instruction(
                user_id=user_id,
                repo_name=repo_name,
                query_text=prompt_usuario
            )
            
            contexto_para_llm, fontes_ui = self._format_context_for_llm(documentos_similares)
            
            print("[RAGService] Contexto enviado para LLMService...")
            resposta = self.llm_service.generate_rag_response(
                contexto=contexto_para_llm,
                prompt=prompt_usuario,
                instrucao_rag=instrucao
            )

            return {
                "response_type": "answer",
                "message": resposta,
                "job_id": None,
                "fontes": fontes_ui
            }
        except Exception as e:
            print(f"[RAGService] ERRO CRÍTICO ao gerar resposta RAG: {e}")
            return {"response_type": "error", "message": f"Erro: {e}", "job_id": None}

    def gerar_resposta_rag_stream(self, user_id: str, query: str, repo_name: str) -> Iterator[str]:
        if not self.metadata_service or not self.llm_service:
            yield f"Erro: Serviços dependentes falharam."
            return

        print(f"[RAGService-Stream] Recebida consulta (User: {user_id}) para {repo_name}: '{query}'")
        try:
            documentos_similares = self.metadata_service.find_similar_documents(
                user_id=user_id, query_text=query, repo_name=repo_name, k=5,
            )
            instrucao = self.metadata_service.find_similar_instruction(
                user_id=user_id, repo_name=repo_name, query_text=query
            )

            contexto_para_llm, fontes_ui = self._format_context_for_llm(documentos_similares)

            # Envia as fontes primeiro
            yield json.dumps(fontes_ui) + "[[SOURCES_END]]"

            print("[RAGService-Stream] Contexto enviado para LLMService (stream)...")
            for token in self.llm_service.generate_rag_response_stream(
                contexto=contexto_para_llm,
                prompt=query,
                instrucao_rag=instrucao
            ):
                yield token
            print("[RAGService-Stream] Streaming concluído.")
        except Exception as e:
            print(f"[RAGService-Stream] ERRO CRÍTICO ao gerar resposta RAG: {e}")
            yield f"\n\n**Erro ao gerar resposta:** {e}"

# --- Instância Singleton (para o main.py importar) ---
try:
    _rag_service_instance = RAGService()
    gerar_resposta_rag = _rag_service_instance.gerar_resposta_rag
    gerar_resposta_rag_stream = _rag_service_instance.gerar_resposta_rag_stream
except Exception as e:
    print(f"[RAGService] FALHA AO INICIALIZAR SINGLETON: {e}")
    def gerar_resposta_rag(*args, **kwargs):
        return {"response_type": "error", "message": f"Erro na inicialização do RAGService: {e}", "job_id": None}
    def gerar_resposta_rag_stream(*args, **kwargs):
        yield f"Erro na inicialização do RAGService: {e}"