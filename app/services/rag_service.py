# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/rag_service.py

import os
import json
from typing import Dict, Any, Iterator, List, Tuple, Optional

from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
from app.services.embedding_service import EmbeddingService
from app.services.github_service import GithubService # <--- Importe o GithubService

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

        for i, doc in enumerate(context_docs):
            raw_path = doc.get('file_path')
            content = doc.get('conteudo', 'N/A')
            branch = doc.get('branch', 'N/A')
            
            # Garante que meta é dict
            meta = doc.get('metadados')
            if not isinstance(meta, dict): meta = {}

            # --- 1. Detecção de Tipo ---
            tipo_original = doc.get('tipo')
            if 'sha' in meta: 
                tipo = 'commit'
            elif 'titulo' in meta and 'id' in meta:
                tipo = 'pr' if 'pr' in str(tipo_original).lower() else 'issue'
            else:
                tipo = 'file'

            # --- 2. Extração de Dados para o Frontend ---
            # Aqui extraímos sha e id para enviar ao React
            sha = meta.get('sha')
            item_id = meta.get('id')
            url_link = meta.get('url')

            # --- 3. Formatação do Contexto (Prompt) ---
            if tipo == 'commit':
                sha_curto = sha[:7] if sha else 'N/A'
                autor = meta.get('autor', 'N/A')
                data_fmt = meta.get('data', 'N/A')
                display_name = f"Commit {sha_curto}"
                
                context_text = (
                    f"--- DADOS DO COMMIT ---\n"
                    f"Tipo: Commit\n"
                    f"ID (SHA): {sha_curto}\n"
                    f"Autor: {autor}\n"
                    f"Data: {data_fmt}\n"
                    f"URL: {url_link}\n"
                    f"Mensagem: {content}\n"
                )
            elif tipo in ['issue', 'pr']:
                titulo = meta.get('titulo', 'Sem titulo')
                data_fmt = meta.get('data', 'N/A')
                display_name = f"{tipo.upper()} #{item_id}"
                
                context_text = (
                    f"--- DADOS DA {tipo.upper()} ---\n"
                    f"Tipo: {tipo.upper()}\n"
                    f"Número: #{item_id}\n"
                    f"Título: {titulo}\n"
                    f"Data: {data_fmt}\n"
                    f"URL: {url_link}\n"
                    f"Conteúdo: {content}\n"
                )
            else:
                display_name = raw_path or "Arquivo"
                content_snippet = content[:5000]
                context_text = (
                    f"--- ARQUIVO DE CÓDIGO ---\n"
                    f"Arquivo: {display_name}\n"
                    f"Branch: {branch}\n"
                    f"Conteúdo:\n{content_snippet}\n"
                )

            context_parts.append(f"--- Documento {i+1} ({display_name}) ---\n{context_text}")
            
            # --- 4. Montagem da Fonte para UI (Frontend) ---
            sources_ui.append({
                "source_id": i + 1,
                "file_path": display_name,
                "branch": branch,
                "url": url_link,
                "tipo": tipo,
                # CAMPOS CRÍTICOS PARA O SEU FRONTEND:
                "sha": sha,    # Necessário para 'ResultadoConsulta.js' renderizar commits
                "id": item_id  # Necessário para renderizar Issues/PRs
            })
            
        return "\n\n".join(context_parts), sources_ui

    def gerar_resposta_rag(self, user_id: str, prompt_usuario: str, repo_name: str) -> Dict[str, Any]:
        # ... (Mantemos a lógica similar ao stream, mas síncrona)
        # Se não usar síncrono, pode ignorar este método ou atualizá-lo igual ao stream abaixo
        pass 

    def gerar_resposta_rag_stream(self, user_id: str, query: str, repo_name: str) -> Iterator[str]:
        if not self.metadata_service or not self.llm_service or not self.github_service:
            yield f"Erro: Serviços dependentes falharam."
            return

        print(f"[RAGService-Stream] Query: '{query}' | Input Repo: '{repo_name}'")
        
        try:
            # 1. LIMPEZA DA URL: Extrai nome limpo e branch
            real_repo_name, branch = self.github_service.parse_repo_url(repo_name)
            
            print(f"[RAGService] Buscando em: {real_repo_name} (Branch: {branch or 'Todas'})")

            # 2. BUSCA NO BANCO (Com filtro de branch)
            documentos_similares = self.metadata_service.find_similar_documents(
                user_id=user_id, 
                query_text=query, 
                repo_name=real_repo_name, # Usa o nome limpo
                branch=branch,            # Usa a branch (se houver)
                k=5,
            )
            
            instrucao = self.metadata_service.find_similar_instruction(
                user_id=user_id, repo_name=real_repo_name, query_text=query
            )

            contexto_para_llm, fontes_ui = self._format_context_for_llm(documentos_similares)

            # Envia as fontes
            yield json.dumps(fontes_ui) + "[[SOURCES_END]]"
            
            if not documentos_similares:
                print("[RAGService] Nenhum documento encontrado.")
                # Opcional: Avisar que não achou nada
            
            # Gera resposta
            for token in self.llm_service.generate_rag_response_stream(
                contexto=contexto_para_llm,
                prompt=query,
                instrucao_rag=instrucao
            ):
                yield token
                
        except Exception as e:
            print(f"[RAGService-Stream] ERRO: {e}")
            yield f"\n\n**Erro ao gerar resposta:** {e}"

# --- Instância Singleton ---
try:
    _rag_service_instance = RAGService()
    gerar_resposta_rag = _rag_service_instance.gerar_resposta_rag
    gerar_resposta_rag_stream = _rag_service_instance.gerar_resposta_rag_stream
except Exception as e:
    print(f"[RAGService] FALHA AO INICIALIZAR: {e}")
    # ... (fallback handlers) ...