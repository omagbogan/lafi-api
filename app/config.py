from pathlib import Path

MY_SHOP_ID = 1          # provisoire : pas encore de connexion, on agit toujours pour la boutique 1
DELIVERY_FEE = 1500     # frais de livraison estimés (FCFA)
CATEGORIES = ["Alimentation", "Mode", "Beauté", "Électronique", "Maison", "Bébé"]

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 Mo