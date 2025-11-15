# CÓDIGO COMPLETO PARA: app/services/llm_service.py
# (Adicionada a função 'get_intent' com 'OpenAI Tools' para roteamento)

import os
import json
from openai import OpenAI
from typing import List, Dict, Any, Optional

class LLMService:
    """
    Serviço para integração com modelos de linguagem grandes (LLMs).
    """
    
    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini"):
        """
        Inicializa o serviço LLM.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Chave da API OpenAI não fornecida")
        
        self.model = model
        self.client = OpenAI(api_key=self.api_key)
        
        # Contador para monitoramento de uso
        self.token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }

        # --- NOVO: Definição das Ferramentas para o Roteador de Intenção ---
        self.intent_tools = [
            {
                "type": "function",
                "function": {
                    "name": "call_ingest_tool",
                    "description": "Usado quando o usuário quer ingerir, re-ingerir ou indexar um repositório.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repositorio": {
                                "type": "string",
                                "description": "O nome do repositório no formato 'usuario/nome'.",
                            }
                        },
                        "required": ["repositorio"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_query_tool",
                    "description": "Usado quando o usuário faz uma pergunta geral sobre um repositório (ex: 'quem...', 'o que...', 'me fale sobre...').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repositorio": {
                                "type": "string",
                                "description": "O nome do repositório no formato 'usuario/nome'.",
                            },
                            "prompt_usuario": {
                                "type": "string",
                                "description": "A pergunta específica do usuário.",
                            }
                        },
                        "required": ["repositorio", "prompt_usuario"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_report_tool",
                    "description": "Usado quando o usuário pede explicitamente um 'relatório', 'gráfico' ou 'análise' para download.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repositorio": {
                                "type": "string",
                                "description": "O nome do repositório no formato 'usuario/nome'.",
                            },
                            "prompt_usuario": {
                                "type": "string",
                                "description": "A instrução para o relatório (ex: 'gere um gráfico de pizza dos commits').",
                            }
                        },
                        "required": ["repositorio", "prompt_usuario"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_schedule_tool",
                    "description": "Usado quando o usuário quer agendar um relatório para o futuro (ex: 'todo dia', 'às 17h').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "instrucao_agendamento": {
                                "type": "string",
                                "description": "O prompt completo do usuário sobre o agendamento.",
                            }
                        },
                        "required": ["instrucao_agendamento"],
                    },
                },
            },
        ]

    # --- NOVA FUNÇÃO: O Roteador de Intenção ---
    def get_intent(self, user_query: str) -> Dict[str, Any]:
        """
        Usa a LLM e 'Tools' para classificar a intenção do usuário
        e extrair as entidades necessárias.
        """
        if not self.client:
            raise Exception("LLMService não inicializado.")
            
        print(f"[LLMService] Classificando intenção para: '{user_query}'")

        system_prompt = "Você é um roteador de API. Sua tarefa é analisar o prompt do usuário e chamar a ferramenta correta com os parâmetros corretos. Se o repositório não for mencionado, pergunte ao usuário."

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                tools=self.intent_tools,
                tool_choice="auto" # Deixa a OpenAI decidir a ferramenta
            )

            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            # --- Verificação de Erro 1: A LLM não escolheu uma ferramenta ---
            if not tool_calls:
                print(f"[LLMService] Nenhuma ferramenta chamada. A LLM respondeu: {response_message.content}")
                # A LLM pode estar pedindo mais informações (ex: qual repositório?)
                return {"intent": "CLARIFY", "response_text": response_message.content}

            # --- Sucesso: A LLM escolheu uma ferramenta ---
            tool_call = tool_calls[0] # Pegamos a primeira ferramenta
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)

            print(f"[LLMService] Intenção classificada: {function_name}")
            
            # Retorna um dicionário unificado
            return {
                "intent": function_name,
                "args": function_args
            }

        except Exception as e:
            print(f"[LLMService] Erro CRÍTICO ao classificar intenção: {e}")
            raise Exception(f"Erro ao processar sua solicitação na LLM: {e}")
    
    # --- FUNÇÃO EXISTENTE (generate_response) ---
    # (Não muda, mas agora é chamada pelo RAGService)
    def generate_response(self, query: str, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Gera uma resposta contextual usando o LLM.
        """
        formatted_context = self._format_context(context)
        
        system_prompt = """
Você é um assistente de engenharia de software de elite. Sua especialidade é 
analisar o contexto de um repositório GitHub (commits, issues, PRs) e 
responder perguntas sobre rastreabilidade de requisitos.

REGRAS DE FORMATAÇÃO OBRIGATÓRIAS:
1.  **Formato de Resposta:** Sempre formate sua resposta em Markdown.
2.  **Seja Direto:** Responda à pergunta do usuário diretamente.
3.  **CITE SUAS FONTES:** Esta é a regra mais importante. Ao citar uma fonte, você DEVE usar os metadados 'URL' (que estão no contexto) para criar um link Markdown clicável.
4.  **RELAÇÕES:** Se um commit (no seu texto) menciona "Fixes #123", você DEVE fazer a relação com a Issue correspondente, se ela também estiver no contexto.
5.  **PERGUNTAS CRONOLÓGICAS:** Se o usuário perguntar sobre "último", "mais recente" ou "primeiro", você DEVE usar os metadados 'Data' (que estão no contexto) para determinar a ordem correta antes de responder.
EXEMPLO DE FORMATAÇÃO CORRETA (Use este padrão):
- A funcionalidade X foi implementada por fulano no commit [a4f5c6d](https://github.com/usuario/repo/commit/a4f5c6d3...).
- Isso foi discutido na Issue [#123](https://github.com/usuario/repo/issues/123).
- Veja também a Pull Request [#45](https://github.com/usuario/repo/pull/45).

EXEMPLO DE FORMATAÇÃO INCORRETA (NUNCA FAÇA ISSO):
- A funcionalidade foi feita no commit usuario_repo/a4f5c6d.
"""
        
        user_prompt = f"""
        Contexto do Repositório:
        ---
        {formatted_context}
        ---
        
        Consulta do Usuário:
        "{query}"
        
        Com base APENAS no contexto acima, responda à consulta do usuário seguindo 
        TODAS as regras do seu prompt de sistema.
        """
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3, 
            max_tokens=1000
        )
        
        usage = response.usage
        self.token_usage["prompt_tokens"] += usage.prompt_tokens
        self.token_usage["completion_tokens"] += usage.completion_tokens
        self.token_usage["total_tokens"] += usage.total_tokens
        
        return {
            "response": response.choices[0].message.content,
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens
            }
        }
    
    # --- FUNÇÃO EXISTENTE (generate_analytics_report) ---
    # (Corrigida para usar 'pie' chart)
    def generate_analytics_report(self, repo_name: str, user_prompt: str, raw_data: List[Dict[str, Any]]) -> str:
        """
        Gera um relatório de análise de dados (analytics) com base
        em um prompt do usuário e dados brutos do SQL.
        """
        
        context_json_string = json.dumps(raw_data)
        
        # --- CORREÇÃO DO PROMPT (para 'pie' chart) ---
        system_prompt = f"""
Você é um analista de dados e engenheiro de software de elite, 
especializado em analisar repositórios GitHub.
Sua tarefa é responder a uma pergunta do usuário (prompt) usando um 
conjunto de dados brutos (em JSON) fornecido.

REGRAS OBRIGATÓRIAS:
1.  **Formato:** O relatório final DEVE ser em Markdown.
2.  **Seja Analítico:** Não apenas liste dados, gere *insights* que 
    respondam diretamente ao prompt do usuário.
3.  **Use os Dados:** Baseie sua análise APENAS nos dados JSON fornecidos.
4.  **GRÁFICOS (Regra mais importante):** Para visualização de dados 
    (como contagem de commits por autor), você DEVE gerar um 
    GRÁFICO DE PIZZA (pie chart) usando a sintaxe 'pie' do Mermaid.
    
    NÃO USE 'graph TD'. Use APENAS a sintaxe 'pie'.

    Exemplo OBRIGATÓRIO de Gráfico de Pizza:
    ```mermaid
    pie title Contribuições por Autor
        "Autor A": 30
        "Autor B": 10
        "Autor C": 3
    ```
"""
        
        final_user_prompt = f"""
Contexto do Repositório: {repo_name}

Prompt do Usuário:
"{user_prompt}"

---
Dados Brutos (JSON):
{context_json_string}
---

Gere um relatório completo em Markdown que responda ao prompt do usuário,
usando os dados brutos e incluindo um gráfico de pizza (pie chart) Mermaid.js.
"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": final_user_prompt}
            ],
            temperature=0.3,
            max_tokens=4000
        )
        
        usage = response.usage
        self.token_usage["prompt_tokens"] += usage.prompt_tokens
        self.token_usage["completion_tokens"] += usage.completion_tokens
        self.token_usage["total_tokens"] += usage.total_tokens
        
        return response.choices[0].message.content
    
    # --- Funções existentes (não mudam) ---
    def get_token_usage(self) -> Dict[str, int]:
        return self.token_usage
    
    def _format_context(self, context: List[Dict[str, Any]]) -> str:
        # (Esta função permanece inalterada)
        formatted = ""
        for i, doc in enumerate(context):
            doc_type = doc.get("metadata", {}).get("type", "documento")
            doc_id = doc.get("metadata", {}).get("id", i)
            if doc_type == "issue":
                formatted += f"Issue #{doc_id}: {doc.get('metadata', {}).get('title', '')}\nURL: {doc.get('metadata', {}).get('url', '')}\nData: {doc.get('metadata', {}).get('created_at', '')}\nConteúdo: {doc.get('text', '')}\n\n"
            elif doc_type == "pull_request":
                formatted += f"Pull Request #{doc_id}: {doc.get('metadata', {}).get('title', '')}\nURL: {doc.get('metadata', {}).get('url', '')}\nData: {doc.get('metadata', {}).get('created_at', '')}\nConteúdo: {doc.get('text', '')}\n\n"
            elif doc_type == "commit":
                formatted += f"Commit {doc.get('metadata', {}).get('sha', '')[:7]}\nURL: {doc.get('metadata', {}).get('url', '')}\nAutor: {doc.get('metadata', {}).get('author', '')}\nData: {doc.get('metadata', {}).get('date', '')}\nMensagem: {doc.get('text', '')}\n\n"
            else:
                formatted += f"Documento {i+1}:\n{doc.get('text', '')}\n\n"
        return formatted
    
    def _format_requirements_data(self, requirements_data: List[Dict[str, Any]]) -> str:
        # (Esta função permanece inalterada)
        formatted = ""
        for i, req in enumerate(requirements_data):
            formatted += f"Requisito {i+1}: {req.get('title', '')}\nDescrição: {req.get('description', '')}\n"
            if "issues" in req and req["issues"]:
                formatted += "Issues relacionadas:\n"
                for issue in req["issues"]:
                    formatted += f"- Issue #{issue.get('id')}: {issue.get('title')}\n"
            if "pull_requests" in req and req["pull_requests"]:
                formatted += "Pull Requests relacionados:\n"
                for pr in req["pull_requests"]:
                    formatted += f"- PR #{pr.get('id')}: {pr.get('title')}\n"
            if "commits" in req and req["commits"]:
                formatted += "Commits relacionados:\n"
                for commit in req["commits"]:
                    formatted += f"- {commit.get('sha')[:7]}: {commit.get('message')}\n"
            formatted += "\n"
        return formatted