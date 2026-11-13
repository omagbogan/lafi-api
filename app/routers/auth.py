"""
lafi-api/app/routers/auth.py
----------------------------
Gestion de l'authentification, de l'inscription et de la sécurité des comptes (Bloc 3 - Application).

Fonctionnalités clés :
  1. Authentification Client & Commerçant par Email + Mot de passe (hachage PBKDF2-SHA256).
  2. Conservation du numéro de téléphone pour les flux logistiques Yango et WhatsApp.
  3. Réinitialisation de mot de passe sécurisée (OTP 6 chiffres par email, validité 15 min).
  4. Mode démonstration pour la soutenance : code universel 123456 et journalisation console.
"""

import random
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from ..db import get_session
from ..geo import DEFAULT_LAT, DEFAULT_LNG
from ..mailer import send_reset_code_email, send_verification_email
from ..models import (
    Customer,
    CustomerCreate,
    CustomerLogin,
    CustomerOut,
    CustomerUpdate,
    EmailVerificationCode,
    ForgotPasswordRequest,
    MerchantLogin,
    MerchantRegister,
    OtpSend,
    OtpVerify,
    PasswordResetCode,
    ResetPasswordRequest,
    SendEmailCodeRequest,
    Shop,
    ShopOut,
    VerifyEmailCodeRequest,
    now_ms,
)
from ..otp import send_otp, verify_otp
from ..security import hash_password, verify_password

router = APIRouter(prefix="/auth")


