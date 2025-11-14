# CÓDIGO COMPLETO PARA: app/main.py
# (Com o novo endpoint /api/relatorio/download/{filename} adicionado)

from dotenv import load_dotenv
load_dotenv() # Garante que o .env seja lido
from app.services.report_service import processar_e_salvar_relatorio
from fastapi import FastAPI, Depends, HTTPException, status, Header, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
from app.services.metadata_service import MetadataService
from app.services.llm_service import LLMService
# --- INÍCIO DAS NOVAS ADIÇÕES (Parte 3) ---
import redis
from rq import Queue
from app.services.ingest_service import ingest_repo # Importamos a função de ingestão
# -----------------------------------------------

# --- INÍCIO DAS ADIÇÕES PARA DOWNLOAD DE RELATÓRIO ---
import io
from fastapi.responses import StreamingResponse
from supabase import create_client
# --- FIM DAS ADIÇÕES PARA DOWNLOAD DE RELATÓRIO ---

# Importações de serviços existentes
from app.services.rag_service import gerar_resposta_rag
from app.services.report_service import ReportService 

# --- INÍCIO DA CONFIGURAÇÃO DA FILA (Parte 3) ---
# Pega a URL do Redis (do Heroku Add-on ou do nosso localhost)
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
conn = redis.from_url(redis_url)

# 'ingest' é o nome da fila que nosso worker.py está escutando
q = Queue('ingest', connection=conn) 

q_reports = Queue('reports', connection=conn)

metadata_service_relatorio = MetadataService()
llm_service_relatorio = LLMService()
report_service_relatorio = ReportService()

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
    prompt: str
    formato: str = "html"

