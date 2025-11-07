import os
from functools import lru_cache
from typing import Dict, Any, Optional, List

class CacheService:
    """
    Serviço para implementação de cache em memória para consultas frequentes.
    Utiliza decorador lru_cache para otimizar o desempenho e reduzir chamadas redundantes.
    """
    
    def __init__(self, max_size: int = 128, ttl: int = 3600):
        """
        Inicializa o serviço de cache.
        
        Args:
            max_size: Tamanho máximo do cache (número de itens)
            ttl: Tempo de vida do cache em segundos (padrão: 1 hora)
        """
        self.max_size = max_size
        self.ttl = ttl
        
        # Configurar cache baseado nas variáveis de ambiente
        self.enabled = os.getenv("ENABLE_CACHE", "true").lower() == "true"
        if os.getenv("CACHE_EXPIRATION"):
            try:
                self.ttl = int(os.getenv("CACHE_EXPIRATION"))
            except (ValueError, TypeError):
                pass
    
    @lru_cache(maxsize=128)
    def cached_query(self, query: str, repo: str) -> Dict[str, Any]:
        """
        Placeholder para função que será decorada com cache.
        Na implementação real, esta função não será chamada diretamente.
        
        Args:
            query: Consulta em texto
            repo: Nome do repositório
            
        Returns:
            Resultado em cache ou None
        """
        # Esta função é apenas um placeholder
        # O cache real será implementado decorando as funções de consulta
        return None
    
    def clear_cache(self):
        """
        Limpa todo o cache em memória.
        """
        self.cached_query.cache_clear()
    
    def get_cache_info(self) -> Dict[str, Any]:
        """
        Retorna informações sobre o estado atual do cache.
        
        Returns:
            Dicionário com estatísticas do cache
        """
        cache_info = self.cached_query.cache_info()
        return {
            "enabled": self.enabled,
            "max_size": self.max_size,
            "ttl": self.ttl,
            "hits": cache_info.hits,
            "misses": cache_info.misses,
            "current_size": cache_info.currsize
        }
    
    def is_enabled(self) -> bool:
        """
        Verifica se o cache está habilitado.
        
        Returns:
            True se o cache estiver habilitado, False caso contrário
        """
        return self.enabled
    
    def create_key(self, *args, **kwargs) -> str:
        """
        Cria uma chave de cache a partir dos argumentos.
        
        Args:
            *args: Argumentos posicionais
            **kwargs: Argumentos nomeados
            
        Returns:
            String representando a chave de cache
        """
        # Criar uma representação de string dos argumentos para usar como chave
        key_parts = [str(arg) for arg in args]
        key_parts.extend([f"{k}={v}" for k, v in sorted(kwargs.items())])
        return ":".join(key_parts)
    
    def apply_to_function(self, func):
        """
        Aplica cache a uma função existente.
        
        Args:
            func: Função a ser decorada com cache
            
        Returns:
            Função decorada com cache
        """
        if not self.enabled:
            return func
            
        @lru_cache(maxsize=self.max_size)
        def cached_func(*args, **kwargs):
            return func(*args, **kwargs)
            
        return cached_func
