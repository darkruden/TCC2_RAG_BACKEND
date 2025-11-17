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
                "description": (
                    "Usado quando o usuário quer ingerir, re-ingerir ou atualizar o índice RAG "
                    "de um repositório GitHub. "
                    "Serve para a primeira ingestão, para atualizar dados após novas alterações "
                    "ou para garantir que o índice esteja sincronizado antes de consultas, "
                    "relatórios ou agendamentos."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {
                            "type": "string",
                            "description": (
                                "O nome do repositório no formato 'usuario/nome'. "
                                "Nunca invente esse valor. Se não for fornecido, peça esclarecimento."
                            )
                        }
                    },
                    "required": ["repositorio"],
                },
            },
        }
        
        self.tool_query = {
            "type": "function",
            "function": {
                "name": "call_query_tool",
                "description": (
                    "Usado para perguntas sobre um repositório (RAG). "
                    "Ideal para dúvidas pontuais sobre requisitos, commits, PRs, issues, "
                    "design de módulos, histórico de mudanças, impactos, rastreabilidade etc. "
                    "A resposta aparecerá diretamente na interface de chat, não como arquivo."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {
                            "type": "string",
                            "description": (
                                "O nome do repositório no formato 'usuario/nome'. "
                                "Nunca invente esse valor. Se não for fornecido, peça esclarecimento."
                            )
                        },
                        "prompt_usuario": {
                            "type": "string",
                            "description": (
                                "A pergunta específica do usuário. "
                                "Inclua aqui detalhes de escopo: requisito(s), módulo(s), branch, "
                                "intervalo de tempo, tipo de artefato (commits, PRs, issues), etc."
                            )
                        }
                    },
                    "required": ["repositorio", "prompt_usuario"],
                },
            },
        }

        self.tool_report = {
            "type": "function",
            "function": {
                "name": "call_report_tool",
                "description": (
                    "Usado para pedir um 'relatório' ou 'gráfico' para DOWNLOAD IMEDIATO "
                    "(salvar o arquivo no computador). "
                    "Exemplos: relatório de rastreabilidade de requisitos, mapa de impacto de PRs, "
                    "resumo da sprint, estatísticas de commits por autor/arquivo, "
                    "exportar dados para planilha. "
                    "Nunca use esta ferramenta para envios por e-mail."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {
                            "type": "string",
                            "description": (
                                "O nome do repositório no formato 'usuario/nome'. "
                                "Nunca invente esse valor."
                            )
                        },
                        "prompt_usuario": {
                            "type": "string",
                            "description": (
                                "A instrução para o relatório. "
                                "Descreva claramente o tipo de análise desejada "
                                "(por exemplo: rastreabilidade de requisito X, comparação entre releases, "
                                "métricas de PR, hotspots de código, etc.)."
                            )
                        }
                    },
                    "required": ["repositorio", "prompt_usuario"],
                },
            },
        }

        self.tool_schedule = {
            "type": "function",
            "function": {
                "name": "call_schedule_tool",
                "description": (
                    "Usado quando o usuário quer ENVIAR um relatório por EMAIL (agora ou agendado). "
                    "Use sempre que 'email', 'e-mail', 'agendar', 'alerta', 'monitorar', "
                    "'todo dia', 'toda semana', 'todo mês' ou 'enviar para mim' for mencionado. "
                    "Ideal para monitorar requisitos, módulos críticos, qualidade de código e "
                    "evolução do projeto ao longo do tempo."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {
                            "type": "string",
                            "description": "O nome do repositório no formato 'usuario/nome'."
                        },
                        "prompt_relatorio": {
                            "type": "string",
                            "description": (
                                "O que o relatório deve conter. "
                                "Descreva o objetivo do relatório e o foco de rastreabilidade "
                                "ou métricas que devem ser monitoradas."
                            )
                        },
                        "frequencia": {
                            "type": "string",
                            "enum": ["once", "daily", "weekly", "monthly"],
                            "description": (
                                "A frequência. Use 'once' para envio imediato. "
                                "'daily' para diário, 'weekly' para semanal, 'monthly' para mensal."
                            )
                        },
                        "hora": {
                            "type": "string",
                            "description": "A hora no formato HH:MM (24h)."
                        },
                        "timezone": {
                            "type": "string",
                            "description": "O fuso horário (ex: 'America/Sao_Paulo')."
                        },
                        "user_email": {
                            "type": "string",
                            "description": "O email do destinatário (ex: usuario@gmail.com)."
                        }
                    },
                    "required": ["repositorio", "prompt_relatorio", "frequencia", "hora", "timezone"], 
                },
            },
        }
        
        self.tool_save_instruction = {
            "type": "function",
            "function": {
                "name": "call_save_instruction_tool",
                "description": (
                    "Usado para salvar uma instrução para futuros relatórios. "
                    "Ideal quando o usuário quer registrar um 'template' de análise, "
                    "como por exemplo: 'relatório de rastreabilidade do requisito X', "
                    "'relatório de qualidade de PRs da equipe Y', etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repositorio": {
                            "type": "string",
                            "description": (
                                "O repositório ao qual esta instrução se aplica. "
                                "Formato 'usuario/nome'."
                            )
                        },
                        "instrucao": {
                            "type": "string",
                            "description": (
                                "A instrução específica que o usuário quer salvar. "
                                "Descreva de forma reutilizável, pois será usada em execuções futuras."
                            )
                        }
                    },
                    "required": ["repositorio", "instrucao"],
                },
            },
        }

        self.tool_chat = {
            "type": "function",
            "function": {
                "name": "call_chat_tool",
                "description": (
                    "Usado para bate-papo casual, saudações, explicações conceituais ou "
                    "respostas curtas que NÃO exigem acesso aos dados do repositório. "
                    "Exemplos: explicar o que é GitRAG, RAG, rastreabilidade, como usar a extensão, "
                    "ajudar a formular uma pergunta melhor, onboarding do usuário, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "O texto do usuário."
                        }
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
        if not self.client:
            raise Exception("LLMService não inicializado")
        
        print(f"[LLMService] Iniciando Agente de Encadeamento para: '{user_query}'")
        
        # 1. Ajuste do prompt do sistema para o Agente
        system_prompt = f"""
Você é o Orquestrador de Tarefas da plataforma GitRAG, uma solução de Engenharia de Software
que utiliza IA + RAG para rastreabilidade e análise de requisitos em repositórios GitHub.

Sua função é LER o pedido do usuário e devolvê-lo como uma LISTA ORDENADA de chamadas de ferramentas
(steps), na sequência correta, com todos os argumentos necessários.

CONTEXTUALIZAÇÃO DA PLATAFORMA:
- O GitRAG trabalha com artefatos de desenvolvimento (código-fonte, commits, Pull Requests, Issues, tags, releases)
  como uma 'documentação viva' consultável.
- Os objetivos típicos dos usuários incluem:
  - Entender se um requisito está implementado, onde e por quem.
  - Ver o impacto de um requisito, PR ou issue em diferentes módulos.
  - Investigar histórico de decisões (por meio de commits, PRs e issues).
  - Gerar relatórios de rastreabilidade, auditoria e qualidade.
  - Agendar relatórios recorrentes por email para monitorar o projeto ao longo do tempo.
- As ferramentas disponíveis são:
  - call_ingest_tool      → ingere/atualiza o índice RAG de um repositório.
  - call_query_tool       → responde perguntas no chat com base no RAG.
  - call_report_tool      → gera relatórios/exports para DOWNLOAD imediato.
  - call_schedule_tool    → agenda/manda relatórios por EMAIL (uma vez ou recorrente).
  - call_save_instruction_tool → salva templates de instrução para relatórios futuros.
  - call_chat_tool        → conversa casual, onboarding e explicações que não exigem dados do repo.

REGRAS CRÍTICAS DE ENCAMINHAMENTO:
1. CHAME MÚLTIPLAS FERRAMENTAS QUANDO NECESSÁRIO:
   - Se o usuário pedir 'ingira X e depois gere relatório', retorne steps em ordem:
     [call_ingest_tool, call_report_tool].
   - Se o usuário pedir 'ingira X e depois responda minha pergunta', retorne:
     [call_ingest_tool, call_query_tool].
   - Se o usuário pedir 'ingira X, salve um template de relatório e agende por email', retorne:
     [call_ingest_tool, call_save_instruction_tool, call_schedule_tool].

2. EMAIL vs DOWNLOAD:
   - Use APENAS call_schedule_tool para qualquer solicitação que mencione explicitamente:
     'email', 'e-mail', 'agendar', 'todo dia', 'toda semana', 'todo mês', 'alerta',
     'monitorar', 'mandar para mim por email'.
   - Use APENAS call_report_tool quando o usuário quiser gerar algo para download imediato:
     'gerar relatório', 'gerar gráfico', 'exportar', 'baixar', 'download', 'PDF', 'planilha', etc.

3. INGESTÃO PRÉVIA:
   - Se o usuário pedir consulta (call_query_tool), relatório (call_report_tool) ou agendamento
     (call_schedule_tool) para um repositório, inclua **call_ingest_tool** como o PRIMEIRO passo,
     exceto se o usuário deixar claro que o repositório já foi ingerido e que ele quer apenas
     'reusar' o índice existente.
   - Quando em dúvida, prefira incluir call_ingest_tool como primeiro passo.

4. CHAT GERAL / ONBOARDING:
   - Se o usuário só estiver:
     - cumprimentando ('oi', 'olá', 'bom dia'),
     - agradecendo ('valeu', 'obrigado'),
     - pedindo explicações sobre a própria plataforma GitRAG, RAG ou conceitos gerais de Git/GitHub,
     e NÃO exigir dados do repositório,
     → use call_chat_tool (pode ser a única ferramenta).
   - NÃO chame ferramentas de ingestão/consulta se a pergunta for apenas conceitual.

5. ESCOLHA ENTRE QUERY, REPORT E SCHEDULE:
   - use call_query_tool para perguntas exploratórias que o usuário quer responder dentro do chat:
     'explique a implementação do requisito X', 'quais commits mencionam a issue Y?',
     'como o módulo A evoluiu ao longo do tempo?', 'liste PRs que tocam o arquivo Z'.
   - use call_report_tool quando o usuário pedir explicitamente um RELATÓRIO/GRÁFICO/EXPORT
     para DOWNLOAD AGORA.
   - use call_schedule_tool sempre que houver desejo de ENVIO POR EMAIL ou RECORRÊNCIA
     (diária, semanal, mensal).

6. SALVAR INSTRUÇÕES:
   - use call_save_instruction_tool quando o usuário falar coisas como:
     'salvar esse modelo de relatório', 'guarde essa instrução para usar depois',
     'crie um template de relatório de rastreabilidade', etc.
   - É comum combinar com call_report_tool ou call_schedule_tool em um plano multi-etapas.

7. VALIDAÇÃO DE ARGUMENTOS:
   - Se um argumento obrigatório estiver faltando (como o nome do repositório),
     NÃO invente valores.
     Em vez disso, retorne uma resposta textual de clarificação (tipo: pedir para o usuário informar).
   - Nunca invente o nome de repositório, email ou timezone.

8. IDIOMA:
   - Responda sempre no mesmo idioma do usuário (neste caso, normalmente português).

Data/Hora de referência: Hoje é {datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%Y-%m-%d')}.
Fuso horário padrão para agendamentos: 'America/Sao_Paulo'.
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
                    return {
                        "type": "clarify",
                        "response_text": (
                            "A IA falhou em formatar a requisição de ferramenta. "
                            "Por favor, reformule sua solicitação de forma mais direta."
                        )
                    }
            
            # Validação: Se a IA tentou chamar uma ferramenta mas retornou campos vazios, é falha na intenção.
            for step in steps:
                if step["intent"] != "call_chat_tool":
                    func_def = self.tool_map.get(step["intent"], {}).get("function", {})
                    required_params = func_def.get("parameters", {}).get("required", [])
                    
                    for param in required_params:
                        if not step["args"].get(param):
                            return {
                                "type": "clarify",
                                "response_text": (
                                    f"O campo obrigatório '{param}' está faltando. "
                                    "Por favor, forneça esse valor (por exemplo, o nome do repositório)."
                                )
                            }

            print(f"[LLMService] Intenções detectadas: {len(steps)} etapas.")
            
            return {
                "type": "multi_step", 
                "steps": steps
            }

        except Exception as e:
            print(f"[LLMService] Erro no get_intent multi-step: {e}")
            return {"type": "clarify", "response_text": f"Erro interno ao processar: {e}"}

    
    def generate_response(self, query: str, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.client:
            raise Exception("LLMService não inicializado.")
        print("[LLMService] Iniciando resposta RAG (NÃO-Streaming)...")
        
        formatted_context = self._format_context(context)
        
        system_prompt = """
Você é um assistente de IA da plataforma GitRAG, especialista em análise de repositórios GitHub
com foco em rastreabilidade e análise de requisitos.

OBJETIVO:
- Responder à consulta do usuário usando EXCLUSIVAMENTE o contexto fornecido
  (commits, issues, PRs, arquivos, metadados).
- Ajudar o usuário a entender como os requisitos se relacionam com o código,
  quais artefatos dão suporte a cada afirmação e quais são os possíveis impactos.

REGRAS PRINCIPAIS:
1. Use SOMENTE o contexto fornecido.
   - Se algo não estiver no contexto, diga claramente que não encontrou evidências.
   - Nunca invente IDs de requisito, hashes de commit, números de PR, "
     "issues ou arquivos que não apareçam no texto do contexto.

2. Estruture a resposta de forma clara e útil para Engenharia de Software.
   Sugestão de estrutura (quando fizer sentido):
   - Visão geral da resposta.
   - Evidências principais (commits, PRs, issues, arquivos relevantes).
   - Impactos/implicações (por exemplo: módulos afetados, possíveis riscos).
   - Lacunas e incertezas (o que o contexto não cobre).

3. Linguagem:
   - Responda no MESMO idioma da consulta (se a pergunta estiver em português, responda em português).
   - Seja direto, técnico o suficiente, mas sem jargão desnecessário.

4. Transparência:
   - Se o contexto parece contraditório ou incompleto, aponte isso explicitamente.
   - Se houver múltiplas interpretações possíveis, explique as alternativas.

5. Tamanho:
   - Seja conciso, mas completo o bastante para ser útil.
   - Use parágrafos curtos e, quando ajudar, listas/bullets.
"""
        user_prompt = (
            f"Contexto (documentos de commits, issues, PRs etc.):\n{formatted_context}\n\n"
            f"Consulta do usuário: \"{query}\"\n\n"
            "Baseado APENAS no contexto acima, responda à consulta seguindo as regras do sistema."
        )

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
        if not self.client:
            raise Exception("LLMService não inicializado.")
        print("[LLMService] Iniciando resposta em STREAMING...")
        
        formatted_context = self._format_context(context)
        
        system_prompt = """
Você é um assistente de IA da plataforma GitRAG, especialista em análise de repositórios GitHub
com foco em rastreabilidade e análise de requisitos.

OBJETIVO:
- Responder à consulta do usuário usando EXCLUSIVAMENTE o contexto fornecido
  (commits, issues, PRs, arquivos, metadados).

Siga as mesmas regras de estilo e transparência descritas anteriormente:
- Use apenas o contexto.
- Não invente IDs de requisito, commits ou PRs.
- Estruture a resposta (visão geral, evidências, impactos, lacunas) quando fizer sentido.
- Responda no idioma da pergunta, de forma clara e direta.
"""
        user_prompt = (
            f"Contexto (documentos de commits, issues, PRs etc.):\n{formatted_context}\n\n"
            f"Consulta do usuário: \"{query}\"\n\n"
            "Baseado APENAS no contexto acima, responda à consulta seguindo as regras do sistema."
        )

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
Você é um analista de dados especializado em repositórios de software na plataforma GitRAG.

Sua tarefa é transformar dados brutos de um repositório (commits, PRs, issues, arquivos, métricas)
em um ÚNICO objeto JSON com duas chaves principais:

1. "analysis_markdown": texto em Markdown com uma análise interpretativa de alto nível.
2. "chart_json": especificação de um gráfico em formato compatível com Chart.js (ou similar).

REGRAS OBRIGATÓRIAS:
1. Formato:
   - O resultado FINAL DEVE ser um ÚNICO objeto JSON válido.
   - Não escreva texto fora do JSON.

2. Estrutura JSON:
   - "analysis_markdown": string Markdown.
     Recomenda-se a seguinte estrutura (quando fizer sentido):
       # Visão Geral
       - Explique rapidamente o que os dados parecem mostrar.

       ## Principais Métricas
       - Destaque números importantes (ex.: número de commits, PRs, issues, autores, arquivos mais modificados).

       ## Hotspots e Concentração
       - Quais arquivos, diretórios ou módulos parecem ser mais modificados?
       - Há concentração de conhecimento em poucos autores (risco de bus factor)?

       ## Rastreabilidade de Requisitos
       - Quando possível, comente como commits/PRs/issues se relacionam a requisitos (IDs, tags, descrições).

       ## Riscos e Pontos de Atenção
       - Apresente possíveis riscos (ex.: muitos bugs em um módulo, alta rotatividade em arquivos críticos).

       ## Recomendações
       - Sugira ações práticas (ex.: adicionar testes, refatorar módulos, melhorar documentação, etc.).

   - "chart_json": objeto JSON descrevendo UM gráfico útil.
     Exemplos de gráficos possíveis:
       - Commits por autor.
       - Commits por arquivo ou diretório.
       - PRs por estado (aberto/fechado).
       - Issues abertas x fechadas ao longo do tempo.
       - Requisitos (ou tags) mais referenciados.

     O formato pode ser similar ao do Chart.js, por exemplo:
       {{
         "type": "bar",
         "data": {{
           "labels": ["autor1", "autor2"],
           "datasets": [{{
             "label": "Commits por autor",
             "data": [10, 5]
           }}]
         }},
         "options": {{}}
       }}

3. Consistência:
   - Não invente dados. Use SOMENTE o que estiver contido em "Dados Brutos".
   - Se algo não estiver disponível, ignore ou explique na análise que a informação não está presente.

4. Idioma:
   - Produza "analysis_markdown" em português, pois o contexto da plataforma é pt-BR.

5. Tamanho:
   - Seja objetivo, mas informativo. Evite textos extremamente longos.
"""
        final_user_prompt = f"""
Contexto do Repositório: {repo_name}
Prompt do Usuário: "{user_prompt}"
Dados Brutos (JSON): {context_json_string}
---
Gere o relatório em um único objeto JSON com as chaves "analysis_markdown" e "chart_json",
seguindo estritamente as regras fornecidas no sistema.
"""
        try:
            response = self.client.chat.completions.create(
                model=self.generation_model, 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": final_user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=4000
            )
            
            response_content = response.choices[0].message.content
            
            if not response_content:
                print("[LLMService] ERRO: OpenAI retornou None (provável filtro de conteúdo).")
                return json.dumps({
                    "analysis_markdown": (
                        "# Erro de Geração\n\n"
                        "A IA não conseguiu gerar uma resposta. Isso pode ter sido causado por filtros de conteúdo "
                        "ou uma falha na API."
                    ),
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
Você é um assistente de IA em modo 'resposta rápida' (como um chat de mensageria).

Regras:
- Responda de forma CURTA, casual e prestativa.
- Se o usuário apenas disser 'ok', 'certo', 'beleza', 'show', 'sim', responda com algo simples como '👍' ou 'Entendido.'.
- Se o usuário disser 'obrigado', responda com algo como 'De nada!' ou 'Estou aqui para ajudar!'.
- Se houver uma pergunta simples, responda em 1 ou 2 frases, sem entrar em muitos detalhes técnicos.
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
                summary_line += f"Ingerir o repositório **{args.get('repositorio')}** para atualizar o índice RAG."
            elif intent == 'Query':
                summary_line += (
                    f"Consultar (RAG) o repositório {args.get('repositorio')} "
                    f"com a pergunta: '{args.get('prompt_usuario', '')}'."
                )
            elif intent == 'Report':
                summary_line += (
                    f"Gerar relatório para DOWNLOAD do repositório {args.get('repositorio')} "
                    f"(Prompt: '{args.get('prompt_usuario', '')}')."
                )
            elif intent == 'Schedule':
                freq = args.get('frequencia')
                repo = args.get('repositorio')
                email = args.get('user_email') or user_email
                hora = args.get('hora')
                tz = args.get('timezone')
                
                if freq == 'once':
                    schedule_details = f"e enviar imediatamente para o email **{email}**"
                else:
                    schedule_details = (
                        f"e agendar com frequência **{freq}** às {hora} "
                        f"(fuso {tz}) para o email **{email}**"
                    )
                
                summary_line += f"Preparar relatório {schedule_details} (Repo: {repo})."
            elif intent == 'Saveinstruction':
                summary_line += (
                    f"Salvar a instrução para futuros relatórios do repositório "
                    f"{args.get('repositorio')}."
                )
            
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
