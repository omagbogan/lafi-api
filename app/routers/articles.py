"""
lafi-api/app/routers/articles.py
--------------------------------
Catalogue articles et gestion des boutiques commerçantes (Bloc 3 - Application).

Fonctionnalités clés :
  1. Proximité géographique (Haversine) : calcul automatique de la distance en mètres entre
     la position GPS du client et chaque boutique, avec tri par proximité immédiate.
  2. Filtrage métier des articles visibles : seuls les articles des boutiques ouvertes (is_open=True),
     non masqués (hidden=False) et en stock (out_of_stock=False) sont présentés aux clients.
  3. Gestion boutique commerçant : consultation, ouverture/fermeture et mise à jour complète de l'identité
     et des coordonnées GPS de la boutique (/shops/me).
"""

import json
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
    photos_list: list[str] = []
    if article.photos_json:
        try:
            parsed = json.loads(article.photos_json)
            if isinstance(parsed, list):
                photos_list = [str(p) for p in parsed]
        except Exception:
            pass
    if not photos_list and article.photo_url:
        photos_list = [article.photo_url]

    return ArticleOut(
        id=article.id,
        name=article.name,
        price=article.price,
        category=article.category,
        description=article.description,
        negotiable=article.negotiable,
        hidden=article.hidden,
        out_of_stock=article.out_of_stock,
        color=article.color,
        photo_url=article.photo_url or (photos_list[0] if photos_list else None),
        photos=photos_list,
        shop_id=shop.id,
        shop=shop.name,
        shop_phone=shop.phone,
        open=shop.is_open,
        distance_m=distance_m(lat, lng, shop.lat, shop.lng),
        shop_lat=shop.lat,
        shop_lng=shop.lng,
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


@router.get("/shops", response_model=list[ShopOut])
def list_shops(session: Session = Depends(get_session)):
    """Retourne toutes les boutiques partenaires avec leurs coordonnées GPS."""
    shops = session.exec(select(Shop)).all()
    return shops


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

    update_dict = data.model_dump(exclude_unset=True)
    if "phone" in update_dict and update_dict["phone"]:
        import re

        cleaned_phone = re.sub(r"[^\d+]", "", update_dict["phone"].strip())
        if len(cleaned_phone) < 8:
            raise HTTPException(422, "Numéro de téléphone invalide (au moins 8 chiffres).")
        update_dict["phone"] = cleaned_phone

    for key, value in update_dict.items():
        if value is not None:
            if isinstance(value, str):
                value = value.strip()
            setattr(shop, key, value)

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
        return []
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
    article_dict = data.model_dump(exclude={"photos"})
    if data.photos:
        article_dict["photos_json"] = json.dumps(data.photos)
        if not article_dict.get("photo_url"):
            article_dict["photo_url"] = data.photos[0]
    elif article_dict.get("photo_url"):
        article_dict["photos_json"] = json.dumps([article_dict["photo_url"]])

    article = Article(shop_id=target_shop_id, **article_dict)
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
    update_dict = data.model_dump(exclude_unset=True)
    if "photos" in update_dict:
        photos = update_dict.pop("photos")
        if photos is not None:
            update_dict["photos_json"] = json.dumps(photos)
            if not update_dict.get("photo_url") and photos:
                update_dict["photo_url"] = photos[0]

    for key, value in update_dict.items():
        setattr(article, key, value)
    session.add(article)
    session.commit()
    session.refresh(article)
    return to_out(article, session.get(Shop, target_shop_id), DEFAULT_LAT, DEFAULT_LNG)


@router.delete("/articles/{article_id}")
def delete_article(
    article_id: int,
    x_shop_id: Optional[int] = Header(default=None),
    session: Session = Depends(get_session),
):
    target_shop_id = x_shop_id or MY_SHOP_ID
    article = session.get(Article, article_id)
    if article is None or article.shop_id != target_shop_id:
        raise HTTPException(404, "Article introuvable")
    session.delete(article)
    session.commit()
    return {"ok": True, "deleted_id": article_id}
