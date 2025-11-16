# CÓDIGO COMPLETO PARA: app/services/llm_service.py
# (Adicionada verificação de NoneType da OpenAI)

import os
import json
import pytz
from datetime import datetime
from openai import OpenAI
from typing import List, Dict, Any, Optional, Iterator

class LLMService:
    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Chave da API OpenAI não fornecida")
        self.model = model
        self.client = OpenAI(api_key=self.api_key)
        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        # (Definições de ferramentas omitidas por brevidade)
        self.intent_tools = [
            {"type": "function", "function": {"name": "call_ingest_tool", "description": "Usado para ingerir um repositório...", "parameters": ...}},
            {"type": "function", "function": {"name": "call_query_tool", "description": "Usado para perguntas sobre um repositório...", "parameters": ...}},
            {"type": "function", "function": {"name": "call_report_tool", "description": "Usado para pedir um 'relatório' ou 'gráfico'...", "parameters": ...}},
            {"type": "function", "function": {"name": "call_schedule_tool", "description": "Usado para agendar um relatório...", "parameters": ...}},
            {"type": "function", "function": {"name": "call_save_instruction_tool", "description": "Usado para salvar uma instrução...", "parameters": ...}},
        ]
        # (Definições de ferramentas colapsadas - o código é o mesmo do Marco 7)
        self.intent_tools = [
            {
                "type": "function",
                "function": {
                    "name": "call_ingest_tool",
                    "description": "Usado quando o usuário quer ingerir, re-ingerir ou indexar um repositório. Extrai 'usuario/repo' de URLs completas.",
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
                    "description": "Usado para perguntas sobre um repositório. Ex: 'quem fez mais commits no usuario/repo' OU 'me fale sobre https://github.com/usuario/repo'.",
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
                    "description": "Usado para pedir um 'relatório' ou 'gráfico' para download *imediato*.",
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
                            "frequencia": {"type": "string", "enum": ["daily", "weekly", "monthly"], "description": "A frequência."},
                            "hora": {"type": "string", "description": "A hora no formato HH:MM (24h)."},
                            "timezone": {"type": "string", "description": "O fuso horário (ex: 'America/Sao_Paulo')."}
                        },
                        "required": ["repositorio", "prompt_relatorio", "frequencia", "hora", "timezone"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "call_save_instruction_tool",
                    "description": "Usado para salvar uma instrução para futuros relatórios. Extrai 'usuario/repo' de URLs completas.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "repositorio": {"type": "string", "description": "O repositório ao qual esta instrução se aplica."},
                            "instrucao": {"type": "string", "description": "A instrução específica que o usuário quer salvar."}
                        },
                        "required": ["repositorio", "instrucao"],
                    },
                },
            },
        ]

    def get_intent(self, user_query: str) -> Dict[str, Any]:
        # (Sem alterações)
        if not self.client: raise Exception("LLMService não inicializado.")
        print(f"[LLMService] Classificando intenção para: '{user_query}'")
        system_prompt = f"""
Você é um roteador de API. Sua tarefa é analisar o prompt do usuário e chamar a ferramenta correta.
REGRAS IMPORTANTES:
1.  **Extração de Repositório:** Se o usuário fornecer uma URL completa do GitHub (ex: `https://github.com/usuario/repo`), você DEVE extrair apenas o nome `usuario/repo` para o parâmetro 'repositorio'.
2.  **Fuso Horário:** ... (fuso de Brasília) ...
3.  **Data Atual:** ...
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
            return {"intent": function_name, "args": function_args}
        except Exception as e:
            print(f"[LLMService] Erro CRÍTICO ao classificar intenção: {e}")
            raise Exception(f"Erro ao processar sua solicitação na LLM: {e}")
    
    def generate_response(self, query: str, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        # (Sem alterações)
        formatted_context = self._format_context(context)
        system_prompt = "..."
        user_prompt = f"Contexto:\n{formatted_context}\n\nConsulta: \"{query}\"\n..."
        response = self.client.chat.completions.create(...)
        usage = response.usage
        self.token_usage["prompt_tokens"] += usage.prompt_tokens
        # ...
        return {"response": response.choices[0].message.content, "usage": ...}

    def generate_response_stream(self, query: str, context: List[Dict[str, Any]]) -> Iterator[str]:
        # (Sem alterações)
        if not self.client: raise Exception("LLMService não inicializado.")
        print("[LLMService] Iniciando resposta em STREAMING...")
        formatted_context = self._format_context(context)
        system_prompt = "..."
        user_prompt = f"Contexto:\n{formatted_context}\n\nConsulta: \"{query}\"\n..."
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[...],
                stream=True
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except Exception as e:
            print(f"[LLMService] Erro durante o streaming: {e}")
            yield f"\n\n**Erro ao gerar resposta:** {e}"

    
    def generate_analytics_report(self, repo_name: str, user_prompt: str, raw_data: List[Dict[str, Any]]) -> str:
        # (Função principal do relatório)
        context_json_string = json.dumps(raw_data)
        system_prompt = f"""
Você é um analista de dados...
REGRAS OBRIGATÓRIAS:
1.  **Formato:** O relatório final DEVE ser um ÚNICO objeto JSON.
2.  **Estrutura JSON:** `"analysis_markdown"` e `"chart_json"`...
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
                temperature=0.3, max_tokens=4000
            )
            
            # --- INÍCIO DA CORREÇÃO (Robustez) ---
            response_content = response.choices[0].message.content
            
            if not response_content:
                # Se a OpenAI retornar None (ex: filtro de conteúdo),
                # nós criamos um JSON de erro.
                print("[LLMService] ERRO: OpenAI retornou None (provável filtro de conteúdo).")
                return json.dumps({
                    "analysis_markdown": "# Erro de Geração\n\nA IA não conseguiu gerar uma resposta. Isso pode ter sido causado por filtros de conteúdo ou uma falha na API.",
                    "chart_json": None
                })
            
            # Atualiza os tokens
            usage = response.usage
            self.token_usage["prompt_tokens"] += usage.prompt_tokens
            self.token_usage["completion_tokens"] += usage.completion_tokens
            self.token_usage["total_tokens"] += usage.total_tokens
            
            return response_content # Retorna a string JSON
            # --- FIM DA CORREÇÃO ---

        except Exception as e:
            print(f"[LLMService] Erro ao gerar relatório JSON: {e}")
            return json.dumps({
                "analysis_markdown": f"# Erro\n\nNão foi possível gerar a análise: {e}",
                "chart_json": None
            })

    # (Funções _format e get_token_usage sem alterações)
    def get_token_usage(self) -> Dict[str, int]: ...
    def _format_context(self, context: List[Dict[str, Any]]) -> str: ...
    def _format_requirements_data(self, requirements_data: List[Dict[str, Any]]) -> str: ...