# CÓDIGO COMPLETO E ATUALIZADO PARA: check_schedules.py
# (Atualizado para Multi-Tenancy com 'user_id')

import os
from datetime import datetime, time
import pytz
from dotenv import load_dotenv
from supabase import create_client, Client
import redis
from rq import Queue

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
    
    QUEUE_PREFIX = os.getenv('RQ_QUEUE_PREFIX', '')
    
    q_reports = Queue(f'{QUEUE_PREFIX}reports', connection=conn)

except Exception as e:
    print(f"[Scheduler] ERRO CRÍTICO na inicialização: {e}")
    exit(1)

def fetch_and_queue_jobs():
    """
    Busca no Supabase por agendamentos que precisam rodar e os enfileira.
    Agora inclui o user_id.
    """
    print("[Scheduler] Verificando agendamentos...")
    
    try:
        now_utc = datetime.now(pytz.utc)
        current_utc_hour = now_utc.replace(minute=0, second=0, microsecond=0).time()
        
        print(f"[Scheduler] Hora atual (UTC, arredondada): {current_utc_hour}")

        # --- INÍCIO DA ATUALIZAÇÃO ---
        # 1. Seleciona o user_id junto com os outros campos
        response = supabase.table("agendamentos").select("id, user_email, repositorio, prompt_relatorio, ultimo_envio, user_id") \
            .eq("ativo", True) \
            .eq("hora_utc", str(current_utc_hour)) \
            .execute()
        # --- FIM DA ATUALIZAÇÃO ---

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
            
            # --- INÍCIO DA ATUALIZAÇÃO ---
            # 2. Pega o user_id (essencial)
            user_id = agendamento.get("user_id")
            if not user_id:
                print(f"[Scheduler] ERRO: Pulando job {agendamento['id']} (user_id está nulo no banco).")
                continue
            
            print(f"[Scheduler] Enfileirando relatório (User: {user_id}) para: {agendamento['user_email']}")
            
            # 3. Passa o user_id como o último argumento
            q_reports.enqueue(
                'worker_tasks.enviar_relatorio_agendado', 
                agendamento['id'],
                agendamento['user_email'],
                agendamento['repositorio'],
                agendamento['prompt_relatorio'],
                user_id, # <-- Passa o user_id para o worker
                job_timeout=1800
            )
            # --- FIM DA ATUALIZAÇÃO ---
            
            jobs_enfileirados += 1

        print(f"[Scheduler] {jobs_enfileirados} novos jobs de relatório foram enfileirados.")

    except Exception as e:
        print(f"[Scheduler] ERRO ao buscar ou enfileirar jobs: {e}")

if __name__ == "__main__":
    print("[Scheduler] Executando verificação de agendamentos...")
    fetch_and_queue_jobs()
    print("[Scheduler] Verificação concluída.")