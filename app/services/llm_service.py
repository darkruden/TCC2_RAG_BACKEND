import os
import json
from openai import OpenAI
from typing import List, Dict, Any, Optional

class LLMService:
    """
    Serviço para integração com modelos de linguagem grandes (LLMs).
    Utiliza a API da OpenAI para gerar respostas contextuais.
    """
    
    def __init__(self, api_key: str = None, model: str = "gpt-4"):
        """
        Inicializa o serviço LLM.
        
        Args:
            api_key: Chave da API OpenAI
            model: Modelo a ser utilizado
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Chave da API OpenAI não fornecida")
        
        self.model = model
        self.client = OpenAI(api_key=self.api_key)
        
        # Contador para monitoramento de uso
        self.token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    
    def generate_response(self, query: str, context: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Gera uma resposta contextual usando o LLM.
        
        Args:
            query: Consulta do usuário
            context: Lista de documentos de contexto (já contém metadados)
            
        Returns:
            Resposta gerada e informações de uso
        """
        # Formatar contexto para o prompt (Sua função _format_context já faz isso bem)
        formatted_context = self._format_context(context)
        
        # --- INÍCIO DA CORREÇÃO ---
        # Instruções de prompt muito mais detalhadas
        
        # (Dentro da função generate_response)
        
        # (Dentro da função generate_response)
        
        system_prompt = """
Você é um assistente de engenharia de software de elite. Sua especialidade é 
analisar o contexto de um repositório GitHub (commits, issues, PRs) e 
responder perguntas sobre rastreabilidade de requisitos.

REGRAS DE FORMATAÇÃO OBRIGATÓRIAS:
1.  **Formato de Resposta:** Sempre formate sua resposta em Markdown.
2.  **Seja Direto:** Responda à pergunta do usuário diretamente.
3.  **CITE SUAS FONTES:** Esta é a regra mais importante. Ao citar uma fonte, você DEVE usar os metadados 'URL' (que estão no contexto) para criar um link Markdown clicável.
4.  **RELAÇÕES:** Se um commit (no seu texto) menciona "Fixes #123", você DEVE fazer a relação com a Issue correspondente, se ela também estiver no contexto.
5.  **PERGUNTAS CRONOLÓGICAS:** Se o usuário perguntar sobre "último", "mais recente" ou "primeiro", você DEVE usar os metadados 'Data' (que estão no contexto) para determinar a ordem correta antes de responder.
EXEMPLO DE FORMATAÇÃO CORRETA (Use este padrão):
- A funcionalidade X foi implementada por fulano no commit [a4f5c6d](https://github.com/usuario/repo/commit/a4f5c6d3...).
- Isso foi discutido na Issue [#123](https://github.com/usuario/repo/issues/123).
- Veja também a Pull Request [#45](https://github.com/usuario/repo/pull/45).

EXEMPLO DE FORMATAÇÃO INCORRETA (NUNCA FAÇA ISSO):
- A funcionalidade foi feita no commit usuario_repo/a4f5c6d.
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
        
        # --- FIM DA CORREÇÃO ---
        
        # Chamar a API da OpenAI
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3, # Mantemos a temperatura baixa para respostas factuais
            max_tokens=1000
        )
        
        # Atualizar contadores de uso
        usage = response.usage
        self.token_usage["prompt_tokens"] += usage.prompt_tokens
        self.token_usage["completion_tokens"] += usage.completion_tokens
        self.token_usage["total_tokens"] += usage.total_tokens
        
        return {
            "response": response.choices[0].message.content,
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens
            }
        }
    
    def generate_analytics_report(self, repo_name: str, user_prompt: str, raw_data: List[Dict[str, Any]]) -> str:
        """
        Gera um relatório de análise de dados (analytics) com base
        em um prompt do usuário e dados brutos do SQL.
        Instrui o modelo a gerar gráficos usando Mermaid.js.
        
        Args:
            repo_name: Nome do repositório
            user_prompt: A pergunta do usuário (ex: "quem mais commita?")
            raw_data: Uma lista de dicionários (metadados) do MetadataService
            
        Returns:
            Relatório completo em formato Markdown
        """
        
        # Converte a lista de dados brutos em uma string JSON compacta
        # Isso é muito mais eficiente para a LLM processar do que texto puro.
        context_json_string = json.dumps(raw_data)
        
        system_prompt = f"""
Você é um analista de dados e engenheiro de software de elite, 
especializado em analisar repositórios GitHub.
Sua tarefa é responder a uma pergunta do usuário (prompt) usando um 
conjunto de dados brutos (em JSON) fornecido.

REGRAS OBRIGATÓRIAS:
1.  **Formato:** O relatório final DEVE ser em Markdown.
2.  **Seja Analítico:** Não apenas liste dados, gere *insights* que 
    respondam diretamente ao prompt do usuário.
