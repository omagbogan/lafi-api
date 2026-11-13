"""
lafi-api/app/category_model.py
------------------------------
Suggère la catégorie d'un article à partir de son titre (Bloc 2 — Modèle Texte).

Améliorations de performance :
  1. Pipeline TF-IDF (mots + n-grammes de caractères) + LinearSVC (`models/category.joblib`).
  2. Consensus par catégorie mère Lafi : lorsque le modèle hésite entre deux sous-catégories fines
     qui appartiennent toutes les deux à la même catégorie Lafi (ex. "Audio & enceintes" et
     "Écouteurs & casques" -> "Électronique"), la catégorie mère est validée avec confiance.
  3. Fusion hybride avec un lexique métier & ivoirien enrichi (> 220 termes locaux et techniques)
     pour couvrir parfaitement les réalités du marché d'Abidjan.
"""

import logging
import re
import unicodedata
from pathlib import Path

import numpy as np

log = logging.getLogger("lafi.category")

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "category.joblib"

# Catégories officielles de l'application Lafi (doivent rester identiques partout).
LAFI_CATEGORIES = {"Alimentation", "Mode", "Beauté", "Électronique", "Maison", "Bébé"}

# Classe fine du modèle (31 classes locales) -> catégorie officielle Lafi.
CATEGORY_MAP = {
    # Alimentation
    "Épicerie & condiments": "Alimentation",
    "Boissons & alcools": "Alimentation",
    # Mode
    "Vêtements": "Mode",
    "Chaussures": "Mode",
    "Sacs & portefeuilles": "Mode",
    "Bijoux & montres": "Mode",
    "Accessoires de mode": "Mode",
    # Beauté
    "Soins des cheveux": "Beauté",
    "Parfums": "Beauté",
    "Hygiène & soins du corps": "Beauté",
    "Beauté - autres": "Beauté",
    # Électronique
    "Smartphones": "Électronique",
    "Tablettes": "Électronique",
    "Écouteurs & casques": "Électronique",
    "Montres connectées & bracelets": "Électronique",
    "Batteries externes & chargeurs": "Électronique",
    "Accessoires téléphone": "Électronique",
    "Audio & enceintes": "Électronique",
    "Télévisions": "Électronique",
    "Accessoires TV & vidéo": "Électronique",
    "Caméras & surveillance": "Électronique",
    "Électronique auto": "Électronique",
    "Électronique - autres": "Électronique",
    # Maison
    "Électroménager & ventilation": "Maison",
    "Cuisine & art de la table": "Maison",
    "Rangement, déco & éclairage": "Maison",
    "Outillage & bricolage": "Maison",
    "Produits ménagers": "Maison",
    # Bébé
    "Alimentation & biberons bébé": "Bébé",
    "Puériculture & jouets bébé": "Bébé",
    "Couches & soins bébé": "Bébé",
}

DEFAULT_SUBCATEGORY = {
    "Alimentation": "Épicerie & condiments",
    "Mode": "Vêtements",
    "Beauté": "Hygiène & soins du corps",
    "Électronique": "Électronique - autres",
    "Maison": "Rangement, déco & éclairage",
    "Bébé": "Puériculture & jouets bébé",
}

