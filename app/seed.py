from sqlmodel import Session, select

from .geo import DEFAULT_LAT, DEFAULT_LNG
from .models import Article, Shop


def seed(session: Session) -> None:
    """Remplit la base avec les données de démonstration, une seule fois."""
    if session.exec(select(Shop)).first():
        return

    shops = [
        Shop(name="Chez Aïcha", phone="2250700000001", lat=DEFAULT_LAT + 0.0031, lng=DEFAULT_LNG),
        Shop(name="Maman Awa", phone="2250700000002", lat=DEFAULT_LAT + 0.0054, lng=DEFAULT_LNG),
        Shop(name="Beauté Naturelle", phone="2250700000003", lat=DEFAULT_LAT, lng=DEFAULT_LNG + 0.0072),
        Shop(name="Tech Plateau", phone="2250700000004", lat=DEFAULT_LAT - 0.0085, lng=DEFAULT_LNG),
        Shop(name="Boutique Karim", phone="2250700000005", lat=DEFAULT_LAT, lng=DEFAULT_LNG - 0.0127),
    ]
    session.add_all(shops)
    session.commit()
    ids = {shop.name: shop.id for shop in shops}

    rows = [
        ("Chez Aïcha", "Sac à main en cuir", 15000, "Mode", "#B9854A"),
        ("Maman Awa", "Attiéké poisson", 2500, "Alimentation", "#E0A93B"),
        ("Beauté Naturelle", "Beurre de karité", 3000, "Beauté", "#C9B28A"),
        ("Tech Plateau", "Écouteurs sans fil", 9500, "Électronique", "#4A4A4A"),
        ("Chez Aïcha", "Robe wax", 12500, "Mode", "#D9663F"),
        ("Boutique Karim", "Sandales en cuir", 8000, "Mode", "#7A5C3E"),
    ]
    for shop_name, name, price, category, color in rows:
        session.add(
            Article(shop_id=ids[shop_name], name=name, price=price, category=category, color=color)
        )
    session.commit()