# CÓDIGO ATUALIZADO PARA: worker.py
# (Modificado para importar as novas tarefas)

import os
import redis
from rq import Worker, Queue, Connection
from dotenv import load_dotenv

load_dotenv()

listen = ['ingest', 'reports'] # As filas que ele escuta

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

conn = redis.from_url(redis_url)

if __name__ == '__main__':
    with Connection(conn):
        # Importa as tarefas APÓS a conexão ser estabelecida
        from app.services.ingest_service import ingest_repo
        from app.services.report_service import processar_e_salvar_relatorio
        from worker_tasks import enviar_relatorio_agendado # <-- NOVA TAREFA

        print(f"Worker iniciado. Escutando as filas: {listen}")
        worker = Worker(map(Queue, listen), connection=conn)
        worker.work()