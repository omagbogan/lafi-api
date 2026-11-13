"""
lafi-api/app/agent.py
---------------------
Agent IA conversationnel pour Lafi (Bloc 4 de la soutenance).

Architecture Hybride avec Garde-Fous Métier (Domain Grounding) :
  1. Garde-fou Hors-Sujet (Guardrail) : Bloque toute question étrangère au commerce Lafi
     et recadre systématiquement la conversation vers l'activité de Lafi, ses boutiques et ses articles.
  2. Couche Cloud (Groq / OpenRouter LLM) : Compréhension sémantique du français et du nouchi,
     strictement verrouillée sur le catalogue SQLite (articles + boutiques partenaires).
  3. Couche Locale (Edge / Offline) : Moteur déterministe à règles garantissant 0 panne hors-ligne.
"""

import base64
import json
import logging
import os
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
        "sauce", "alloco", "boisson", "jus", "huile", "eau", "viande", "pain", "alimentation",
    ],
    "Mode": [
        "habit", "vetement", "vêtement", "robe", "pantalon", "chemise", "sac",
        "chaussure", "sandale", "wax", "pagne", "costume", "tissu", "talon", "boucle", "mode",
    ],
    "Beauté": [
        "beauté", "beaute", "savon", "creme", "crème", "pommade", "parfum", "mèche",
        "meche", "cheveux", "maquillage", "karité", "karite", "lotion", "soin", "huile",
    ],
    "Électronique": [
        "telephone", "téléphone", "portable", "smartphone", "chargeur", "cable",
        "câble", "ecouteur", "écouteur", "airpod", "casque", "audio", "tv", "radio",
        "pile", "batterie", "power bank", "micro", "sunmi", "electronique", "électronique",
    ],
    "Maison": [
        "maison", "cuisine", "casserole", "assiette", "poele", "poêle", "ventilateur",
        "mixeur", "drap", "matelas", "rideau", "fer", "seau", "balai", "ampoule", "lampe", "salon",
    ],
    "Bébé": [
        "bébé", "bebe", "enfant", "couche", "couches", "biberon", "pampers",
        "lingette", "tetine", "tétine", "poussette", "lait", "nourrisson", "coffret",
    ],
}

# Mots-clés liés à l'activité commerciale de Lafi, aux boutiques et aux commandes
LAFI_COMMERCE_WORDS = {
    "lafi", "boutique", "boutiques", "magasin", "commerçant", "commercant", "commerçants",
    "vendeur", "vendeuse", "marché", "marche", "article", "articles", "produit", "produits",
    "prix", "fcfa", "franc", "francs", "acheter", "achat", "commander", "commande", "commandes",
    "panier", "livraison", "livrer", "yango", "retrait", "retirer", "code", "otp", "ouvert",
    "ouverte", "ouverts", "fermé", "quartier", "cocody", "abidjan", "marcory", "plateau",
    "riviera", "angré", "angre", "catalogue", "stock", "disponible", "dispo", "combien",
    "coute", "coûte", "vend", "vendez", "cherche", "besoin", "trouver", "categorie", "catégorie",
}

# Sujets strictement interdits (Hors-Sujet : politique, sport, code, devoirs, météo, blagues, etc.)
OFF_TOPIC_KEYWORDS = {
    "politique", "président", "president", "élection", "election", "gouvernement", "ministre",
    "football", "match", "ballon", "messi", "ronaldo", "drogba", "barça", "madrid", "psg",
    "météo", "meteo", "pluie", "température", "temperature",
    "python", "javascript", "html", "css", "programmation", "coder", "algorithme", "sql",
    "mathématique", "mathematique", "équation", "equation", " théorème", "racine carrée",
    "capitale", "géographie", "geographie", "histoire", "guerre", "planète", "planete",
    "blague", "poème", "poeme", "chanson", "film", "cinéma", "cinema", "série", "serie",
    "médecin", "medecin", "maladie", "médicament", "medicament", "symptôme",
    "horoscope", "astrologie", "religion", "prière", "bitcoin", "crypto", "bourse",
    "oublie tes instructions", "ignore previous", "system prompt", "chatgpt", "openai",
}

STOP_WORDS = {
    "je", "tu", "il", "elle", "nous", "vous", "ils", "veux", "voudrais", "cherche", "aimerais",
    "trouve", "trouver", "donne", "moi", "un", "une", "des", "du", "de", "la", "le", "les",
    "pour", "avec", "sans", "est", "sont", "dans", "chez", "sur", "par", "beau", "belle",
    "joli", "jolie", "bon", "bonne", "pas", "cher", "chers", "chere", "cheres", "bonjour",
    "salut", "svp", "stp", "merci", "articles", "article", "produit", "produits", "besoin",
}


