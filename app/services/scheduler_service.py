# CÓDIGO ATUALIZADO PARA: app/services/scheduler_service.py
# (Adicionados logs de depuração)

import os
import pytz
from datetime import datetime
from supabase import create_client, Client
from typing import Dict, Any
from app.services.email_service import send_verification_email

# --- Inicialização do Cliente Supabase ---
try:
    url: str = os.getenv("SUPABASE_URL")
    key: str = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")
    
    supabase: Client = create_client(url, key)
    print("[SchedulerService] Cliente Supabase inicializado.")
    
except Exception as e:
    print(f"[SchedulerService] Erro ao inicializar Supabase: {e}")
    supabase = None

def _convert_time_to_utc(local_time_str: str, timezone_str: str) -> str:
    """
    Converte uma hora local (ex: "17:00") e um timezone (ex: "America/Sao_Paulo")
    para a hora correspondente em UTC.
    """
    try:
        # Pega a data de hoje (apenas como referência)
        today = datetime.now(pytz.timezone(timezone_str)).date()
        
        # Pega a hora
        local_time = datetime.strptime(local_time_str, '%H:%M').time()
        
        # Combina data e hora local
        local_dt = datetime.combine(today, local_time)
        
        # Adiciona a informação do timezone
        local_tz = pytz.timezone(timezone_str)
        local_dt = local_tz.localize(local_dt)
        
        # Converte para UTC e retorna apenas a string da hora (HH:MM:SS)
        utc_dt = local_dt.astimezone(pytz.utc)
        return utc_dt.strftime('%H:%M:%S')
        
    except Exception as e:
        print(f"[SchedulerService] Erro ao converter timezone: {e}. Usando UTC como fallback.")
        # Fallback: se o timezone for inválido, assume que a hora já é UTC
        try:
            return datetime.strptime(local_time_str, '%H:%M').strftime('%H:%M:%S')
        except:
            return "00:00:00" # Fallback final

def create_schedule(user_email: str, repo: str, prompt: str, freq: str, hora: str, tz: str) -> str:
    """
    Cria uma nova solicitação de agendamento e envia o email de verificação.
    """
    if not supabase:
        raise Exception("Serviço Supabase não está inicializado.")
    
    # --- INÍCIO DA ADIÇÃO (DEBUG) ---
    print(f"--- [DEBUG create_schedule] ---")
    print(f"Email: {user_email}, Repo: {repo}, Freq: {freq}, Hora: {hora}, TZ: {tz}")
    # --- FIM DA ADIÇÃO (DEBUG) ---
    
    try:
        # 1. Converte a hora local para a hora UTC (que o 'check_schedules.py' usa)
        hora_utc_str = _convert_time_to_utc(hora, tz)
        
        # 2. Verifica se o email já foi verificado
        email_check = supabase.table("emails_verificados").select("verificado, token_verificacao") \
            .eq("email", user_email).execute()

        token = None
        email_ja_verificado = False
        
        if email_check.data:
            email_status = email_check.data[0]
            if email_status["verificado"]:
                email_ja_verificado = True
                print("[SchedulerService-Debug] Email JÁ está verificado.") # <-- LOG
            else:
                token = email_status["token_verificacao"]
                print("[SchedulerService-Debug] Email NÃO verificado, usando token existente.") # <-- LOG
        else:
            # Email nunca visto, cria novo registro de verificação
            print("[SchedulerService-Debug] Email novo. Criando registro de verificação.") # <-- LOG
            new_email_entry = supabase.table("emails_verificados").insert({"email": user_email}) \
                .execute()
            token = new_email_entry.data[0]["token_verificacao"]

        # 3. Salva o novo agendamento no banco
        # (Se o email já for verificado, 'ativo' será True. Senão, 'ativo' será False)
        novo_agendamento = {
            "user_email": user_email,
            "repositorio": repo,
            "prompt_relatorio": prompt,
            "frequencia": freq,
            "hora_utc": hora_utc_str,
            "timezone": tz,
            "ativo": email_ja_verificado 
        }
        
        supabase.table("agendamentos").insert(novo_agendamento).execute()
        
        # 4. Envia email de verificação (se necessário)
        if not email_ja_verificado and token:
            print("[SchedulerService-Debug] ENVIANDO email de verificação...") # <-- LOG
            send_verification_email(user_email, str(token))
            return "Agendamento criado. Por favor, verifique seu email para ativar."
        else:
            print("[SchedulerService-Debug] PULO envio de email (usuário já verificado).") # <-- LOG
            return "Agendamento criado e ativado com sucesso."

    except Exception as e:
        print(f"[SchedulerService] ERRO ao criar agendamento: {e}")
        raise Exception(f"Falha ao salvar agendamento: {e}")

def verify_email_token(email: str, token: str) -> bool:
    """
    Verifica um token de email e ativa os agendamentos pendentes.
    """
    if not supabase:
        raise Exception("Serviço Supabase não está inicializado.")
    
    print(f"[SchedulerService] Tentando verificar email {email} com token {token}")
    
    try:
        # 1. Procura o token
        response = supabase.table("emails_verificados") \
            .select("verificado") \
            .eq("email", email) \
            .eq("token_verificacao", token) \
            .execute()

        if not response.data:
            print("[SchedulerService] VERIFICAÇÃO FALHOU: Email ou token não encontrado.")
            return False

        # 2. Se encontrou, marca o email como verificado
        print(f"[SchedulerService] Token válido. Marcando {email} como verificado.")
        supabase.table("emails_verificados") \
            .update({"verificado": True}) \
            .eq("email", email) \
            .execute()
            
        # 3. Ativa todos os agendamentos pendentes para este email
        print(f"[SchedulerService] Ativando agendamentos pendentes para {email}...")
        supabase.table("agendamentos") \
            .update({"ativo": True}) \
            .eq("user_email", email) \
            .eq("ativo", False) \
            .execute()
            
        return True

    except Exception as e:
        print(f"[SchedulerService] ERRO ao verificar token: {e}")
        return False