import os
import redis
from rq import Worker, Queue, Connection

# Importa a função de ingestão que o trabalhador precisa executar
# (Como o worker.py está na raiz, a importação do pacote 'app' funciona)
from app.services.ingest_service import ingest_repo

# Define a fila que este trabalhador irá escutar
listen = ['ingest']

# Pega a URL do Redis (do Heroku Add-on ou do nosso localhost)
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

conn = redis.from_url(redis_url)

if __name__ == '__main__':
    # Inicia a conexão com o Redis
    with Connection(conn):
        # Passa a lista de filas para o Worker escutar
        queues = [Queue(name, connection=conn) for name in listen]

        print(f"Trabalhador (Worker) iniciado. Aguardando tarefas na(s) fila(s): {', '.join(listen)}...")

        # O Worker começa a escutar e só aceitará
        # tarefas que chamam as funções que ele conhece (neste caso, 'ingest_repo')
        worker = Worker(queues, connection=conn)
        worker.work()