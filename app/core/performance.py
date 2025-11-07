import os
import time
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable

class PerformanceMiddleware(BaseHTTPMiddleware):
    """
    Middleware para monitoramento de performance das requisições.
    Registra o tempo de execução de cada requisição e adiciona headers de performance.
    """
    
    async def dispatch(self, request: Request, call_next: Callable):
        # Registrar tempo de início
        start_time = time.time()
        
        # Processar a requisição
        response = await call_next(request)
        
        # Calcular tempo de processamento
        process_time = time.time() - start_time
        
        # Adicionar headers de performance
        response.headers["X-Process-Time"] = str(process_time)
        
        return response

def configure_performance(app: FastAPI):
    """
    Configura otimizações de performance para o aplicativo FastAPI.
    
    Args:
        app: Instância do FastAPI
    """
    # Adicionar middleware de compressão Gzip
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
    # Adicionar middleware de monitoramento de performance
    app.add_middleware(PerformanceMiddleware)
    
    # Configurar CORS com opções otimizadas
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Em produção, especificar origens permitidas
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        max_age=86400,  # Cache de preflight por 24 horas
    )
    
    # Adicionar headers de segurança e cache
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: Callable):
        response = await call_next(request)
        
        # Headers de segurança
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Headers de cache para respostas estáticas
        if request.url.path.startswith(("/static/", "/reports/")):
            response.headers["Cache-Control"] = "public, max-age=3600"
        
        return response
    
    return app

def configure_rate_limiting(app: FastAPI, rate_limit: int = 100, time_window: int = 60):
    """
    Configura limitação de taxa de requisições para o aplicativo FastAPI.
    
    Args:
        app: Instância do FastAPI
        rate_limit: Número máximo de requisições por janela de tempo
        time_window: Janela de tempo em segundos
    """
    # Dicionário para armazenar contadores de requisições por IP
    request_counts = {}
    
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next: Callable):
        # Obter IP do cliente
        client_ip = request.client.host
        
        # Obter timestamp atual
        current_time = time.time()
        
        # Limpar entradas antigas
        for ip in list(request_counts.keys()):
            if current_time - request_counts[ip]["timestamp"] > time_window:
                del request_counts[ip]
        
        # Verificar limite de taxa
        if client_ip in request_counts:
            if request_counts[client_ip]["count"] >= rate_limit:
                # Verificar se ainda está dentro da janela de tempo
                if current_time - request_counts[client_ip]["timestamp"] < time_window:
                    return HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Limite de requisições excedido. Tente novamente mais tarde."
                    )
                else:
                    # Reiniciar contador se a janela de tempo expirou
                    request_counts[client_ip] = {"count": 1, "timestamp": current_time}
            else:
                # Incrementar contador
                request_counts[client_ip]["count"] += 1
        else:
            # Inicializar contador para novo IP
            request_counts[client_ip] = {"count": 1, "timestamp": current_time}
        
        # Processar a requisição
        response = await call_next(request)
        
        # Adicionar headers de limite de taxa
        response.headers["X-Rate-Limit-Limit"] = str(rate_limit)
        response.headers["X-Rate-Limit-Remaining"] = str(rate_limit - request_counts[client_ip]["count"])
        response.headers["X-Rate-Limit-Reset"] = str(int(request_counts[client_ip]["timestamp"] + time_window))
        
        return response
    
    return app
