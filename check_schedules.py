# CÓDIGO COMPLETO PARA: check_schedules.py
# (Novo arquivo - Coloque na pasta RAIZ do seu backend)

import os
from datetime import datetime, time
import pytz
from dotenv import load_dotenv
from supabase import create_client, Client
import redis
from rq import Queue
from app.services.report_service import processar_e_salvar_relatorio # Importa a função do worker

# Carrega as variáveis de .env (para testes locais)
load_dotenv()

# --- Configuração de Conexão ---
try:
    # Conexão com Supabase
    url: str = os.getenv("SUPABASE_URL")
    key: str = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
    supabase: Client = create_client(url, key)
    print("[Scheduler] Conectado ao Supabase.")

    # Conexão com Redis (para enfileirar os jobs)
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    conn = redis.from_url(redis_url)
    conn.ping()
    print("[Scheduler] Conectado ao Redis.")
    
    # Fila de Relatórios (a mesma do main.py)
    q_reports = Queue('reports', connection=conn)

except Exception as e:
    print(f"[Scheduler] ERRO CRÍTICO na inicialização: {e}")
    # Se não conectar, não há nada a fazer.
    exit(1) # Sai do script com código de erro

def fetch_and_queue_jobs():
    """
    Busca no Supabase por agendamentos que precisam rodar e os enfileira.
    """
    print("[Scheduler] Verificando agendamentos...")
    
    try:
        # Pega a hora atual em UTC
        now_utc = datetime.now(pytz.utc)
        # Arredonda para a hora (ex: 17:34 -> 17:00)
        current_utc_hour = now_utc.replace(minute=0, second=0, microsecond=0).time()
        
        print(f"[Scheduler] Hora atual (UTC, arredondada): {current_utc_hour}")

        # Busca agendamentos que estão:
        # 1. Ativos (email verificado)
        # 2. Marcados para a hora atual (em UTC)
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
            # Lógica para evitar re-envio (ex: 'daily')
            # Se já enviamos hoje, pulamos.
            ultimo_envio = agendamento.get("ultimo_envio")
            if ultimo_envio:
                ultimo_envio_data = datetime.fromisoformat(ultimo_envio).date()
                if ultimo_envio_data == now_utc.date():
                    print(f"[Scheduler] Pulando job {agendamento['id']} (já enviado hoje).")
                    continue
            
            # (Aqui você pode adicionar lógicas para 'weekly', 'monthly')

            # --- Enfileira o Job ---
            # O worker 'processar_e_salvar_relatorio' agora faz 3 coisas:
            # 1. Gera o HTML (com Chart.js)
            # 2. NÃO salva no Supabase
            # 3. ENVIA por email
            # (Precisamos modificar o 'report_service.py' para fazer isso)
            
            print(f"[Scheduler] Enfileirando relatório para: {agendamento['user_email']}")
            
            # (Vamos assumir por agora que a função do worker fará a coisa certa)
            q_reports.enqueue(
                'worker_tasks.enviar_relatorio_agendado', # Uma NOVA tarefa de worker
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