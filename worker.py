# CÓDIGO ATUALIZADO PARA: worker.py
# (Atualizado para usar 'RQ_QUEUE_PREFIX' e isolar as filas)

import os
import redis
from rq import Worker, Queue, Connection
from dotenv import load_dotenv

load_dotenv()

# --- INÍCIO DA CORREÇÃO (Prefixo de Fila) ---
# Lê o prefixo do ambiente (ex: 'test_').
QUEUE_PREFIX = os.getenv('RQ_QUEUE_PREFIX', '')
if QUEUE_PREFIX:
    print(f"[Worker] Usando prefixo de fila: '{QUEUE_PREFIX}'")
# --- FIM DA CORREÇÃO ---

# Adiciona o prefixo aos nomes das filas que este worker escutará
listen = [
    f'{QUEUE_PREFIX}ingest', 
    f'{QUEUE_PREFIX}reports'
]

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

conn = redis.from_url(redis_url)

if __name__ == '__main__':
    with Connection(conn):
        
        # Importa TODAS as tarefas (sem alterações)
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
        worker = Worker(map(Queue, listen), connection=conn)
        
        try:
            worker.work()
        except Exception as e:
            print(f"Worker encontrou um erro fatal: {e}")