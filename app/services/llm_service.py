# CÓDIGO COMPLETO PARA: app/services/llm_service.py
# (Adicionada a função 'generate_response_stream')

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
        
        self.token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }

        # Definição das Ferramentas (Sem alterações)
        self.intent_tools = [
            {"type": "function", "function": {"name": "call_ingest_tool", ...}},
            {"type": "function", "function": {"name": "call_query_tool", ...}},
            {"type": "function", "function": {"name": "call_report_tool", ...}},
            {"type": "function", "function": {"name": "call_schedule_tool", ...}},
            {"type": "function", "function": {"name": "call_save_instruction_tool", ...}},
        ]
        # (Definições de ferramentas omitidas por brevidade)
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
2.  **Fuso Horário:** Se o usuário mencionar um fuso horário (ex: 'Brasília'), use a formatação IANA (ex: 'America/Sao_Paulo'). Se nenhum fuso horário for mencionado, assuma 'America/Sao_Paulo'.
3.  **Data Atual:** A data atual (contexto) é: {datetime.now(pytz.utc).astimezone(pytz.timezone('America/Sao_Paulo')).isoformat()}
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
        system_prompt = """...""" # (prompt do sistema omitido por brevidade)
        user_prompt = f"Contexto:\n{formatted_context}\n\nConsulta: \"{query}\"\nResponda com base no contexto."
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3, max_tokens=1000
        )
        usage = response.usage
        self.token_usage["prompt_tokens"] += usage.prompt_tokens
        self.token_usage["completion_tokens"] += usage.completion_tokens
        self.token_usage["total_tokens"] += usage.total_tokens
        return {"response": response.choices[0].message.content, "usage": ...}

    # --- NOVA FUNÇÃO (Marco 8 - Streaming) ---
    def generate_response_stream(self, query: str, context: List[Dict[str, Any]]) -> Iterator[str]:
        """
        Gera uma resposta contextual (RAG) em modo STREAMING.
        Cede (yields) os tokens de texto à medida que são recebidos.
        """
        if not self.client:
            raise Exception("LLMService não inicializado.")
            
        print("[LLMService] Iniciando resposta em STREAMING...")
        
        # Formata o contexto (igual à função não-stream)
        formatted_context = self._format_context(context)
        system_prompt = """
Você é um assistente de engenharia de software de elite. Sua especialidade é 
analisar o contexto de um repositório GitHub (commits, issues, PRs) e 
responder perguntas sobre rastreabilidade de requisitos.
REGRAS DE FORMATAÇÃO OBRIGATÓRIAS:
1.  **Formato de Resposta:** Sempre formate sua resposta em Markdown.
2.  **Seja Direto:** Responda à pergunta do usuário diretamente.
3.  **CITE SUAS FONTES:** Esta é a regra mais importante. Ao citar uma fonte, você DEVE usar os metadados 'URL' (que estão no contexto) para criar um link Markdown clicável.
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
        
        try:
            # 1. Chama a API com stream=True
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=1000,
                stream=True # <-- A MÁGICA ACONTECE AQUI
            )
            
            # 2. Itera sobre os "chunks" (pedaços) da resposta
            for chunk in stream:
                # Pega o conteúdo (o token de texto)
                content = chunk.choices[0].delta.content
                if content:
                    # 3. Cede (yield) o token para o chamador
                    yield content
                    
        except Exception as e:
            print(f"[LLMService] Erro durante o streaming: {e}")
            yield f"\n\n**Erro ao gerar resposta:** {e}"

    # (O restante do arquivo: generate_analytics_report, get_token_usage, _format_context, etc.
    #  permanece o mesmo do Marco 7)
    # ...
    def generate_analytics_report(self, repo_name: str, user_prompt: str, raw_data: List[Dict[str, Any]]) -> str: ...
    def get_token_usage(self) -> Dict[str, int]: ...
    def _format_context(self, context: List[Dict[str, Any]]) -> str: ...
    def _format_requirements_data(self, requirements_data: List[Dict[str, Any]]) -> str: ...