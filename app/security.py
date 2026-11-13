"""
lafi-api/app/security.py
------------------------
Sécurité et hachage cryptographique des mots de passe (Bloc 3 - Application & Sécurité).

Algorithme utilisé : PBKDF2-HMAC-SHA256 avec sel cryptographique aléatoire de 16 octets (128 bits)
et 100 000 itérations, conforme aux recommandations strictes de l'OWASP et de l'ANSSI.

Avantages pour la soutenance Développeur Data IA :
  - Aucune dépendance C binaire fragile (utilise hashlib et secrets de la bibliothèque standard Python).
  - Résistant aux attaques par tables arc-en-ciel (rainbow tables) grâce au sel unique par utilisateur.
  - Résistant aux attaques par timing (timing attacks) grâce à secrets.compare_digest.
"""

import hashlib
import secrets

ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """Génère une empreinte salée sécurisée pour le mot de passe."""
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        ITERATIONS,
    )
    return f"{salt}${ITERATIONS}${derived.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Vérifie si un mot de passe en clair correspond à l'empreinte salée."""
    try:
        parts = hashed.split("$")
        if len(parts) != 3:
            return False
        salt, iterations_str, derived_hex = parts
        iterations = int(iterations_str)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        return secrets.compare_digest(derived.hex(), derived_hex)
    except Exception:
        return False

