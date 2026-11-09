"""
lafi-api/app/agent.py
---------------------
Agent IA conversationnel pour Lafi (Bloc 4 de la soutenance).

Architecture Hybride :
  1. Couche Cloud (OpenRouter LLM) : Compréhension sémantique profonde du langage naturel,
     des contextes ivoiriens/nouchi, et sélection intelligente dans le catalogue SQLite.
  2. Couche Locale (Edge / Offline) : Moteur déterministe à règles & expressions régulières
     qui garantit un fonctionnement immédiat et infaillible sans connexion internet.
"""

import json
import logging
import re
import urllib.request
from typing import Optional
from sqlmodel import Session, select

from .config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from .geo import DEFAULT_LAT, DEFAULT_LNG, distance_m
from .models import Article, ArticleOut, Shop

logger = logging.getLogger("lafi.agent")

CATEGORY_KEYWORDS = {
    "Alimentation": [
        "manger", "faim", "plat", "nourriture", "repas", "dejeuner", "déjeuner",
        "dîner", "diner", "garba", "attieke", "attiéké", "poisson", "riz", "poulet",
        "sauce", "alloco", "boisson", "jus", "huile", "eau", "viande", "pain",
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


STOP_WORDS = {
    "je", "tu", "il", "elle", "nous", "vous", "ils", "veux", "voudrais", "cherche", "aimerais",
    "trouve", "trouver", "donne", "moi", "un", "une", "des", "du", "de", "la", "le", "les",
    "pour", "avec", "sans", "est", "sont", "dans", "chez", "sur", "par", "beau", "belle",
    "joli", "jolie", "bon", "bonne", "pas", "cher", "chers", "chere", "cheres", "bonjour",
    "salut", "svp", "stp", "merci", "articles", "article", "produit", "produits", "besoin",
}


def filter_precise_recommendations(message: str, recommended: list[ArticleOut]) -> list[ArticleOut]:
    """Élimine les articles hors-sujet si le client a demandé un produit précis (ex: 'robe' ne doit pas renvoyer de sac)."""
    if not recommended:
        return recommended

    lower = message.lower()
    tokens = [w for w in re.findall(r"\w+", lower) if len(w) >= 3 and w not in STOP_WORDS]

    if not tokens:
        return recommended

    # Vérifier si certains articles contiennent directement l'un des mots-clés dans leur nom
    matching_articles = [
        art for art in recommended
        if any(tok in art.name.lower() for tok in tokens)
    ]

    # Si au moins un article correspond précisément au mot-clé demandé, on ne garde QUE ceux-là !
    if matching_articles:
        return matching_articles

    return recommended


def extract_budget(text: str) -> Optional[int]:
    """Extrait un montant en FCFA de la phrase (ex. 'moins de 3000 F', 'budget 5000')."""
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
                if val > 50:
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


def run_local_agent(
    message: str,
    articles_data: list[tuple[Article, Shop, int]],
) -> dict:
    """Moteur local déterministe (repli sans dépendance externe)."""
    cleaned = message.strip()
    lower = cleaned.lower()
    budget = extract_budget(cleaned)
    target_categories = detect_categories(cleaned)
    search_tokens = [w for w in re.findall(r"\w+", lower) if len(w) >= 3 and w not in STOP_WORDS]

    scored = []
    for article, shop, dist in articles_data:
        art_name_lower = article.name.lower()
        score = 0

        if budget is not None and article.price > budget:
            continue

        if target_categories and article.category in target_categories:
            score += 10

        for token in search_tokens:
            if token in art_name_lower:
                score += 20

        if score > 0 or (not target_categories and budget is not None):
            scored.append((score, dist, article, shop))

    # Si certains articles correspondent directement à un mot-clé du nom (score >= 20),
    # on élimine les articles qui n'avaient que le bonus de catégorie générale (+10)
    has_name_matches = any(item[0] >= 20 for item in scored)
    if has_name_matches:
        scored = [item for item in scored if item[0] >= 20]

    scored.sort(key=lambda item: (-item[0], item[1]))
    top = scored[:4]

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

    recommended = filter_precise_recommendations(message, recommended)

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
        "source": "agent-local",
    }


def query_openrouter(
    message: str,
    articles_data: list[tuple[Article, Shop, int]],
) -> Optional[dict]:
    """Interroge OpenRouter LLM pour comprendre la requête et sélectionner les articles."""
    if not OPENROUTER_API_KEY:
        return None

    # Préparer le catalogue compact des articles disponibles
    catalog_snapshot = [
        {
            "id": art.id,
            "nom": art.name,
            "prix_fcfa": art.price,
            "categorie": art.category,
            "boutique": shop.name,
            "distance_m": dist,
            "negociable": art.negotiable,
        }
        for art, shop, dist in articles_data
    ]

    system_prompt = (
        "Tu es l'assistant IA officiel de l'application mobile Lafi (commerce de proximité à Abidjan, Côte d'Ivoire). "
        "Ton rôle est d'orienter et conseiller les clients de façon chaleureuse, naturelle et bienveillante. "
        "Tu comprends parfaitement le français, le français parlé ivoirien, le nouchi et les budgets en FCFA.\n\n"
        "Voici le catalogue des articles actuellement disponibles chez les commerçants ouverts à proximité :\n"
        f"{json.dumps(catalog_snapshot, ensure_ascii=False)}\n\n"
        "Instructions :\n"
        "1. Sélectionne dans le catalogue UNIQUEMENT les articles qui correspondent précisément à la demande du client. "
        "ATTENTION À LA PERTINENCE : si le client demande un produit précis (ex: une 'robe', 'chaussure', 'chargeur', 'poisson', 'sac'), "
        "ne sélectionne QUE les articles de ce type précis ! Ne sélectionne JAMAIS d'articles hors sujet (ex: NE sélectionne PAS de sac pour une demande de robe). "
        "Si un seul article correspond, renvoie une liste avec cet unique identifiant. "
        "Si aucun article ne correspond exactement, renvoie une liste vide [].\n"
        "2. Rédige une réponse concise, polie et engageante (max 2 phrases) pour présenter ta sélection ou guider le client.\n"
        "3. Tu DOIS impérativement répondre au format JSON strict avec exactement deux clés :\n"
        "{\"reply\": \"...\", \"recommended_ids\": [\"...\"]}"
    )

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "max_tokens": 350,
    }

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://lafi.ci",
            "X-Title": "Lafi Mobile Assistant",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content_str = res_data["choices"][0]["message"]["content"]
            parsed = json.loads(content_str)

            reply = parsed.get("reply", "").strip()
            rec_ids = parsed.get("recommended_ids", [])

            # Récupérer les objets ArticleOut correspondant aux IDs (supporte int et str)
            articles_by_id = {}
            for art, shop, dist in articles_data:
                articles_by_id[art.id] = (art, shop, dist)
                articles_by_id[str(art.id)] = (art, shop, dist)

            recommended = []
            seen_ids = set()
            for rid in rec_ids:
                matched = None
                if rid in articles_by_id:
                    matched = articles_by_id[rid]
                else:
                    try:
                        digits = re.sub(r"\D", "", str(rid))
                        if digits and int(digits) in articles_by_id:
                            matched = articles_by_id[int(digits)]
                    except Exception:
                        pass

                if matched and matched[0].id not in seen_ids:
                    seen_ids.add(matched[0].id)
                    art, shop, dist = matched
                    recommended.append(
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
                    )

            # Si le LLM n'a pas inclus d'ID mais a formulé une réponse pour un produit,
            # on complète automatiquement avec la recherche de proximité pour toujours afficher les cartes
            if not recommended:
                local_fallback = run_local_agent(message, articles_data)
                recommended = local_fallback.get("recommended_articles", [])

            # Filtre strict de pertinence : évite les hallucinations ou articles hors sujet
            recommended = filter_precise_recommendations(message, recommended)

            if reply:
                return {
                    "reply": reply,
                    "recommended_articles": recommended,
                    "intent": "openrouter_llm",
                    "source": "openrouter",
                }
    except Exception as exc:
        logger.warning("Échec appel OpenRouter (%s), repli sur le moteur local", exc)

    return None


def run_agent(
    message: str,
    session: Session,
    lat: float = DEFAULT_LAT,
    lng: float = DEFAULT_LNG,
) -> dict:
    """Exécute l'agent conversationnel : tente OpenRouter en priorité, avec repli local instantané."""
    statement = (
        select(Article, Shop)
        .where(Article.shop_id == Shop.id)
        .where(Shop.is_open == True)  # noqa: E712
        .where(Article.hidden == False)  # noqa: E712
        .where(Article.out_of_stock == False)  # noqa: E712
    )
    results = session.exec(statement).all()

    # Liste unifiée (Article, Shop, Distance)
    articles_data = [
        (article, shop, distance_m(lat, lng, shop.lat, shop.lng))
        for article, shop in results
    ]

    # 1. Tentative avec le modèle LLM OpenRouter si la clé est fournie
    if OPENROUTER_API_KEY:
        llm_result = query_openrouter(message, articles_data)
        if llm_result:
            return llm_result

    # 2. Repli local déterministe (garantit 0 panne)
    return run_local_agent(message, articles_data)
