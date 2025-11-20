# CÓDIGO COMPLETO E CORRIGIDO PARA: check_schedules.py
# (Adiciona suporte a janelas de tempo: data_inicio e data_fim)

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
    Agora verifica janelas de tempo (data_inicio e data_fim).
    """
    print("[Scheduler] Verificando agendamentos...")

    try:
        # Data/Hora atual em UTC
        now_utc = datetime.now(pytz.utc)
        current_date = now_utc.date() # Apenas a data (para comparações)
        
        # Usa hora e minuto atuais (segundos fixos em 00) para bater com 'hora_utc'
        current_utc_time_str = now_utc.strftime("%H:%M") + ":00"

        print(f"[Scheduler] Hora atual (UTC): {current_utc_time_str} | Data: {current_date}")

        # --- SELECT ATUALIZADO ---
        response = (
            supabase.table("agendamentos")
            .select(
                "id, user_email, repositorio, prompt_relatorio, ultimo_envio, user_id, frequencia, data_inicio, data_fim"
            )
            .eq("ativo", True)
            .eq("hora_utc", current_utc_time_str)
            .execute()
        )

        if not response.data:
            print("[Scheduler] Nenhum agendamento ativo encontrado para esta hora.")
            return

        print(f"[Scheduler] Encontrados {len(response.data)} candidatos.")
        jobs_enfileirados = 0

        for agendamento in response.data:
            ag_id = agendamento["id"]
            freq = agendamento.get("frequencia") or "once"
            ultimo_envio = agendamento.get("ultimo_envio")
            
            # Parse das datas (se existirem)
            dt_inicio = None
            dt_fim = None
            
            if agendamento.get("data_inicio"):
                dt_inicio = datetime.strptime(agendamento["data_inicio"], "%Y-%m-%d").date()
                
            if agendamento.get("data_fim"):
                dt_fim = datetime.strptime(agendamento["data_fim"], "%Y-%m-%d").date()

            # --- 1. VALIDAÇÃO DE JANELA DE TEMPO ---
            
            # Se ainda não chegou o dia de começar
            if dt_inicio and current_date < dt_inicio:
                print(f"[Scheduler] Job {ag_id} pulado (Inicia apenas em {dt_inicio}).")
                continue

            # Se já passou da data final -> Desativa automaticamente (Auto-Expire)
            if dt_fim and current_date > dt_fim:
                print(f"[Scheduler] Job {ag_id} EXPIROU (Fim: {dt_fim}). Desativando...")
                supabase.table("agendamentos").update({"ativo": False}).eq("id", ag_id).execute()
                continue

            # --- 2. VALIDAÇÃO DE FREQUÊNCIA (Lógica original) ---
            
            # Se já foi enviado alguma vez e a frequência é 'once', desativa.
            if ultimo_envio and freq == "once":
                print(f"[Scheduler] Desativando agendamento {ag_id} (frequencia=once, já executado).")
                supabase.table("agendamentos").update({"ativo": False}).eq("id", ag_id).execute()
                continue

            if ultimo_envio:
                # Converte o timestamp salvo (que inclui data e timezone) para datetime
                ultimo_envio_dt = datetime.fromisoformat(ultimo_envio.replace("Z", "+00:00"))

                # Para frequências diárias, se já enviou hoje, pula
                if freq == "daily" and ultimo_envio_dt.date() == current_date:
                    print(f"[Scheduler] Pulando job {ag_id} (daily, já enviado hoje).")
                    continue
            
            # --- ENFILEIRAMENTO ---
            
            user_id = agendamento.get("user_id")
            if not user_id:
                print(f"[Scheduler] ERRO: Pulando job {ag_id} (user_id está nulo no banco).")
                continue

            print(f"[Scheduler] Enfileirando relatório (User: {user_id}) para: {agendamento['user_email']}")

            q_reports.enqueue(
                "worker_tasks.enviar_relatorio_agendado",
                ag_id, # schedule_id
                agendamento["user_email"],
                agendamento["repositorio"],
                agendamento["prompt_relatorio"],
                user_id,
                job_timeout=1800,
            )

            jobs_enfileirados += 1

        print(f"[Scheduler] {jobs_enfileirados} novos jobs de relatório foram enfileirados.")

    except Exception as e:
        print(f"[Scheduler] ERRO ao buscar ou enfileirar jobs: {e}")

if __name__ == "__main__":
    fetch_and_queue_jobs()