import time
from typing import Literal, Optional

from sqlmodel import Field, SQLModel


def now_ms() -> int:
    return int(time.time() * 1000)


# ---------- Tables de la base de données ----------

class Shop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str
    lat: float
    lng: float
    is_open: bool = True


class Article(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    shop_id: int = Field(foreign_key="shop.id", index=True)
    name: str
    price: int
    category: str = Field(index=True)
    negotiable: bool = False
    hidden: bool = False
    out_of_stock: bool = False
    color: str = "#B9854A"
    photo_url: Optional[str] = None
    created_at: int = Field(default_factory=now_ms)


class Order(SQLModel, table=True):
    __tablename__ = "orders"
    id: Optional[int] = Field(default=None, primary_key=True)
    shop_id: int = Field(foreign_key="shop.id", index=True)
    mode: str
    subtotal: int
    delivery_fee: int
    total: int
    status: str = "pending"
    created_at: int = Field(default_factory=now_ms)


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="orders.id", index=True)
    article_id: int
    name: str
    price: int
    qty: int


# ---------- Formes des données échangées avec l'application ----------

class ShopOut(SQLModel):
    id: int
    name: str
    phone: str
    is_open: bool


class ShopUpdate(SQLModel):
    is_open: bool


class ArticleCreate(SQLModel):
    name: str = Field(min_length=1, max_length=120)
    price: int = Field(gt=0)
    category: str
    negotiable: bool = False
    color: str = "#B9854A"
    photo_url: Optional[str] = None


class ArticleUpdate(SQLModel):
    name: Optional[str] = None
    price: Optional[int] = Field(default=None, gt=0)
    category: Optional[str] = None
    negotiable: Optional[bool] = None
    hidden: Optional[bool] = None
    out_of_stock: Optional[bool] = None
    photo_url: Optional[str] = None


class ArticleOut(SQLModel):
    id: int
    name: str
    price: int
    category: str
    negotiable: bool
    hidden: bool
    out_of_stock: bool
    color: str
    photo_url: Optional[str]
    shop_id: int
    shop: str
    shop_phone: str
    open: bool
    distance_m: int


class OrderItemIn(SQLModel):
    article_id: int
    qty: int = Field(gt=0, le=99)


class OrderCreate(SQLModel):
    mode: Literal["pickup", "yango"]
    items: list[OrderItemIn] = Field(min_length=1)


class OrderItemOut(SQLModel):
    article_id: int
    name: str
    price: int
    qty: int


class OrderOut(SQLModel):
    id: int
    shop_id: int
    shop: str
    mode: str
    subtotal: int
    delivery_fee: int
    total: int
    status: str
    created_at: int
    items: list[OrderItemOut]


class StatusUpdate(SQLModel):
    status: Literal["accepted", "refused"]