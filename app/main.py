from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
from app.services.ingest_service import ingest_repo
from app.services.rag_service import gerar_resposta_rag
# Carregar variáveis de ambiente
#alteração minima para teste, linha insignificante
# Inicializar aplicação FastAPI
app = FastAPI(
    title="GitHub RAG API",
    description="API para análise e rastreabilidade de requisitos de software usando RAG",
    version="0.1.0"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, especificar origens permitidas
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modelos de dados
class ConsultaRequest(BaseModel):
    query: str
    repositorio: str
    filtros: Optional[Dict[str, Any]] = None

class RelatorioRequest(BaseModel):
    repositorio: str
    requisitos: Optional[List[str]] = None
    formato: str = "markdown"  # markdown ou pdf

class ConsultaResponse(BaseModel):
    resposta: str
    fontes: List[Dict[str, Any]]
    contexto: Optional[Dict[str, Any]] = None

class RelatorioResponse(BaseModel):
    url: str
    formato: str

# Função para verificar token de autenticação
async def verificar_token(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("API_TOKEN"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de API inválido"
        )
    return x_api_key

# Rotas da API
@app.get("/health")
async def health_check():
    return {"status": "online", "version": "0.1.0"}

@app.get("/test")
async def test_route():
    return {"message": "Conexão com o backend estabelecida com sucesso!"}


@app.post("/api/consultar", response_model=ConsultaResponse, dependencies=[Depends(verificar_token)])
async def consultar(request: ConsultaRequest):
    resultado = gerar_resposta_rag(request.query, request.repositorio)

    return {
        "resposta": resultado["texto"],
        "fontes": [
            {
                "tipo": "repositório",
                "id": "contexto",
                "url": f"https://github.com/{request.repositorio}"
            }
        ],
        "contexto": {"trechos": resultado["contexto"]}
    }



@app.post("/api/relatorio", response_model=RelatorioResponse, dependencies=[Depends(verificar_token)])
async def gerar_relatorio(request: RelatorioRequest):
    # Implementação temporária - será substituída pela geração real de relatórios
    return {
        "url": f"https://exemplo.com/relatorios/{request.repositorio.replace('/', '_')}.{request.formato}",
        "formato": request.formato
    }

@app.post("/api/ingest")
async def ingestar(dados: Dict[str, str], x_api_key: str = Header(...)):
    if x_api_key != os.getenv("API_TOKEN"):
        raise HTTPException(status_code=401, detail="Token inválido")

    repo = dados.get("repositorio")
    if not repo:
        raise HTTPException(status_code=400, detail="Campo 'repositorio' é obrigatório")

    msg = ingest_repo(repo)
    return {"mensagem": msg}

# Ponto de entrada para execução direta
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
