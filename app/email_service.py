"""
Email service using Resend API
"""
import resend
from .config import settings
from typing import Optional


def init_resend():
    """Initialize Resend with API key"""
    api_key = getattr(settings, 'RESEND_API_KEY', None) or ""
    if api_key:
        resend.api_key = api_key
        return True
    return False


def send_password_reset_email(to_email: str, reset_token: str, user_name: Optional[str] = None) -> bool:
    """
    Send password reset email
    Returns True if sent successfully, False otherwise
    """
    if not init_resend():
        print(f"[EMAIL] Resend not configured. Token for {to_email}: {reset_token}")
        return False
    
    reset_url = f"{settings.APP_URL}/reset-password?token={reset_token}"
    
    try:
        params = {
            "from": f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>",
            "to": [to_email],
            "subject": "🔐 Reimposta la tua password - Insurance Lab AI",
            "html": f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .header h1 {{ color: white; margin: 0; font-size: 24px; }}
                    .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
                    .button {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white !important; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 20px 0; }}
                    .button:hover {{ opacity: 0.9; }}
                    .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
                    .warning {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 10px 15px; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🔐 Insurance Lab AI</h1>
                    </div>
                    <div class="content">
                        <h2>Reimposta la tua password</h2>
                        <p>Ciao{f' {user_name}' if user_name else ''},</p>
                        <p>Abbiamo ricevuto una richiesta per reimpostare la password del tuo account Insurance Lab AI.</p>
                        <p style="text-align: center;">
                            <a href="{reset_url}" class="button">Reimposta Password</a>
                        </p>
                        <div class="warning">
                            ⏰ <strong>Questo link scade tra 1 ora.</strong><br>
                            Se non hai richiesto il reset della password, ignora questa email.
                        </div>
                        <p>Se il pulsante non funziona, copia e incolla questo link nel browser:</p>
                        <p style="word-break: break-all; background: #e5e7eb; padding: 10px; border-radius: 5px; font-size: 12px;">
                            {reset_url}
                        </p>
                    </div>
                    <div class="footer">
                        <p>© 2024 Insurance Lab AI. Tutti i diritti riservati.</p>
                        <p>Questa email è stata inviata automaticamente, non rispondere.</p>
                    </div>
                </div>
            </body>
            </html>
            """
        }
        
        result = resend.Emails.send(params)
        print(f"[EMAIL] Sent password reset email to {to_email}. ID: {result.get('id', 'unknown')}")
        return True
        
    except Exception as e:
        print(f"[EMAIL] Failed to send email to {to_email}: {e}")
        return False


def send_welcome_email(to_email: str, user_name: Optional[str] = None) -> bool:
    """Send welcome email to new user"""
    if not init_resend():
        print(f"[EMAIL] Resend not configured. Skipping welcome email to {to_email}")
        return False
    
    try:
        params = {
            "from": f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>",
            "to": [to_email],
            "subject": "🎉 Benvenuto in Insurance Lab AI!",
            "html": f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .header h1 {{ color: white; margin: 0; font-size: 24px; }}
                    .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
                    .button {{ display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white !important; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 20px 0; }}
                    .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎉 Insurance Lab AI</h1>
                    </div>
                    <div class="content">
                        <h2>Benvenuto!</h2>
                        <p>Ciao{f' {user_name}' if user_name else ''},</p>
                        <p>Il tuo account Insurance Lab AI è stato creato con successo!</p>
                        <p>Con Insurance Lab AI puoi:</p>
                        <ul>
                            <li>📄 Analizzare polizze assicurative con l'AI</li>
                            <li>🔒 Mascherare dati sensibili automaticamente</li>
                            <li>📊 Generare report dettagliati</li>
                        </ul>
                        <p style="text-align: center;">
                            <a href="{settings.APP_URL}" class="button">Accedi Ora</a>
                        </p>
                    </div>
                    <div class="footer">
                        <p>© 2024 Insurance Lab AI. Tutti i diritti riservati.</p>
                    </div>
                </div>
            </body>
            </html>
            """
        }
        
        result = resend.Emails.send(params)
        print(f"[EMAIL] Sent welcome email to {to_email}. ID: {result.get('id', 'unknown')}")
        return True
        
    except Exception as e:
        print(f"[EMAIL] Failed to send welcome email to {to_email}: {e}")
        return False
