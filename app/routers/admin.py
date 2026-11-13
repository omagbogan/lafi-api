"""
lafi-api/app/routers/admin.py
-----------------------------
Routeur Super-Administrateur en temps réel (Supervision, Gestion & Outils de Test).
"""

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from .. import category_model, image_model
from ..config import ADMIN_EMAIL, ADMIN_PASSWORD, CATEGORIES, OPENROUTER_API_KEY
from ..db import get_session
from ..geo import DEFAULT_LAT, DEFAULT_LNG, distance_m
from ..models import (
    Article,
    ArticleOut,
    Customer,
    EmailVerificationCode,
    Order,
    OrderItem,
    OrderItemOut,
    OrderOut,
    PasswordResetCode,
    Shop,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminLoginRequest(SQLModel):
    email: str
    password: str


class AdminArticleCreate(SQLModel):
    name: str
    price: int
    category: str
    description: Optional[str] = None
    photo_url: Optional[str] = None
    photos: Optional[list[str]] = None
    shop_id: Optional[int] = None
    shop_name: Optional[str] = "Boutique Officielle Lafi"
    shop_phone: Optional[str] = "0700000001"
    shop_address: Optional[str] = "Cocody, Abidjan"
    negotiable: bool = False


class AdminShopCreate(SQLModel):
    name: str
    owner_name: Optional[str] = "Administrateur"
    phone: str = "0700000001"
    address: Optional[str] = "Abidjan, Côte d'Ivoire"
    email: Optional[str] = None
    lat: float = DEFAULT_LAT
    lng: float = DEFAULT_LNG


class AdminOrderStatusUpdate(SQLModel):
    status: str


def is_admin_credentials(email: Optional[str], password: Optional[str]) -> bool:
    if not email or not password or not ADMIN_EMAIL or not ADMIN_PASSWORD:
        return False
    return email.strip().lower() == ADMIN_EMAIL.lower() and password.strip() == ADMIN_PASSWORD


@router.post("/login")
def admin_login(body: AdminLoginRequest):
    if not is_admin_credentials(body.email, body.password):
        raise HTTPException(401, "Identifiants administrateur invalides.")
    return {
        "id": 0,
        "name": "Super Administrateur",
        "email": ADMIN_EMAIL,
        "phone": "0700000000",
        "role": "admin",
    }


@router.get("/overview")
def admin_overview(session: Session = Depends(get_session)):
    shops = session.exec(select(Shop).order_by(Shop.id.desc())).all()
    shops_by_id = {s.id: s for s in shops}

    articles = session.exec(select(Article).order_by(Article.id.desc())).all()
    customers = session.exec(select(Customer).order_by(Customer.id.desc())).all()
    orders = session.exec(select(Order).order_by(Order.id.desc())).all()

    # Formatage des articles
    articles_out: list[ArticleOut] = []
    article_counts_by_shop: dict[int, int] = {}
    for a in articles:
        article_counts_by_shop[a.shop_id] = article_counts_by_shop.get(a.shop_id, 0) + 1
        shop = shops_by_id.get(a.shop_id)
        photos_list: list[str] = []
        if a.photos_json:
            try:
                photos_list = json.loads(a.photos_json)
            except Exception:
                photos_list = []
        if not photos_list and a.photo_url:
            photos_list = [a.photo_url]

        articles_out.append(
            ArticleOut(
                id=a.id,
                name=a.name,
                price=a.price,
                category=a.category,
                description=a.description,
                negotiable=a.negotiable,
                hidden=a.hidden,
                out_of_stock=a.out_of_stock,
                color=a.color,
                photo_url=a.photo_url,
                photos=photos_list,
                shop_id=a.shop_id,
                shop=shop.name if shop else "Boutique supprimée",
                shop_phone=shop.phone if shop else "",
                open=shop.is_open if shop else False,
                distance_m=distance_m(DEFAULT_LAT, DEFAULT_LNG, shop.lat, shop.lng) if shop else 0,
                shop_lat=shop.lat if shop else DEFAULT_LAT,
                shop_lng=shop.lng if shop else DEFAULT_LNG,
            )
        )

    # Formatage des commandes
    orders_out: list[OrderOut] = []
    order_counts_by_customer: dict[int, int] = {}
    for o in orders:
        if o.customer_id:
            order_counts_by_customer[o.customer_id] = order_counts_by_customer.get(o.customer_id, 0) + 1
        shop = shops_by_id.get(o.shop_id)
        items = session.exec(select(OrderItem).where(OrderItem.order_id == o.id)).all()
        orders_out.append(
            OrderOut(
                id=o.id,
                shop_id=o.shop_id,
                shop=shop.name if shop else f"Boutique #{o.shop_id}",
                mode=o.mode,
                subtotal=o.subtotal,
                delivery_fee=o.delivery_fee,
                total=o.total,
                status=o.status,
                customer_id=o.customer_id,
                customer_name=o.customer_name,
                customer_phone=o.customer_phone,
                customer_address=o.customer_address,
                pickup_code=o.pickup_code,
                customer_lat=o.customer_lat,
                customer_lng=o.customer_lng,
                driver_dispatched=o.driver_dispatched,
                package_handed_over=o.package_handed_over,
                shop_lat=shop.lat if shop else None,
                shop_lng=shop.lng if shop else None,
                shop_address=shop.address if shop else None,
                shop_phone=shop.phone if shop else None,
                created_at=o.created_at,
                items=[
                    OrderItemOut(article_id=it.article_id, name=it.name, price=it.price, qty=it.qty)
                    for it in items
                ],
            )
        )

    # Calcul des statistiques en temps réel
    total_revenue = sum(o.total for o in orders if o.status in ("accepted", "completed"))
    pending_revenue = sum(o.total for o in orders if o.status == "pending")

    stats = {
        "total_revenue": total_revenue,
        "pending_revenue": pending_revenue,
        "orders_total": len(orders),
        "orders_pending": sum(1 for o in orders if o.status == "pending"),
        "orders_accepted": sum(1 for o in orders if o.status == "accepted"),
        "orders_completed": sum(1 for o in orders if o.status == "completed"),
        "orders_cancelled": sum(1 for o in orders if o.status in ("cancelled", "refused")),
        "shops_total": len(shops),
        "shops_open": sum(1 for s in shops if s.is_open),
        "customers_total": len(customers),
        "articles_total": len(articles),
        "articles_in_stock": sum(1 for a in articles if not a.hidden and not a.out_of_stock),
    }

    ai_status = {
        "category_model_ready": getattr(category_model, "_model", None) is not None,
        "vision_model_ready": getattr(image_model, "_model", None) is not None,
        "llm_agent_ready": bool(os.getenv("GROQ_API_KEY") or OPENROUTER_API_KEY),
    }

    shops_data = [
        {
            "id": s.id,
            "name": s.name,
            "owner_name": s.owner_name,
            "phone": s.phone,
            "email": s.email,
            "address": s.address,
            "is_open": s.is_open,
            "lat": s.lat,
            "lng": s.lng,
            "articles_count": article_counts_by_shop.get(s.id, 0),
        }
        for s in shops
    ]

    customers_data = [
        {
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "email": c.email,
            "address": c.address,
            "created_at": c.created_at,
            "orders_count": order_counts_by_customer.get(c.id, 0),
        }
        for c in customers
    ]

    return {
        "stats": stats,
        "ai_status": ai_status,
        "shops": shops_data,
        "customers": customers_data,
        "articles": articles_out,
        "orders": orders_out,
    }


@router.post("/shops", status_code=201)
def admin_create_shop(body: AdminShopCreate, session: Session = Depends(get_session)):
    shop = Shop(
        name=body.name.strip(),
        owner_name=(body.owner_name or "Administrateur").strip(),
        phone=body.phone.strip(),
        address=(body.address or "Abidjan").strip(),
        email=body.email.strip().lower() if body.email else None,
        lat=body.lat,
        lng=body.lng,
        is_open=True,
    )
    session.add(shop)
    session.commit()
    session.refresh(shop)
    return shop


@router.delete("/shops/{shop_id}", status_code=204)
def admin_delete_shop(shop_id: int, session: Session = Depends(get_session)):
    shop = session.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Boutique introuvable")
    # Supprimer les articles et commandes rattachés
    articles = session.exec(select(Article).where(Article.shop_id == shop_id)).all()
    for a in articles:
        session.delete(a)
    orders = session.exec(select(Order).where(Order.shop_id == shop_id)).all()
    for o in orders:
        items = session.exec(select(OrderItem).where(OrderItem.order_id == o.id)).all()
        for it in items:
            session.delete(it)
        session.delete(o)
    session.delete(shop)
    session.commit()


@router.post("/articles", status_code=201)
def admin_create_article(body: AdminArticleCreate, session: Session = Depends(get_session)):
    if body.category not in CATEGORIES:
        raise HTTPException(422, f"Catégorie invalide. Choisir parmi : {CATEGORIES}")

    shop: Optional[Shop] = None
    if body.shop_id:
        shop = session.get(Shop, body.shop_id)

    if not shop:
        target_name = (body.shop_name or "Boutique Officielle Lafi").strip()
        shop = session.exec(select(Shop).where(Shop.name == target_name)).first()
        if not shop:
            shop = Shop(
                name=target_name,
                owner_name="Super Administrateur",
                phone=(body.shop_phone or "0700000001").strip(),
                address=(body.shop_address or "Cocody, Abidjan").strip(),
                lat=DEFAULT_LAT + 0.002,
                lng=DEFAULT_LNG + 0.002,
                is_open=True,
            )
            session.add(shop)
            session.commit()
            session.refresh(shop)

    photos_list = [p.strip() for p in (body.photos or []) if p and p.strip()]
    if not photos_list and body.photo_url and body.photo_url.strip():
        photos_list = [body.photo_url.strip()]
    main_photo = photos_list[0] if photos_list else None

    article = Article(
        shop_id=shop.id,
        name=body.name.strip(),
        price=body.price,
        category=body.category,
        description=body.description.strip() if body.description else f"{body.name.strip()} disponible immédiatement chez {shop.name} à Abidjan.",
        negotiable=body.negotiable,
        photo_url=main_photo,
        photos_json=json.dumps(photos_list) if photos_list else None,
        color="#2C64E8",
    )
    session.add(article)
    session.commit()
    session.refresh(article)
    return article


@router.delete("/articles/{article_id}", status_code=204)
def admin_delete_article(article_id: int, session: Session = Depends(get_session)):
    article = session.get(Article, article_id)
    if not article:
        raise HTTPException(404, "Article introuvable")
    session.delete(article)
    session.commit()


@router.patch("/orders/{order_id}/status")
def admin_update_order_status(order_id: int, body: AdminOrderStatusUpdate, session: Session = Depends(get_session)):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Commande introuvable")
    order.status = body.status
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.delete("/orders/{order_id}", status_code=204)
def admin_delete_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Commande introuvable")
    items = session.exec(select(OrderItem).where(OrderItem.order_id == order_id)).all()
    for it in items:
        session.delete(it)
    session.delete(order)
    session.commit()


@router.delete("/customers/{customer_id}", status_code=204)
def admin_delete_customer(customer_id: int, session: Session = Depends(get_session)):
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Client introuvable")
    session.delete(customer)
    session.commit()


@router.post("/seed-demo")
def admin_seed_demo(session: Session = Depends(get_session)):
    """
    Injecte un pack d'articles de démonstration dans les 6 catégories officielles
    pour tester rapidement la plateforme.
    """
    demo_shops = [
        ("Saveurs d'Abidjan", "Maman Awa", "0701020304", "Cocody Angré, Abidjan", DEFAULT_LAT + 0.0031, DEFAULT_LNG + 0.0015),
        ("Maison du Wax & Cuir", "Aïcha Koné", "0702030405", "Marcory Zone 4, Abidjan", DEFAULT_LAT - 0.0042, DEFAULT_LNG + 0.0032),
        ("Karité & Nature", "Fatou Bamba", "0703040506", "Riviera Palmeraie, Abidjan", DEFAULT_LAT + 0.0055, DEFAULT_LNG - 0.0041),
        ("Tech Hub Plateau", "Koffi Kouadio", "0704050607", "Plateau, Abidjan", DEFAULT_LAT - 0.0068, DEFAULT_LNG - 0.0025),
    ]

    shop_map: dict[str, Shop] = {}
    for name, owner, phone, addr, lat, lng in demo_shops:
        existing = session.exec(select(Shop).where(Shop.name == name)).first()
        if not existing:
            existing = Shop(name=name, owner_name=owner, phone=phone, address=addr, lat=lat, lng=lng, is_open=True)
            session.add(existing)
            session.commit()
            session.refresh(existing)
        shop_map[name] = existing

    demo_articles = [
        (
            "Saveurs d'Abidjan",
            "Attiéké Poisson Braisé Royal",
            3500,
            "Alimentation",
            "Attiéké frais de Dabou accompagné de poisson bar braisé, alloco doré et piment maison.",
            "https://images.unsplash.com/photo-1544025162-d76694265947?w=800&auto=format&fit=crop&q=80",
        ),
        (
            "Maison du Wax & Cuir",
            "Sac à Main Artisanal en Cuir & Wax",
            15000,
            "Mode",
            "Sac à main confectionné à la main à Abidjan en cuir véritable et tissu pagne Wax authentique.",
            "https://images.unsplash.com/photo-1584917865442-de89df76afd3?w=800&auto=format&fit=crop&q=80",
        ),
        (
            "Karité & Nature",
            "Beurre de Karité Pur Bio (500g)",
            3000,
            "Beauté",
            "Beurre de karité 100% naturel non raffiné du Nord de la Côte d'Ivoire, hydratation intense peau et cheveux.",
            "https://images.unsplash.com/photo-1608248597359-0e6d526a6c58?w=800&auto=format&fit=crop&q=80",
        ),
        (
            "Tech Hub Plateau",
            "Écouteurs Bluetooth Sans Fil Pro",
            12000,
            "Électronique",
            "Écouteurs intra-auriculaires Bluetooth 5.3 avec réduction de bruit active et boîtier de charge rapide.",
            "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=800&auto=format&fit=crop&q=80",
        ),
        (
            "Maison du Wax & Cuir",
            "Lampe de Salon Artisanale en Rotin",
            18500,
            "Maison",
            "Lampe décorative chaleureuse tressée à la main pour illuminer votre salon avec élégance.",
            "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=800&auto=format&fit=crop&q=80",
        ),
        (
            "Karité & Nature",
            "Coffret Douceur Bébé Coton Bio",
            9500,
            "Bébé",
            "Ensemble complet hypoallergénique en coton doux avec lotion naturelle au karité pour nouveau-né.",
            "https://images.unsplash.com/photo-1515488042361-ee00e0ddd4e4?w=800&auto=format&fit=crop&q=80",
        ),
    ]

    added = 0
    for shop_name, title, price, cat, desc, photo in demo_articles:
        shop = shop_map[shop_name]
        exists = session.exec(select(Article).where(Article.name == title, Article.shop_id == shop.id)).first()
        if not exists:
            art = Article(
                shop_id=shop.id,
                name=title,
                price=price,
                category=cat,
                description=desc,
                photo_url=photo,
                photos_json=json.dumps([photo]),
                negotiable=False,
                color="#2C64E8",
            )
            session.add(art)
            added += 1

    session.commit()
    return {"status": "ok", "added_articles": added}


@router.post("/reset-all")
def admin_reset_all(session: Session = Depends(get_session)):
    """
    Vide intégralement toutes les tables de la base de données (articles, boutiques, commandes, clients).
    """
    for model in (OrderItem, Order, Article, Shop, Customer, PasswordResetCode, EmailVerificationCode):
        rows = session.exec(select(model)).all()
        for r in rows:
            session.delete(r)
    session.commit()
    return {"status": "ok", "message": "Toutes les données ont été effacées."}

