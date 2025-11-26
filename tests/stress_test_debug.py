import requests
import concurrent.futures
import time
import random
import logging
import sys

# --- CONFIGURAÇÃO ---
API_URL = "https://meu-tcc-testes-041c1dd46d1d.herokuapp.com/api/chat"
# !!! IMPORTANTE: COLOCAR SUA API KEY REAL AQUI !!!
API_KEY = "d4936ab9-47f1-43ed-ae9a-51c3c3c4bc29"

# Quantidade de requisições
NUM_REQUESTS = 60

# --- CONFIGURAÇÃO DE LOGGING (Arquivo + Terminal) ---
# Limpa o arquivo de log anterior
with open("stress_test.log", "w") as f:
    f.write("")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("stress_test.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger()

# Lista de 60 Repositórios Reais para carga pesada
REAL_REPOS = [
    "pallets/flask", "django/django", "fastapi/fastapi", "psf/requests", "pydantic/pydantic",
    "encode/starlette", "encode/httpx", "tiangolo/typer", "celery/celery", "sqlalchemy/sqlalchemy",
    "facebook/react", "vuejs/core", "angular/angular", "sveltejs/svelte", "reduxjs/redux",
    "axios/axios", "expressjs/express", "nestjs/nest", "vercel/next.js", "remix-run/remix",
    "twbs/bootstrap", "tailwindlabs/tailwindcss", "mui/material-ui", "ant-design/ant-design", "chakra-ui/chakra-ui",
    "golang/go", "gin-gonic/gin", "gofiber/fiber", "spf13/cobra", "spf13/viper",
    "rust-lang/rust", "tokio-rs/tokio", "serde-rs/serde", "bevyengine/bevy", "denoland/deno",
    "microsoft/vscode", "microsoft/typescript", "facebook/jest", "cypress-io/cypress", "puppeteer/puppeteer",
    "docker/cli", "kubernetes/kubernetes", "helm/helm", "hashicorp/terraform", "ansible/ansible",
    "grafana/grafana", "prometheus/prometheus", "elastic/elasticsearch", "redis/redis", "mongodb/mongo",
    "kamranahmedse/developer-roadmap", "public-apis/public-apis", "donnemartin/system-design-primer", "jwasham/coding-interview-university", "ohmyzsh/ohmyzsh",
    "torvalds/linux", "git/git", "neovim/neovim", "tmux/tmux", "curl/curl"
]

# Garante tamanho da lista
while len(REAL_REPOS) < NUM_REQUESTS:
    REAL_REPOS.extend(REAL_REPOS[:NUM_REQUESTS - len(REAL_REPOS)])

def simulate_student(index, repo_name):
    # Jitter (atraso aleatório) para simular comportamento humano e não um DDoS instantâneo
    delay = random.uniform(0.5, 3.0)
    time.sleep(delay)
    
    student_id = f"Student-{index+1:02d}"
    logger.info(f"[{student_id}] Iniciando ingestão para: {repo_name}")
    
    payload = {
        "messages": [
            {"sender": "user", "text": f"Atualize o repositório https://github.com/{repo_name}"}
        ]
    }
    
    start_time = time.time()
    try:
        response = requests.post(
            API_URL,
            headers={
                "Content-Type": "application/json", 
                "X-API-Key": API_KEY
            },
            json=payload,
            timeout=60 # Timeout maior para evitar falsos negativos de rede
        )
        
        duration = time.time() - start_time
        
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get("response_type") == "job_enqueued":
                    msg = f"✅ [{student_id}] SUCESSO | Repo: {repo_name} | JobID: {data.get('job_id')} | Tempo API: {duration:.2f}s"
                    logger.info(msg)
                    return True
                else:
                    logger.warning(f"⚠️ [{student_id}] ATENÇÃO | Resposta inesperada: {data}")
                    return False
            except Exception as json_err:
                logger.error(f"❌ [{student_id}] ERRO JSON | Não foi possível ler resposta: {response.text}")
                return False
        else:
            logger.error(f"❌ [{student_id}] FALHA HTTP {response.status_code} | Body: {response.text}")
            return False
            
    except Exception as e:
        logger.critical(f"🔥 [{student_id}] EXCEÇÃO CRÍTICA | {str(e)}")
        return False

def run_stress_test():
    logger.info(f"=== INICIANDO TESTE DE ESTRESSE DETALHADO ===")
    logger.info(f"Alvo: {API_URL}")
    logger.info(f"Carga: {NUM_REQUESTS} requisições concorrentes")
    logger.info(f"Log: Salvando em stress_test.log\n")
    
    start_global = time.time()
    success_count = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_REQUESTS) as executor:
        futures = [executor.submit(simulate_student, i, REAL_REPOS[i]) for i in range(NUM_REQUESTS)]
        
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                success_count += 1
            
    end_global = time.time()
    total_time = end_global - start_global
    
    logger.info("\n=== RELATÓRIO FINAL ===")
    logger.info(f"Total Requisições: {NUM_REQUESTS}")
    logger.info(f"Sucessos: {success_count}")
    logger.info(f"Falhas: {NUM_REQUESTS - success_count}")
    logger.info(f"Tempo Total de Execução: {total_time:.2f}s")
    logger.info(f"Taxa de Sucesso: {(success_count/NUM_REQUESTS)*100:.1f}%")

if __name__ == "__main__":
    run_stress_test()