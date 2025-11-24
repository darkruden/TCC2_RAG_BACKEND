# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/rag_service.py

import os
import json
import traceback
from typing import Dict, Any, Iterator, List, Tuple, Optional

from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from app.services.embedding_service import EmbeddingService
from app.services.github_service import GithubService 

class RAGService:
    def __init__(self):
        try:
            self.llm_service = LLMService()
            self.embedding_service = EmbeddingService(
                model_name=os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
            )
            self.metadata_service = MetadataService(embedding_service=self.embedding_service)
            
            # Inicializa o GithubService para poder fazer o parse de URLs
            self.github_service = GithubService(token=os.getenv("GITHUB_TOKEN"))
            
            print("[RAGService] Serviços (LLM, Embedding, Metadata, Github) inicializados.")
        except Exception as e:
            print(f"[RAGService] Erro crítico ao inicializar serviços dependentes: {e}")
            self.llm_service = None
            self.metadata_service = None
            self.github_service = None

    def _format_context_for_llm(self, context_docs: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        if not context_docs:
            return "", []
            
        context_parts = []
        sources_ui = []
        
        # Set para evitar duplicatas VISUAIS exatas
        seen_sources = set()

        for i, doc in enumerate(context_docs):
            # --- Pula documentos de instrução interna (SISTEMA) ---
            if doc.get('tipo') == 'info' or doc.get('file_path') == 'SISTEMA':
                # Adiciona apenas ao TEXTO do LLM, mas não à lista visual
                context_parts.append(doc.get('conteudo', ''))
                continue
            
            raw_path = doc.get('file_path')
            content = doc.get('conteudo', 'N/A')
            branch = doc.get('branch', 'N/A')
            meta = doc.get('metadados') if isinstance(doc.get('metadados'), dict) else {}

            tipo_original = doc.get('tipo')
            identificador = raw_path # Default

            if 'sha' in meta: 
                tipo = 'commit'
                identificador = meta.get('sha')
            elif 'titulo' in meta and 'id' in meta:
                tipo = 'pr' if 'pr' in str(tipo_original).lower() else 'issue'
                identificador = str(meta.get('id'))
            else:
                tipo = 'file'

            # --- DEDUPLICAÇÃO VISUAL ---
            # Se já mostramos este SHA ou Arquivo, não adiciona na lista visual de novo
            unique_key = f"{tipo}:{identificador}"
            should_add_to_ui = False
            if unique_key not in seen_sources:
                seen_sources.add(unique_key)
                should_add_to_ui = True

            # --- Formatação do Texto (Prompt) ---
            display_name = raw_path
            url_link = meta.get('url', '#')
            
            context_text = ""
            if tipo == 'commit':
                sha_curto = identificador[:7] if identificador else 'N/A'
                display_name = f"Commit {sha_curto}"
                context_text = (
                    f"--- DADOS DO COMMIT ---\nID: {sha_curto}\nAutor: {meta.get('autor')}\nData: {meta.get('data')}\nURL: {url_link}\nMensagem: {content}\n"
                )
            elif tipo in ['issue', 'pr']:
                display_name = f"{tipo.upper()} #{identificador}"
                context_text = (
                    f"--- {tipo.upper()} ---\nNúmero: #{identificador}\nTítulo: {meta.get('titulo')}\nURL: {url_link}\nConteúdo: {content}\n"
                )
            else:
                # Arquivo
                context_text = f"--- ARQUIVO: {display_name} (Branch: {branch}) ---\n{content[:5000]}\n"

            context_parts.append(context_text)
            
            # --- Adiciona à UI apenas se for único e real ---
            if should_add_to_ui:
                sources_ui.append({
                    "source_id": len(sources_ui) + 1,
                    "file_path": display_name,
                    "branch": branch,
                    "url": url_link,
                    "tipo": tipo,
                    "sha": meta.get('sha'),
                    "id": meta.get('id')
                })
            
        return "\n\n".join(context_parts), sources_ui

    def _get_combined_context(self, user_id: str, query: str, repo_name: str) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
        """
        Helper privado que executa a lógica de busca híbrida e retorna:
        (texto_prompt, lista_fontes_ui, instrucao_rag)
        Evita duplicação de código entre sync e stream.
        """
        real_repo_name, branch = self.github_service.parse_repo_url(repo_name)
        
        # 1. Busca Semântica
        documentos_similares = self.metadata_service.find_similar_documents(
            user_id=user_id, 
            query_text=query, 
            repo_name=real_repo_name, 
            branch=branch,          
            k=5,
        )
        
        # 2. Busca Temporal (SQL Sort)
        commits_recentes = self.metadata_service.get_recent_commits(
            user_id=user_id,
            repo_name=real_repo_name,
            branch=branch,
            limit=5 
        )
        
        # 3. Combinação Inteligente
        final_docs_map = {} 
        ordered_docs = []

        # A. Adiciona Cabeçalho Temporal
        if commits_recentes:
            ordered_docs.append({
                "conteudo": "--- INÍCIO DA LINHA DO TEMPO (MAIS RECENTES) ---\nEstes são os commits mais atuais do branch selecionado. Priorize esta informação para perguntas sobre 'último' ou 'atual'.",
                "file_path": "SISTEMA",
                "tipo": "info",
                "metadados": {}
            })
            for doc in commits_recentes:
                sha = doc['metadados'].get('sha')
                if sha:
                    final_docs_map[sha] = doc
                    ordered_docs.append(doc)

            ordered_docs.append({
                "conteudo": "--- FIM DA LINHA DO TEMPO ---\nSeguem documentos por similaridade:",
                "file_path": "SISTEMA",
                "tipo": "info",
                "metadados": {}
            })

        # B. Adiciona Similares
        for doc in documentos_similares:
            meta = doc.get('metadados') or {}
            identifier = meta.get('sha') or doc.get('file_path')
            
            if identifier not in final_docs_map:
                final_docs_map[identifier] = doc
                ordered_docs.append(doc)
        
        instrucao = self.metadata_service.find_similar_instruction(
            user_id=user_id, repo_name=real_repo_name, query_text=query
        )

        contexto_para_llm, fontes_ui = self._format_context_for_llm(ordered_docs)
        
        return contexto_para_llm, fontes_ui, instrucao

    def gerar_resposta_rag(self, user_id: str, prompt_usuario: str, repo_name: str) -> Dict[str, Any]:
        """
        Versão SÍNCRONA da geração de resposta (útil para relatórios ou chamadas sem stream).
        """
        if not self.metadata_service or not self.llm_service or not self.github_service:
             return {"error": "Serviços não inicializados"}

        try:
            print(f"[RAGService-Sync] Query: '{prompt_usuario}'")
            contexto_llm, fontes_ui, instrucao = self._get_combined_context(user_id, prompt_usuario, repo_name)
            
            resposta_texto = self.llm_service.generate_rag_response(
                contexto=contexto_llm,
                prompt=prompt_usuario,
                instrucao_rag=instrucao
            )
            
            return {
                "response_type": "answer",
                "message": resposta_texto,
                "fontes": fontes_ui,
                "contexto": {"trechos": "Contexto híbrido processado."}
            }
            
        except Exception as e:
            print(f"[RAGService-Sync] ERRO: {e}")
            traceback.print_exc()
            return {"error": str(e)}

    def gerar_resposta_rag_stream(self, user_id: str, query: str, repo_name: str) -> Iterator[str]:
        """
        Versão STREAMING da geração de resposta (usada pelo Chat).
        """
        if not self.metadata_service or not self.llm_service or not self.github_service:
            yield f"Erro: Serviços dependentes falharam."
            return

        print(f"[RAGService-Stream] Query: '{query}'")
        
        try:
            # Reutiliza a lógica de busca unificada
            contexto_llm, fontes_ui, instrucao = self._get_combined_context(user_id, query, repo_name)

            # Envia as fontes primeiro (protocolo do frontend)
            yield json.dumps(fontes_ui) + "[[SOURCES_END]]"
            
            # Gera o texto via stream
            for token in self.llm_service.generate_rag_response_stream(
                contexto=contexto_llm,
                prompt=query,
                instrucao_rag=instrucao
            ):
                yield token
                
        except Exception as e:
            print(f"[RAGService-Stream] ERRO: {e}")
            traceback.print_exc()
            yield f"\n\n**Erro ao gerar resposta:** {e}"

# --- Instância Singleton ---
try:
    _rag_service_instance = RAGService()
    gerar_resposta_rag = _rag_service_instance.gerar_resposta_rag
    gerar_resposta_rag_stream = _rag_service_instance.gerar_resposta_rag_stream
except Exception as e:
    print(f"[RAGService] FALHA AO INICIALIZAR: {e}")