# Lexique métier & ivoirien enrichi (sans accents, normalisé)
KEYWORDS = {
    "Alimentation": [
        "riz", "huile", "tomate", "oignon", "poisson", "viande", "poulet", "attieke",
        "garba", "alloco", "placali", "foutou", "kedjenou", "degue", "bissap", "gingembre",
        "gnamankoudji", "gbofloto", "tchep", "choukouya", "braise", "tilapia", "machoiron",
        "banane", "plantain", "igname", "manioc", "sucre", "farine", "lait", "cafe", "the",
        "jus", "eau", "biere", "vin", "boisson", "epice", "piment", "maggi", "dinor", "aya",
        "pain", "gateau", "biscuit", "chocolat", "miel", "confiture", "oeuf", "fromage",
        "yaourt", "spaghetti", "macaroni", "pates", "sardine", "thon", "crevette", "crabe",
        "escargot", "arachide", "pate d arachide", "graine", "sauce", "condiment",
    ],
    "Mode": [
        "robe", "pagne", "wax", "kita", "bazin", "boubou", "chemise", "pantalon", "jean",
        "jupe", "culotte", "short", "veste", "costume", "blazer", "pull", "gilet", "t-shirt",
        "tshirt", "polo", "maillot", "survêtement", "survetement", "sac", "sacoche",
        "portefeuille", "porte-monnaie", "valise", "chaussure", "sandale", "tapette",
        "claquette", "basket", "sneaker", "talon", "escarpin", "mocassin", "botte",
        "montre", "bijou", "collier", "chaine", "bracelet", "bague", "boucle d oreille",
        "casquette", "chapeau", "bonnet", "foulard", "echarpe", "ceinture", "lunettes",
        "cuir", "dentelle", "brode", "tenue", "ensemble",
    ],
    "Beauté": [
        "creme", "savon", "savon noir", "parfum", "eau de toilette", "deodorant",
        "huile de coco", "karite", "beurre de karite", "shampoing", "apres-shampoing",
        "cheveux", "perruque", "meche", "lace wig", "closure", "tresse", "defrisant",
        "pommade", "maquillage", "rouge a levres", "gloss", "fond de teint", "poudre",
        "mascara", "eyeliner", "fard", "vernis", "ongle", "manucure", "lotion",
        "lait de corps", "lait eclaircissant", "gel douche", "gommage", "serum",
        "soin visage", "masque visage", "huile essentielle", "huile de ricin", "rasoir",
        "tondeuse", "brosse a cheveux", "seche-cheveux", "lisseur",
    ],
    "Électronique": [
        "telephone", "smartphone", "iphone", "samsung", "galaxy", "tecno", "infinix",
        "itel", "xiaomi", "redmi", "huawei", "oppo", "realme", "nokia", "tablette", "ipad",
        "ecouteur", "airpod", "airpods", "casque", "bluetooth", "enceinte", "haut-parleur",
        "jbl", "bose", "micro", "microphone", "micro cravate", "cravate", "sunmi", "tpe",
        "terminal", "chargeur", "cable", "adaptateur", "usb", "type-c", "lightning",
        "powerbank", "power bank", "batterie externe", "pile", "television", "tv",
        "decodeur", "ordinateur", "pc", "laptop", "macbook", "ecran", "moniteur",
        "clavier", "souris", "cle usb", "disque dur", "carte memoire", "sd",
        "camera", "webcam", "ring light", "anneau lumineux", "trepied", "montre connectee",
        "smartwatch", "routeur", "modem", "wifi", "console", "playstation", "ps4", "ps5",
        "manette", "imprimante", "onduleur",
    ],
    "Maison": [
        "ventilateur", "climatiseur", "split", "brasseur", "mixeur", "blender", "batteur",
        "hachoir", "bouilloire", "cafetiere", "micro-onde", "four", "gaziniere", "rechaud",
        "frigo", "refrigerateur", "congelateur", "casserole", "marmite", "poele", "faitout",
        "assiette", "bol", "verre", "tasse", "mug", "couvert", "cuillere", "fourchette",
        "couteau", "plateau", "thermos", "glaciere", "drap", "couette", "oreiller", "taie",
        "matelas", "rideau", "voilage", "tapis", "moquette", "lampe", "ampoule", "led",
        "lustre", "veilleuse", "rallonge", "multiprise", "fer a repasser", "planche a repasser",
        "seau", "bassine", "balai", "serpilliere", "Vadrouille", "poubelle", "lessive",
        "javel", "detergent", "desodorisant", "insecticide", "moustiquaire", "chaise",
        "table", "fauteuil", "canape", "etagere", "armoire", "commode", "rotin", "deco",
        "cadre", "miroir", "horloge", "vase", "outil", "tournevis", "marteau", "perceuse",
    ],
    "Bébé": [
        "bebe", "nourrisson", "nouveau-ne", "biberon", "tetine", "chauffe-biberon",
        "sterilisateur", "tire-lait", "couche", "couches", "pampers", "huggies", "lingette",
        "lait infantile", "lait de croissance", "cerelac", "bouillie", "farine bebe",
        "poussette", "landau", "berceau", "lit parapluie", "siege auto", "transat",
        "porte-bebe", "trotteur", "youpala", "bavoir", "body bebe", "grenouillere",
        "pyjama bebe", "chausson bebe", "coffret bebe", "trousseau", "hochet", "doudou",
        "jouet bebe", "baignoire bebe", "pot bebe", "talc", "liniment",
    ],
}

_STATE = {"loaded": False, "bundle": None, "keep": None, "names": None}
_model = None


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    clean = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s-]", " ", clean)


def _load():
    """Charge le modèle une seule fois. En cas d'échec, on garde le repli (l'API démarre quand même)."""
    global _model
    if _STATE["loaded"]:
        return
    _STATE["loaded"] = True
    if not MODEL_PATH.is_file():
        log.warning("Modèle absent (%s) : repli par mots-clés.", MODEL_PATH)
        return
    try:
        import joblib

        bundle = joblib.load(MODEL_PATH)
        classes = np.asarray(bundle["model"][-1].classes_)
        local = set(bundle["local_classes"])
        _STATE["bundle"] = bundle
        _STATE["keep"] = np.array([c in local for c in classes])
        _STATE["names"] = classes[_STATE["keep"]]
        _model = bundle["model"]
        log.info("Classifieur chargé : %s", bundle.get("model_name", "?"))
    except Exception:
        log.exception("Impossible de charger le modèle : repli par mots-clés.")
        _STATE["bundle"] = None
        _model = None


