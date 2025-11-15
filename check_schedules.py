# CÓDIGO COMPLETO PARA: check_schedules.py
# (Corrigido para a nova sintaxe do 'rq' sem 'Connection')

import os
from datetime import datetime, time
import pytz
from dotenv import load_dotenv
from supabase import create_client, Client
import redis
from rq import Queue # <-- 'Connection' NÃO é importada

load_dotenv()

try:
    url: str = os.getenv("SUPABASE_URL")
    key: str = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
    supabase: Client = create_client(url, key)
    print("[Scheduler] Conectado ao Supabase.")

    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    conn = redis.from_url(redis_url)
    conn.ping()
    print("[Scheduler] Conectado ao Redis.")
    
    # Lê o prefixo (deve ser o mesmo do worker)
    QUEUE_PREFIX = os.getenv('RQ_QUEUE_PREFIX', '')
    
    # Instancia a Fila com a sintaxe moderna (passando a conexão)
    q_reports = Queue(f'{QUEUE_PREFIX}reports', connection=conn)

except Exception as e:
    print(f"[Scheduler] ERRO CRÍTICO na inicialização: {e}")
    exit(1)

def fetch_and_queue_jobs():
    """
    Busca no Supabase por agendamentos que precisam rodar e os enfileira.
    """
    print("[Scheduler] Verificando agendamentos...")
    
    try:
        now_utc = datetime.now(pytz.utc)
        current_utc_hour = now_utc.replace(minute=0, second=0, microsecond=0).time()
        
        print(f"[Scheduler] Hora atual (UTC, arredondada): {current_utc_hour}")

        response = supabase.table("agendamentos").select("*") \
            .eq("ativo", True) \
            .eq("hora_utc", str(current_utc_hour)) \
            .execute()

        if not response.data:
            print("[Scheduler] Nenhum agendamento encontrado para esta hora.")
            return

        print(f"[Scheduler] Encontrados {len(response.data)} agendamentos.")
        jobs_enfileirados = 0
        
        for agendamento in response.data:
            ultimo_envio = agendamento.get("ultimo_envio")
            if ultimo_envio:
                ultimo_envio_data = datetime.fromisoformat(ultimo_envio).date()
                if ultimo_envio_data == now_utc.date():
                    print(f"[Scheduler] Pulando job {agendamento['id']} (já enviado hoje).")
                    continue
            
            print(f"[Scheduler] Enfileirando relatório para: {agendamento['user_email']}")
            
            # Enfileira a tarefa (sem alterações aqui)
            q_reports.enqueue(
                'worker_tasks.enviar_relatorio_agendado', 
                agendamento['id'],
                agendamento['user_email'],
                agendamento['repositorio'],
                agendamento['prompt_relatorio'],
                job_timeout=1800
            )
            jobs_enfileirados += 1

        print(f"[Scheduler] {jobs_enfileirados} novos jobs de relatório foram enfileirados.")

    except Exception as e:
        print(f"[Scheduler] ERRO ao buscar ou enfileirar jobs: {e}")

if __name__ == "__main__":
    print("[Scheduler] Executando verificação de agendamentos...")
    fetch_and_queue_jobs()
    print("[Scheduler] Verificação concluída.")