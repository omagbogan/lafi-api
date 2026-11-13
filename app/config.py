import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

MY_SHOP_ID = 1          # valeur par défaut si pas d'en-tête X-Shop-Id
DELIVERY_FEE = 0        # la course Yango est réglée en direct au livreur selon le tarif dynamique Yango
CATEGORIES = ["Alimentation", "Mode", "Beauté", "Électronique", "Maison", "Bébé"]

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 Mo

# Configuration Twilio Verify pour les SMS réels
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_VERIFY_SERVICE_SID = os.getenv("TWILIO_VERIFY_SERVICE_SID")

# Configuration OpenRouter pour l'Agent IA augmenté (Bloc 4)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")

# Configuration SMTP Email transactionnel (Google Gmail)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").replace(" ", "").strip()
default_from = f"Lafi Marché <{SMTP_USER}>" if SMTP_USER else "Lafi Marché <no-reply@lafi.ci>"
SMTP_FROM = os.getenv("SMTP_FROM", default_from)
if SMTP_USER and ("no-reply" in SMTP_FROM or "lafi.ci" in SMTP_FROM):
    SMTP_FROM = f"Lafi Marché <{SMTP_USER}>"

# Identifiants Super-Administrateur (lus depuis le fichier .env non versionné)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", SMTP_USER).strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()

