# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/llm_service.py

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
                "description": "Usado para pedir um 'relatório' ou 'gráfico' para DOWNLOAD (salvar o arquivo no computador). NÃO usado para email.",
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
                "description": "Usado quando o usuário quer ENVIAR um relatório por EMAIL. Pode ser para agora (frequencia: 'once') ou agendado (ex: 'daily', 'weekly').",
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
                    # O e-mail não é obrigatório aqui; a lógica em main.py tratará disso
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
                "description": "Usado para bate-papo casual, saudações ou respostas curtas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "O texto do usuário."}
                    },
                    "required": ["prompt"],
                },
            },
        }

        self.tool_map = {
            "INGEST": self.tool_ingest,
            "QUERY": self.tool_query,
            "REPORT": self.tool_report,
            "SCHEDULE": self.tool_schedule,
            "SAVE_INSTRUCTION": self.tool_save_instruction,
            "CHAT": self.tool_chat # <-- Adiciona CHAT ao mapa
        }

    
    def _get_meta_intent(self, user_query: str) -> Dict[str, Any]:
        """
        Etapa 1: O Meta-Roteador.
        """
        print(f"[LLMService] Etapa 1: Classificando Meta-Intenção para: '{user_query}'")
        intent_categories = list(self.tool_map.keys())
        
        system_prompt = f"""
Você é um roteador de API. Sua tarefa é classificar o prompt do usuário em UMA das seguintes categorias:
{json.dumps(intent_categories)}

- INGEST: Ingerir, indexar ou atualizar um repositório.
- QUERY: Fazer uma pergunta sobre o código ou dados de um repositório (RAG).
- REPORT: Gerar um relatório para DOWNLOAD IMEDIATO.
- SCHEDULE: Enviar um relatório por EMAIL (agora ou no futuro).
- SAVE_INSTRUCTION: Salvar uma preferência ou instrução para o futuro.
- CHAT: Bate-papo casual, saudações, ou respostas curtas como 'ok', 'obrigado', 'correto'.
- CLARIFY: Se a intenção for vaga, ambígua ou não relacionada a nenhuma das anteriores.

Responda APENAS com um objeto JSON no formato: {{"intent": "NOME_DA_INTENCAO"}}
"""
        try:
            response = self.client.chat.completions.create(
                model=self.routing_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            
            result_json = json.loads(response.choices[0].message.content)
            intent = result_json.get("intent")
            print(f"[LLMService] Etapa 1: Meta-Intenção decidida: {intent}")
            
            if intent in self.tool_map:
                return {"status": "success", "intent": intent}
            else:
                return {"status": "clarify", "response_text": "Desculpe, não entendi sua solicitação. Você pode tentar reformular?"}

        except Exception as e:
            print(f"[LLMService] Erro CRÍTICO na Etapa 1 (Meta-Roteador): {e}")
            return {"status": "clarify", "response_text": f"Erro interno no roteador: {e}"}

    def _get_arguments_for_intent(self, user_query: str, intent_name: str) -> Dict[str, Any]:
        """
        Etapa 2: O Extrator de Argumentos.
        """
        print(f"[LLMService] Etapa 2: Extraindo argumentos para: {intent_name}")
        
        tool_definition = self.tool_map.get(intent_name)
        if not tool_definition:
            raise ValueError(f"Intenção '{intent_name}' não tem uma ferramenta definida no tool_map.")

        tool_name = tool_definition["function"]["name"] 
        
        system_prompt = f"""
Você é um extrator de argumentos JSON. O usuário quer executar a ação '{intent_name}'.
Sua tarefa é extrair os parâmetros necessários para a ferramenta '{tool_name}' a partir do prompt do usuário.
Use 'America/Sao_Paulo' como fuso horário padrão se o usuário mencionar 'Brasília' ou 'horário de São Paulo'.
Se o usuário disser "agora" ou "imediatamente" para um agendamento, use 'frequencia: "once"' e a hora atual (no fuso correto).
"""
        try:
            response = self.client.chat.completions.create(
                model=self.routing_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                tools=[tool_definition],
                tool_choice={"type": "function", "function": {"name": tool_name}}
            )
            
            tool_calls = response.choices[0].message.tool_calls
            if not tool_calls:
                print(f"[LLMService] ERRO na Etapa 2: {tool_name} não foi chamada, mesmo sendo forçada.")
                raise Exception("Falha ao extrair argumentos.")

            call = tool_calls[0]
            function_args = json.loads(call.function.arguments)
            
            print(f"[LLMService] Etapa 2: Argumentos extraídos: {function_args}")
            
            return {
                "status": "success",
                "intent_tool_name": tool_name,
                "args": function_args
            }

        except Exception as e:
            print(f"[LLMService] Erro CRÍTICO na Etapa 2 (Extrator de Argumentos): {e}")
            return {
                "status": "clarify",
                "response_text": f"Eu entendi que você quer {intent_name}, mas não consegui extrair os detalhes. Pode, por favor, fornecer o repositório e outros dados?"
            }

    
    def get_intent(self, user_query: str) -> Dict[str, Any]:
        """
        Orquestra a cadeia de roteamento robusto em duas etapas.
        """
        if not self.client: raise Exception("LLMService não inicializado.")

        # Etapa 1: Decidir a intenção
        meta_intent_result = self._get_meta_intent(user_query)
        
        if meta_intent_result["status"] == "clarify":
            return {"intent": "CLARIFY", "response_text": meta_intent_result["response_text"]}

        intent_name = meta_intent_result["intent"] # ex: "SCHEDULE"

        # Se for CHAT, não precisamos extrair argumentos complexos
        if intent_name == "CHAT":
            return {
                "intent": "call_chat_tool",
                "args": {"prompt": user_query.split('\n')[-1]} # Envia só a última linha
            }

        # Etapa 2: Extrair os argumentos
        args_result = self._get_arguments_for_intent(user_query, intent_name)
        
        if args_result["status"] == "clarify":
            return {"intent": "CLARIFY", "response_text": args_result["response_text"]}

        # Sucesso!
        return {
            "intent": args_result["intent_tool_name"], # ex: "call_schedule_tool"
            "args": args_result["args"]
        }
    
    
    def generate_response(self, query: str, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Gera uma resposta RAG padrão (não-streaming).
        """
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
        """
        Gera uma resposta RAG em streaming.
        """
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
Gere o relatório em um único objeto JSON...
"""
        try:
            response = self.client.chat.completions.create(
                model=self.generation_model, # Usa o modelo mais forte
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
            
            return response_content # Retorna a string JSON

        except Exception as e:
            print(f"[LLMService] Erro ao gerar relatório JSON: {e}")
            return json.dumps({
                "analysis_markdown": f"# Erro\n\nNão foi possível gerar a análise: {e}",
                "chart_json": None
            })

    
    def generate_simple_response(self, prompt: str) -> str:
        """
        Gera uma resposta curta e casual.
        """
        print(f"[LLMService] Gerando resposta simples para: '{prompt}'")
        
        system_prompt = """
Você é um assistente de IA. Responda ao usuário de forma curta, casual e prestativa.
Se o usuário apenas disser 'ok', 'certo' ou 'correto', responda com '👍' ou 'Entendido.'.
Se o usuário disser 'obrigado', responda com 'De nada!' ou 'Estou aqui para ajudar!'.
"""
        try:
            response = self.client.chat.completions.create(
                model=self.routing_model, # Usa o modelo rápido
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
            return "👍" # Fallback

    
    def get_token_usage(self) -> Dict[str, int]:
        """Retorna o uso total de tokens acumulado."""
        return self.token_usage

    def _format_context(self, context: List[Dict[str, Any]]) -> str:
        """
        Formata os documentos de contexto (RAG) em uma string de texto 
        para ser usada no prompt da LLM.
        """
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

    def _format_requirements_data(self, requirements_data: List[Dict[str, Any]]) -> str:
        """
        Formata dados de requisitos (atualmente não utilizado na arquitetura principal).
        """
        if not requirements_data:
            return "Nenhum dado de requisito fornecido."
        
        return json.dumps(requirements_data, indent=2, ensure_ascii=False)

    def summarize_action_for_confirmation(self, intent_name: str, args: Dict[str, Any]) -> str:
        """
        Gera uma pergunta de confirmação humanizada baseada na ação e nos argumentos.
        """
        print(f"[LLMService] Gerando sumário de confirmação para {intent_name}...")
        
        system_prompt = f"""
Você é um assistente de confirmação. Sua tarefa é ler um JSON de argumentos e traduzi-lo 
em uma pergunta de confirmação clara, educada e em português.

- Comece com 'Ok, só para confirmar...'
- Resuma todos os argumentos de forma fluida.
- Termine com a pergunta 'Isso está correto?'

Exemplo de Entrada:
{{"intent": "agendamento", "args": {{"repositorio": "user/repo", "frequencia": "daily", "hora": "10:00"}}}}

Exemplo de Saída:
Ok, só para confirmar: Devo agendar o relatório para o repositório 'user/repo', 
com frequência diária, às 10:00. Isso está correto?
"""
        
        action_summary = json.dumps({"intent": intent_name, "args": args})

        try:
            response = self.client.chat.completions.create(
                model=self.routing_model, # Usa o modelo rápido
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": action_summary}
                ],
                temperature=0.1
            )
            confirmation_text = response.choices[0].message.content
            return confirmation_text
        
        except Exception as e:
            print(f"[LLMService] Erro ao gerar sumário: {e}")
            # Fallback
            return f"Ok, devo executar a ação '{intent_name}' com os argumentos: {json.dumps(args)}. Isso está correto?"