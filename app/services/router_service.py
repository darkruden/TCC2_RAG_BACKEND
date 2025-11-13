# CÓDIGO COMPLETO PARA: app/services/router_service.py
import os
from openai import OpenAI
import json
from typing import Dict, Any

class RouterService:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        # Usamos um modelo rápido e barato para roteamento
        self.model = "gpt-4o-mini"
        self.system_prompt = """
Você é um roteador de consultas de API. Sua tarefa é classificar a intenção do usuário
e extrair entidades. Responda APENAS com um objeto JSON válido.

A consulta deve ser classificada em uma destas "categorias":
1. "semantica": Para perguntas sobre "como" algo funciona, "por que", "explique", ou propósito geral.
2. "cronologica": Para perguntas que usam "último", "primeiro", "mais recente", "mais antigo".
3. "desconhecida": Se a intenção não for clara.

Se a categoria for "cronologica", extraia também:
- "entidade": (commit, issue, pull_request)
- "ordem": (asc, desc)
- "limite": (o número de itens solicitados, ex: 4. O padrão é 1 se não for especificado.)

Se a categoria for "semantica" ou "desconhecida", retorne apenas a categoria.

Exemplos:

Usuário: "como funciona o sistema de login?"
{"categoria": "semantica"}

Usuário: "qual o ultimo commit deste repositorio e quem fez?"
{"categoria": "cronologica", "entidade": "commit", "ordem": "desc", "limite": 1}

Usuário: "quais os 4 ultimos commits deste repositório?"
{"categoria": "cronologica", "entidade": "commit", "ordem": "desc", "limite": 4}

Usuário: "me mostre a issue mais antiga"
{"categoria": "cronologica", "entidade": "issue", "ordem": "asc", "limite": 1}
"""

    def route_query(self, query: str) -> Dict[str, Any]:
        """
        Classifica a consulta do usuário para busca semântica ou cronológica.
        """
        print(f"[RouterService] Roteando consulta: {query}")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": query}
                ],
                temperature=0,
                response_format={"type": "json_object"} # Força a saída em JSON
            )
            
            result_json = json.loads(response.choices[0].message.content)
            print(f"[RouterService] Rota decidida: {result_json}")
            return result_json

        except Exception as e:
            print(f"[RouterService] Erro no roteamento, usando fallback semântico: {e}")
            # Fallback seguro: se o roteador falhar, apenas faça a busca semântica
            return {"categoria": "semantica"}