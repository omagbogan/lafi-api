from fastapi import APIRouter, Depends, HTTPException
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
)

router = APIRouter()


def build_out(session: Session, order: Order) -> OrderOut:
    shop = session.get(Shop, order.shop_id)
    lines = session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    return OrderOut(
        id=order.id,
        shop_id=order.shop_id,
        shop=shop.name,
        mode=order.mode,
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        total=order.total,
        status=order.status,
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

    order = Order(shop_id=shop.id, mode=data.mode, subtotal=subtotal, delivery_fee=fee, total=subtotal + fee)
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


@router.get("/shops/me/orders", response_model=list[OrderOut])
def my_orders(session: Session = Depends(get_session)):
    orders = session.exec(
        select(Order).where(Order.shop_id == MY_SHOP_ID).order_by(col(Order.created_at).desc())
    ).all()
    return [build_out(session, order) for order in orders]


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
def set_status(order_id: int, data: StatusUpdate, session: Session = Depends(get_session)):
    order = session.get(Order, order_id)
    if order is None or order.shop_id != MY_SHOP_ID:
        raise HTTPException(404, "Commande introuvable")
    if order.status != "pending":
        raise HTTPException(409, "Cette commande a déjà été traitée")
    order.status = data.status
    session.add(order)
    session.commit()
    session.refresh(order)
    return build_out(session, order)