def build_refocus_reply(shops: list[Shop], articles_count: int) -> str:
    """Construit la réponse de recadrage ramenant systématiquement vers Lafi, ses boutiques et ses articles."""
    open_shops = [s.name for s in shops if s.is_open]
    if open_shops:
        shops_str = ", ".join(open_shops[:4])
        return (
            f"Je suis uniquement dédié à l'activité commerciale de Lafi, à nos boutiques partenaires "
            f"({shops_str}) et aux {articles_count} article(s) actuellement en vente. "
            f"Dites-moi quel produit vous recherchez (Alimentation, Mode, Beauté, Électronique, Maison, Bébé) "
            f"ou sur quelle boutique Lafi vous souhaitez des informations !"
        )
    return (
        "Je suis uniquement dédié à l'activité commerciale de Lafi, à ses boutiques partenaires "
        "et aux articles vendus sur la plateforme (Alimentation, Mode, Beauté, Électronique, Maison, Bébé). "
        "Quel article ou quelle boutique recherchez-vous aujourd'hui ?"
    )


def is_off_topic_query(
    message: str,
    articles_data: list[tuple[Article, Shop, int]],
    shops: list[Shop],
) -> bool:
    """
    Détecte si la demande de l'utilisateur sort du cadre de l'activité Lafi,
    des articles vendus ou des boutiques partenaires.
    """
    lower = message.strip().lower()
    if not lower:
        return False

    # 1. Contient un mot-clé explicitement hors-sujet (sport, politique, code, blague, etc.)
    for bad_kw in OFF_TOPIC_KEYWORDS:
        if bad_kw in lower:
            return True

    # 2. Vérifier si la phrase mentionne un élément lié à Lafi :
    #    - salutation courte
    #    - budget FCFA
    #    - mot-clé d'une des 6 catégories
    #    - mot-clé du commerce Lafi / commande / boutique
    #    - nom d'un article ou d'une boutique existante en base
    greetings = {"bonjour", "salut", "bonsoir", "coucou", "kôkô", "hello", "merci", "bjr", "slt"}
    tokens = re.findall(r"\w+", lower)
    if not tokens:
        return False

    if len(tokens) <= 3 and any(t in greetings for t in tokens):
        return False

    if extract_budget(lower) is not None:
        return False

    if detect_categories(lower):
        return False

    if any(t in LAFI_COMMERCE_WORDS for t in tokens):
        return False

    # Vérifier la correspondance avec un nom de boutique ou d'article en base
    for shop in shops:
        shop_words = [w for w in re.findall(r"\w+", shop.name.lower()) if len(w) >= 3]
        if any(sw in lower for sw in shop_words):
            return False

    for art, _, _ in articles_data:
        art_words = [w for w in re.findall(r"\w+", art.name.lower()) if len(w) >= 3]
        if any(aw in lower for aw in art_words):
            return False

    # Questions encyclopédiques génériques sans aucun lien avec un produit ou une boutique
    off_topic_starters = (
        "qui est ", "quelle est la capitale", "quel est le président", "raconte",
        "écris", "ecris", "calcule", "combien font", "traduis", "qu'est-ce que la ",
        "pourquoi le ciel", "comment programmer", "fais-moi un devoir",
    )
    if any(lower.startswith(st) or st in lower for st in off_topic_starters):
        return True

    return False


