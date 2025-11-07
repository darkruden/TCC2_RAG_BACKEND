import os
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
            context: Lista de documentos de contexto
            
        Returns:
            Resposta gerada e informações de uso
        """
        # Formatar contexto para o prompt
        formatted_context = self._format_context(context)
        
        # Construir o prompt completo
        system_prompt = """
        Você é um assistente especializado em análise de requisitos de software.
        Sua função é analisar informações de repositórios GitHub e fornecer insights sobre requisitos.
        Responda apenas com base no contexto fornecido. Se a informação não estiver no contexto, indique claramente.
        Formate sua resposta em Markdown para melhor legibilidade.
        """
        
        user_prompt = f"""
        Consulta: {query}
        
        Contexto:
        {formatted_context}
        
        Responda à consulta com base apenas nas informações do contexto acima.
        """
        
        # Chamar a API da OpenAI
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
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
    
    def generate_report(self, repo_name: str, requirements_data: List[Dict[str, Any]]) -> str:
        """
        Gera um relatório de requisitos em formato Markdown.
        
        Args:
            repo_name: Nome do repositório
            requirements_data: Dados dos requisitos e suas relações
            
        Returns:
            Relatório em formato Markdown
        """
        # Formatar dados dos requisitos para o prompt
        formatted_data = self._format_requirements_data(requirements_data)
        
        system_prompt = """
        Você é um especialista em engenharia de requisitos de software.
        Sua tarefa é gerar um relatório detalhado sobre requisitos de software com base nos dados fornecidos.
        O relatório deve ser bem estruturado, em formato Markdown, e incluir:
        
        1. Um resumo executivo dos requisitos
        2. Uma análise detalhada de cada requisito
        3. Relações entre requisitos, issues, pull requests e commits
        4. Recomendações para melhorias na documentação e rastreabilidade
        
        Use formatação Markdown para criar um documento bem estruturado e legível.
        """
        
        user_prompt = f"""
        Gere um relatório completo de requisitos para o repositório: {repo_name}
        
        Dados dos requisitos:
        {formatted_data}
        
        O relatório deve seguir a estrutura mencionada e incluir todos os detalhes relevantes dos dados fornecidos.
        """
        
        # Chamar a API da OpenAI
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=2500
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
                formatted += f"Conteúdo: {doc.get('text', '')}\n\n"
            
            elif doc_type == "pull_request":
                formatted += f"Pull Request #{doc_id}: {doc.get('metadata', {}).get('title', '')}\n"
                formatted += f"URL: {doc.get('metadata', {}).get('url', '')}\n"
                formatted += f"Conteúdo: {doc.get('text', '')}\n\n"
            
            elif doc_type == "commit":
                formatted += f"Commit {doc.get('metadata', {}).get('sha', '')[:7]}\n"
                formatted += f"Autor: {doc.get('metadata', {}).get('author', '')}\n"
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
