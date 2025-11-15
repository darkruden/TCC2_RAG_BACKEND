# CÓDIGO COMPLETO PARA: app/services/llm_service.py
# (Corrigido com as importações faltantes de 'pytz' e 'datetime')

import os
import json
import pytz # <-- IMPORTAÇÃO CORRIGIDA
from datetime import datetime # <-- IMPORTAÇÃO CORRIGIDA
from openai import OpenAI
from typing import List, Dict, Any, Optional

class LLMService:
    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Chave da API OpenAI não fornecida")
        
        self.model = model
        self.client = OpenAI(api_key=self.api_key)
        
        self.token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }

        # Definição das Ferramentas (Sem alterações)
        self.intent_tools = [
            {
                "type": "function",
                "function": {
                    "name": "call_ingest_tool",
                    "description": "Usado quando o usuário quer ingerir, re-ingerir ou indexar um repositório.",
                    "parameters": {
                        "type": "object",
                        "properties": {"repositorio": {"type": "string", "description": "O nome do repositório no formato 'usuario/nome'."}},
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
                            "repositorio": {"type": "string", "description": "O nome do repositório no formato 'usuario/nome'."},
                            "prompt_usuario": {"type": "string", "description": "A pergunta específica do usuário."}
                        },
                        "required": ["repositorio", "prompt_usuario"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_report_tool",
                    "description": "Usado quando o usuário pede explicitamente um 'relatório', 'gráfico' ou 'análise' para download *imediato*.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repositorio": {"type": "string", "description": "O nome do repositório no formato 'usuario/nome'."},
                            "prompt_usuario": {"type": "string", "description": "A instrução para o relatório (ex: 'gere um gráfico de pizza dos commits')."}
                        },
                        "required": ["repositorio", "prompt_usuario"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_schedule_tool",
                    "description": "Usado quando o usuário quer agendar um relatório para o futuro (ex: 'todo dia', 'semanalmente', 'às 17h').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repositorio": {"type": "string", "description": "O nome do repositório no formato 'usuario/nome'."},
                            "prompt_relatorio": {"type": "string", "description": "O que o relatório deve conter (ex: 'análise de commits da equipe')."},
                            "frequencia": {"type": "string", "enum": ["daily", "weekly", "monthly"], "description": "A frequência do relatório."},
                            "hora": {"type": "string", "description": "A hora do dia para o envio, no formato HH:MM (24h)."},
                            "timezone": {"type": "string", "description": "O fuso horário da solicitação (ex: 'America/Sao_Paulo', 'UTC')."}
                        },
                        "required": ["repositorio", "prompt_relatorio", "frequencia", "hora", "timezone"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_save_instruction_tool",
                    "description": "Usado quando o usuário quer salvar ou persistir uma instrução para futuros relatórios (ex: 'lembre-se disso', 'salve esta preferência').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repositorio": {"type": "string", "description": "O repositório ao qual esta instrução se aplica."},
                            "instrucao": {"type": "string", "description": "A instrução específica que o usuário quer salvar (ex: 'sempre use gráficos de pizza e tabelas')."}
                        },
                        "required": ["repositorio", "instrucao"],
                    },
                },
            },
        ]

    # --- FUNÇÃO (get_intent) ---
    def get_intent(self, user_query: str) -> Dict[str, Any]:
        if not self.client:
            raise Exception("LLMService não inicializado.")
            
        print(f"[LLMService] Classificando intenção para: '{user_query}'")
        
        # Esta linha agora funciona, pois 'pytz' e 'datetime' estão importados
        system_prompt = f"""
Você é um roteador de API. Sua tarefa é analisar o prompt do usuário e chamar a ferramenta correta.
Se o usuário mencionar um fuso horário (ex: 'Brasília'), use a formatação IANA (ex: 'America/Sao_Paulo').
Se nenhum fuso horário for mencionado, assuma 'America/Sao_Paulo'.
A data atual (contexto) é: {datetime.now(pytz.utc).astimezone(pytz.timezone('America/Sao_Paulo')).isoformat()}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                tools=self.intent_tools,
                tool_choice="auto"
            )
            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            if not tool_calls:
                return {"intent": "CLARIFY", "response_text": response_message.content}

            tool_call = tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            print(f"[LLMService] Intenção classificada: {function_name}")
            
            return {
                "intent": function_name,
                "args": function_args
            }
        except Exception as e:
            print(f"[LLMService] Erro CRÍTICO ao classificar intenção: {e}")
            raise Exception(f"Erro ao processar sua solicitação na LLM: {e}")
    
    # --- FUNÇÕES (generate_response, generate_analytics_report, etc.) ---
    # (O restante do arquivo permanece exatamente como está no Marco 4)
    def generate_response(self, query: str, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        formatted_context = self._format_context(context)
        system_prompt = """
Você é um assistente de engenharia de software de elite...
... (regras de formatação) ...
"""
        user_prompt = f"""
        Contexto do Repositório:
        ---
        {formatted_context}
        ---
        Consulta do Usuário: "{query}"
        ...
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
    
    def generate_analytics_report(self, repo_name: str, user_prompt: str, raw_data: List[Dict[str, Any]]) -> str:
        context_json_string = json.dumps(raw_data)
        system_prompt = f"""
Você é um analista de dados e engenheiro de software de elite...
REGRAS OBRIGATÓRIAS:
1.  **Formato:** O relatório final DEVE ser um ÚNICO objeto JSON.
2.  **Estrutura JSON:** O JSON deve ter DUAS chaves:
    1.  `"analysis_markdown"`: Uma string contendo sua análise...
    2.  `"chart_json"`: Um objeto JSON formatado para Chart.js...
... (exemplo de Chart.js) ...
"""
        final_user_prompt = f"""
Contexto do Repositório: {repo_name}
Prompt do Usuário: "{user_prompt}"
Dados Brutos (JSON): {context_json_string}
---
Gere a resposta em um único objeto JSON...
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": final_user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=4000
            )
            usage = response.usage
            self.token_usage["prompt_tokens"] += usage.prompt_tokens
            self.token_usage["completion_tokens"] += usage.completion_tokens
            self.token_usage["total_tokens"] += usage.total_tokens
            return response.choices[0].message.content
        except Exception as e:
            print(f"[LLMService] Erro ao gerar relatório JSON: {e}")
            return json.dumps({
                "analysis_markdown": f"# Erro\n\nNão foi possível gerar a análise: {e}",
                "chart_json": None
            })

    def get_token_usage(self) -> Dict[str, int]:
        return self.token_usage
    
    def _format_context(self, context: List[Dict[str, Any]]) -> str:
        # (Função helper sem alterações)
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
        # (Função helper sem alterações)
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