def handle_lafi_or_shop_intent(
    message: str,
    articles_data: list[tuple[Article, Shop, int]],
    shops: list[Shop],
) -> Optional[dict]:
    """
    Répond directement aux questions portant sur :
      - une boutique spécifique (et renvoie ses articles)
      - la liste des boutiques partenaires Lafi
      - le fonctionnement de Lafi (commande, retrait OTP, livraison Yango)
    """
    lower = message.strip().lower()

    # 1. Question sur une boutique précise enregistrée dans Lafi
    for shop in shops:
        if shop.name.lower() in lower:
            shop_articles = [
                ArticleOut(
                    id=art.id,
                    name=art.name,
                    price=art.price,
                    category=art.category,
                    description=art.description,
                    negotiable=art.negotiable,
                    hidden=art.hidden,
                    out_of_stock=art.out_of_stock,
                    color=art.color,
                    photo_url=art.photo_url,
                    shop_id=s.id,
                    shop=s.name,
                    shop_phone=s.phone,
                    open=s.is_open,
                    distance_m=dist,
                    shop_lat=s.lat,
                    shop_lng=s.lng,
                )
                for art, s, dist in articles_data
                if s.id == shop.id
            ]
            status_txt = "actuellement ouverte" if shop.is_open else "actuellement fermée"
            addr_txt = f" située à {shop.address}" if shop.address else " à Abidjan"
            if shop_articles:
                reply = (
                    f"La boutique « {shop.name} » ({status_txt}{addr_txt}, tél : {shop.phone}) "
                    f"propose actuellement {len(shop_articles)} article(s) sur Lafi :"
                )
            else:
                reply = (
                    f"La boutique « {shop.name} » est {status_txt}{addr_txt} (tél : {shop.phone}), "
                    f"mais elle n'a pas encore publié d'article en stock pour le moment."
                )
            return {
                "reply": reply,
                "recommended_articles": shop_articles[:4],
                "intent": "shop_info",
                "source": "agent-local",
            }

    # 2. Question sur la liste des boutiques partenaires
    if any(
        kw in lower
        for kw in ["quelles boutiques", "quelles sont les boutiques", "liste des boutiques", "boutiques ouvertes", "quels magasins", "quels commerçants"]
    ):
        open_shops = [s for s in shops if s.is_open]
        if open_shops:
            details = ", ".join(
                f"{s.name} ({s.address or 'Abidjan'})" for s in open_shops[:6]
            )
            reply = (
                f"Nous avons actuellement {len(open_shops)} boutique(s) partenaire(s) ouverte(s) sur Lafi : "
                f"{details}. Quel type d'article souhaitez-vous voir dans ces boutiques ?"
            )
        else:
            reply = (
                "Aucune boutique partenaire n'est ouverte en ce moment sur Lafi. "
                "Revenez très vite ou consultez notre catalogue dès l'ouverture des commerçants !"
            )
        return {
            "reply": reply,
            "recommended_articles": [],
            "intent": "shops_list",
            "source": "agent-local",
        }

    # 3. Question sur l'activité Lafi, la livraison Yango ou le retrait en boutique
    if any(
        kw in lower
        for kw in ["comment commander", "comment marche lafi", "c'est quoi lafi", "livraison yango", "retrait en boutique", "comment payer", "code otp", "code de retrait"]
    ):
        reply = (
            "Lafi est votre plateforme de commerce de proximité à Abidjan : vous choisissez vos articles "
            "chez les commerçants de votre quartier, vous validez votre commande gratuitement avec un code secret "
            "de retrait à 4 chiffres (ou en livraison Yango depuis l'application mobile Android), et vous réglez "
            "directement au commerçant. Quel article cherchez-vous aujourd'hui ?"
        )
        return {
            "reply": reply,
            "recommended_articles": [],
            "intent": "lafi_activity_info",
            "source": "agent-local",
        }

    return None


