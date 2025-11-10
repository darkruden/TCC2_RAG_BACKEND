# CÓDIGO COMPLETO PARA: app/main.py

from dotenv import load_dotenv
load_dotenv() # Garante que o .env seja lido

from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os

# --- INÍCIO DAS NOVAS ADIÇÕES (Parte 3) ---
import redis
from rq import Queue
from app.services.ingest_service import ingest_repo # Importamos a função de ingestão
# -----------------------------------------------

# Importações de serviços existentes
from app.services.rag_service import gerar_resposta_rag
from app.services.report_service import ReportService 

# --- INÍCIO DA CONFIGURAÇÃO DA FILA (Parte 3) ---
# Pega a URL do Redis (do Heroku Add-on ou do nosso localhost)
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
conn = redis.from_url(redis_url)

# 'ingest' é o nome da fila que nosso worker.py está escutando
q = Queue('ingest', connection=conn) 
# -----------------------------------------------


# Inicializar aplicação FastAPI
app = FastAPI(
    title="GitHub RAG API",
    description="API para análise e rastreabilidade de requisitos de software usando RAG",
    version="0.1.0"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modelos de dados (Pydantic)
class ConsultaRequest(BaseModel):
    query: str
    repositorio: str
    filtros: Optional[Dict[str, Any]] = None

class RelatorioRequest(BaseModel):
    repositorio: str
    requisitos: Optional[List[str]] = None
    formato: str = "markdown"

class IngestRequest(BaseModel):
    repositorio: str
    issues_limit: Optional[int] = 20  # O padrão é 20
    prs_limit: Optional[int] = 10      # O padrão é 10
    commits_limit: Optional[int] = 15  # O padrão é 15

class ConsultaResponse(BaseModel):
    resposta: str
    fontes: List[Dict[str, Any]]
    contexto: Optional[Dict[str, Any]] = None

class RelatorioResponse(BaseModel):
    url: str
    formato: str

class IngestResponse(BaseModel):
    mensagem: str
    job_id: Optional[str] = None

# Dependência para verificar token de API
async def verificar_token(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("API_TOKEN"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de API inválido"
        )
    return x_api_key

# --- Rotas da API ---

@app.get("/health")
async def health_check():
    """Verifica se a API está online."""
    try:
        # Testa a conexão com o Redis também
        conn.ping()
        redis_status = "conectado"
    except Exception as e:
        redis_status = f"desconectado ({e})"
        
    return {
        "status": "online", 
        "version": "0.1.0",
        "redis_status": redis_status
    }

@app.get("/test")
async def test_route():
    """Endpoint de teste simples."""
    return {"message": "Conexão com o backend estabelecida com sucesso!"}


@app.post("/api/consultar", response_model=ConsultaResponse, dependencies=[Depends(verificar_token)])
async def consultar(request: ConsultaRequest):
    """
    Recebe uma consulta, busca o contexto no RAG e retorna a resposta da IA.
    (Esta rota não muda, ela continua síncrona e rápida)
    """
    try:
        resultado = gerar_resposta_rag(request.query, request.repositorio)
        
        # Sanitiza o nome do repositório para a URL de fontes
        repo_url_name = request.repositorio.replace('/', '_')
        
        return {
            "resposta": resultado["texto"],
            "fontes": [
                {
                    "tipo": "repositório",
                    "id": "contexto",
                    "url": f"https://github.com/{repo_url_name}"
                }
            ],
            "contexto": {"trechos": resultado["contexto"]}
        }
    except Exception as e:
        print(f"Erro em /api/consultar: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar consulta RAG: {repr(e)}")


@app.post("/api/relatorio", response_model=RelatorioResponse, dependencies=[Depends(verificar_token)])
async def gerar_relatorio(request: RelatorioRequest):
    """
    Gera um relatório (atualmente apenas Markdown).
    (Esta rota não muda)
    """
    service = ReportService()
    try:
        # (Simulando a busca de dados e geração de conteúdo)
        content = f"# Relatório para {request.repositorio}\n\n"
        content += "Este é um relatório de exemplo.\n"
        
        resultado = service.generate_report(
            request.repositorio, 
            content, 
            request.formato
        )
        
        # (Em um app real, retornaríamos uma URL pública, não um caminho de arquivo)
        return {
            "url": f"/reports/{resultado['filename']}", # Simulação
            "formato": resultado["format"]
        }
    except Exception as e:
        print(f"Erro em /api/relatorio: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar relatório: {repr(e)}")


# --- ROTA MODIFICADA (Parte 3) ---
@app.post("/api/ingest", response_model=IngestResponse, dependencies=[Depends(verificar_token)])
async def ingestar(dados: IngestRequest):
    """
    Recebe um repositório, ENFILEIRA a tarefa de ingestão e retorna IMEDIATAMENTE.
    """
    repo = dados.repositorio
    if not repo:
        raise HTTPException(status_code=400, detail="Campo 'repositorio' é obrigatório")

    try:
    # Agora passamos os limites para a função que será enfileirada
        job = q.enqueue(
            ingest_repo, 
            repo, 
            dados.issues_limit, 
            dados.prs_limit, 
            dados.commits_limit
        )

        msg = f"Solicitação de ingestão para {repo} recebida e enfileirada."
        print(f"[SUCESSO] {msg} Job ID: {job.id}")

        return {"mensagem": msg, "job_id": job.id}

    except Exception as e:
        error_message = repr(e) 
        print(f"Erro DETALHADO ao enfileirar ingestão de {repo}: {error_message}")
        raise HTTPException(status_code=500, detail=f"Erro ao enfileirar tarefa de ingestão: {error_message}")

# ---------------------------------

# Ponto de entrada para execução direta (testes locais)
if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor Uvicorn local em http://0.0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)