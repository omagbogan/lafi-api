import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

MY_SHOP_ID = 1          # valeur par défaut si pas d'en-tête X-Shop-Id
DELIVERY_FEE = 1500     # frais de livraison estimés (FCFA)
CATEGORIES = ["Alimentation", "Mode", "Beauté", "Électronique", "Maison", "Bébé"]

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 Mo

# Configuration Twilio Verify pour les SMS réels
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_VERIFY_SERVICE_SID = os.getenv("TWILIO_VERIFY_SERVICE_SID")
