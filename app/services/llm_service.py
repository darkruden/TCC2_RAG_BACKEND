# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/llm_service.py
# (Implementa o Agente de Múltiplas Etapas com Parallel Tool Calls)

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

        # --- ARQUITETURA DE FERRAMENTAS ROBUSTA ---
        self.tool_ingest = {
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
        }
        
        self.tool_query = {
            "type": "function",
            "function": {
                "name": "call_query_tool",
                "description": "Usado para perguntas sobre um repositório (RAG).",
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

        self.tool_report = {
            "type": "function",
            "function": {
                "name": "call_report_tool",
                "description": "Usado para pedir um 'relatório' ou 'gráfico' para DOWNLOAD IMEDIATO (salvar o arquivo no computador). Nunca use para email.",
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

        self.tool_schedule = {
            "type": "function",
            "function": {
                "name": "call_schedule_tool",
                "description": "Usado quando o usuário quer ENVIAR um relatório por EMAIL (agora ou agendado). Use sempre que 'email', 'agendar' ou 'enviar' for mencionado.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "O nome do repositório no formato 'usuario/nome'."},
                        "prompt_relatorio": {"type": "string", "description": "O que o relatório deve conter."},
                        "frequencia": {"type": "string", "enum": ["once", "daily", "weekly", "monthly"], "description": "A frequência. Use 'once' para envio imediato."},
                        "hora": {"type": "string", "description": "A hora no formato HH:MM (24h)."},
                        "timezone": {"type": "string", "description": "O fuso horário (ex: 'America/Sao_Paulo')."},
                        "user_email": {"type": "string", "description": "O email do destinatário (ex: usuario@gmail.com)."}
                    },
                    "required": ["repositorio", "prompt_relatorio", "frequencia", "hora", "timezone"], 
                },
            },
        }
        
        self.tool_save_instruction = {
            "type": "function",
            "function": {
                "name": "call_save_instruction_tool",
                "description": "Usado para salvar uma instrução para futuros relatórios.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "O repositório ao qual esta instrução se aplica."},
                        "instrucao": {"type": "string", "description": "A instrução específica que o usuário quer salvar."}
                    },
                    "required": ["repositorio", "instrucao"],
                },
            },
        }

        self.tool_chat = {
            "type": "function",
            "function": {
                "name": "call_chat_tool",
                "description": "Usado para bate-papo casual, saudações, ou respostas curtas. NENHUM argumento é necessário se for um chat simples.",
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
            self.tool_schedule,
            self.tool_save_instruction,
            self.tool_chat
        ]

        self.tool_map = {
            "call_ingest_tool": self.tool_ingest,
            "call_query_tool": self.tool_query,
            "call_report_tool": self.tool_report,
            "call_schedule_tool": self.tool_schedule,
            "call_save_instruction_tool": self.tool_save_instruction,
            "call_chat_tool": self.tool_chat
        }

    
    def get_intent(self, user_query: str) -> Dict[str, Any]:
        """
        Orquestra o roteamento. Agora retorna UMA ou MAIS ferramentas encadeadas.
        """
        if not self.client: raise Exception("LLMService não inicializado")
        
        print(f"[LLMService] Iniciando Agente de Encadeamento para: '{user_query}'")
        
        # 1. Ajuste do prompt do sistema para o Agente
        system_prompt = f"""
Você é um Agente de Encadeamento de Tarefas que decomponhe um prompt de usuário em uma lista de etapas (chamadas de ferramenta) na ordem correta.

REGRAS CRÍTICAS DE ENCAMINHAMENTO:
1.  CHAME MÚLTIPLAS FERRAMENTAS: Se o usuário pedir 'Ingira e depois gere relatório', retorne [call_ingest_tool, call_report_tool/schedule] em ordem.
2.  EMAIL vs DOWNLOAD: Use APENAS call_schedule_tool para qualquer solicitação que mencione 'email', 'agendar' ou 'enviar para mim'. Use APENAS call_report_tool para 'gerar relatório' ou 'download'.
3.  INGESTÃO PRÉVIA: Se o usuário pedir uma consulta, relatório ou agendamento de um repositório, inclua **call_ingest_tool** como o **PRIMEIRO** passo.
4.  VALIDE ARGUMENTOS: Se um argumento obrigatório estiver faltando (como o nome do repo), você DEVE retornar uma resposta textual para CLARIFICAÇÃO. NUNCA tente inventar o nome do repositório.
- Data/Hora: Hoje é {datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%Y-%m-%d')}. O fuso horário padrão para agendamentos é 'America/Sao_Paulo'.
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
                # A IA decidiu que era um bate-papo simples (retornando apenas texto)
                chat_text = message.content or "Entendido."
                return {
                    "type": "simple_chat", 
                    "response_text": chat_text
                }

            # 2. Processa as chamadas de ferramenta (multi-step ou single-step)
            steps = []
            for call in tool_calls:
                try:
                    args = json.loads(call.function.arguments)
                    steps.append({
                        "intent": call.function.name,
                        "args": args
                    })
                except json.JSONDecodeError:
                    return {"type": "clarify", "response_text": "A IA falhou em formatar a requisição. Por favor, reformule sua solicitação."}
            
            # Validação: Se a IA tentou chamar uma ferramenta mas retornou campos vazios, é falha na intenção.
            for step in steps:
                if step["intent"] != "call_chat_tool":
                    func_def = self.tool_map.get(step["intent"], {}).get("function", {})
                    required_params = func_def.get("parameters", {}).get("required", [])
                    
                    for param in required_params:
                        if not step["args"].get(param):
                            return {"type": "clarify", "response_text": f"O campo obrigatório '{param}' está faltando. Por favor, forneça o valor."}

            print(f"[LLMService] Intenções detectadas: {len(steps)} etapas.")
            
            return {
                "type": "multi_step", 
                "steps": steps
            }

        except Exception as e:
            print(f"[LLMService] Erro no get_intent multi-step: {e}")
            return {"type": "clarify", "response_text": f"Erro interno ao processar: {e}"}

    
    def generate_response(self, query: str, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.client: raise Exception("LLMService não inicializado.")
        print("[LLMService] Iniciando resposta RAG (NÃO-Streaming)...")
        
        formatted_context = self._format_context(context)
        
        system_prompt = """
Você é um assistente de IA especialista em análise de repositórios GitHub.
Sua tarefa é responder à consulta do usuário com base estritamente no contexto fornecido (documentos de commits, issues e PRs).
Seja conciso e direto.
Se o contexto não for suficiente, informe que não encontrou informações sobre aquele tópico específico.
"""
        user_prompt = f"Contexto:\n{formatted_context}\n\nConsulta: \"{query}\"\n\nBaseado APENAS no contexto acima, responda à consulta."

        try:
            response = self.client.chat.completions.create(
                model=self.generation_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1
            )
            
            usage = response.usage
            if usage:
                self.token_usage["prompt_tokens"] += usage.prompt_tokens
                self.token_usage["completion_tokens"] += usage.completion_tokens
                self.token_usage["total_tokens"] += usage.total_tokens

            response_text = response.choices[0].message.content
            return {"response": response_text, "usage": usage}

        except Exception as e:
            print(f"[LLMService] Erro durante o generate_response: {e}")
            return {"response": f"Erro ao gerar resposta: {e}", "usage": None}

    
    def generate_response_stream(self, query: str, context: List[Dict[str, Any]]) -> Iterator[str]:
        if not self.client: raise Exception("LLMService não inicializado.")
        print("[LLMService] Iniciando resposta em STREAMING...")
        
        formatted_context = self._format_context(context)
        
        system_prompt = """
Você é um assistente de IA especialista em análise de repositórios GitHub.
Sua tarefa é responder à consulta do usuário com base estritamente no contexto fornecido (documentos de commits, issues e PRs).
Seja conciso e direto.
Se o contexto não for suficiente, informe que não encontrou informações sobre aquele tópico específico.
"""
        user_prompt = f"Contexto:\n{formatted_context}\n\nConsulta: \"{query}\"\n\nBaseado APENAS no contexto acima, responda à consulta."

        try:
            stream = self.client.chat.completions.create(
                model=self.generation_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                stream=True,
                temperature=0.1
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except Exception as e:
            print(f"[LLMService] Erro durante o streaming: {e}")
            yield f"\n\n**Erro ao gerar resposta:** {e}"

    
    def generate_analytics_report(self, repo_name: str, user_prompt: str, raw_data: List[Dict[str, Any]]) -> str:
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
Gere o relatório em um único objeto JSON...
"""
        try:
            response = self.client.chat.completions.create(
                model=self.generation_model, 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": final_user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3, max_tokens=4000
            )
            
            response_content = response.choices[0].message.content
            
            if not response_content:
                print("[LLMService] ERRO: OpenAI retornou None (provável filtro de conteúdo).")
                return json.dumps({
                    "analysis_markdown": "# Erro de Geração\n\nA IA não conseguiu gerar uma resposta. Isso pode ter sido causado por filtros de conteúdo ou uma falha na API.",
                    "chart_json": None
                })
            
            usage = response.usage
            self.token_usage["prompt_tokens"] += usage.prompt_tokens
            self.token_usage["completion_tokens"] += usage.completion_tokens
            self.token_usage["total_tokens"] += usage.total_tokens
            
            return response_content 

        except Exception as e:
            print(f"[LLMService] Erro ao gerar relatório JSON: {e}")
            return json.dumps({
                "analysis_markdown": f"# Erro\n\nNão foi possível gerar a análise: {e}",
                "chart_json": None
            })

    
    def generate_simple_response(self, prompt: str) -> str:
        print(f"[LLMService] Gerando resposta simples para: '{prompt}'")
        
        system_prompt = """
Você é um assistente de IA. Responda ao usuário de forma curta, casual e prestativa.
Se o usuário apenas disser 'ok', 'certo' ou 'correto', responda com '👍' ou 'Entendido.'.
Se o usuário disser 'obrigado', responda com 'De nada!' ou 'Estou aqui para ajudar!'.
"""
        try:
            response = self.client.chat.completions.create(
                model=self.routing_model, 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=50
            )
            return response.choices[0].message.content
        
        except Exception as e:
            print(f"[LLMService] Erro ao gerar resposta simples: {e}")
            return "👍" 

    
    def get_token_usage(self) -> Dict[str, int]:
        return self.token_usage

    def _format_context(self, context: List[Dict[str, Any]]) -> str:
        if not context:
            return "Nenhum contexto encontrado."
        
        formatted_text = ""
        for doc in context:
            meta = doc.get('metadata', {})
            tipo = meta.get('type', 'documento')
            conteudo = doc.get('text', '')
            
            formatted_text += f"--- Fonte (Tipo: {tipo}) ---\n"
            if 'url' in meta:
                formatted_text += f"URL: {meta.get('url')}\n"
            if 'autor' in meta:
                formatted_text += f"Autor: {meta.get('autor')}\n"
            if 'titulo' in meta:
                formatted_text += f"Título: {meta.get('titulo')}\n"
                
            formatted_text += f"Conteúdo: {conteudo}\n\n"
        
        return formatted_text

    def summarize_plan_for_confirmation(self, steps: List[Dict[str, Any]], user_email: str) -> str:
        """
        Gera uma pergunta de confirmação humanizada baseada no plano de execução.
        (Usa regras determinísticas para estabilidade e velocidade)
        """
        print(f"[LLMService] Gerando sumário de confirmação para plano de {len(steps)} etapas (Deterministic)...")
        
        plan_summary_list = []
        for step in steps:
            intent = step['intent'].replace('call_', '').replace('_tool', '').capitalize()
            args = step['args']
            
            summary_line = f"* **{intent}:** "

            if intent == 'Ingest':
                summary_line += f"Ingerir o repositório **{args.get('repositorio')}** para atualizar o RAG."
            elif intent == 'Query':
                summary_line += f"Consultar (RAG) o repositório {args.get('repositorio')} com a pergunta: '{args.get('prompt_usuario', '')}'."
            elif intent == 'Report':
                summary_line += f"Gerar relatório para **DOWNLOAD** do repositório {args.get('repositorio')} (Prompt: '{args.get('prompt_usuario', '')}')."
            elif intent == 'Schedule':
                freq = args.get('frequencia')
                repo = args.get('repositorio')
                email = args.get('user_email') or user_email
                
                schedule_details = f"e enviar Imediatamente para o email **{email}**" if freq == 'once' else f"e agendar para **{freq}** às {args.get('hora')} (fuso {args.get('timezone')})"
                
                summary_line += f"Preparar relatório {schedule_details} (Repo: {repo})."
            elif intent == 'SaveInstruction':
                summary_line += f"Salvar a instrução para futuros relatórios do repositório {args.get('repositorio')}."
            
            plan_summary_list.append(summary_line)

        plan_text = "\n".join(plan_summary_list)
        
        confirmation_message = f"""
**Ok, só para confirmar o plano de execução ({len(steps)} etapas):**
{plan_text}

As ações acima serão executadas em ordem sequencial (uma depende da anterior).
**Isso está correto?** (Responda 'sim' ou 'não')
"""
        return confirmation_message

    def summarize_action_for_confirmation(self, intent_name: str, args: Dict[str, Any]) -> str:
        """
        [MANTIDA] - Gera a confirmação para uma ÚNICA ação de Agendamento Recorrente (Regra de Negócio Antiga).
        """
        print(f"[LLMService] Gerando sumário de confirmação para agendamento recorrente: {intent_name}...")
        
        # NOTE: Esta função agora lida apenas com o cenário de agendamento recorrente de um passo.
        # Caso 1: Agendamento Recorrente (a única ação single-step que precisa de confirmação)
        repo = args.get("repositorio")
        prompt = args.get("prompt_relatorio")
        freq = args.get("frequencia")
        hora = args.get("hora")
        tz = args.get("timezone")

        confirmation_text = f"""
Ok, só para confirmar: Devo **agendar** o relatório para o repositório '{repo}' com o prompt: '{prompt[:50]}...',
com frequência **{freq}**, às **{hora}** (fuso {tz}).

Isso está correto? (Responda 'sim' ou 'não')
"""
        return confirmation_text

    def _format_requirements_data(self, requirements_data: List[Dict[str, Any]]) -> str:
        if not requirements_data:
            return "Nenhum dado de requisito fornecido."
        
        return json.dumps(requirements_data, indent=2, ensure_ascii=False)