import time
from typing import Literal, Optional

from sqlmodel import Field, SQLModel


def now_ms() -> int:
    return int(time.time() * 1000)


# ---------- Tables de la base de données ----------

class Shop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str = Field(index=True)
    lat: float
    lng: float
    is_open: bool = True
    owner_name: Optional[str] = None
    address: Optional[str] = None


class Customer(SQLModel, table=True):
    __tablename__ = "customers"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str = Field(index=True, unique=True)
    address: str
    created_at: int = Field(default_factory=now_ms)


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
    customer_id: Optional[int] = Field(default=None, foreign_key="customers.id", index=True)
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_address: Optional[str] = None
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
    owner_name: Optional[str] = None
    address: Optional[str] = None


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
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_address: Optional[str] = None


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
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_address: Optional[str] = None
    created_at: int
    items: list[OrderItemOut]


class StatusUpdate(SQLModel):
    status: Literal["accepted", "refused"]


class CustomerOut(SQLModel):
    id: int
    name: str
    phone: str
    address: str
    created_at: int


class CustomerCreate(SQLModel):
    name: str
    phone: str
    address: str


class CustomerLogin(SQLModel):
    phone: str


class MerchantRegister(SQLModel):
    owner_name: str
    shop_name: str
    phone: str
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class MerchantLogin(SQLModel):
    phone: str
