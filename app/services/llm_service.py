# CÓDIGO COMPLETO E DEFINITIVO PARA: app/services/llm_service.py
# (Inclui: Correção "Email Imediato" + Funções Auxiliares Restauradas)

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

        # 1. Ferramenta para enviar e-mail imediatamente (não agendado)
        self.tool_send_onetime_report = {
            "type": "function",
            "function": {
                "name": "call_send_onetime_report_tool",
                "description": (
                    "Usado quando o usuário quer **enviar imediatamente** um relatório por e-mail, "
                    "sem agendamento recorrente. Use para comandos como 'envie agora', 'não agende', 'mande o relatório por email'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "Nome completo do repositório GitHub (ex: user/repo)."},
                        "prompt_relatorio": {"type": "string", "description": "Prompt detalhado para gerar o relatório."},
                        "email_destino": {"type": "string", "description": "O endereço de e-mail para onde o relatório deve ser enviado imediatamente."},
                    },
                    "required": ["repositorio", "prompt_relatorio", "email_destino"],
                },
            },
        }

        # 2. Ingestão
        self.tool_ingest = {
            "type": "function",
            "function": {
                "name": "call_ingest_tool",
                "description": (
                    "Usado quando o usuário quer **explicitamente** ingerir, re-ingerir ou "
                    "atualizar o índice RAG de um repositório GitHub."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "O nome completo do repositório GitHub (ex: 'user/repo_name').", "pattern": "^[^/]+/[^/]+$"}
                    },
                    "required": ["repositorio"]
                }
            }
        }
        
        # 3. Consulta RAG (Chat)
        self.tool_query = {
            "type": "function",
            "function": {
                "name": "call_query_tool",
                "description": (
                    "Usado para perguntas sobre um repositório (RAG) respondidas no chat."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "O nome do repositório no formato 'usuario/nome'."},
                        "prompt_usuario": {"type": "string", "description": "A pergunta específica do usuário."}
                    },
                    "required": ["repositorio", "prompt_usuario"],
                },
            },
        }

        # 4. Relatório Download (Sem email)
        self.tool_report = {
            "type": "function",
            "function": {
                "name": "call_report_tool",
                "description": (
                    "Usado para pedir um relatório para DOWNLOAD IMEDIATO (arquivo). "
                    "Nunca use esta ferramenta para envios por e-mail."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "O nome do repositório no formato 'usuario/nome'."},
                        "prompt_usuario": {"type": "string", "description": "A instrução para o relatório."}
                    },
                    "required": ["repositorio", "prompt_usuario"],
                },
            },
        }

        # 5. Agendamento Recorrente/Futuro
        self.tool_schedule = {
            "type": "function",
            "function": {
                "name": "call_schedule_tool",
                "description": (
                    "Usado para agendar um relatório recorrente ou futuro por e-mail."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "O nome completo do repositório GitHub (ex: 'user/repo_name')."},
                        "prompt_relatorio": {"type": "string", "description": "O prompt do relatório a ser agendado."},
                        "frequencia": {"type": "string", "description": "A frequência: 'diariamente', 'semanalmente', 'mensalmente' ou 'once' (apenas se for agendado para o futuro)."},
                        "hora": {"type": "string", "description": "A hora do dia no formato HH:MM."},
                        "timezone": {"type": "string", "description": "Fuso horário do usuário."}
                    },
                    "required": ["repositorio", "prompt_relatorio", "frequencia", "hora"]
                }
            }
        }
        
        # 6. Salvar Instrução
        self.tool_save_instruction = {
            "type": "function",
            "function": {
                "name": "call_save_instruction_tool",
                "description": "Usado para salvar uma instrução/template para futuros relatórios.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "O repositório ao qual esta instrução se aplica."},
                        "instrucao": {"type": "string", "description": "A instrução específica a ser salva."}
                    },
                    "required": ["repositorio", "instrucao"],
                },
            },
        }

        # 7. Chat Simples
        self.tool_chat = {
            "type": "function",
            "function": {
                "name": "call_chat_tool",
                "description": "Usado para bate-papo casual ou explicações conceituais.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "O texto do usuário."}
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
        """Aplica lógica de fallback e validação nos argumentos da ferramenta."""
        name = tool_call.get('function', {}).get('name')
        args = tool_call.get('function', {}).get('arguments', {})
        
        if name == "call_schedule_tool":
            # Fallback de Timezone
            if 'timezone' not in args or not args['timezone']:
                args['timezone'] = 'America/Sao_Paulo'
                print(f"[LLMService] AVISO: Timezone não fornecido. Usando fallback: {args['timezone']}")
        
        return args

    def get_intent(self, user_query: str) -> Dict[str, Any]:
        if not self.client:
            raise Exception("LLMService não inicializado")
        
        print(f"[LLMService] Iniciando Agente de Encadeamento para: '{user_query}'")
        
        system_prompt = f"""
Você é o Orquestrador de Tarefas da plataforma GitRAG.

Sua função é LER o pedido do usuário e devolvê-lo como uma LISTA ORDENADA de chamadas de ferramentas.

As ferramentas disponíveis são:
  - call_ingest_tool      → ingere/atualiza o índice RAG.
  - call_query_tool       → responde perguntas no chat.
  - call_report_tool      → gera relatórios para DOWNLOAD.
  - call_send_onetime_report_tool → envia relatório por EMAIL IMEDIATAMENTE (sem agendar).
  - call_schedule_tool    → agenda relatórios RECORRENTES ou FUTUROS.
  - call_save_instruction_tool → salva templates.
  - call_chat_tool        → conversa casual.

REGRAS CRÍTICAS:

1. EMAIL IMEDIATO vs AGENDAMENTO:
   - Se o usuário disser "envie agora", "mande por email já", "não agende, só envie":
     → Use **call_send_onetime_report_tool**.
   - Se o usuário disser "agende", "todo dia", "semanalmente", "daqui a pouco":
     → Use **call_schedule_tool**.

2. DOWNLOAD vs EMAIL:
   - "Baixar", "Download", "Gerar relatório" (sem mencionar email) → **call_report_tool**.
   - "Mandar por email" → **call_send_onetime_report_tool** ou **call_schedule_tool**.

3. FLUXOS COMPOSTOS:
   - Se precisar ingerir antes: [call_ingest_tool, call_send_onetime_report_tool].

4. VALIDAÇÃO:
   - Nunca invente argumentos obrigatórios.

Data de referência: {datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%Y-%m-%d')}.
Fuso horário padrão: 'America/Sao_Paulo'.
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
                chat_text = message.content or "Entendido."
                return {
                    "type": "simple_chat", 
                    "response_text": chat_text
                }

            steps = []
            for call in tool_calls:
                try:
                    args = json.loads(call.function.arguments)
                    args_with_fallback = self._handle_tool_call_args({
                        'function': {'name': call.function.name, 'arguments': args}
                    })
                    steps.append({
                        "intent": call.function.name,
                        "args": args_with_fallback
                    })
                except json.JSONDecodeError:
                    return {
                        "type": "clarify",
                        "response_text": "Erro ao processar argumentos da ferramenta."
                    }
            
            # Validação de campos obrigatórios
            for step in steps:
                if step["intent"] != "call_chat_tool":
                    func_def = self.tool_map.get(step["intent"], {}).get("function", {})
                    required_params = func_def.get("parameters", {}).get("required", [])
                    args_to_check = step["args"] 
                    
                    for param in required_params:
                        if not args_to_check.get(param): 
                            return {
                                "type": "clarify",
                                "response_text": f"O campo obrigatório '{param}' está faltando."
                            }

            print(f"[LLMService] Intenções detectadas: {len(steps)} etapas.")
            return {"type": "multi_step", "steps": steps}

        except Exception as e:
            print(f"[LLMService] Erro no get_intent: {e}")
            return {"type": "clarify", "response_text": f"Erro interno: {e}"}

    def generate_response(self, query: str, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.client: raise Exception("LLMService não inicializado.")
        formatted_context = self._format_context(context)
        system_prompt = "Você é um assistente especialista da plataforma GitRAG. Responda com base no contexto."
        user_prompt = f"Contexto:\n{formatted_context}\n\nConsulta: \"{query}\""
        try:
            response = self.client.chat.completions.create(
                model=self.generation_model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.1
            )
            return {"response": response.choices[0].message.content, "usage": response.usage}
        except Exception as e:
            return {"response": f"Erro: {e}", "usage": None}

    def generate_response_stream(self, query: str, context: List[Dict[str, Any]]) -> Iterator[str]:
        if not self.client: raise Exception("LLMService não inicializado.")
        formatted_context = self._format_context(context)
        system_prompt = "Você é um assistente especialista da plataforma GitRAG."
        user_prompt = f"Contexto:\n{formatted_context}\n\nConsulta: \"{query}\""
        try:
            stream = self.client.chat.completions.create(
                model=self.generation_model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                stream=True, temperature=0.1
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content: yield content
        except Exception as e:
            yield f"Erro: {e}"

    def generate_analytics_report(self, repo_name: str, user_prompt: str, raw_data: List[Dict[str, Any]]) -> str:
        context_json = json.dumps(raw_data)
        system_prompt = "Você é um analista de dados. Gere um JSON com 'analysis_markdown' e 'chart_json'."
        try:
            response = self.client.chat.completions.create(
                model=self.generation_model, 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Repo: {repo_name}\nPrompt: {user_prompt}\nDados: {context_json}"}
                ],
                response_format={"type": "json_object"}, temperature=0.3, max_tokens=4000
            )
            return response.choices[0].message.content
        except Exception as e:
            return json.dumps({"analysis_markdown": f"Erro: {e}", "chart_json": None})

    def generate_simple_response(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.routing_model, 
                messages=[{"role": "system", "content": "Seja breve e casual."}, {"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=50
            )
            return response.choices[0].message.content
        except Exception: return "👍"

    # --- FUNÇÕES RESTAURADAS ---
    def get_token_usage(self) -> Dict[str, int]:
        return self.token_usage
        
    def _format_requirements_data(self, requirements_data: List[Dict[str, Any]]) -> str:
        if not requirements_data:
            return "Nenhum dado de requisito fornecido."
        return json.dumps(requirements_data, indent=2, ensure_ascii=False)
    # ---------------------------

    def _format_context(self, context: List[Dict[str, Any]]) -> str:
        if not context: return "Nenhum contexto."
        text = ""
        for doc in context:
            text += f"--- Fonte ---\nConteúdo: {doc.get('text', '')}\n\n"
        return text

    def summarize_plan_for_confirmation(self, steps: List[Dict[str, Any]], user_email: str) -> str:
        print(f"[LLMService] Gerando sumário de confirmação para plano de {len(steps)} etapas...")
        
        plan_summary_list = []
        for step in steps:
            raw_intent = step['intent'].replace('call_', '').replace('_tool', '')
            intent_capitalized = raw_intent.capitalize()
            
            args = step['args']
            summary_line = f"* **{intent_capitalized}:** "

            if raw_intent == 'ingest':
                summary_line += f"Ingerir o repositório **{args.get('repositorio')}**."
            elif raw_intent == 'query':
                summary_line += f"Consultar: '{args.get('prompt_usuario', '')}'."
            elif raw_intent == 'report':
                summary_line += f"Gerar relatório para DOWNLOAD (Repo: {args.get('repositorio')})."
            
            # Confirmação específica para o envio imediato
            elif raw_intent == 'send_onetime_report':
                summary_line = f"* **Email Imediato:** Gerar e enviar relatório AGORA para **{args.get('email_destino')}** (Repo: {args.get('repositorio')})."
            
            elif raw_intent == 'schedule':
                freq = args.get('frequencia')
                hora = args.get('hora')
                tz = args.get('timezone')
                email = args.get('user_email') or user_email
                summary_line += f"Agendar envio **{freq}** às {hora} ({tz}) para **{email}**."
            
            elif raw_intent == 'save_instruction':
                summary_line += "Salvar instrução."
            
            plan_summary_list.append(summary_line)

        plan_text = "\n".join(plan_summary_list)
        
        confirmation_message = f"""
**Confirme o plano ({len(steps)} etapas):**
{plan_text}

As ações serão executadas na ordem acima. **Posso prosseguir?** (Sim/Não)
"""
        return confirmation_message

    def summarize_action_for_confirmation(self, intent_name: str, args: Dict[str, Any]) -> str:
        repo = args.get("repositorio")
        return f"Confirmar ação: {intent_name} em {repo}?"