class IngestRequest(BaseModel):
    repositorio: str
    issues_limit: Optional[int] = 20
    prs_limit: Optional[int] = 10
    commits_limit: Optional[int] = 15

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
    """
    try:
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
    except Exception as e:
        print(f"Erro em /api/consultar: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar consulta RAG: {repr(e)}")


@app.post("/api/relatorio", response_model=IngestResponse, dependencies=[Depends(verificar_token)])
async def gerar_relatorio_async(request: RelatorioRequest):
    """
    Recebe um prompt, ENFILEIRA a tarefa de geração de relatório
    e retorna IMEDIATAMENTE.
    """
    repo = request.repositorio
    prompt = request.prompt
    if not repo or not prompt:
        raise HTTPException(status_code=400, detail="Campos 'repositorio' e 'prompt' são obrigatórios")

    try:
        job = q_reports.enqueue(
            processar_e_salvar_relatorio, 
            repo, 
            prompt,
            request.formato,
            job_timeout=1800
        )

        msg = f"Solicitação de relatório para {repo} recebida e enfileirada."
        print(f"[SUCESSO] {msg} Job ID: {job.id}")

        return {"mensagem": msg, "job_id": job.id}

    except Exception as e:
        error_message = repr(e) 
        print(f"Erro DETALHADO ao enfileirar relatório de {repo}: {error_message}")
        raise HTTPException(status_code=500, detail=f"Erro ao enfileirar tarefa de relatório: {error_message}")

@app.post("/api/consultar_arquivo", response_model=ConsultaResponse, dependencies=[Depends(verificar_token)])
async def consultar_arquivo(
    repositorio: str = Form(...),
    arquivo: UploadFile = File(...)
):
    """
    Recebe uma consulta via UPLOAD DE ARQUIVO, busca o contexto no RAG
    e retorna a resposta da IA.
    """
    
    if not arquivo:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")
        
    if arquivo.content_type not in ["text/plain", "text/markdown", "application/octet-stream"]:
        print(f"[API] Tipo de arquivo rejeitado: {arquivo.content_type}")
        raise HTTPException(status_code=400, detail="Tipo de arquivo inválido. Envie .txt ou .md.")

    try:
        conteudo_bytes = await arquivo.read()
        
        try:
            query_do_arquivo = conteudo_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Não foi possível decodificar o arquivo. Certifique-se de que está em UTF-8.")

        if not query_do_arquivo.strip():
             raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")

        print(f"[API] Consulta recebida via arquivo: {arquivo.filename}")

        resultado = gerar_resposta_rag(query_do_arquivo, repositorio)
        
        return {
            "resposta": resultado["texto"],
            "fontes": [
                {
                    "tipo": "repositório",
                    "id": "contexto",
                    "url": f"https://github.com/{repositorio}"
                }
            ],
            "contexto": {"trechos": resultado["contexto"]}
        }
        
    except Exception as e:
        print(f"Erro em /api/consultar_arquivo: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar arquivo: {repr(e)}")

@app.post("/api/ingest", response_model=IngestResponse, dependencies=[Depends(verificar_token)])
async def ingestar(dados: IngestRequest):
    """
    Recebe um repositório, ENFILEIRA a tarefa de ingestão e retorna IMEDIATAMENTE.
    """
    repo = dados.repositorio
    if not repo:
        raise HTTPException(status_code=400, detail="Campo 'repositorio' é obrigatório")

    try:
        job = q.enqueue(
            ingest_repo, 
            repo, 
            dados.issues_limit, 
            dados.prs_limit, 
            dados.commits_limit,
            job_timeout=1200
)

        msg = f"Solicitação de ingestão para {repo} recebida e enfileirada."
        print(f"[SUCESSO] {msg} Job ID: {job.id}")

        return {"mensagem": msg, "job_id": job.id}

    except Exception as e:
        error_message = repr(e) 
        print(f"Erro DETALHADO ao enfileirar ingestão de {repo}: {error_message}")
        raise HTTPException(status_code=500, detail=f"Erro ao enfileirar tarefa de ingestão: {error_message}")


@app.get("/api/ingest/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_job_status(job_id: str):
    """
    Verifica o status de um trabalho de ingestão na fila do RQ.
    """
    print(f"[API] Verificando status do Job ID: {job_id}")
    try:
        job = q.fetch_job(job_id)
    except Exception as e:
        print(f"[API] Erro ao buscar job (Redis?): {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")

    if job is None:
        print(f"[API] Job {job_id} não encontrado.")
        return {"status": "not_found"}

    status = job.get_status()
    result = None
    error_info = None

    if status == 'finished':
        result = job.result
        print(f"[API] Job {job_id} finalizado. Resultado: {result}")
    elif status == 'failed':
        error_info = str(job.exc_info)
        print(f"[API] Job {job_id} falhou. Erro: {error_info}")
    
    return {"status": status, "result": result, "error": error_info}

@app.get("/api/relatorio/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_report_job_status(job_id: str):
    """
    Verifica o status de um trabalho de RELATÓRIO na fila do RQ.
    """
    print(f"[API] Verificando status do Job de Relatório ID: {job_id}")
    try:
        job = q_reports.fetch_job(job_id)
    except Exception as e:
        print(f"[API] Erro ao buscar job de relatório (Redis?): {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")

    if job is None:
        print(f"[API] Job de Relatório {job_id} não encontrado.")
        return {"status": "not_found"}

    status = job.get_status()
    result = None
    error_info = None

    if status == 'finished':
        result = job.result
        print(f"[API] Job de Relatório {job_id} finalizado. Resultado: {result}")
    elif status == 'failed':
        error_info = str(job.exc_info)
        print(f"[API] Job de Relatório {job_id} falhou. Erro: {error_info}")
    
    return {"status": status, "result": result, "error": error_info}


# --- INÍCIO DA NOVA ROTA DE DOWNLOAD ---

@app.get("/api/relatorio/download/{filename}", dependencies=[Depends(verificar_token)])
async def download_report(filename: str):
    """
    Baixa um arquivo de relatório do Supabase Storage e o transmite
    ao usuário, forçando o download.
    """
    SUPABASE_BUCKET_NAME = "reports"
    
    try:
        # 1. Inicializa o cliente storage
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')
        if not url or not key:
            raise Exception("Credenciais Supabase não encontradas no servidor")
            
        client = create_client(url, key)
        
        print(f"[API-DOWNLOAD] Usuário solicitou download de: {filename}")

        # 2. Baixa o arquivo do Supabase (em memória)
        file_bytes = client.storage.from_(SUPABASE_BUCKET_NAME).download(filename)
        
        if not file_bytes:
            raise HTTPException(status_code=404, detail="Arquivo de relatório não encontrado no storage.")

        print(f"[API-DOWNLOAD] Arquivo encontrado. Transmitindo para o usuário...")

        # 3. Define os cabeçalhos para FORÇAR o download
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }

        # 4. Retorna o arquivo como um stream
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type='text/html', # Força o tipo correto
            headers=headers
        )

    except Exception as e:
        print(f"[API-DOWNLOAD] Erro ao baixar o arquivo: {repr(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar download do relatório: {repr(e)}")

# --- FIM DA NOVA ROTA DE DOWNLOAD ---


# Ponto de entrada para execução direta (testes locais)
if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor Uvicorn local em http://0.0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)