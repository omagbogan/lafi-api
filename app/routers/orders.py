"""
lafi-api/app/routers/orders.py
------------------------------
Gestion des commandes côté API REST FastAPI (Bloc 3 - Application & Bloc 5 - Intégration).

Règles de sécurité et fonctionnalités clés :
  1. Recalcul serveur garanti : les prix soumis par le client sont TOUJOURS ignorés et recalculés
     directement depuis la table Article en base de données pour empêcher toute fraude ou altération de prix.
  2. Code secret de retrait (OTP 4 chiffres) : généré automatiquement à la commande pour sécuriser
     la remise en main propre en boutique (validate_pickup_code).
  3. Découplage de la livraison Yango : DELIVERY_FEE = 0 (course réglée directement au livreur).
  4. Suivi par rôle : filtrage par boutique (/shops/me/orders) et par client (/customers/{customer_id}/orders).
"""

import random
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlmodel import Session, col, select

from ..config import DELIVERY_FEE, MY_SHOP_ID
from ..db import get_session
from ..models import (
    Article,
    Order,
    OrderCreate,
    OrderItem,
    OrderItemOut,
    OrderOut,
    Shop,
    StatusUpdate,
    ValidatePickup,
)

router = APIRouter()


def build_out(session: Session, order: Order) -> OrderOut:
    shop = session.get(Shop, order.shop_id)
    lines = session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    return OrderOut(
        id=order.id,
        shop_id=order.shop_id,
        shop=shop.name if shop else "Boutique",
        mode=order.mode,
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        total=order.total,
        status=order.status,
        customer_id=order.customer_id,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        customer_address=order.customer_address,
        pickup_code=order.pickup_code,
        customer_lat=order.customer_lat,
        customer_lng=order.customer_lng,
        driver_dispatched=bool(order.driver_dispatched),
        package_handed_over=bool(order.package_handed_over),
        shop_lat=shop.lat if shop else None,
        shop_lng=shop.lng if shop else None,
        shop_address=shop.address if shop else None,
        shop_phone=shop.phone if shop else None,
        created_at=order.created_at,
        items=[
            OrderItemOut(article_id=line.article_id, name=line.name, price=line.price, qty=line.qty)
            for line in lines
        ],
    )