3.  **Use os Dados:** Baseie sua análise APENAS nos dados JSON fornecidos.
4.  **GRÁFICOS (Regra mais importante):** Para melhorar a experiência visual,
    você DEVE gerar gráficos usando a sintaxe Mermaid.js sempre que 
    uma visualização for apropriada (ex: gráficos de barras, pizza, etc.).
    
    Exemplo de Gráfico de Barras Mermaid:
    ```mermaid
    graph TD
        A[Cassiano: 15 commits] --> B(João: 10 commits)
        A --> C(Maria: 5 commits)
    end
    ```

    Exemplo de Gráfico de Pizza Mermaid:
    ```mermaid
    pie title Commits por Autor
        "Cassiano" : 15
        "João" : 10
        "Maria" : 5
    ```
"""
        
        final_user_prompt = f"""
Contexto do Repositório: {repo_name}

Prompt do Usuário:
"{user_prompt}"

---
Dados Brutos (JSON):
{context_json_string}
---

Gere um relatório completo em Markdown que responda ao prompt do usuário,
usando os dados brutos e incluindo gráficos Mermaid.js.
"""
        
        # Chamar a API da OpenAI
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": final_user_prompt}
            ],
            temperature=0.3, # Baixa temperatura para análise factual
            max_tokens=4000  # Aumentamos os tokens para relatórios longos
        )
        
        # Atualizar contadores de uso
        usage = response.usage
        self.token_usage["prompt_tokens"] += usage.prompt_tokens
        self.token_usage["completion_tokens"] += usage.completion_tokens
        self.token_usage["total_tokens"] += usage.total_tokens
        
        return response.choices[0].message.content
    
    def get_token_usage(self) -> Dict[str, int]:
        """
        Retorna estatísticas de uso de tokens.
        
        Returns:
            Dicionário com contagem de tokens
        """
        return self.token_usage
    
    def _format_context(self, context: List[Dict[str, Any]]) -> str:
        """
        Formata o contexto para inclusão no prompt.
        
        Args:
            context: Lista de documentos de contexto
            
        Returns:
            Contexto formatado como string
        """
        formatted = ""
        
        for i, doc in enumerate(context):
            doc_type = doc.get("metadata", {}).get("type", "documento")
            doc_id = doc.get("metadata", {}).get("id", i)
            
            if doc_type == "issue":
                formatted += f"Issue #{doc_id}: {doc.get('metadata', {}).get('title', '')}\n"
                formatted += f"URL: {doc.get('metadata', {}).get('url', '')}\n"
                formatted += f"Data: {doc.get('metadata', {}).get('created_at', '')}\n"
                formatted += f"Conteúdo: {doc.get('text', '')}\n\n"
            
            elif doc_type == "pull_request":
                formatted += f"Pull Request #{doc_id}: {doc.get('metadata', {}).get('title', '')}\n"
                formatted += f"URL: {doc.get('metadata', {}).get('url', '')}\n"
                formatted += f"Data: {doc.get('metadata', {}).get('created_at', '')}\n"
                formatted += f"Conteúdo: {doc.get('text', '')}\n\n"
            
            elif doc_type == "commit":
                formatted += f"Commit {doc.get('metadata', {}).get('sha', '')[:7]}\n"
                formatted += f"URL: {doc.get('metadata', {}).get('url', '')}\n"  # <-- LINHA ADICIONADA
                formatted += f"Autor: {doc.get('metadata', {}).get('author', '')}\n"
                formatted += f"Data: {doc.get('metadata', {}).get('date', '')}\n"
                formatted += f"Mensagem: {doc.get('text', '')}\n\n"
            
            else:
                formatted += f"Documento {i+1}:\n{doc.get('text', '')}\n\n"
        
        return formatted
    
    def _format_requirements_data(self, requirements_data: List[Dict[str, Any]]) -> str:
        """
        Formata os dados dos requisitos para inclusão no prompt.
        
        Args:
            requirements_data: Lista de dados dos requisitos
            
        Returns:
            Dados formatados como string
        """
        formatted = ""
        
        for i, req in enumerate(requirements_data):
            formatted += f"Requisito {i+1}: {req.get('title', '')}\n"
            formatted += f"Descrição: {req.get('description', '')}\n"
            
            # Adicionar issues relacionadas
            if "issues" in req and req["issues"]:
                formatted += "Issues relacionadas:\n"
                for issue in req["issues"]:
                    formatted += f"- Issue #{issue.get('id')}: {issue.get('title')}\n"
            
            # Adicionar PRs relacionados
            if "pull_requests" in req and req["pull_requests"]:
                formatted += "Pull Requests relacionados:\n"
                for pr in req["pull_requests"]:
                    formatted += f"- PR #{pr.get('id')}: {pr.get('title')}\n"
            
            # Adicionar commits relacionados
            if "commits" in req and req["commits"]:
                formatted += "Commits relacionados:\n"
                for commit in req["commits"]:
                    formatted += f"- {commit.get('sha')[:7]}: {commit.get('message')}\n"
            
            formatted += "\n"
        
        return formatted
