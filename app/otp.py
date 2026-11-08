import base64
import json
import logging
import re
import urllib.parse
import urllib.request
from fastapi import HTTPException
from .config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VERIFY_SERVICE_SID

logger = logging.getLogger("lafi.otp")

TEST_PHONE = "+2250700000000"
TEST_CODE = "123456"


def format_ci_phone(phone: str) -> str:
    """Normalise un numéro ivoirien au format international E.164 (+225...)."""
    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("00"):
        return "+" + cleaned[2:]
    if cleaned.startswith("225"):
        return "+" + cleaned
    return "+225" + cleaned


def send_otp(phone: str) -> dict:
    """Envoie un code de vérification SMS via Twilio Verify."""
    formatted = format_ci_phone(phone)

    # Mode démonstration / soutenance (numéro magique sans consommer d'unités SMS)
    if formatted == TEST_PHONE:
        logger.info(f"[OTP DEMO] Code pour {formatted} : {TEST_CODE}")
        return {"status": "pending", "to": formatted, "test_mode": True}

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_VERIFY_SERVICE_SID:
        raise HTTPException(500, "Service SMS non configuré sur le serveur (clés manquantes).")

    url = f"https://verify.twilio.com/v2/Services/{TWILIO_VERIFY_SERVICE_SID}/Verifications"
    data = urllib.parse.urlencode({"To": formatted, "Channel": "sms"}).encode("utf-8")
    req = urllib.request.Request(url, data=data)

    credentials = f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}"
    base64_cred = base64.b64encode(credentials.encode("ascii")).decode("ascii")
    req.add_header("Authorization", f"Basic {base64_cred}")

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            return {"status": result.get("status", "pending"), "to": formatted}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        logger.error(f"Erreur Twilio Send OTP ({e.code}) : {error_body}")
        try:
            err_json = json.loads(error_body)
            msg = err_json.get("message", "Impossible d'envoyer le SMS de vérification.")
        except Exception:
            msg = "Erreur lors de l'envoi du SMS."
        raise HTTPException(400, f"Erreur SMS : {msg}")


def verify_otp(phone: str, code: str) -> bool:
    """Vérifie le code OTP à 6 chiffres entré par l'utilisateur."""
    formatted = format_ci_phone(phone)
    clean_code = code.strip()

    # Mode démonstration / soutenance
    if formatted == TEST_PHONE and clean_code == TEST_CODE:
        return True

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_VERIFY_SERVICE_SID:
        raise HTTPException(500, "Service SMS non configuré sur le serveur.")

    url = f"https://verify.twilio.com/v2/Services/{TWILIO_VERIFY_SERVICE_SID}/VerificationCheck"
    data = urllib.parse.urlencode({"To": formatted, "Code": clean_code}).encode("utf-8")
    req = urllib.request.Request(url, data=data)

    credentials = f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}"
    base64_cred = base64.b64encode(credentials.encode("ascii")).decode("ascii")
    req.add_header("Authorization", f"Basic {base64_cred}")

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            return result.get("status") == "approved"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        logger.error(f"Erreur Twilio Check OTP ({e.code}) : {error_body}")
        return False
