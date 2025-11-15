# CÓDIGO ATUALIZADO PARA: worker.py
# (Corrigido para a nova sintaxe do 'rq' sem 'Connection')

import os
import redis
from rq import Worker, Queue # <-- 'Connection' removida
from dotenv import load_dotenv

load_dotenv()

# Lê o prefixo do ambiente (ex: 'test_').
QUEUE_PREFIX = os.getenv('RQ_QUEUE_PREFIX', '')
if QUEUE_PREFIX:
    print(f"[Worker] Usando prefixo de fila: '{QUEUE_PREFIX}'")

# Adiciona o prefixo aos nomes das filas
listen = [
    f'{QUEUE_PREFIX}ingest', 
    f'{QUEUE_PREFIX}reports'
]

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

conn = redis.from_url(redis_url)

if __name__ == '__main__':
    
    # O 'with Connection(conn):' (que causava o erro) foi removido.
    
    # Importa TODAS as tarefas
    print("Importando tarefas do worker...")
    from worker_tasks import (
        ingest_repo, 
        save_instruction, 
        processar_e_salvar_relatorio, 
        enviar_relatorio_agendado, 
        process_webhook_payload 
    )
    print("Tarefas importadas com sucesso.")

    print(f"Worker iniciado. Escutando as filas: {listen}")
    
    # Mapeia os nomes das filas para objetos Queue
    # A conexão 'conn' é passada aqui
    queues = [Queue(name, connection=conn) for name in listen]
    
    # Passa a lista de Queues e a conexão para o Worker
    worker = Worker(queues, connection=conn)
    
    try:
        worker.work()
    except Exception as e:
        print(f"Worker encontrou um erro fatal: {e}")