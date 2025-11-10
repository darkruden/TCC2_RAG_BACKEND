from dotenv import load_dotenv
load_dotenv()
import os
import redis
from rq import SimpleWorker, Worker, Queue

# Importa a função de ingestão que o trabalhador precisa executar
# (Como o worker.py está na raiz, a importação do pacote 'app' funciona)
from app.services.ingest_service import ingest_repo

# Define a fila que este trabalhador irá escutar
listen = ['ingest']

# Pega a URL do Redis (do Heroku Add-on ou do nosso localhost)
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

conn = redis.from_url(redis_url)

if __name__ == '__main__':
    queues = [Queue(name, connection=conn) for name in listen]
    print(f"Trabalhador (Worker) iniciado. Aguardando tarefas na(s) fila(s): {', '.join(listen)}...")

    # --- INÍCIO DA CORREÇÃO ---
    # Determina qual classe de Worker usar com base no Sistema Operacional

    if os.name == 'nt':  # 'nt' significa que é Windows
        print("Rodando no Windows: Usando SimpleWorker (sem fork).")
        worker_class = SimpleWorker
    else:  # posix (Linux, macOS)
        print("Rodando no POSIX: Usando Worker padrão (com fork).")
        worker_class = Worker

    worker = worker_class(queues, connection=conn)
    worker.work()
    # --- FIM DA CORREÇÃO ---