def clean_phone(phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    if len(cleaned) < 8:
        raise HTTPException(422, "Numéro de téléphone invalide (au moins 8 chiffres).")
    return cleaned


# ---------- Sécurité OWASP : Protection contre les attaques par force brute & robots ----------
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MS = 5 * 60 * 1000  # 5 minutes de verrouillage temporaire

# Stockage en mémoire : clé d'identifiant -> {"attempts": int, "locked_until": int}
login_attempts: dict[str, dict[str, int]] = {}


def check_login_rate_limit(key: str) -> None:
    """Bloque la connexion si plus de 5 tentatives infructueuses ont été effectuées."""
    now = now_ms()
    record = login_attempts.get(key)
    if record:
        locked_until = record.get("locked_until", 0)
        if locked_until > now:
            remaining_seconds = max(1, int((locked_until - now) / 1000))
            remaining_minutes = max(1, (remaining_seconds + 59) // 60)
            raise HTTPException(
                status_code=429,
                detail=f"Trop de tentatives infructueuses. Veuillez patienter {remaining_minutes} minute(s) avant de réessayer.",
            )
        # Si la durée de blocage est écoulée, on nettoie
        if locked_until and locked_until <= now:
            login_attempts.pop(key, None)


def record_failed_login(key: str) -> None:
    """Incrémente le compteur de tentatives infructueuses et verrouille à partir de 5 échecs."""
    now = now_ms()
    record = login_attempts.setdefault(key, {"attempts": 0, "locked_until": 0})
    record["attempts"] += 1
    if record["attempts"] >= MAX_LOGIN_ATTEMPTS:
        record["locked_until"] = now + LOCKOUT_DURATION_MS


def reset_login_attempts(key: str) -> None:
    """Réinitialise les tentatives après une connexion réussie."""
    login_attempts.pop(key, None)


# ---------- Authentification Client ----------

@router.post("/customer/register", response_model=CustomerOut)
def register_customer(data: CustomerCreate, session: Session = Depends(get_session)):
    phone = clean_phone(data.phone)
    name = data.name.strip()
    address = data.address.strip()
    email = data.email.strip().lower() if data.email else None

    if not name:
        raise HTTPException(422, "Le nom est obligatoire.")
    if not address:
        raise HTTPException(422, "L'adresse ou le quartier est obligatoire.")

    if email:
        existing_email = session.exec(select(Customer).where(Customer.email == email)).first()
        if existing_email and existing_email.phone != phone:
            raise HTTPException(409, "Cette adresse email est déjà associée à un autre compte.")

    password_hash = None
    if data.password:
        pwd = data.password.strip()
        if len(pwd) < 6:
            raise HTTPException(422, "Le mot de passe doit comporter au moins 6 caractères.")
        password_hash = hash_password(pwd)

    statement = select(Customer).where(Customer.phone == phone)
    customer = session.exec(statement).first()

    if customer:
        customer.name = name
        customer.address = address
        if email:
            customer.email = email
        if password_hash:
            customer.password_hash = password_hash
    else:
        customer = Customer(
            name=name,
            phone=phone,
            address=address,
            email=email,
            password_hash=password_hash,
        )

    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


@router.post("/customer/login", response_model=CustomerOut)
def login_customer(data: CustomerLogin, session: Session = Depends(get_session)):
    # 1. Connexion par Email et Mot de passe
    if data.email:
        email = data.email.strip().lower()
        key = f"customer:email:{email}"
        check_login_rate_limit(key)

        customer = session.exec(select(Customer).where(Customer.email == email)).first()

        # Sécurité OWASP : message unique et neutre (anti-énumération de comptes)
        if (
            not customer
            or not customer.password_hash
            or not data.password
            or not verify_password(data.password.strip(), customer.password_hash)
        ):
            record_failed_login(key)
            raise HTTPException(401, "Adresse email ou mot de passe incorrect.")

        reset_login_attempts(key)
        return customer

    # 2. Repli par Téléphone (avec vérification mot de passe si configuré)
    if data.phone:
        phone = clean_phone(data.phone)
        key = f"customer:phone:{phone}"
        check_login_rate_limit(key)

        statement = select(Customer).where(Customer.phone == phone)
        customer = session.exec(statement).first()

        if not customer or (
            customer.password_hash
            and (not data.password or not verify_password(data.password.strip(), customer.password_hash))
        ):
            record_failed_login(key)
            raise HTTPException(401, "Numéro de téléphone ou mot de passe incorrect.")

        reset_login_attempts(key)
        return customer

    raise HTTPException(422, "Veuillez renseigner une adresse email ou un numéro de téléphone.")


@router.patch("/customer/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int,
    data: CustomerUpdate,
    session: Session = Depends(get_session),
):
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Client introuvable.")

    update_dict = data.model_dump(exclude_unset=True)

    if "phone" in update_dict and update_dict["phone"]:
        cleaned = clean_phone(update_dict["phone"])
        existing = session.exec(
            select(Customer).where(Customer.phone == cleaned, Customer.id != customer_id)
        ).first()
        if existing:
            raise HTTPException(409, "Ce numéro de téléphone est déjà associé à un autre compte.")
        customer.phone = cleaned

    if "email" in update_dict and update_dict["email"]:
        email_clean = update_dict["email"].strip().lower()
        existing_email = session.exec(
            select(Customer).where(Customer.email == email_clean, Customer.id != customer_id)
        ).first()
        if existing_email:
            raise HTTPException(409, "Cette adresse email est déjà associée à un autre compte.")
        customer.email = email_clean

    if "name" in update_dict and update_dict["name"] is not None:
        name = update_dict["name"].strip()
        if not name:
            raise HTTPException(422, "Le nom ne peut pas être vide.")
        customer.name = name

    if "address" in update_dict and update_dict["address"] is not None:
        address = update_dict["address"].strip()
        if not address:
            raise HTTPException(422, "L'adresse ne peut pas être vide.")
        customer.address = address

    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


# ---------- Authentification & Création Boutique Commerçant ----------

@router.post("/merchant/register", response_model=ShopOut)
def register_merchant(data: MerchantRegister, session: Session = Depends(get_session)):
    phone = clean_phone(data.phone)
    owner_name = data.owner_name.strip()
    shop_name = data.shop_name.strip()
    address = data.address.strip()
    email = data.email.strip().lower() if data.email else None

    if not owner_name:
        raise HTTPException(422, "Le nom du propriétaire est obligatoire.")
    if not shop_name:
        raise HTTPException(422, "Le nom de la boutique est obligatoire.")
    if not address:
        raise HTTPException(422, "L'adresse ou le quartier de la boutique est obligatoire.")

    if email:
        existing_email = session.exec(select(Shop).where(Shop.email == email)).first()
        if existing_email and existing_email.phone != phone:
            raise HTTPException(409, "Cette adresse email est déjà associée à une autre boutique.")

    password_hash = None
    if data.password:
        pwd = data.password.strip()
        if len(pwd) < 6:
            raise HTTPException(422, "Le mot de passe doit comporter au moins 6 caractères.")
        password_hash = hash_password(pwd)

    statement = select(Shop).where(Shop.phone == phone)
    existing = session.exec(statement).first()
    if existing:
        existing.name = shop_name
        existing.owner_name = owner_name
        existing.address = address
        if email:
            existing.email = email
        if password_hash:
            existing.password_hash = password_hash
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    shop = Shop(
        name=shop_name,
        owner_name=owner_name,
        phone=phone,
        address=address,
        email=email,
        password_hash=password_hash,
        lat=data.lat if data.lat is not None else DEFAULT_LAT,
        lng=data.lng if data.lng is not None else DEFAULT_LNG,
        is_open=True,
    )
    session.add(shop)
    session.commit()
    session.refresh(shop)
    return shop


@router.post("/merchant/login", response_model=ShopOut)
def login_merchant(data: MerchantLogin, session: Session = Depends(get_session)):
    # 1. Connexion par Email et Mot de passe
    if data.email:
        email = data.email.strip().lower()
        key = f"merchant:email:{email}"
        check_login_rate_limit(key)

        shop = session.exec(select(Shop).where(Shop.email == email)).first()

        # Sécurité OWASP : message unique et neutre (anti-énumération de comptes)
        if (
            not shop
            or not shop.password_hash
            or not data.password
            or not verify_password(data.password.strip(), shop.password_hash)
        ):
            record_failed_login(key)
            raise HTTPException(401, "Adresse email ou mot de passe incorrect.")

        reset_login_attempts(key)
        return shop

    # 2. Repli par Téléphone
    if data.phone:
        phone = clean_phone(data.phone)
        key = f"merchant:phone:{phone}"
        check_login_rate_limit(key)

        statement = select(Shop).where(Shop.phone == phone)
        shop = session.exec(statement).first()

        if not shop or (
            shop.password_hash
            and (not data.password or not verify_password(data.password.strip(), shop.password_hash))
        ):
            record_failed_login(key)
            raise HTTPException(401, "Numéro de téléphone ou mot de passe incorrect.")

        reset_login_attempts(key)
        return shop

    raise HTTPException(422, "Veuillez renseigner une adresse email ou un numéro de téléphone.")


# ---------- Mot de passe oublié & Réinitialisation ----------

@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, session: Session = Depends(get_session)):
    email = data.email.strip().lower()
    if "@" not in email:
        raise HTTPException(422, "Adresse email invalide.")

    user_name = "Utilisateur Lafi"
    if data.user_type == "customer":
        customer = session.exec(select(Customer).where(Customer.email == email)).first()
        if not customer:
            raise HTTPException(404, "Aucun compte client trouvé avec cette adresse email.")
        user_name = customer.name
    else:
        shop = session.exec(select(Shop).where(Shop.email == email)).first()
        if not shop:
            raise HTTPException(404, "Aucune boutique trouvée avec cette adresse email.")
        user_name = shop.owner_name or shop.name

    code = f"{random.randint(100000, 999999)}"
    reset_record = PasswordResetCode(
        email=email,
        code=code,
        user_type=data.user_type,
        expires_at=now_ms() + 15 * 60 * 1000,
    )
    session.add(reset_record)
    session.commit()

    send_reset_code_email(email, code, user_name)
    return {"status": "ok", "message": "Code de réinitialisation envoyé par email.", "email": email}


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, session: Session = Depends(get_session)):
    email = data.email.strip().lower()
    code = data.code.strip()
    new_password = data.new_password.strip()

    if len(new_password) < 6:
        raise HTTPException(422, "Le nouveau mot de passe doit comporter au moins 6 caractères.")

    # Vérification du code (avec code 123456 pour la soutenance)
    if code != "123456":
        record = session.exec(
            select(PasswordResetCode)
            .where(
                PasswordResetCode.email == email,
                PasswordResetCode.code == code,
                PasswordResetCode.user_type == data.user_type,
                PasswordResetCode.used == False,
            )
            .order_by(col(PasswordResetCode.created_at).desc())
        ).first()

        if not record:
            raise HTTPException(400, "Code de réinitialisation invalide ou déjà utilisé.")
        if now_ms() > record.expires_at:
            raise HTTPException(400, "Ce code de réinitialisation a expiré (durée 15 minutes).")

        record.used = True
        session.add(record)

    # Mise à jour du mot de passe
    new_hash = hash_password(new_password)
    if data.user_type == "customer":
        customer = session.exec(select(Customer).where(Customer.email == email)).first()
        if not customer:
            raise HTTPException(404, "Compte client introuvable.")
        customer.password_hash = new_hash
        session.add(customer)
    else:
        shop = session.exec(select(Shop).where(Shop.email == email)).first()
        if not shop:
            raise HTTPException(404, "Boutique introuvable.")
        shop.password_hash = new_hash
        session.add(shop)

    session.commit()
    return {"status": "ok", "message": "Votre mot de passe a été réinitialisé avec succès."}


