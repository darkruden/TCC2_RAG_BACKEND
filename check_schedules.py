# CÓDIGO COMPLETO E CORRIGIDO PARA: check_schedules.py
# (Implementa lógica de "Catch-up" para não perder envios se o script atrasar)

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
    print("[Scheduler] Verificando agendamentos (Modo Catch-up)...")

    try:
        now_utc = datetime.now(pytz.utc)
        current_date = now_utc.date()
        current_time = now_utc.time()
        
        print(f"[Scheduler] Agora (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")

        # --- 1. BUSCA TODOS OS ATIVOS ---
        # Removemos o filtro de hora exata (.eq("hora_utc", ...))
        response = (
            supabase.table("agendamentos")
            .select(
                "id, user_email, repositorio, prompt_relatorio, ultimo_envio, user_id, frequencia, data_inicio, data_fim, hora_utc"
            )
            .eq("ativo", True)
            .execute()
        )

        if not response.data:
            print("[Scheduler] Nenhum agendamento ativo no sistema.")
            return

        print(f"[Scheduler] Analisando {len(response.data)} agendamentos ativos...")
        jobs_enfileirados = 0

        for agendamento in response.data:
            ag_id = agendamento["id"]
            freq = agendamento.get("frequencia") or "once"
            
            # Converte a string do banco para objeto Time
            # O Supabase retorna '11:00:00', pegamos os primeiros 8 chars para garantir HH:MM:SS
            hora_alvo_str = agendamento["hora_utc"][:8] 
            hora_alvo = datetime.strptime(hora_alvo_str, "%H:%M:%S").time()

            # --- CHECAGEM 1: JÁ CHEGOU A HORA? ---
            if current_time < hora_alvo:
                # Ainda é cedo para este agendamento hoje
                continue

            # --- CHECAGEM 2: JÁ ENVIOU HOJE? ---
            ultimo_envio = agendamento.get("ultimo_envio")
            ja_enviou_hoje = False
            
            if ultimo_envio:
                ultimo_envio_dt = datetime.fromisoformat(ultimo_envio.replace("Z", "+00:00"))
                if ultimo_envio_dt.date() == current_date:
                    ja_enviou_hoje = True

            if ja_enviou_hoje:
                # Já rodou hoje, ignora (espera amanhã)
                continue

            # --- CHECAGEM 3: JANELAS DE DATA (Lógica anterior mantida) ---
            dt_inicio = None
            dt_fim = None
            if agendamento.get("data_inicio"):
                dt_inicio = datetime.strptime(agendamento["data_inicio"], "%Y-%m-%d").date()
            if agendamento.get("data_fim"):
                dt_fim = datetime.strptime(agendamento["data_fim"], "%Y-%m-%d").date()

            if dt_inicio and current_date < dt_inicio:
                continue # Ainda não começou

            ifVP dt_fim and current_date > dt_fim:
                print(f"[Scheduler] Job {ag_id} EXPIROU. Desativando...")
                supabase.table("agendamentos").update({"ativo": False}).eq("id", ag_id).execute()
                continue

            # --- CHECAGEM 4: FREQUÊNCIA ONCE ---
            if freq == "once" and ultimo_envio:
                print(f"[Scheduler] Job {ag_id} (once) já executado anteriormente. Desativando...")
                supabase.table("agendamentos").update({"ativo": False}).eq("id", ag_id).execute()
                continue
            
            # --- SE PASSOU POR TUDO, ENFILEIRA ---
            
            user_id = agendamento.get("user_id")
            if not user_id:
                print(f"[Scheduler] ERRO: user_id nulo para {ag_id}.")
                continue

            print(f"[Scheduler] >>> DISPARANDO: {agendamento['user_email']} (Era para ser às {hora_alvo_str}, agora são {current_time.strftime('%H:%M')})")

            q_reports.enqueue(
                "worker_tasks.enviar_relatorio_agendado",
                ag_id, 
                agendamento["user_email"],
                agendamento["repositorio"],
                agendamento["prompt_relatorio"],
                user_id,
                (ultimo_envio is None), # is_first_run logic
                job_timeout=1800,
            )

            jobs_enfileirados += 1

        print(f"[Scheduler] Ciclo finalizado. {jobs_enfileirados} jobs processados.")

    except Exception as e:
        print(f"[Scheduler] ERRO ao buscar ou enfileirar jobs: {e}")

if __name__ == "__main__":
    fetch_and_queue_jobs()