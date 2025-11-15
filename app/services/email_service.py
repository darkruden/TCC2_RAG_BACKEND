# CÓDIGO COMPLETO PARA: app/services/email_service.py
# (Novo arquivo - Atualizado para usar BREVO)

import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from typing import Dict, Any

# --- Configuração do Cliente Brevo ---

# Pega a API Key e o email do remetente das Config Vars do Heroku
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
# (O SENDER_EMAIL deve ser um "Remetente Verificado" no seu painel Brevo)

# Configura a instância da API do Brevo
configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = BREVO_API_KEY

# Cria uma instância da API que usaremos
api_client = sib_api_v3_sdk.ApiClient(configuration)
api_instance = sib_api_v3_sdk.TransactionalEmailsApi(api_client)

def _send_email(subject: str, html_content: str, to_email: str):
    """
    Função helper interna para enviar um email transacional.
    """
    if not BREVO_API_KEY or not SENDER_EMAIL:
        print("[EmailService] ERRO: BREVO_API_KEY ou SENDER_EMAIL não configurados.")
        # Não lança erro, apenas loga, para não quebrar o worker
        return

    # Define o remetente (Sender)
    sender = sib_api_v3_sdk.SendSmtpEmailSender(email=SENDER_EMAIL, name="GitHub RAG TCC")
    
    # Define o destinatário (Recipient)
    to = [sib_api_v3_sdk.SendSmtpEmailTo(email=to_email)]

    # Cria o objeto do email
    smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=to,
        sender=sender,
        subject=subject,
        html_content=html_content
    )

    try:
        # Envia o email
        api_response = api_instance.send_transac_email(smtp_email)
        print(f"[EmailService] Email enviado para {to_email}. Brevo Message ID: {api_response.message_id}")
        
    except ApiException as e:
        print(f"[EmailService] ERRO (Brevo API) ao enviar para {to_email}: {e}")
    except Exception as e:
        print(f"[EmailService] ERRO (Geral) ao enviar para {to_email}: {e}")

# --- Funções Públicas (chamadas pelos seus workers) ---

def send_report_email(to_email: str, subject: str, html_content: str):
    """
    Envia um email de relatório (HTML) para o usuário.
    """
    print(f"[EmailService] Preparando email de relatório para {to_email}...")
    try:
        _send_email(subject, html_content, to_email)
    except Exception as e:
        # Pega qualquer erro inesperado
        print(f"[EmailService] Falha crítica ao tentar enviar relatório: {e}")

def send_verification_email(to_email: str, token: str):
    """
    Envia o email de verificação (Double Opt-In).
    """
    print(f"[EmailService] Preparando email de verificação para {to_email}...")
    
    # Pega a URL da API (ex: https://meu-tcc-testes.herokuapp.com)
    APP_URL = os.getenv("APP_URL", "http://localhost:8000")
    
    if "localhost" in APP_URL:
        print("[EmailService] AVISO: APP_URL aponta para localhost. O link de verificação pode não funcionar.")
    
    # Cria o link de verificação
    verification_link = f"{APP_URL}/api/email/verify?token={token}&email={to_email}"
    
    subject = "Confirme seu Email para Relatórios Agendados"
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
            .container {{ width: 90%; margin: auto; padding: 20px; }}
            .button {{
                padding: 10px 15px; 
                background-color: #007bff; 
                color: white !important; /* Importante para o cliente de email */
                text-decoration: none; 
                border-radius: 5px; 
                font-weight: bold;
            }}
            .link {{ color: #555; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <p>Olá,</p>
            <p>Obrigado por se inscrever para receber relatórios do GitHub RAG.</p>
            <p>Por favor, clique no link abaixo para confirmar seu email e ativar seus agendamentos:</p>
            <br>
            <p>
                <a href="{verification_link}" class="button">
                    Confirmar meu Email
                </a>
            </p>
            <br>
            <p>Se você não solicitou isso, pode ignorar este email.</p>
            <hr>
            <p class="link">Se o botão não funcionar, copie e cole este link no seu navegador:<br>
                <code>{verification_link}</code>
            </p>
        </div>
    </body>
    </html>
    """
    
    try:
        _send_email(subject, html_content, to_email)
    except Exception as e:
        print(f"[EmailService] Falha crítica ao tentar enviar verificação: {e}")