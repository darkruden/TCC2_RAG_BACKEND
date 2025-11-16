# CÓDIGO ATUALIZADO (ROBUSTO) PARA: app/services/llm_service.py
# (Implementa o padrão Meta-Roteador + Extrator de Argumentos)

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
        
        # Usamos o modelo mais rápido e barato para roteamento
        self.routing_model = "gpt-4o-mini"
        # Usamos o modelo principal para geração de relatórios
        self.generation_model = model 
        
        self.client = OpenAI(api_key=self.api_key)
        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # --- ARQUITETURA DE FERRAMENTAS ROBUSTA ---
        # 1. Definições de ferramentas individuais
        # (Isso nos permite chamar apenas a ferramenta que queremos na Etapa 2)

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
                        "timezone": {"type": "string", "description": "O fuso horário (ex: 'America/Sao_Paulo')."}
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

        # 2. Mapeamento de Meta-Intenção para a definição da ferramenta
        # (Este é o "cérebro" da nova arquitetura)
        self.tool_map = {
            "INGEST": self.tool_ingest,
            "QUERY": self.tool_query,
            "REPORT": self.tool_report,
            "SCHEDULE": self.tool_schedule,
            "SAVE_INSTRUCTION": self.tool_save_instruction
        }

    
    def _get_meta_intent(self, user_query: str) -> Dict[str, Any]:
        """
        Etapa 1: O Meta-Roteador.
        Decide a intenção principal (o que o usuário quer).
        """
        print(f"[LLMService] Etapa 1: Classificando Meta-Intenção para: '{user_query}'")
        
        # Lista simples de intenções que o Meta-Roteador pode escolher
        intent_categories = list(self.tool_map.keys()) # ["INGEST", "QUERY", ...]
        
        system_prompt = f"""
Você é um roteador de API. Sua tarefa é classificar o prompt do usuário em UMA das seguintes categorias:
{json.dumps(intent_categories)}

- INGEST: Ingerir, indexar ou atualizar um repositório.
- QUERY: Fazer uma pergunta sobre o código ou dados de um repositório (RAG).
- REPORT: Gerar um relatório para DOWNLOAD IMEDIATO.
- SCHEDULE: Enviar um relatório por EMAIL (agora ou no futuro).
- SAVE_INSTRUCTION: Salvar uma preferência ou instrução para o futuro.
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
        Força a extração de argumentos para a intenção já decidida.
        """
        print(f"[LLMService] Etapa 2: Extraindo argumentos para: {intent_name}")
        
        tool_definition = self.tool_map.get(intent_name)
        if not tool_definition:
            raise ValueError(f"Intenção '{intent_name}' não tem uma ferramenta definida no tool_map.")

        # Extrai o nome da ferramenta (ex: "call_schedule_tool")
        tool_name = tool_definition["function"]["name"] 
        
        system_prompt = f"""
Você é um extrator de argumentos JSON. O usuário quer executar a ação '{intent_name}'.
Sua tarefa é extrair os parâmetros necessários para a ferramenta '{tool_name}' a partir do prompt do usuário.
Use 'America/Sao_Paulo' como fuso horário padrão se o usuário mencionar 'Brasília' ou 'horário de São Paulo'.
Se o usuário disser "agora" ou "imediatamente" para um agendamento, use 'frequencia: "once"' e a hora atual.
"""
        try:
            response = self.client.chat.completions.create(
                model=self.routing_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                tools=[tool_definition], # Passa APENAS a ferramenta que queremos
                tool_choice={"type": "function", "function": {"name": tool_name}} # FORÇA o uso dessa ferramenta
            )
            
            tool_calls = response.choices[0].message.tool_calls
            if not tool_calls:
                # Isso não deve acontecer devido ao 'tool_choice' forçado, mas é uma boa guarda
                print(f"[LLMService] ERRO na Etapa 2: {tool_name} não foi chamada, mesmo sendo forçada.")
                raise Exception("Falha ao extrair argumentos.")

            call = tool_calls[0]
            function_args = json.loads(call.function.arguments)
            
            print(f"[LLMService] Etapa 2: Argumentos extraídos: {function_args}")
            
            return {
                "status": "success",
                "intent_tool_name": tool_name, # ex: "call_schedule_tool"
                "args": function_args
            }

        except Exception as e:
            print(f"[LLMService] Erro CRÍTICO na Etapa 2 (Extrator de Argumentos): {e}")
            # Se a extração falhar, pedimos clarificação
            return {
                "status": "clarify",
                "response_text": f"Eu entendi que você quer {intent_name}, mas não consegui extrair os detalhes. Pode, por favor, fornecer o repositório e outros dados?"
            }

    # --- FUNÇÃO PÚBLICA PRINCIPAL ---
    
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

        # Etapa 2: Extrair os argumentos
        args_result = self._get_arguments_for_intent(user_query, intent_name)
        
        if args_result["status"] == "clarify":
            return {"intent": "CLARIFY", "response_text": args_result["response_text"]}

        # Sucesso!
        return {
            "intent": args_result["intent_tool_name"], # ex: "call_schedule_tool"
            "args": args_result["args"]
        }
    
    #
    # --- (O RESTANTE DAS FUNÇÕES: generate_response_stream, generate_analytics_report, etc. permanecem as mesmas) ---
    #
    
    # BLOCO CORRIGIDO em app/services/llm_service.py

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
    
    # BLOCO CORRIGIDO em app/services/llm_service.py

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
Gere a resposta em um único objeto JSON...
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

    # (Funções _format e get_token_usage sem alterações)
    def get_token_usage(self) -> Dict[str, int]: ...
    def _format_context(self, context: List[Dict[str, Any]]) -> str: ...
    def _format_requirements_data(self, requirements_data: List[Dict[str, Any]]) -> str: ...