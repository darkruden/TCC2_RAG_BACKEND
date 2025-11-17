# CÓDIGO COMPLETO E CORRIGIDO PARA: app/services/email_service.py
# (Este é o conteúdo correto que remove a importação circular)

import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from typing import Optional

# 1. Configuração do Cliente Brevo (Sendinblue)
#    Ele deve ler as variáveis de ambiente[cite: 2, 7].
configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = os.getenv("BREVO_API_KEY")

api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

SENDER_EMAIL = os.getenv("SENDER_EMAIL", "nao-responda@gitrag.com")
SENDER_NAME = "GitRAG TCC"

def send_report_email(to_email: str, subject: str, html_content: str):
    """
    Envia um relatório (gerado pelo worker) por email.
    """
    print(f"[EmailService] Enviando relatório para {to_email}...")
    
    sender = {"name": SENDER_NAME, "email": SENDER_EMAIL}
    to = [{"email": to_email}]
    
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=to,
        sender=sender,
        subject=subject,
        html_content=html_content
    )
    
    try:
        api_response = api_instance.send_transac_email(send_smtp_email)
        print(f"[EmailService] Resposta da API Brevo: {api_response}")
    except ApiException as e:
        print(f"[EmailService] ERRO CRÍTICO ao enviar email: {e}")
        # Lança a exceção para que o worker possa registrar a falha do job
        raise e

def send_verification_email(to_email: str, token: str):
    """
    Envia o email de verificação (double opt-in) para ativar agendamentos.
    """
    print(f"[EmailService] Enviando verificação para {to_email}...")
    
    # [cite: 2] (APP_URL)
    app_url = os.getenv("APP_URL", "http://localhost:8000")
    verification_link = f"{app_url}/api/email/verify?token={token}&email={to_email}"
    
    subject = "GitRAG - Ative seus Relatórios Agendados"
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6;">
        <h2>Olá!</h2>
        <p>Recebemos uma solicitação para agendar relatórios do GitRAG para este email.</p>
        <p>Para confirmar e ativar seus agendamentos, por favor, clique no link abaixo:</p>
        <p style="text-align: center; margin: 25px 0;">
            <a href="{verification_link}"
               style="background-color: #007bff; color: white; padding: 12px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                Ativar Meus Agendamentos
            </a>
        </p>
        <p>Se você não solicitou isso, pode ignorar este email com segurança.</p>
        <hr>
        <p style="font-size: 0.9em; color: #777;">Link (para copiar e colar): {verification_link}</p>
    </body>
    </html>
    """
    
    sender = {"name": SENDER_NAME, "email": SENDER_EMAIL}
    to = [{"email": to_email}]
    
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=to,
        sender=sender,
        subject=subject,
        html_content=html_content
    )
    
    try:
        api_instance.send_transac_email(send_smtp_email)
    except ApiException as e:
        print(f"[EmailService] ERRO ao enviar email de verificação: {e}")
        # Não lançamos exceção aqui para não travar o fluxo do chat
        # O usuário pode tentar agendar novamente se não receber