# ---------- Vérification de l'adresse Email à l'inscription ----------

@router.post("/email/send-code")
def send_email_verification_code(data: SendEmailCodeRequest, session: Session = Depends(get_session)):
    email = data.email.strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(422, "Adresse email invalide.")

    # Vérification si l'adresse est déjà associée à un compte
    existing_cust = session.exec(select(Customer).where(Customer.email == email)).first()
    existing_shop = session.exec(select(Shop).where(Shop.email == email)).first()
    if existing_cust or existing_shop:
        raise HTTPException(409, "Cette adresse email est déjà utilisée par un autre compte.")

    code = f"{random.randint(100000, 999999)}"
    record = EmailVerificationCode(
        email=email,
        code=code,
        expires_at=now_ms() + 15 * 60 * 1000,
    )
    session.add(record)
    session.commit()

    name = data.name.strip() if data.name else "Nouvel Utilisateur"
    send_verification_email(email, code, name)
    return {"status": "ok", "message": "Code de confirmation envoyé par email.", "email": email}


@router.post("/email/verify-code")
def verify_email_code(data: VerifyEmailCodeRequest, session: Session = Depends(get_session)):
    email = data.email.strip().lower()
    code = data.code.strip()

    if not code:
        raise HTTPException(422, "Veuillez renseigner le code de vérification.")

    # Démonstration soutenance : le code universel 123456 est toujours accepté
    if code == "123456":
        return {"status": "ok", "valid": True, "message": "Email vérifié avec succès."}

    record = session.exec(
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.email == email,
            EmailVerificationCode.code == code,
            EmailVerificationCode.used == False,
        )
        .order_by(col(EmailVerificationCode.created_at).desc())
    ).first()

    if not record:
        raise HTTPException(400, "Code de confirmation incorrect ou déjà utilisé.")

    if now_ms() > record.expires_at:
        raise HTTPException(400, "Ce code de confirmation a expiré (durée 15 minutes).")

    record.used = True
    session.add(record)
    session.commit()

    return {"status": "ok", "valid": True, "message": "Email vérifié avec succès."}


# ---------- Vérification SMS OTP (Twilio Verify) ----------

@router.post("/otp/send")
def request_otp(data: OtpSend):
    cleaned = clean_phone(data.phone)
    result = send_otp(cleaned)
    return {"status": "ok", "message": "Code SMS envoyé avec succès.", **result}


@router.post("/otp/verify")
def check_otp(data: OtpVerify):
    cleaned = clean_phone(data.phone)
    code = data.code.strip()
    if not code or len(code) != 6:
        raise HTTPException(422, "Le code doit comporter exactement 6 chiffres.")

    is_valid = verify_otp(cleaned, code)
    if not is_valid:
        raise HTTPException(400, "Code de vérification incorrect ou expiré.")

    return {"status": "approved", "valid": True, "phone": cleaned}
