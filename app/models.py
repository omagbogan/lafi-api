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
    email: Optional[str] = Field(default=None, index=True)
    password_hash: Optional[str] = None


class Customer(SQLModel, table=True):
    __tablename__ = "customers"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str = Field(index=True, unique=True)
    address: str
    email: Optional[str] = Field(default=None, index=True)
    password_hash: Optional[str] = None
    created_at: int = Field(default_factory=now_ms)


class PasswordResetCode(SQLModel, table=True):
    __tablename__ = "password_reset_codes"
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    code: str = Field(index=True)
    user_type: str = "customer"  # "customer" | "merchant"
    expires_at: int
    used: bool = False
    created_at: int = Field(default_factory=now_ms)


class EmailVerificationCode(SQLModel, table=True):
    __tablename__ = "email_verification_codes"
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    code: str = Field(index=True)
    expires_at: int
    used: bool = False
    created_at: int = Field(default_factory=now_ms)


class Article(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    shop_id: int = Field(foreign_key="shop.id", index=True)
    name: str
    price: int
    category: str = Field(index=True)
    description: Optional[str] = None
    negotiable: bool = False
    hidden: bool = False
    out_of_stock: bool = False
    color: str = "#B9854A"
    photo_url: Optional[str] = None
    photos_json: Optional[str] = None
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
    pickup_code: Optional[str] = None
    customer_lat: Optional[float] = None
    customer_lng: Optional[float] = None
    driver_dispatched: bool = Field(default=False)
    package_handed_over: bool = Field(default=False)
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
    email: Optional[str] = None
    lat: float
    lng: float


class ShopUpdate(SQLModel):
    is_open: Optional[bool] = None
    name: Optional[str] = None
    owner_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class ArticleCreate(SQLModel):
    name: str = Field(min_length=1, max_length=120)
    price: int = Field(gt=0)
    category: str
    description: Optional[str] = None
    negotiable: bool = False
    color: str = "#B9854A"
    photo_url: Optional[str] = None
    photos: Optional[list[str]] = None


class ArticleUpdate(SQLModel):
    name: Optional[str] = None
    price: Optional[int] = Field(default=None, gt=0)
    category: Optional[str] = None
    description: Optional[str] = None
    negotiable: Optional[bool] = None
    hidden: Optional[bool] = None
    out_of_stock: Optional[bool] = None
    photo_url: Optional[str] = None
    photos: Optional[list[str]] = None


class ArticleOut(SQLModel):
    id: int
    name: str
    price: int
    category: str
    description: Optional[str] = None
    negotiable: bool
    hidden: bool
    out_of_stock: bool
    color: str
    photo_url: Optional[str]
    photos: list[str] = Field(default_factory=list)
    shop_id: int
    shop: str
    shop_phone: str
    open: bool
    distance_m: int
    shop_lat: Optional[float] = None
    shop_lng: Optional[float] = None


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
    customer_lat: Optional[float] = None
    customer_lng: Optional[float] = None


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
    pickup_code: Optional[str] = None
    customer_lat: Optional[float] = None
    customer_lng: Optional[float] = None
    driver_dispatched: bool = False
    package_handed_over: bool = False
    shop_lat: Optional[float] = None
    shop_lng: Optional[float] = None
    shop_address: Optional[str] = None
    shop_phone: Optional[str] = None
    created_at: int
    items: list[OrderItemOut]


class StatusUpdate(SQLModel):
    status: Literal["accepted", "refused", "completed", "cancelled"]


class ValidatePickup(SQLModel):
    code: str


class CustomerOut(SQLModel):
    id: int
    name: str
    phone: str
    address: str
    email: Optional[str] = None
    created_at: int


class CustomerCreate(SQLModel):
    name: str
    phone: str
    address: str
    email: Optional[str] = None
    password: Optional[str] = None


class CustomerUpdate(SQLModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class CustomerLogin(SQLModel):
    email: Optional[str] = None
    password: Optional[str] = None
    phone: Optional[str] = None


class MerchantRegister(SQLModel):
    owner_name: str
    shop_name: str
    phone: str
    address: str
    email: Optional[str] = None
    password: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class MerchantLogin(SQLModel):
    email: Optional[str] = None
    password: Optional[str] = None
    phone: Optional[str] = None


class ForgotPasswordRequest(SQLModel):
    email: str
    user_type: Literal["customer", "merchant"] = "customer"


class ResetPasswordRequest(SQLModel):
    email: str
    code: str
    new_password: str
    user_type: Literal["customer", "merchant"] = "customer"


class OtpSend(SQLModel):
    phone: str


class OtpVerify(SQLModel):
    phone: str
    code: str


class SendEmailCodeRequest(SQLModel):
    email: str
    name: Optional[str] = "Nouvel Utilisateur"


class VerifyEmailCodeRequest(SQLModel):
    email: str
    code: str

