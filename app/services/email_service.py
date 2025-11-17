# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/email_service.py
# (Corrige o NameError de escopo da BREVO_API_KEY)

import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from typing import Optional

# 1. Configuração do Cliente Brevo (Sendinblue)
BREVO_API_KEY = os.getenv("BREVO_API_KEY") 

configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = BREVO_API_KEY

api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

# 2. Carrega as configurações do remetente
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_NAME = os.getenv("SENDER_NAME", "GitRAG TCC") 

def _send_email(subject: str, html_content: str, to_email: str):
    """
    Função helper interna para enviar um email transacional.
    """
    if not BREVO_API_KEY or not SENDER_EMAIL:
        print("[EmailService] ERRO: BREVO_API_KEY ou SENDER_EMAIL não configurados.")
        raise ValueError("BREVO_API_KEY e SENDER_EMAIL são obrigatórios.")

    sender = sib_api_v3_sdk.SendSmtpEmailSender(email=SENDER_EMAIL, name=SENDER_NAME)
    to = [sib_api_v3_sdk.SendSmtpEmailTo(email=to_email)]

    smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=to,
        sender=sender,
        subject=subject,
        html_content=html_content
    )

    try:
        api_response = api_instance.send_transac_email(smtp_email)
        print(f"[EmailService] Email enviado para {to_email}. Brevo Message ID: {api_response.message_id}")
    except ApiException as e:
        print(f"[EmailService] ERRO (Brevo API) ao enviar para {to_email}: {e}")
        raise e
    except Exception as e:
        print(f"[EmailService] ERRO (Geral) ao enviar para {to_email}: {e}")
        raise e

def send_report_email(to_email: str, subject: str, html_content: str):
    """
    Envia um email de relatório (HTML) para o usuário.
    """
    print(f"[EmailService] Preparando email de relatório para {to_email}...")
    _send_email(subject, html_content, to_email)


def send_verification_email(to_email: str, token: str):
    """
    Envia o email de verificação (Double Opt-In).
    """
    print(f"[EmailService] Preparando email de verificação para {to_email}...")
    
    APP_URL = os.getenv("APP_URL", "http://localhost:8000")
    
    if "localhost" in APP_URL:
        print("[EmailService] AVISO: APP_URL aponta para localhost. O link de verificação pode não funcionar.")
    
    verification_link = f"{APP_URL}/api/email/verify?token={token}&email={to_email}"
    
    subject = "GitRAG - Ative seus Relatórios Agendados"
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; margin: 20px;">
        <h2>Olá!</h2>
        <p>Recebemos uma solicitação para agendar relatórios do GitRAG para este email.</p>
        <p>Para confirmar e ativar seus agendamentos, por favor, clique no link abaixo:</p>
        <p style="text-align: left; margin: 25px 0;">
            <a href="{verification_link}"
               style="background-color: #007bff; color: #ffffff; padding: 12px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                Ativar Meus Agendamentos
            </a>
        </p>
        <p>Se você não solicitou isso, pode ignorar este email com segurança.</p>
        <hr style="border: 0; border-top: 1px solid #eee;">
        <p style="font-size: 0.9em; color: #777;">Se o botão não funcionar, copie e cole este link no seu navegador:<br>
            <code>{verification_link}</code>
        </p>
    </body>
    </html>
    """
    
    try:
        _send_email(subject, html_content, to_email)
    except Exception as e:
        print(f"[EmailService] Falha ao tentar enviar verificação: {e}")