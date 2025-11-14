# CÓDIGO COMPLETO PARA: app/main.py

from dotenv import load_dotenv
load_dotenv() # Garante que o .env seja lido
from app.services.report_service import processar_e_salvar_relatorio
from fastapi import FastAPI, Depends, HTTPException, status, Header, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
        
        # --- INÍCIO DA CORREÇÃO ---
        # A linha que substituía '/' por '_' foi removida.
        
        return {
            "resposta": resultado["texto"],
            "fontes": [
                {
                    "tipo": "repositório",
                    "id": "contexto",
                    # Usamos 'request.repositorio' diretamente para a URL correta
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
        # Enfileira a tarefa na nova fila 'reports'
        # Passa os argumentos para a função 'processar_e_salvar_relatorio'
        job = q_reports.enqueue(
            processar_e_salvar_relatorio, 
            repo, 
            prompt,
            request.formato,
            job_timeout=1800  # 30 minutos de timeout para a LLM
        )

        msg = f"Solicitação de relatório para {repo} recebida e enfileirada."
        print(f"[SUCESSO] {msg} Job ID: {job.id}")

        # Reutiliza o 'IngestResponse' que já espera uma mensagem e job_id
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
    
    Para funcionar, o frontend deve enviar dados 'multipart/form-data'.
    """
    
    # 1. Validação básica do arquivo
    if not arquivo:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")
        
    if arquivo.content_type not in ["text/plain", "text/markdown", "application/octet-stream"]:
        print(f"[API] Tipo de arquivo rejeitado: {arquivo.content_type}")
        raise HTTPException(status_code=400, detail="Tipo de arquivo inválido. Envie .txt ou .md.")

    try:
        # 2. Ler o conteúdo do arquivo
        # await arquivo.read() lê o arquivo em bytes
        conteudo_bytes = await arquivo.read()
        
        # 3. Decodificar os bytes para uma string (assumindo UTF-8)
        try:
            query_do_arquivo = conteudo_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Não foi possível decodificar o arquivo. Certifique-se de que está em UTF-8.")

        if not query_do_arquivo.strip():
             raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")

        print(f"[API] Consulta recebida via arquivo: {arquivo.filename}")

        # 4. Chamar o serviço RAG (exatamente como a outra rota faz)
        # O 'gerar_resposta_rag' não precisa mudar, ele só quer uma string!
        resultado = gerar_resposta_rag(query_do_arquivo, repositorio)
        
        # 5. Retornar a resposta (código idêntico ao de /api/consultar)
        # (Já inclui a correção do link do GitHub que fizemos)
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
        # Garante que o traceback não vaze, mas dá o erro
        raise HTTPException(status_code=500, detail=f"Erro ao processar arquivo: {repr(e)}")

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
            dados.commits_limit,
            job_timeout=1200  # <--- INFORMA À FILA: "Esta tarefa pode levar 10 minutos"
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
        # Pega a fila 'ingest' (a mesma que o worker usa)
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
    
    # Retorna o status (pode ser 'queued', 'started', 'finished', 'failed')
    return {"status": status, "result": result, "error": error_info}

@app.get("/api/relatorio/status/{job_id}", dependencies=[Depends(verificar_token)])
async def get_report_job_status(job_id: str):
    """
    Verifica o status de um trabalho de RELATÓRIO na fila do RQ.
    """
    print(f"[API] Verificando status do Job de Relatório ID: {job_id}")
    try:
        # Pega da fila 'reports' (q_reports)
        job = q_reports.fetch_job(job_id)
    except Exception as e:
        print(f"[API] Erro ao buscar job de relatório (Redis?): {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao conectar com a fila: {e}")

    if job is None:
        print(f"[API] Job de Relatório {job_id} não encontrado.")
        # Retorna 404 (como o seu log mostrou) se o job não for encontrado
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
    
    # Retorna o status (pode ser 'queued', 'started', 'finished', 'failed')
    return {"status": status, "result": result, "error": error_info}

# Ponto de entrada para execução direta (testes locais)
if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor Uvicorn local em http://0.0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)