def filter_precise_recommendations(message: str, recommended: list[ArticleOut]) -> list[ArticleOut]:
    """Élimine les articles hors-sujet si le client a demandé un produit précis."""
    if not recommended:
        return recommended

    lower = message.lower()
    tokens = [w for w in re.findall(r"\w+", lower) if len(w) >= 3 and w not in STOP_WORDS]

    if not tokens:
        return recommended

    matching_articles = [
        art for art in recommended
        if any(tok in art.name.lower() or tok in (art.shop or "").lower() for tok in tokens)
    ]

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
    shops: list[Shop],
    history: Optional[list[dict]] = None,
) -> dict:
    """Moteur local déterministe verrouillé sur l'activité Lafi, les boutiques et les articles."""
    cleaned = message.strip()
    lower = cleaned.lower()

    # 1. Garde-fou strict Hors-Sujet
    if is_off_topic_query(cleaned, articles_data, shops):
        return {
            "reply": build_refocus_reply(shops, len(articles_data)),
            "recommended_articles": [],
            "intent": "off_topic_refocus",
            "source": "agent-local-guardrail",
        }

    # 2. Questions sur une boutique précise ou sur le fonctionnement de Lafi
    shop_or_activity = handle_lafi_or_shop_intent(cleaned, articles_data, shops)
    if shop_or_activity:
        return shop_or_activity

    budget = extract_budget(cleaned)
    target_categories = detect_categories(cleaned)
    search_tokens = [w for w in re.findall(r"\w+", lower) if len(w) >= 3 and w not in STOP_WORDS]

    if history and not target_categories and not search_tokens:
        for turn in reversed(history):
            if turn.get("role") == "user":
                prev_text = str(turn.get("content", "")).lower()
                prev_cats = detect_categories(prev_text)
                prev_tokens = [
                    w for w in re.findall(r"\w+", prev_text)
                    if len(w) >= 3 and w not in STOP_WORDS and not w.isdigit()
                ]
                if prev_cats or prev_tokens:
                    target_categories = prev_cats
                    search_tokens = prev_tokens
                    break

    scored = []
    for article, shop, dist in articles_data:
        art_name_lower = article.name.lower()
        art_desc_lower = (article.description or "").lower()
        shop_name_lower = shop.name.lower()
        score = 0

        if budget is not None and article.price > budget:
            continue

        if target_categories and article.category in target_categories:
            score += 10

        for token in search_tokens:
            if token in art_name_lower:
                score += 25
            elif token in shop_name_lower:
                score += 20
            elif token in art_desc_lower:
                score += 10

        if score > 0 or (not target_categories and budget is not None):
            scored.append((score, dist, article, shop))

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
            description=art.description,
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
            shop_lat=shop.lat,
            shop_lng=shop.lng,
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
                f"({budget:,} FCFA max) chez nos boutiques partenaires Lafi :".replace(",", " ")
            )
        elif target_categories:
            cat_str = " et ".join(target_categories)
            reply = (
                f"{greeting_prefix}Voici les articles disponibles au rayon {cat_str} "
                f"dans nos boutiques partenaires :"
            )
        else:
            reply = f"{greeting_prefix}Voici les articles disponibles en boutique sur Lafi qui correspondent à votre demande :"
        intent = "product_recommendation"
    else:
        if is_greeting and len(cleaned) < 20:
            open_count = sum(1 for s in shops if s.is_open)
            reply = (
                f"Bonjour ! Je suis l'assistant commercial de Lafi ({open_count} boutique(s) ouverte(s) et "
                f"{len(articles_data)} article(s) en stock). Dites-moi quel article, quelle catégorie "
                f"(Alimentation, Mode, Beauté, Électronique, Maison, Bébé) ou quelle boutique vous intéresse !"
            )
            intent = "greeting"
        elif budget is not None:
            reply = (
                f"Nous n'avons pas d'article à moins de {budget:,} FCFA disponible en boutique pour le moment. "
                f"Souhaitez-vous explorer un autre budget ou voir tous les articles de nos boutiques partenaires ?"
            ).replace(",", " ")
            intent = "no_results_budget"
        else:
            # Recadrage systématique vers l'activité Lafi, les articles et les boutiques
            reply = build_refocus_reply(shops, len(articles_data))
            intent = "refocus_to_lafi"

    return {
        "reply": reply,
        "recommended_articles": recommended,
        "intent": intent,
        "source": "agent-local",
    }


