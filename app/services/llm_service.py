# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/llm_service.py
# (Fix: Permite passagem de URLs completas com /tree/ para suporte a branches)

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
        
        self.routing_model = "gpt-4o-mini"
        self.generation_model = model 
        
        self.client = OpenAI(api_key=self.api_key)
        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # --- DEFINIÇÃO DE FERRAMENTAS ---
        
        self.tool_send_onetime_report = {
            "type": "function",
            "function": {
                "name": "call_send_onetime_report_tool",
                "description": "Envia um relatório por EMAIL IMEDIATAMENTE.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "URL completa ou nome do repositório."},
                        "prompt_relatorio": {"type": "string", "description": "O assunto do relatório."},
                        "email_destino": {"type": "string", "description": "O email para envio."},
                    },
                    "required": ["repositorio", "prompt_relatorio", "email_destino"],
                },
            },
        }

        self.tool_ingest = {
            "type": "function",
            "function": {
                "name": "call_ingest_tool",
                "description": "Ingere/Atualiza o índice do repositório.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "A URL completa do GitHub (ex: https://github.com/user/repo/tree/dev) ou apenas user/repo."}
                    },
                    "required": ["repositorio"]
                }
            }
        }
        
        self.tool_query = {
            "type": "function",
            "function": {
                "name": "call_query_tool",
                "description": "Responde perguntas no chat sobre o código.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "URL ou nome do repositório."},
                        "prompt_usuario": {"type": "string", "description": "A pergunta do usuário."}
                    },
                    "required": ["repositorio", "prompt_usuario"],
                },
            },
        }

        self.tool_report = {
            "type": "function",
            "function": {
                "name": "call_report_tool",
                "description": "Gera relatório para DOWNLOAD (arquivo).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "URL ou nome do repositório."},
                        "prompt_usuario": {"type": "string", "description": "Descrição do relatório."}
                    },
                    "required": ["repositorio", "prompt_usuario"],
                },
            },
        }

        self.tool_schedule = {
            "type": "function",
            "function": {
                "name": "call_schedule_tool",
                "description": "Agenda relatórios futuros.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "URL ou nome do repositório."},
                        "prompt_relatorio": {"type": "string", "description": "Foco do relatório."},
                        "frequencia": {"type": "string", "description": "'diariamente', 'semanalmente', 'mensalmente'."},
                        "hora": {"type": "string", "description": "Hora HH:MM."},
                        "timezone": {"type": "string", "description": "Fuso horário."}
                    },
                    "required": ["repositorio", "prompt_relatorio", "frequencia", "hora"]
                }
            }
        }
        
        self.tool_save_instruction = {
            "type": "function",
            "function": {
                "name": "call_save_instruction_tool",
                "description": "Salva instrução/template.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "URL ou nome do repositório."},
                        "instrucao": {"type": "string", "description": "Texto da instrução."}
                    },
                    "required": ["repositorio", "instrucao"],
                },
            },
        }

        self.tool_chat = {
            "type": "function",
            "function": {
                "name": "call_chat_tool",
                "description": "Bate-papo casual.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Texto do usuário."}
                    },
                },
            },
        }

        self.tools = [
            self.tool_ingest,
            self.tool_query,
            self.tool_report,
            self.tool_send_onetime_report,
            self.tool_schedule,
            self.tool_save_instruction,
            self.tool_chat
        ]

        self.tool_map = {
            "call_ingest_tool": self.tool_ingest,
            "call_query_tool": self.tool_query,
            "call_report_tool": self.tool_report,
            "call_send_onetime_report_tool": self.tool_send_onetime_report,
            "call_schedule_tool": self.tool_schedule,
            "call_save_instruction_tool": self.tool_save_instruction,
            "call_chat_tool": self.tool_chat
        }

    def _handle_tool_call_args(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        name = tool_call.get('function', {}).get('name')
        args = tool_call.get('function', {}).get('arguments', {})
        
        if name == "call_schedule_tool":
            if 'timezone' not in args or not args['timezone']:
                args['timezone'] = 'America/Sao_Paulo'
        
        # --- CORREÇÃO CRÍTICA ---
        # Removemos a lógica de 'parse manual' da URL aqui.
        # Agora passamos a URL inteira para o GithubService lidar com branches.
        if 'repositorio' in args:
            print(f"[LLMService] Repositório preservado (raw): {args['repositorio']}")
            # A validação se é URL ou user/repo acontece no GithubService.parse_repo_url

        return args

    def get_intent(self, user_query: str) -> Dict[str, Any]:
        if not self.client:
            raise Exception("LLMService não inicializado")
        
        print(f"[LLMService] Roteando: '{user_query}'")
        
        # PROMPT OTIMIZADO PARA NÃO CORTRAR URLs
        system_prompt = f"""
Você é um roteador de intenções do GitRAG.

IMPORTANTE SOBRE REPOSITÓRIOS:
1. Se o usuário fornecer uma URL (ex: 'https://github.com/user/repo/tree/dev'), passe a URL COMPLETA como argumento. NÃO TENTE EXTRAIR APENAS O NOME.
2. Se fornecer apenas 'user/repo', use isso.
3. Se não fornecer, deixe o campo vazio.

DECISÃO DE FERRAMENTAS:
- EMAIL AGORA -> call_send_onetime_report_tool
- AGENDAR -> call_schedule_tool
- DOWNLOAD/RELATÓRIO -> call_report_tool
- PERGUNTA SOBRE CÓDIGO -> call_query_tool
- INGESTÃO/ATUALIZAR -> call_ingest_tool
- PAPO FURADO -> call_chat_tool

Data Hoje: {datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%Y-%m-%d')}.
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.routing_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                tools=self.tools,
                tool_choice="auto" 
            )
            
            message = response.choices[0].message
            tool_calls = message.tool_calls

            if not tool_calls:
                return {
                    "type": "simple_chat", 
                    "response_text": message.content or "Entendido."
                }

            steps = []
            for call in tool_calls:
                try:
                    args = json.loads(call.function.arguments)
                    
                    # Processa argumentos sem destruir a URL
                    args_with_fallback = self._handle_tool_call_args({
                        'function': {'name': call.function.name, 'arguments': args}
                    })
                    
                    steps.append({
                        "intent": call.function.name,
                        "args": args_with_fallback
                    })
                except json.JSONDecodeError:
                    return {"type": "clarify", "response_text": "Erro ao processar argumentos."}
            
            # Validação simples
            for step in steps:
                if step["intent"] != "call_chat_tool":
                    required = self.tool_map[step["intent"]]["function"]["parameters"]["required"]
                    for param in required:
                        if not step["args"].get(param): 
                            return {
                                "type": "clarify",
                                "response_text": f"Preciso que você informe o {param}."
                            }

            return {"type": "multi_step", "steps": steps}

        except Exception as e:
            print(f"[LLMService] Erro: {e}")
            return {"type": "clarify", "response_text": f"Erro interno: {e}"}

    # --- MÉTODOS DE GERAÇÃO (Mantidos) ---
    def generate_response(self, query: str, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.client: raise Exception("LLMService não inicializado.")
        formatted_context = self._format_context(context)
        try:
            response = self.client.chat.completions.create(
                model=self.generation_model,
                messages=[
                    {"role": "system", "content": "Responda com base no contexto."},
                    {"role": "user", "content": f"Contexto:\n{formatted_context}\n\nConsulta: {query}"}
                ], temperature=0.1
            )
            return {"response": response.choices[0].message.content, "usage": response.usage}
        except Exception as e: return {"response": f"Erro: {e}", "usage": None}

    def generate_response_stream(self, query: str, context: List[Dict[str, Any]]) -> Iterator[str]:
        if not self.client: raise Exception("LLMService não inicializado.")
        formatted_context = self._format_context(context)
        try:
            stream = self.client.chat.completions.create(
                model=self.generation_model,
                messages=[
                    {"role": "system", "content": "Responda com base no contexto."},
                    {"role": "user", "content": f"Contexto:\n{formatted_context}\n\nConsulta: {query}"}
                ], stream=True, temperature=0.1
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content: yield content
        except Exception as e: yield f"Erro: {e}"

    def generate_analytics_report(self, repo_name: str, user_prompt: str, raw_data: List[Dict[str, Any]]) -> str:
        context_json = json.dumps(raw_data)
        try:
            response = self.client.chat.completions.create(
                model=self.generation_model, 
                messages=[
                    {"role": "system", "content": "Gere um JSON com 'analysis_markdown' e 'chart_json'."},
                    {"role": "user", "content": f"Repo: {repo_name}\nPrompt: {user_prompt}\nDados: {context_json}"}
                ],
                response_format={"type": "json_object"}, temperature=0.3, max_tokens=4000
            )
            return response.choices[0].message.content
        except Exception as e: return json.dumps({"analysis_markdown": f"Erro: {e}", "chart_json": None})

    def generate_simple_response(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.routing_model, 
                messages=[{"role": "system", "content": "Seja breve."}, {"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=50
            )
            return response.choices[0].message.content
        except Exception: return "👍"

    # --- HELPERS ---
    def get_token_usage(self) -> Dict[str, int]: return self.token_usage
    
    def _format_requirements_data(self, requirements_data: List[Dict[str, Any]]) -> str:
        return json.dumps(requirements_data, indent=2, ensure_ascii=False) if requirements_data else "Sem dados."

    def _format_context(self, context: List[Dict[str, Any]]) -> str:
        return "\n".join([f"---\nConteúdo: {doc.get('conteudo', doc.get('text', ''))}" for doc in context]) if context else "Nenhum contexto."

    def summarize_plan_for_confirmation(self, steps: List[Dict[str, Any]], user_email: str) -> str:
        plan_text = ""
        for step in steps:
            intent = step['intent'].replace('call_', '').replace('_tool', '')
            args = step['args']
            repo = args.get('repositorio', 'N/A')
            
            if intent == 'ingest': plan_text += f"* Ingerir **{repo}**.\n"
            elif intent == 'query': plan_text += f"* Consultar: '{args.get('prompt_usuario')}' in {repo}.\n"
            elif intent == 'report': plan_text += f"* Gerar relatório (Download) de **{repo}**.\n"
            elif intent == 'send_onetime_report': plan_text += f"* Enviar email **IMEDIATAMENTE** para **{args.get('email_destino')}** (Repo: {repo}).\n"
            elif intent == 'schedule': plan_text += f"* Agendar envio ({args.get('frequencia')}) de **{repo}** para {args.get('user_email') or user_email}.\n"
            elif intent == 'save_instruction': plan_text += f"* Salvar instrução para {repo}.\n"
            
        return f"**Plano:**\n{plan_text}\n**Confirma?** (Sim/Não)"

    def summarize_action_for_confirmation(self, intent_name: str, args: Dict[str, Any]) -> str:
        return f"Confirmar: {intent_name}?"