@router.post("/orders", response_model=OrderOut, status_code=201)
def create_order(data: OrderCreate, session: Session = Depends(get_session)):
    lines: list[tuple[Article, int]] = []
    shop_ids: set[int] = set()

    for item in data.items:
        article = session.get(Article, item.article_id)
        if article is None:
            raise HTTPException(404, f"Article {item.article_id} introuvable")
        if article.hidden or article.out_of_stock:
            raise HTTPException(409, f"« {article.name} » n'est plus disponible")
        shop_ids.add(article.shop_id)
        lines.append((article, item.qty))

    if len(shop_ids) != 1:
        raise HTTPException(400, "Une commande ne concerne qu'un seul commerçant")

    shop = session.get(Shop, shop_ids.pop())
    if shop is None or not shop.is_open:
        raise HTTPException(409, "Cette boutique est fermée pour le moment")

    # Les prix viennent TOUJOURS de la base, jamais de l'application
    subtotal = sum(article.price * qty for article, qty in lines)
    fee = DELIVERY_FEE if data.mode == "yango" else 0

    pickup_code = f"{random.randint(1000, 9999)}" if data.mode == "pickup" else None

    order = Order(
        shop_id=shop.id,
        mode=data.mode,
        subtotal=subtotal,
        delivery_fee=fee,
        total=subtotal + fee,
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        customer_address=data.customer_address,
        pickup_code=pickup_code,
        customer_lat=data.customer_lat,
        customer_lng=data.customer_lng,
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    for article, qty in lines:
        session.add(
            OrderItem(order_id=order.id, article_id=article.id, name=article.name, price=article.price, qty=qty)
        )
    session.commit()
    return build_out(session, order)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Commande introuvable")
    return build_out(session, order)


@router.get("/customers/{customer_id}/orders", response_model=list[OrderOut])
def customer_orders(customer_id: int, session: Session = Depends(get_session)):
    orders = session.exec(
        select(Order).where(Order.customer_id == customer_id).order_by(col(Order.created_at).desc())
    ).all()
    return [build_out(session, order) for order in orders]


@router.get("/shops/me/orders", response_model=list[OrderOut])
def my_orders(
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    orders = session.exec(
        select(Order).where(Order.shop_id == target_shop_id).order_by(col(Order.created_at).desc())
    ).all()
    return [build_out(session, order) for order in orders]


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
def set_status(
    order_id: int,
    data: StatusUpdate,
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    order = session.get(Order, order_id)
    if order is None or order.shop_id != target_shop_id:
        raise HTTPException(404, "Commande introuvable")
    if data.status in ("accepted", "refused") and order.status != "pending":
        raise HTTPException(409, "Cette commande a déjà été traitée")
    if data.status == "completed" and order.status != "accepted":
        raise HTTPException(409, "Seule une commande acceptée peut être marquée comme terminée")
    if data.status == "cancelled":
        if order.status == "completed":
            raise HTTPException(409, "Une commande terminée ne peut plus être annulée")
        if order.status in ("refused", "cancelled"):
            raise HTTPException(409, "Cette commande est déjà clôturée")
        if order.package_handed_over:
            raise HTTPException(409, "Le colis a déjà été remis au livreur, annulation impossible")
    order.status = data.status
    session.add(order)
    session.commit()
    session.refresh(order)
    return build_out(session, order)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Commande introuvable")
    if order.status == "completed":
        raise HTTPException(409, "Une commande terminée ne peut plus être annulée")
    if order.status in ("refused", "cancelled"):
        raise HTTPException(409, "Cette commande est déjà clôturée")
    if order.package_handed_over:
        raise HTTPException(409, "Le colis a déjà été remis au livreur, annulation impossible")
    if order.status not in ("pending", "accepted"):
        raise HTTPException(409, "Cette commande ne peut pas être annulée")

    order.status = "cancelled"
    session.add(order)
    session.commit()
    session.refresh(order)
    return build_out(session, order)


@router.post("/orders/{order_id}/validate-pickup", response_model=OrderOut)
def validate_pickup(
    order_id: int,
    data: ValidatePickup,
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    order = session.get(Order, order_id)
    if order is None or order.shop_id != target_shop_id:
        raise HTTPException(404, "Commande introuvable")
    if order.status != "accepted":
        raise HTTPException(409, "La commande doit être acceptée avant le retrait")
    if order.mode != "pickup":
        raise HTTPException(400, "Cette commande n'est pas en retrait boutique")
    if not order.pickup_code or order.pickup_code.strip() != data.code.strip():
        raise HTTPException(400, "Code de retrait incorrect")

    order.status = "completed"
    session.add(order)
    session.commit()
    session.refresh(order)
    return build_out(session, order)


@router.post("/orders/{order_id}/dispatch-driver", response_model=OrderOut)
def dispatch_driver(order_id: int, session: Session = Depends(get_session)):
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Commande introuvable")
    if order.mode != "yango":
        raise HTTPException(400, "Cette commande n'est pas en livraison Yango")
    if order.status != "accepted":
        raise HTTPException(409, "La commande doit être acceptée avant de notifier l'envoi du livreur")

    order.driver_dispatched = True
    session.add(order)
    session.commit()
    session.refresh(order)
    return build_out(session, order)


@router.post("/orders/{order_id}/handover-package", response_model=OrderOut)
def handover_package(
    order_id: int,
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    order = session.get(Order, order_id)
    if order is None or order.shop_id != target_shop_id:
        raise HTTPException(404, "Commande introuvable")
    if order.mode != "yango":
        raise HTTPException(400, "Cette commande n'est pas en livraison Yango")
    if order.status != "accepted":
        raise HTTPException(409, "La commande doit être acceptée avant de remettre le colis")
    if not order.driver_dispatched:
        raise HTTPException(409, "Le client doit d'abord notifier l'envoi du livreur")

    order.package_handed_over = True
    session.add(order)
    session.commit()
    session.refresh(order)
    return build_out(session, order)

