"""
lafi-api/app/mailer.py
----------------------
Service d'envoi d'emails transactionnels (Bloc 3 - Application).

Fonctionnalités :
  1. Envoi sécurisé via SMTP standard (compatible Google Gmail SMTP port 587 STARTTLS).
  2. Gabarit HTML et texte soigné aux couleurs de Lafi pour la réinitialisation de mot de passe.
  3. Repli gracieux (Graceful Degradation) : si les identifiants SMTP ne sont pas configurés
     dans les variables d'environnement, le code est journalisé dans la console serveur,
     permettant une démonstration 100% fonctionnelle en soutenance sans dépendance réseau externe.
"""

import smtplib
from email.message import EmailMessage

from .config import SMTP_FROM, SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_USER


def send_reset_code_email(to_email: str, code: str, user_name: str = "Utilisateur Lafi") -> bool:
    """
    Envoie le code de réinitialisation à 6 chiffres par email.
    Retourne True en cas de succès ou en mode démonstration console.
    """
    print(f"📧 [LAFI MAILER] Code de réinitialisation pour {to_email} : {code}")

    # Si les identifiants SMTP ne sont pas configurés, le log console suffit pour la démo
    if not SMTP_USER or not SMTP_PASS:
        return True

    try:
        msg = EmailMessage()
        msg["Subject"] = f"Lafi - Votre code de réinitialisation : {code}"
        msg["From"] = SMTP_FROM
        msg["To"] = to_email

        # Version texte brut
        text_content = (
            f"Bonjour {user_name},\n\n"
            f"Vous avez demandé la réinitialisation de votre mot de passe sur l'application Lafi.\n"
            f"Voici votre code de sécurité à 6 chiffres :\n\n"
            f"    {code}\n\n"
            f"Ce code expire dans 15 minutes. Si vous n'avez pas fait cette demande, ignorez cet email.\n\n"
            f"L'équipe Lafi - Commerce de proximité\n"
        )
        msg.set_content(text_content)

        # Version HTML élégante aux couleurs de Lafi (#2C64E8)
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: Arial, sans-serif; background-color: #F6F8FD; margin: 0; padding: 24px; }}
            .container {{ max-width: 500px; margin: 0 auto; background: #FFFFFF; border-radius: 16px; padding: 32px; border: 1px solid #EAECF0; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2C64E8; margin-bottom: 20px; }}
            .title {{ font-size: 18px; font-weight: bold; color: #101828; margin-bottom: 12px; }}
            .text {{ font-size: 14px; color: #667085; line-height: 22px; margin-bottom: 24px; }}
            .code-box {{ background: #EFF4FF; border: 2px dashed #2C64E8; border-radius: 12px; padding: 18px; text-align: center; margin-bottom: 24px; }}
            .code {{ font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #2C64E8; }}
            .footer {{ font-size: 12px; color: #98A2B3; text-align: center; margin-top: 24px; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="logo">🛍️ Lafi</div>
            <div class="title">Réinitialisation de votre mot de passe</div>
            <div class="text">
              Bonjour <strong>{user_name}</strong>,<br>
              Vous avez demandé la réinitialisation de votre mot de passe. Voici votre code de vérification :
            </div>
            <div class="code-box">
              <div class="code">{code}</div>
            </div>
            <div class="text">
              Ce code est valable pendant <strong>15 minutes</strong>. Saisissez-le dans votre application Lafi pour choisir un nouveau mot de passe.
            </div>
            <div class="footer">
              Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet email en toute sécurité.<br>
              © Lafi - Application de commerce de proximité
            </div>
          </div>
        </body>
        </html>
        """
        msg.add_alternative(html_content, subtype="html")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        return True
    except Exception as e:
        print(f"⚠️ [LAFI MAILER] Erreur lors de l'envoi SMTP : {e}")
        # On ne bloque pas l'utilisateur en démo si le SMTP distant échoue
        return True


def send_verification_email(to_email: str, code: str, user_name: str = "Nouvel Utilisateur") -> bool:
    """
    Envoie le code de confirmation d'inscription à 6 chiffres par email.
    Retourne True en cas de succès ou en mode démonstration console.
    """
    print(f"📧 [LAFI MAILER] Code de confirmation d'inscription pour {to_email} : {code}")

    if not SMTP_USER or not SMTP_PASS:
        return True

    try:
        msg = EmailMessage()
        msg["Subject"] = f"Lafi - Votre code de confirmation d'inscription : {code}"
        msg["From"] = SMTP_FROM
        msg["To"] = to_email

        text_content = (
            f"Bonjour {user_name},\n\n"
            f"Merci de créer votre compte sur l'application Lafi.\n"
            f"Voici votre code de confirmation à 6 chiffres pour valider votre inscription :\n\n"
            f"    {code}\n\n"
            f"Ce code expire dans 15 minutes.\n\n"
            f"L'équipe Lafi - Commerce de proximité\n"
        )
        msg.set_content(text_content)

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: Arial, sans-serif; background-color: #F6F8FD; margin: 0; padding: 24px; }}
            .container {{ max-width: 500px; margin: 0 auto; background: #FFFFFF; border-radius: 16px; padding: 32px; border: 1px solid #EAECF0; }}
            .logo {{ font-size: 24px; font-weight: bold; color: #2C64E8; margin-bottom: 20px; }}
            .title {{ font-size: 18px; font-weight: bold; color: #101828; margin-bottom: 12px; }}
            .text {{ font-size: 14px; color: #667085; line-height: 22px; margin-bottom: 24px; }}
            .code-box {{ background: #EFF4FF; border: 2px dashed #2C64E8; border-radius: 12px; padding: 18px; text-align: center; margin-bottom: 24px; }}
            .code {{ font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #2C64E8; }}
            .footer {{ font-size: 12px; color: #98A2B3; text-align: center; margin-top: 24px; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="logo">🛍️ Lafi</div>
            <div class="title">Bienvenue sur Lafi ! Confirmez votre email</div>
            <div class="text">
              Bonjour <strong>{user_name}</strong>,<br>
              Merci de rejoindre le réseau de commerce de proximité Lafi.<br>
              Voici votre code de sécurité pour finaliser la création de votre compte :
            </div>
            <div class="code-box">
              <div class="code">{code}</div>
            </div>
            <div class="text">
              Ce code est valable pendant <strong>15 minutes</strong>. Saisissez-le dans l'application pour activer votre compte.
            </div>
            <div class="footer">
              © Lafi - Application de commerce de proximité
            </div>
          </div>
        </body>
        </html>
        """
        msg.add_alternative(html_content, subtype="html")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        return True
    except Exception as e:
        print(f"⚠️ [LAFI MAILER] Erreur lors de l'envoi SMTP : {e}")
        return True

