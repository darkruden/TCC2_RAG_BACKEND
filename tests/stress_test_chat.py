import requests
import concurrent.futures
import time
import random
import logging
import sys
import json

# --- CONFIGURAÇÃO ---
API_URL = "https://meu-tcc-testes-041c1dd46d1d.herokuapp.com/api/chat"
# Substitua pela sua API Key de teste (a mesma do arquivo .http ou do banco)
API_KEY = "d4936ab9-47f1-43ed-ae9a-51c3c3c4bc29" 

# Carga de usuários simultâneos (tente aumentar/diminuir para achar o limite)
NUM_CONCURRENT_USERS = 20 

# Timeout do Client (Python) - Deve ser maior que o do Heroku (30s) para capturar o erro real do servidor
TIMEOUT_SECONDS = 60

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("stress_test_chat_result.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger()

# Perguntas variadas para forçar o RAG a buscar contextos diferentes
QUESTIONS = [
    ("darkruden/tcc2_rag_backend", "Explique a arquitetura principal deste projeto."),
    ("darkruden/tcc2_rag_backend", "Quais são as principais dependências no requirements.txt?"),
    ("darkruden/tcc2_rag_frontend", "Como funciona o componente de Chat?"),
    ("facebook/react", "Como o React lida com o Virtual DOM?"),
    ("pallets/flask", "Existe alguma menção a banco de dados no código?"),
    ("django/django", "Resuma o objetivo deste repositório em um parágrafo.")
]

def simulate_chat_user(user_id):
    # Escolhe uma pergunta aleatória
    repo, question = random.choice(QUESTIONS)
    
    # Jitter: Pequeno atraso aleatório (0.1s a 2s) para simular comportamento humano 
    # e não bater na API exatamente no mesmo milissegundo
    time.sleep(random.uniform(0.1, 2.0))
    
    logger.info(f"🔵 [User-{user_id:02d}] Perguntando sobre: {repo} | Query: '{question}'")

    # Payload no formato esperado pelo /api/chat
    payload = {
        "messages": [
            {
                "sender": "user",
                "text": f"Sobre o repositório https://github.com/{repo}: {question}"
            }
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
        
        # --- ANÁLISE DE RESPOSTA ---
        if response.status_code == 200:
            try:
                data = response.json()
                resp_type = data.get("response_type")
                
                # Verifica se foi uma resposta de chat válida
                if resp_type in ["answer", "stream_answer"]:
                    logger.info(f"✅ [User-{user_id:02d}] SUCESSO | Tempo: {duration:.2f}s | Tipo: {resp_type}")
                    return "success"
                elif resp_type == "job_enqueued":
                    # Se o LLM achou que era pra baixar o repo em vez de responder
                    logger.warning(f"⚠️ [User-{user_id:02d}] ALERTA | Roteado para Job (Inesperado): {data.get('message')}")
                    return "routed_to_job"
                else:
                    logger.warning(f"⚠️ [User-{user_id:02d}] RESPOSTA ESTRANHA: {data}")
                    return "unknown_200"

            except Exception:
                logger.error(f"❌ [User-{user_id:02d}] ERRO JSON | {response.text[:100]}")
                return "json_error"
                
        elif response.status_code == 503:
             # O erro mais comum no Heroku Free/Basic sob carga
             logger.error(f"Hz [User-{user_id:02d}] FALHA 503 (Heroku Busy/Timeout) | Tempo: {duration:.2f}s")
             return "fail_503"
             
        elif response.status_code == 429:
             # Rate Limit (OpenAI ou sua API)
             logger.error(f"Hz [User-{user_id:02d}] FALHA 429 (Rate Limit) | Tempo: {duration:.2f}s")
             return "fail_429"
             
        else:
            logger.error(f"❌ [User-{user_id:02d}] FALHA HTTP {response.status_code} | Tempo: {duration:.2f}s")
            return f"fail_{response.status_code}"

    except requests.exceptions.ReadTimeout:
        logger.error(f"fw [User-{user_id:02d}] TIMEOUT CLIENTE (> {TIMEOUT_SECONDS}s)")
        return "fail_timeout"
        
    except Exception as e:
        logger.critical(f"fw [User-{user_id:02d}] EXCEÇÃO CRÍTICA: {str(e)}")
        return "fail_exception"

def run_stress_test():
    logger.info(f"=== INICIANDO TESTE DE CARGA (RAG/CONSULTAS) ===")
    logger.info(f"URL: {API_URL}")
    logger.info(f"Usuários Simultâneos: {NUM_CONCURRENT_USERS}")
    logger.info("--------------------------------------------------")

    start_global = time.time()
    results = []

    # Executa os usuários em paralelo usando Threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_CONCURRENT_USERS) as executor:
        futures = [executor.submit(simulate_chat_user, i+1) for i in range(NUM_CONCURRENT_USERS)]
        
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    end_global = time.time()
    total_time = end_global - start_global

    # Relatório Final
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