import requests
import concurrent.futures
import time
import random
import logging
import sys
import json

# --- CONFIGURAÇÃO ---
# Alvo: Endpoint de Chat Principal
API_URL = "https://meu-tcc-testes-041c1dd46d1d.herokuapp.com/api/chat"
# !!! IMPORTANTE: Use sua API KEY real !!!
API_KEY = "d4936ab9-47f1-43ed-ae9a-51c3c3c4bc29"

# Número de usuários simultâneos fazendo perguntas
NUM_CONCURRENT_USERS = 20 

# Timeout alto (60s) pois o RAG pode demorar para responder, 
# especialmente se o cold start do Heroku ou da OpenAI ocorrer.
TIMEOUT_SECONDS = 60

# --- LOGGING DETALHADO ---
# Salva tanto no arquivo quanto mostra no terminal para você acompanhar
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("stress_test_query.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger()

# Lista de Repositórios (Devem ser repositórios que JÁ FORAM INGERIDOS para o RAG funcionar bem)
# Se o repo não existir no banco, o sistema pode responder "Não encontrei informações".
TARGET_REPOS = [
    "darkruden/tcc2_rag_backend",
    "darkruden/tcc2_rag_frontend",
    "pallets/flask",
    "django/django",
    "facebook/react"
]

# Perguntas variadas para evitar cache exato (se houver cache de query hash)
QUESTIONS = [
    "Explique a arquitetura principal deste projeto.",
    "Como funciona o sistema de autenticação?",
    "Quais são as principais dependências listadas?",
    "Existe alguma menção a banco de dados no código?",
    "Resuma o objetivo deste repositório em um parágrafo.",
    "Quem são os principais autores nos commits recentes?"
]

def simulate_query_user(user_id):
    # Seleciona aleatoriamente um repo e uma pergunta
    repo = random.choice(TARGET_REPOS)
    question = random.choice(QUESTIONS)
    
    # Constrói um prompt que força o contexto do repositório (Sticky Context explícito)
    prompt_text = f"Sobre o repositório https://github.com/{repo}: {question}"
    
    # Jitter: pequeno atraso aleatório para desincronizar o início exato
    time.sleep(random.uniform(0.1, 2.0))
    
    logger.info(f"🔵 [User-{user_id:02d}] Perguntando sobre: {repo} | Query: '{question}'")

    payload = {
        "messages": [
            {"sender": "user", "text": prompt_text}
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
            timeout=TIMEOUT_SECONDS
        )
        
        duration = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            
            # Verifica se a resposta é do tipo esperado (answer ou stream_answer simulado)
            resp_type = data.get("response_type")
            
            if resp_type in ["answer", "stream_answer"]:
                # Sucesso: O RAG respondeu
                logger.info(f"✅ [User-{user_id:02d}] SUCESSO | Tempo: {duration:.2f}s | Tipo: {resp_type}")
                return "success"
            elif resp_type == "job_enqueued":
                # Inesperado: Se cair aqui, o LLM confundiu a pergunta com uma ordem de ingestão/relatório
                logger.warning(f"⚠️ [User-{user_id:02d}] ALERTA | Roteado para Job (Inesperado): {data.get('message')}")
                return "routed_to_job"
            else:
                logger.warning(f"⚠️ [User-{user_id:02d}] RESPOSTA ESTRANHA: {data}")
                return "unknown_response"
                
        elif response.status_code == 503:
             # Erro comum no Heroku quando o Dyno está sobrecarregado ou reiniciando
             logger.error(f"Hz [User-{user_id:02d}] FALHA 503 (Heroku Busy/Timeout) | Tempo: {duration:.2f}s")
             return "fail_503"
             
        elif response.status_code == 429:
             # Rate Limit (pode ser OpenAI ou sua própria implementação)
             logger.error(f"hz [User-{user_id:02d}] FALHA 429 (Rate Limit) | Tempo: {duration:.2f}s")
             return "fail_429"
             
        else:
            logger.error(f"❌ [User-{user_id:02d}] FALHA HTTP {response.status_code} | Body: {response.text[:100]}...")
            return f"fail_{response.status_code}"

    except requests.exceptions.ReadTimeout:
        logger.error(f"rw [User-{user_id:02d}] TIMEOUT DE LEITURA (> {TIMEOUT_SECONDS}s)")
        return "fail_timeout"
        
    except Exception as e:
        logger.critical(f"fw [User-{user_id:02d}] EXCEÇÃO: {str(e)}")
        return "fail_exception"

def run_stress_test():
    logger.info(f"=== INICIANDO TESTE DE CARGA (RAG/CONSULTAS) ===")
    logger.info(f"URL: {API_URL}")
    logger.info(f"Usuários Simultâneos: {NUM_CONCURRENT_USERS}")
    logger.info("--------------------------------------------------")

    start_global = time.time()
    results = []

    # Executa em paralelo
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS) as executor:
        futures = [executor.submit(simulate_query_user, i+1) for i in range(NUM_CONCURRENT_USERS)]
        
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    end_global = time.time()
    total_time = end_global - start_global

    # Consolidação dos resultados
    counts = {k: results.count(k) for k in set(results)}
    success_count = counts.get("success", 0)
    
    logger.info("\n=== RELATÓRIO FINAL DE ESTRESSE (CONSULTA) ===")
    logger.info(f"Tempo Total: {total_time:.2f}s")
    logger.info(f"Throughput: {NUM_CONCURRENT_USERS / total_time:.2f} req/s")
    logger.info(f"Taxa de Sucesso: {(success_count/NUM_CONCURRENT_USERS)*100:.1f}%")
    logger.info("Detalhamento dos status:")
    for status, count in counts.items():
        logger.info(f"  - {status}: {count}")

if __name__ == "__main__":
    run_stress_test()