from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlmodel import Session, col, select

from ..config import CATEGORIES, MY_SHOP_ID
from ..db import get_session
from ..geo import DEFAULT_LAT, DEFAULT_LNG, distance_m
from ..models import (
    Article,
    ArticleCreate,
    ArticleOut,
    ArticleUpdate,
    Shop,
    ShopOut,
    ShopUpdate,
)

router = APIRouter()


def to_out(article: Article, shop: Shop, lat: float, lng: float) -> ArticleOut:
    return ArticleOut(
        id=article.id,
        name=article.name,
        price=article.price,
        category=article.category,
        negotiable=article.negotiable,
        hidden=article.hidden,
        out_of_stock=article.out_of_stock,
        color=article.color,
        photo_url=article.photo_url,
        shop_id=shop.id,
        shop=shop.name,
        shop_phone=shop.phone,
        open=shop.is_open,
        distance_m=distance_m(lat, lng, shop.lat, shop.lng),
    )


def check_category(category: Optional[str]) -> None:
    if category is not None and category not in CATEGORIES:
        raise HTTPException(422, f"Catégorie inconnue. Choix possibles : {', '.join(CATEGORIES)}")


# ---------- Côté client ----------

@router.get("/articles", response_model=list[ArticleOut])
def list_articles(
    lat: float = DEFAULT_LAT,
    lng: float = DEFAULT_LNG,
    category: Optional[str] = None,
    q: Optional[str] = None,
    radius_m: Optional[int] = None,
    session: Session = Depends(get_session),
):
    """Articles visibles par un client : boutique ouverte, article ni masqué ni en rupture."""
    statement = (
        select(Article, Shop)
        .where(Article.shop_id == Shop.id)
        .where(col(Shop.is_open).is_(True))
        .where(col(Article.hidden).is_(False))
        .where(col(Article.out_of_stock).is_(False))
    )
    if category and category != "Tout":
        statement = statement.where(Article.category == category)

    items = [to_out(a, s, lat, lng) for a, s in session.exec(statement).all()]

    if q and q.strip():
        needle = q.strip().lower()
        items = [i for i in items if needle in i.name.lower()]
    if radius_m is not None:
        items = [i for i in items if i.distance_m <= radius_m]

    return sorted(items, key=lambda i: i.distance_m)


@router.get("/articles/{article_id}", response_model=ArticleOut)
def get_article(
    article_id: int,
    lat: float = DEFAULT_LAT,
    lng: float = DEFAULT_LNG,
    session: Session = Depends(get_session),
):
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(404, "Article introuvable")
    return to_out(article, session.get(Shop, article.shop_id), lat, lng)


# ---------- Côté commerçant ----------

@router.get("/shops/me", response_model=ShopOut)
def my_shop(
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    shop = session.get(Shop, target_shop_id)
    if shop is None:
        raise HTTPException(404, "Boutique introuvable")
    return shop


@router.patch("/shops/me", response_model=ShopOut)
def update_my_shop(
    data: ShopUpdate,
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    shop = session.get(Shop, target_shop_id)
    if shop is None:
        raise HTTPException(404, "Boutique introuvable")
    shop.is_open = data.is_open
    session.add(shop)
    session.commit()
    session.refresh(shop)
    return shop


@router.get("/shops/me/articles", response_model=list[ArticleOut])
def my_articles(
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    shop = session.get(Shop, target_shop_id)
    if shop is None:
        raise HTTPException(404, "Boutique introuvable")
    articles = session.exec(
        select(Article).where(Article.shop_id == target_shop_id).order_by(col(Article.created_at).desc())
    ).all()
    return [to_out(a, shop, DEFAULT_LAT, DEFAULT_LNG) for a in articles]


@router.post("/articles", response_model=ArticleOut, status_code=201)
def create_article(
    data: ArticleCreate,
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    shop = session.get(Shop, target_shop_id)
    if shop is None:
        raise HTTPException(404, "Boutique introuvable")
    check_category(data.category)
    article = Article(shop_id=target_shop_id, **data.model_dump())
    session.add(article)
    session.commit()
    session.refresh(article)
    return to_out(article, shop, DEFAULT_LAT, DEFAULT_LNG)


@router.patch("/articles/{article_id}", response_model=ArticleOut)
def update_article(
    article_id: int,
    data: ArticleUpdate,
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    article = session.get(Article, article_id)
    if article is None or article.shop_id != target_shop_id:
        raise HTTPException(404, "Article introuvable")
    check_category(data.category)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(article, key, value)
    session.add(article)
    session.commit()
    session.refresh(article)
    return to_out(article, session.get(Shop, target_shop_id), DEFAULT_LAT, DEFAULT_LNG)