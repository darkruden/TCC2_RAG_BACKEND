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
                        "email_destino": {"type": "string", "description": "O email para envio. Se não informado, será enviado para o próprio usuário."},
                    },
                    "required": ["repositorio", "prompt_relatorio"], # <-- email_destino removido daqui
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
                "description": "Agenda relatórios futuros. ATENÇÃO: O usuário fornecerá datas em formato brasileiro (dia/mês/ano). Converta SEMPRE para o padrão ISO YYYY-MM-DD.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {"type": "string", "description": "URL ou nome do repositório."},
                        "prompt_relatorio": {"type": "string", "description": "Foco do relatório."},
                        "frequencia": {"type": "string", "description": "'diariamente', 'semanalmente', 'mensalmente'."},
                        "hora": {"type": "string", "description": "Hora HH:MM."},
                        "timezone": {"type": "string", "description": "Fuso horário (padrão: America/Sao_Paulo)."},
                        "data_inicio": {
                            "type": "string", 
                            "description": "Data de início convertida EXCLUSIVAMENTE para o formato YYYY-MM-DD. Ex: se o usuário disser '04/11/2025' ou '4 de novembro', envie '2025-11-04'."
                        },
                        "data_fim": {
                            "type": "string", 
                            "description": "Data final convertida EXCLUSIVAMENTE para o formato YYYY-MM-DD. Calcule baseando-se na duração se necessário."
                        }
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
        
        # Mantém a URL intacta para o GithubService processar a branch
        if 'repositorio' in args:
            print(f"[LLMService] Repositório preservado (raw): {args['repositorio']}")

        return args

    def get_intent(self, user_query: str) -> Dict[str, Any]:
        if not self.client:
            raise Exception("LLMService não inicializado")
        
        print(f"[LLMService] Roteando: '{user_query}'")
        
        system_prompt = f"""
Você é um roteador de intenções do GitRAG.

IMPORTANTE SOBRE REPOSITÓRIOS:
1. Se o usuário fornecer uma URL (ex: 'https://github.com/user/repo/tree/dev'), passe a URL COMPLETA como argumento.
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
                    args_with_fallback = self._handle_tool_call_args({
                        'function': {'name': call.function.name, 'arguments': args}
                    })
                    steps.append({
                        "intent": call.function.name,
                        "args": args_with_fallback
                    })
                except json.JSONDecodeError:
                    return {"type": "clarify", "response_text": "Erro ao processar argumentos."}
            
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

    # --- MÉTODOS DE GERAÇÃO RAG (NOVOS) ---
    def generate_rag_response_stream(
        self, 
        contexto: str, 
        prompt: str, 
        instrucao_rag: Optional[str] = None
    ) -> Iterator[str]:
        """
        Gera resposta RAG via stream com formatação de links garantida.
        """
        if not self.client: raise Exception("LLMService não inicializado.")
        
        # --- PROMPT DO SISTEMA REFORÇADO PARA LINKS ---
        system_content = """Você é um assistente especializado em análise de código (GitRAG).

DIRETRIZES OBRIGATÓRIAS DE FORMATAÇÃO:
1. CITAÇÕES CLICÁVEIS: Sempre que citar um Commit, Issue ou Pull Request, você DEVE formatá-lo como um link Markdown usando a URL fornecida no contexto.
   - Formato para Commits: `[SHA_CURTO](URL_DO_GITHUB)`
   - Formato para Issues/PRs: `[#NUMERO](URL_DO_GITHUB)`
   - Exemplo: "A correção foi feita no commit [a1b2c3d](https://github.com/...)."

2. PRECISÃO: Use exatamente os dados fornecidos no bloco de contexto. Não invente links.
"""
        if instrucao_rag:
            system_content += f"\n\nInstrução Especial do Usuário:\n{instrucao_rag}"
            
        user_content = f"""Com base EXCLUSIVAMENTE no contexto abaixo, responda à pergunta.

--- CONTEXTO INÍCIO ---
{contexto}
--- CONTEXTO FIM ---

Pergunta do Usuário: {prompt}
"""
        try:
            stream = self.client.chat.completions.create(
                model=self.generation_model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content}
                ], 
                stream=True, 
                temperature=0.2 
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content: yield content
        except Exception as e:
            yield f"Erro na geração stream: {e}"

    def generate_rag_response(
        self, 
        contexto: str, 
        prompt: str, 
        instrucao_rag: Optional[str] = None
    ) -> str:
        """
        Versão síncrona da resposta RAG.
        """
        full_response = ""
        for chunk in self.generate_rag_response_stream(contexto, prompt, instrucao_rag):
            full_response += chunk
        return full_response

    # --- MÉTODOS LEGADOS / UTILITÁRIOS ---
    def generate_analytics_report(self, repo_name: str, user_prompt: str, raw_data: List[Dict[str, Any]]) -> str:
        # Converte apenas os campos necessários para economizar tokens
        # Se o raw_data for muito grande, isso pode estourar o contexto.
        # Idealmente, aqui faríamos um resumo, mas para TCC serve.
        simplified_data = []
        for item in raw_data:
            if item.get('tipo') in ['commit', 'issue', 'pr']:
                simplified_data.append({'tipo': item['tipo'], 'meta': item.get('metadados')})
            else:
                # Arquivos: truncamos o conteúdo
                content = item.get('conteudo', '')[:200] + "..."
                simplified_data.append({'tipo': 'file', 'path': item.get('file_path'), 'content_snippet': content})
                
        context_json = json.dumps(simplified_data)
        
        try:
            system_prompt = """
Você é um analista de engenharia de software. Gere um JSON com duas chaves:
1. 'analysis_markdown': O texto do relatório.
2. 'chart_json': Configuração Chart.js (opcional).

REGRAS CRÍTICAS:
- Se os 'Dados' fornecidos não contiverem atividades recentes (commits/issues/PRs) compatíveis com o período solicitado no 'Prompt', SEJA HONESTO.
- Declare explicitamente: "Não foram detectadas alterações no período analisado."
- Não invente dados.
- Se não houver dados para gráfico, defina 'chart_json' como null.
"""
            response = self.client.chat.completions.create(
                model=self.generation_model, 
                messages=[
                    {"role": "system", "content": system_prompt},
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
            plan_text += f"* Ação: {intent} em {repo}\n"
            
        return f"**Plano:**\n{plan_text}\n**Confirma?** (Sim/Não)"

    def summarize_action_for_confirmation(self, intent_name: str, args: Dict[str, Any]) -> str:
        return f"Confirmar: {intent_name}?"