import re
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..geo import DEFAULT_LAT, DEFAULT_LNG
from ..models import (
    Customer,
    CustomerCreate,
    CustomerLogin,
    CustomerOut,
    MerchantLogin,
    MerchantRegister,
    Shop,
    ShopOut,
)

router = APIRouter(prefix="/auth")


def clean_phone(phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    if len(cleaned) < 8:
        raise HTTPException(422, "Numéro de téléphone invalide (au moins 8 chiffres).")
    return cleaned


# ---------- Authentification Client ----------

@router.post("/customer/register", response_model=CustomerOut)
def register_customer(data: CustomerCreate, session: Session = Depends(get_session)):
    phone = clean_phone(data.phone)
    name = data.name.strip()
    address = data.address.strip()

    if not name:
        raise HTTPException(422, "Le nom est obligatoire.")
    if not address:
        raise HTTPException(422, "L'adresse ou le quartier est obligatoire.")

    statement = select(Customer).where(Customer.phone == phone)
    customer = session.exec(statement).first()

    if customer:
        customer.name = name
        customer.address = address
    else:
        customer = Customer(name=name, phone=phone, address=address)

    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


@router.post("/customer/login", response_model=CustomerOut)
def login_customer(data: CustomerLogin, session: Session = Depends(get_session)):
    phone = clean_phone(data.phone)
    statement = select(Customer).where(Customer.phone == phone)
    customer = session.exec(statement).first()

    if not customer:
        raise HTTPException(404, "Aucun compte client trouvé avec ce numéro. Veuillez vous inscrire.")
    return customer


# ---------- Authentification & Création Boutique Commerçant ----------

@router.post("/merchant/register", response_model=ShopOut)
def register_merchant(data: MerchantRegister, session: Session = Depends(get_session)):
    phone = clean_phone(data.phone)
    owner_name = data.owner_name.strip()
    shop_name = data.shop_name.strip()
    address = (data.address or "Cocody, Abidjan").strip()

    if not owner_name:
        raise HTTPException(422, "Le nom du propriétaire est obligatoire.")
    if not shop_name:
        raise HTTPException(422, "Le nom de la boutique est obligatoire.")

    # Vérifier si une boutique existe déjà avec ce téléphone
    statement = select(Shop).where(Shop.phone == phone)
    existing = session.exec(statement).first()
    if existing:
        existing.name = shop_name
        existing.owner_name = owner_name
        existing.address = address
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    shop = Shop(
        name=shop_name,
        owner_name=owner_name,
        phone=phone,
        address=address,
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
    phone = clean_phone(data.phone)
    statement = select(Shop).where(Shop.phone == phone)
    shop = session.exec(statement).first()

    if not shop:
        raise HTTPException(404, "Aucune boutique trouvée avec ce numéro de téléphone.")
    return shop