def _keyword_hits_by_category(title: str) -> dict[str, int]:
    text = _normalize(title)
    words = set(text.replace("-", " ").split())
    # Gérer également le singulier simple (sans 's' final) pour les mots de plus de 4 lettres
    stems = {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words}
    all_tokens = words | stems

    hits_map: dict[str, int] = {}
    for category, keys in KEYWORDS.items():
        hits = 0
        for k in keys:
            k_norm = _normalize(k).strip()
            if " " in k_norm:
                if k_norm in text:
                    hits += 2  # Expression multi-mots (ex: "micro cravate", "beurre de karite") = poids double
            else:
                if k_norm in all_tokens:
                    hits += 1
        if hits > 0:
            hits_map[category] = hits
    return hits_map


def _by_keywords(title: str) -> dict:
    hits_map = _keyword_hits_by_category(title)
    if not hits_map:
        return {
            "category": None,
            "sous_categorie": None,
            "accepte": False,
            "propositions": [],
            "source": "keywords",
        }
    best = max(hits_map, key=lambda k: hits_map[k])
    sub = DEFAULT_SUBCATEGORY.get(best)
    return {
        "category": best,
        "sous_categorie": sub,
        "accepte": True,
        "propositions": [
            {"sous_categorie": DEFAULT_SUBCATEGORY.get(cat, cat), "category": cat, "score": float(score)}
            for cat, score in sorted(hits_map.items(), key=lambda x: -x[1])[:3]
        ],
        "source": "keywords",
    }


def predict_category(title: str) -> dict:
    """
    Renvoie :
      category        catégorie Lafi (ex. "Mode") ou None
      sous_categorie  classe fine du modèle (ex. "Sacs & portefeuilles")
      accepte         True = sûr : l'app peut pré-remplir ; False = incertain
      propositions    les 3 meilleures classes fines avec leur score
      source          "model", "keywords" ou "none"
    """
    title = (title or "").strip()
    if not title:
        return {"category": None, "sous_categorie": None, "accepte": False, "propositions": [], "source": "none"}

    _load()
    bundle = _STATE["bundle"]
    if bundle is None:
        return _by_keywords(title)

    try:
        raw_scores = bundle["model"].decision_function([title])[0][_STATE["keep"]].copy()
    except Exception:
        log.exception("Échec de la prédiction : repli par mots-clés.")
        return _by_keywords(title)

    # 1. Fusion hybride : renforcement des sous-catégories lorsqu'un mot-clé métier / ivoirien est reconnu
    hits_map = _keyword_hits_by_category(title)
    if hits_map:
        for idx, fine_name in enumerate(_STATE["names"]):
            parent_cat = CATEGORY_MAP.get(str(fine_name))
            if parent_cat and parent_cat in hits_map:
                raw_scores[idx] += 0.38 * min(hits_map[parent_cat], 3)

    order = np.argsort(raw_scores)[::-1][:3]
    names = [str(_STATE["names"][i]) for i in order]
    top_cats = [CATEGORY_MAP.get(n) for n in names]

    gap = float(raw_scores[order[0]] - raw_scores[order[1]])
    base_threshold = float(bundle["threshold"])

    # 2. Règle de consensus par catégorie Lafi :
    #    Si la 1re et la 2e sous-catégorie appartiennent à la MÊME catégorie Lafi
    #    (ex: "Audio & enceintes" et "Écouteurs & casques" -> "Électronique"),
    #    le modèle n'hésite que sur la sous-catégorie fine mais est certain de la catégorie Lafi !
    same_parent_top2 = (top_cats[0] is not None and top_cats[0] == top_cats[1] and float(raw_scores[order[0]]) > -0.25)
    keyword_confirmed = (top_cats[0] is not None and top_cats[0] in hits_map)

    accepte = (gap >= base_threshold) or same_parent_top2 or keyword_confirmed
    fine = names[0]
    category = top_cats[0]
    if category not in LAFI_CATEGORIES:
        category = None

    return {
        "category": category,
        "sous_categorie": fine,
        "accepte": bool(accepte and category is not None),
        "propositions": [
            {"sous_categorie": n, "category": CATEGORY_MAP.get(n), "score": round(float(raw_scores[i]), 3)}
            for n, i in zip(names, order)
        ],
        "source": "model",
    }


def load_model() -> None:
    """À appeler au démarrage du serveur pour ne pas faire attendre la première requête."""
    _load()