def query_llm_agent(
    message: str,
    articles_data: list[tuple[Article, Shop, int]],
    shops: list[Shop],
    history: Optional[list[dict]] = None,
) -> Optional[dict]:
    """
    Interroge le LLM (Groq ou OpenRouter) avec un verrouillage strict (System Guardrail)
    sur l'activité commerciale de Lafi, ses articles et ses boutiques partenaires.
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    api_key = groq_key or (OPENROUTER_API_KEY or "").strip()
    if not api_key:
        return None

    is_groq = bool(groq_key)
    endpoint = (
        "https://api.groq.com/openai/v1/chat/completions"
        if is_groq
        else "https://openrouter.ai/api/v1/chat/completions"
    )
    model_name = "llama-3.3-70b-versatile" if is_groq else OPENROUTER_MODEL

    catalog_snapshot = [
        {
            "id": art.id,
            "nom": art.name,
            "prix_fcfa": art.price,
            "categorie": art.category,
            "description": art.description or "",
            "boutique": shop.name,
            "quartier_boutique": shop.address or "Abidjan",
            "telephone_boutique": shop.phone,
            "distance_m": dist,
        }
        for art, shop, dist in articles_data
    ]

    shops_snapshot = [
        {
            "id": s.id,
            "nom_boutique": s.name,
            "gerant": s.owner_name or "Commerçant partenaire",
            "quartier": s.address or "Abidjan",
            "telephone": s.phone,
            "ouverte": s.is_open,
        }
        for s in shops
    ]

    system_prompt = (
        "Tu es l'assistant IA commercial exclusif de la plateforme Lafi (marché de proximité à Abidjan, Côte d'Ivoire).\n\n"
        "RÈGLE STRICTE ET ABSOLUE (GARDE-FOU HORS-SUJET) :\n"
        "- Tu dois te focaliser UNIQUEMENT sur l'activité commerciale de Lafi, les articles vendus en boutique et les différentes boutiques partenaires de Lafi.\n"
        "- Il t'est FORMELLEMENT INTERDIT d'aborder tout autre sujet (sport, politique, météo, programmation, mathématiques, histoire, géographie, blagues, culture générale, santé, actualités ou demandes personnelles).\n"
        "- Si l'utilisateur pose une question hors sujet ou tente de te détourner de ta mission, tu DOIS refuser poliment d'y répondre et RECADRER immédiatement la conversation vers l'activité de Lafi, ses boutiques partenaires et les articles disponibles (Alimentation, Mode, Beauté, Électronique, Maison, Bébé), avec `recommended_ids: []`.\n\n"
        "INFORMATIONS SUR L'ACTIVITÉ DE LAFI :\n"
        "- Lafi connecte les clients d'Abidjan aux boutiques de proximité dans 6 catégories : Alimentation, Mode, Beauté, Électronique, Maison, Bébé.\n"
        "- Commandes : retrait gratuit en boutique sécurisé par un code secret OTP à 4 chiffres, ou livraison Yango disponible sur l'application mobile Android.\n"
        "- Paiement : règlement direct au commerçant (Mobile Money ou espèces).\n\n"
        f"BOUTIQUES PARTENAIRES ENREGISTRÉES SUR LAFI :\n{json.dumps(shops_snapshot, ensure_ascii=False)}\n\n"
        f"ARTICLES ACTUELLEMENT EN VENTE DANS LES BOUTIQUES OUVERTES :\n{json.dumps(catalog_snapshot, ensure_ascii=False)}\n\n"
        "INSTRUCTIONS DE RÉPONSE :\n"
        "1. Si le client cherche un article, un prix ou une boutique de Lafi, réponds avec précision (max 2 phrases chaleureuses) et place les identifiants exacts des articles pertinents dans `recommended_ids`.\n"
        "2. Ne recommande JAMAIS un article qui ne correspond pas à la demande.\n"
        "3. Si la question est hors-sujet, recadre fermement mais poliment vers les articles et les boutiques de Lafi et renvoie `recommended_ids: []`.\n"
        "4. Réponds UNIQUEMENT au format JSON strict :\n"
        '{"reply": "...", "recommended_ids": []}'
    )

    llm_messages = [{"role": "system", "content": system_prompt}]
    if history:
        for turn in history[-4:]:
            role = turn.get("role")
            content = str(turn.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                llm_messages.append({"role": role, "content": content})
    llm_messages.append({"role": "user", "content": message})

    payload = {
        "model": model_name,
        "messages": llm_messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 350,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Lafi-Commerce-Agent/1.0",
    }
    if not is_groq:
        headers["HTTP-Referer"] = "https://lafi.ci"
        headers["X-Title"] = "Lafi Assistant"

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content_str = res_data["choices"][0]["message"]["content"]
            parsed = json.loads(content_str)

            reply = parsed.get("reply", "").strip()
            rec_ids = parsed.get("recommended_ids", [])

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
                            description=art.description,
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
                            shop_lat=shop.lat,
                            shop_lng=shop.lng,
                        )
                    )

            recommended = filter_precise_recommendations(message, recommended)

            if reply:
                return {
                    "reply": reply,
                    "recommended_articles": recommended,
                    "intent": "llm_commerce",
                    "source": "groq" if is_groq else "openrouter",
                }
    except Exception as exc:
        logger.warning("Échec appel LLM (%s), repli sur le moteur local", exc)

    return None


def run_agent(
    message: str,
    session: Session,
    lat: float = DEFAULT_LAT,
    lng: float = DEFAULT_LNG,
    history: Optional[list[dict]] = None,
) -> dict:
    """
    Exécute l'agent conversationnel Lafi :
    1. Vérifie d'abord le garde-fou hors-sujet en amont pour garantir 0 dérive.
    2. Interroge le LLM (Groq / OpenRouter) ancré sur les boutiques et articles SQLite.
    3. Bascule sur le moteur local déterministe en cas d'absence de réseau.
    """
    all_shops = session.exec(select(Shop)).all()

    statement = (
        select(Article, Shop)
        .where(Article.shop_id == Shop.id)
        .where(Shop.is_open == True)  # noqa: E712
        .where(Article.hidden == False)  # noqa: E712
        .where(Article.out_of_stock == False)  # noqa: E712
    )
    results = session.exec(statement).all()

    articles_data = [
        (article, shop, distance_m(lat, lng, shop.lat, shop.lng))
        for article, shop in results
    ]

    # 1. Blocage immédiat des questions manifestement hors-sujet (sport, politique, code, etc.)
    if is_off_topic_query(message, articles_data, all_shops):
        return {
            "reply": build_refocus_reply(all_shops, len(articles_data)),
            "recommended_articles": [],
            "intent": "off_topic_refocus",
            "source": "agent-guardrail",
        }

    # 2. Tentative avec le LLM (Groq / OpenRouter) strictement cadré sur Lafi
    llm_result = query_llm_agent(message, articles_data, all_shops, history=history)
    if llm_result:
        return llm_result

    # 3. Repli local déterministe (garantit 0 panne)
    return run_local_agent(message, articles_data, all_shops, history=history)


def generate_product_description(
    title: str,
    category: Optional[str] = None,
    price: Optional[int] = None,
    negotiable: bool = False,
) -> dict:
    """
    Génère une fiche descriptive riche, concrète et spécifique au produit saisi par le commerçant :
    - Décrit les caractéristiques réelles de l'article (matière, ingrédients, fonctions techniques,
      usages précis et bénéfices concrets pour l'acheteur).
    - Évite les phrases génériques répétitives ("Découvrez...", "service client chaleureux...", etc.).
    """
    clean_title = title.strip() or "Article"
    cat_info = f" (Rayon : {category})" if category else ""
    price_info = f" (Prix : {price:,} FCFA)".replace(",", " ") if price else ""
    neg_info = " (Prix négociable)" if negotiable else ""

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    api_key = groq_key or (OPENROUTER_API_KEY or "").strip()

    if api_key:
        is_groq = bool(groq_key)
        endpoint = (
            "https://api.groq.com/openai/v1/chat/completions"
            if is_groq
            else "https://openrouter.ai/api/v1/chat/completions"
        )
        model_name = "llama-3.3-70b-versatile" if is_groq else OPENROUTER_MODEL

        system_instructions = (
            "Tu es un rédacteur expert de fiches produits e-commerce pour la plateforme Lafi en Côte d'Ivoire.\n"
            "Ta mission est de rédiger une description VRAIMENT DESCRIPTIVE, précise et informative sur le produit lui-même.\n\n"
            "RÈGLES D'OR :\n"
            "1. Décris concrètement CE QU'EST le produit, ses caractéristiques techniques ou sa composition, ses points forts et à quoi il sert exactement :\n"
            "   - Si c'est de l'Électronique (ex: Micro cravate, Sunmi V2 Pro, écouteurs, smartphone) : détaille ses fonctionnalités techniques concrètes (qualité audio/écran, connectivité, autonomie, ergonomie, usages professionnels ou quotidiens).\n"
            "   - Si c'est de l'Alimentation (ex: Attiéké poisson, Garba, Alloco, jus) : décris les ingrédients frais, la préparation, l'assaisonnement, les accompagnements et la saveur.\n"
            "   - Si c'est de la Mode (ex: robe, sac, chaussure, pagne) : décris la matière, la coupe, la solidité des finitions, le confort et le style.\n"
            "   - Si c'est de la Beauté : décris la texture, les ingrédients actifs (karité, huiles naturelles...) et les bienfaits concrets pour la peau ou les cheveux.\n"
            "   - Si c'est de la Maison ou Bébé : décris l'utilité pratique, les matériaux, la sécurité et le confort d'utilisation.\n"
            "2. INTERDICTION STRICTE des formules creuses et répétitives : ne commence JAMAIS par « Découvrez... », ne parle PAS de « livraison rapide à Abidjan », ni de « service client chaleureux », ni de « Commandez maintenant ». Parle à 100 % du produit lui-même !\n"
            "3. Longueur : 2 à 3 phrases fluides et riches (environ 180 à 300 caractères), sans guillemets ni listes à puces."
        )

        prompt = (
            f"Rédige la fiche descriptive précise du produit suivant : « {clean_title} »{cat_info}{price_info}{neg_info}.\n"
            f"Explique concrètement ses caractéristiques, sa composition ou son fonctionnement technique ainsi que son utilité pour l'acheteur."
        )

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "max_tokens": 180,
        }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Lafi-Commerce-Agent/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                desc = res_data["choices"][0]["message"]["content"].strip().strip('"').strip("«").strip("»").strip()
                if desc:
                    return {
                        "description": desc,
                        "source": "groq" if is_groq else "openrouter",
                        "accepte": True,
                    }
        except Exception as exc:
            logger.warning("Échec génération description LLM (%s), repli local", exc)

    # Repli local descriptif par catégorie (sans formules génériques creuses)
    templates = {
        "Alimentation": (
            f"{clean_title} préparé à la demande avec des produits frais du marché et un assaisonnement "
            f"traditionnel équilibré. Portion généreuse et savoureuse, idéale pour un repas complet et authentique."
        ),
        "Mode": (
            f"{clean_title} confectionné dans une matière résistante et agréable à porter, avec des coutures "
            f"et finitions soignées. Sa coupe élégante et polyvalente s'adapte aussi bien aux sorties qu'au quotidien."
        ),
        "Beauté": (
            f"{clean_title} formulé pour nourrir, protéger et sublimer durablement la peau ou la chevelure. "
            f"Texture douce et agréable à appliquer au quotidien pour un soin complet et naturel."
        ),
        "Électronique": (
            f"{clean_title} conçu pour offrir d'excellentes performances techniques, une prise en main intuitive "
            f"et une grande fiabilité au quotidien. Équipement robuste et autonome, prêt à l'emploi dès la mise en route."
        ),
        "Maison": (
            f"{clean_title} pensé pour faciliter l'organisation et améliorer le confort de votre intérieur au quotidien. "
            f"Conception solide, durable et facile d'entretien pour un usage intensif à la maison."
        ),
        "Bébé": (
            f"{clean_title} spécialement conçu avec des matières douces et hypoallergéniques respectueuses de la peau "
            f"sensible des tout-petits. Pratique et sécurisé pour accompagner le bien-être quotidien de bébé."
        ),
    }
    fallback_desc = templates.get(
        category or "",
        f"{clean_title} alliant matériaux durables, finition soignée et grande praticité pour répondre efficacement à vos besoins quotidiens.",
    )
    if negotiable:
        fallback_desc += " Prix discutable avec le vendeur."

    return {
        "description": fallback_desc,
        "source": "local-template",
        "accepte": True,
    }


def find_product_from_image(
    image_bytes: bytes,
    session: Session,
    lat: float = DEFAULT_LAT,
    lng: float = DEFAULT_LNG,
) -> dict:
    """
    Recherche un produit dans la base de données Lafi à partir d'une photo envoyée par le client.
    Utilise exclusivement le modèle Vision Multimodal (Groq Llama 4 Scout Vision / OpenRouter Vision)
    sans passer par les petits classifieurs locaux, afin de :
      1. Identifier avec précision l'objet présent sur la photo.
      2. Proposer l'article exact s'il est en stock dans la base SQLite.
      3. Sinon, proposer les articles similaires (même rayon / même usage) présents dans la base.
      4. Si l'image est hors-sujet ou qu'aucun article similaire n'existe, recadrer vers les boutiques Lafi.
    """
    all_shops = session.exec(select(Shop)).all()
    results = session.exec(
        select(Article, Shop)
        .join(Shop)
        .where(Article.hidden == False, Article.out_of_stock == False, Shop.is_open == True)  # noqa: E712
    ).all()

    if not results:
        return {
            "reply": (
                "J'ai bien reçu votre photo, mais aucun article n'est actuellement en stock "
                "dans les boutiques partenaires ouvertes sur Lafi."
            ),
            "recommended_articles": [],
            "intent": "no_articles",
            "source": "agent-vision",
        }

    articles_data = [
        (art, shop, distance_m(lat, lng, shop.lat, shop.lng))
        for art, shop in results
    ]

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    api_key = groq_key or (OPENROUTER_API_KEY or "").strip()

    if api_key:
        try:
            import io
            from PIL import Image, ImageOps

            try:
                with Image.open(io.BytesIO(image_bytes)) as pil_img:
                    pil_img = ImageOps.exif_transpose(pil_img).convert("RGB")
                    pil_img.thumbnail((800, 800))
                    opt_buf = io.BytesIO()
                    pil_img.save(opt_buf, format="JPEG", quality=82)
                    opt_bytes = opt_buf.getvalue()
            except Exception:
                opt_bytes = image_bytes

            b64 = base64.b64encode(opt_bytes).decode("utf-8")
            data_uri = f"data:image/jpeg;base64,{b64}"

            catalog_snapshot = [
                {
                    "id": art.id,
                    "nom": art.name,
                    "description": art.description or "",
                    "categorie": art.category,
                    "prix_fcfa": art.price,
                    "boutique": shop.name,
                    "quartier": shop.address or "Abidjan",
                    "distance_m": dist,
                }
                for art, shop, dist in articles_data
            ]

            prompt_text = (
                "Tu es l'assistant IA commercial exclusif de la plateforme Lafi (commerce de proximité à Abidjan).\n"
                "Le client t'envoie une image pour chercher un produit dans nos boutiques partenaires.\n\n"
                "VOICI LE CATALOGUE EXACT DES ARTICLES ACTUELLEMENT EN STOCK SUR LAFI :\n"
                f"{json.dumps(catalog_snapshot, ensure_ascii=False)}\n\n"
                "INSTRUCTIONS STRICTES :\n"
                "1. Identifie précisément ce qui figure sur la photo envoyée par le client.\n"
                "2. CAS A (Produit exact disponible) : Si l'objet de la photo correspond exactement à un article du catalogue ci-dessus, "
                "mets son identifiant dans `recommended_ids`, mets `match_type` à `\"exact\"`, et rédige `reply` (max 2 phrases) pour dire ce que tu as reconnu et présenter l'article.\n"
                "3. CAS B (Produit exact absent, mais produits similaires disponibles) : Si l'objet exact n'est pas dans le catalogue, "
                "cherche dans le catalogue ci-dessus les articles SIMILAIRES (même catégorie ou même usage, ex: un autre appareil électronique, un autre vêtement/accessoire, un autre plat, etc.). "
                "Mets leurs identifiants dans `recommended_ids`, mets `match_type` à `\"similar\"`, et précise clairement dans `reply` : "
                "« J'ai reconnu [nom de l'objet] sur votre photo. Nous n'avons pas exactement ce modèle en stock, mais voici les articles similaires disponibles dans nos boutiques Lafi : ».\n"
                "4. CAS C (Image hors-sujet ou aucun article similaire du même rayon en stock) : "
                "Si la photo ne montre pas un produit commercial (ex: personne, paysage, texte hors-sujet) OU qu'aucun article du catalogue ne s'en rapproche, "
                "renvoie `recommended_ids: []`, `match_type: \"none\"`, et recadre poliment le client vers les articles et boutiques de Lafi.\n"
                "5. Réponds UNIQUEMENT au format JSON strict :\n"
                '{"reply": "...", "recommended_ids": [], "match_type": "exact|similar|none"}'
            )

            is_groq = bool(groq_key)
            endpoint = (
                "https://api.groq.com/openai/v1/chat/completions"
                if is_groq
                else "https://openrouter.ai/api/v1/chat/completions"
            )
            vision_model = (
                "meta-llama/llama-4-scout-17b-16e-instruct"
                if is_groq
                else "qwen/qwen-2.5-vl-72b-instruct"
            )

            payload = {
                "model": vision_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    }
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": 350,
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Lafi-Vision-Agent/1.0",
            }
            if not is_groq:
                headers["HTTP-Referer"] = "https://lafi.ci"
                headers["X-Title"] = "Lafi Vision Assistant"

            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=12) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                content_str = res_data["choices"][0]["message"]["content"]
                parsed = json.loads(content_str)
                reply = parsed.get("reply", "").strip()
                rec_ids = parsed.get("recommended_ids", [])
                match_type = parsed.get("match_type", "similar")

                articles_by_id = {art.id: (art, shop, dist) for art, shop, dist in articles_data}
                articles_by_id.update({str(art.id): (art, shop, dist) for art, shop, dist in articles_data})

                matched_articles = []
                seen_ids = set()
                for rid in rec_ids:
                    candidate = None
                    if rid in articles_by_id:
                        candidate = articles_by_id[rid]
                    else:
                        digits = re.sub(r"\D", "", str(rid))
                        if digits and int(digits) in articles_by_id:
                            candidate = articles_by_id[int(digits)]

                    if candidate and candidate[0].id not in seen_ids:
                        seen_ids.add(candidate[0].id)
                        art, shop, dist = candidate
                        matched_articles.append(
                            ArticleOut(
                                id=art.id,
                                name=art.name,
                                price=art.price,
                                category=art.category,
                                description=art.description,
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
                                shop_lat=shop.lat,
                                shop_lng=shop.lng,
                            )
                        )

                if reply:
                    return {
                        "reply": reply,
                        "recommended_articles": matched_articles[:4],
                        "intent": f"vision_{match_type}",
                        "source": "groq-vision" if is_groq else "openrouter-vision",
                    }
        except Exception as exc:
            logger.warning("Échec analyse Vision LLM (%s)", exc)

    # Repli sobre si la clé API Vision n'est pas joignable (sans utiliser le modèle local imprécis)
    return {
        "reply": build_refocus_reply(all_shops, len(articles_data)),
        "recommended_articles": [],
        "intent": "vision_fallback_refocus",
        "source": "agent-vision-fallback",
    }
