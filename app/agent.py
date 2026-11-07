"""
lafi-api/app/agent.py
---------------------
Agent IA conversationnel pour Lafi (Bloc 4 de la soutenance).

Capacités :
  - Comprend le besoin formulé en langage naturel (français / expressions locales).
  - Extrait les contraintes (budget maximum en FCFA, type de produit, catégorie).
  - Interroge le catalogue en temps réel dans SQLite (uniquement les boutiques ouvertes).
  - Reste 100 % opérationnel en local sans dépendance externe obligatoire.
"""

import re
from typing import Optional
from sqlmodel import Session, select

from .geo import DEFAULT_LAT, DEFAULT_LNG, distance_m
from .models import Article, ArticleOut, Shop

CATEGORY_KEYWORDS = {
    "Alimentation": [
        "manger", "faim", "plat", "nourriture", "repas", "dejeuner", "déjeuner",
        "dîner", "diner", "garba", "attieke", "attiéké", "poisson", "riz", "poulet",
        "sauce", "alloco", "boisson", "jus", "huile", "eau", "viande", "pain", "pain",
    ],
    "Mode": [
        "habit", "vetement", "vêtement", "robe", "pantalon", "chemise", "sac",
        "chaussure", "sandale", "wax", "pagne", "costume", "tissu", "talon", "boucle",
    ],
    "Beauté": [
        "beauté", "beaute", "savon", "creme", "crème", "pommade", "parfum", "mèche",
        "meche", "cheveux", "maquillage", "karité", "karite", "lotion", "soin",
    ],
    "Électronique": [
        "telephone", "téléphone", "portable", "smartphone", "chargeur", "cable",
        "câble", "ecouteur", "écouteur", "airpod", "casque", "audio", "tv", "radio",
        "pile", "batterie", "power bank",
    ],
    "Maison": [
        "maison", "cuisine", "casserole", "assiette", "poele", "poêle", "ventilateur",
        "mixeur", "drap", "matelas", "rideau", "fer", "seau", "balai", "ampoule",
    ],
    "Bébé": [
        "bébé", "bebe", "enfant", "couche", "couches", "biberon", "pampers",
        "lingette", "tetine", "tétine", "poussette", "lait", "nourrisson",
    ],
}


def extract_budget(text: str) -> Optional[int]:
    """Extrait un montant en FCFA de la phrase (ex. 'moins de 3000 F', 'budget 5000')."""
    # Ex: 'à moins de 5 000 FCFA', '3000 f', 'budget 15000'
    patterns = [
        r"(?:moins\s+de|budget\s+de|maximum|max|pour|avec)\s+(\d[\d\s.]*)\s*(?:f\b|fcfa|francs?)?",
        r"(\d[\d\s.]*)\s*(?:f\b|fcfa|francs?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            raw = re.sub(r"[\s.]", "", match.group(1))
            try:
                val = int(raw)
                if val > 50:  # filtre les petits chiffres accidentels
                    return val
            except ValueError:
                continue
    return None


def detect_categories(text: str) -> list[str]:
    """Détecte les catégories mentionnées ou sous-entendues."""
    text_lower = text.lower()
    matched = []
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in text_lower for w in words):
            matched.append(cat)
    return matched


def run_agent(
    message: str,
    session: Session,
    lat: float = DEFAULT_LAT,
    lng: float = DEFAULT_LNG,
) -> dict:
    """Exécute l'agent conversationnel et retourne la réponse avec les articles recommandés."""
    cleaned = message.strip()
    lower = cleaned.lower()

    budget = extract_budget(cleaned)
    target_categories = detect_categories(cleaned)

    # Récupérer les articles des boutiques actuellement ouvertes
    statement = (
        select(Article, Shop)
        .where(Article.shop_id == Shop.id)
        .where(Shop.is_open == True)  # noqa: E712
        .where(Article.hidden == False)  # noqa: E712
        .where(Article.out_of_stock == False)  # noqa: E712
    )
    results = session.exec(statement).all()

    # Découpage du message en mots-clés de recherche
    search_tokens = [w for w in re.findall(r"\w+", lower) if len(w) >= 3]

    scored_articles = []
    for article, shop in results:
        art_name_lower = article.name.lower()
        score = 0

        # Filtre de budget strict si précisé
        if budget is not None and article.price > budget:
            continue

        # Bonus si dans la catégorie détectée
        if target_categories and article.category in target_categories:
            score += 10

        # Bonus par mot-clé présent dans le nom de l'article
        for token in search_tokens:
            if token in art_name_lower:
                score += 5

        # Distance en mètres
        dist = distance_m(lat, lng, shop.lat, shop.lng)

        # Si le score est > 0 ou si aucun critère spécifique n'était demandé
        if score > 0 or (not target_categories and budget is not None):
            scored_articles.append((score, dist, article, shop))

    # Trier par score décroissant, puis par proximité croissante
    scored_articles.sort(key=lambda item: (-item[0], item[1]))

    # Garder les 4 meilleurs articles
    top = scored_articles[:4]
    recommended = [
        ArticleOut(
            id=art.id,
            name=art.name,
            price=art.price,
            category=art.category,
            negotiable=art.negotiable,
            hidden=art.hidden,
            out_of_stock=art.out_of_stock,
            color=art.color,
            photo_url=art.photo_url,
            shop_id=shop.id,
            shop=shop.name,
            shop_phone=shop.phone,
            open=shop.is_open,
            distance_m=dist,
        )
        for _, dist, art, shop in top
    ]

    # Construction de la réponse en langage naturel bienveillant
    is_greeting = any(g in lower for g in ["bonjour", "salut", "bonsoir", "coucou", "kôkô", "hello"])

    if len(recommended) > 0:
        greeting_prefix = "Bonjour ! " if is_greeting else ""
        if budget is not None:
            reply = (
                f"{greeting_prefix}J'ai trouvé {len(recommended)} article(s) dans votre budget "
                f"({budget:,} FCFA max) chez nos commerçants ouverts à proximité :".replace(",", " ")
            )
        elif target_categories:
            cat_str = " et ".join(target_categories)
            reply = (
                f"{greeting_prefix}Voici ce qui est actuellement disponible en {cat_str} "
                f"près de vous à Cocody :"
            )
        else:
            reply = f"{greeting_prefix}Voici les articles qui correspondent le mieux à votre demande :"
        intent = "product_recommendation"
    else:
        if is_greeting and len(cleaned) < 15:
            reply = (
                "Bonjour ! Je suis l'assistant intelligent de Lafi. Dites-moi ce que vous cherchez "
                "(un plat, un habit, des écouteurs...) ou votre budget, et je vous montre ce qui est "
                "disponible près de vous !"
            )
            intent = "greeting"
        elif budget is not None:
            reply = (
                f"Je n'ai pas trouvé d'article à moins de {budget:,} FCFA correspondant à cette demande "
                f"actuellement en boutique ouverte. Vous pouvez essayer d'augmenter légèrement le budget ou "
                f"consulter les autres commerces sur la carte !"
            ).replace(",", " ")
            intent = "no_results_budget"
        else:
            reply = (
                f"Je n'ai pas trouvé d'article correspondant exactement à « {cleaned} » parmi les boutiques "
                f"ouvertes en ce moment. Vous pouvez jeter un œil à la carte ou faire une recherche par photo !"
            )
            intent = "no_results"

    return {
        "reply": reply,
        "recommended_articles": recommended,
        "intent": intent,
    }

