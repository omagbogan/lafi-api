"""
lafi-api/app/category_model.py
------------------------------
Suggère la catégorie d'un article à partir de son titre.

Deux sources, dans cet ordre :
  1. le classifieur entraîné (models/category.joblib)  -> source = "model"
  2. un repli par mots-clés si le modèle est absent, illisible ou en panne -> source = "keywords"

Le fichier models/category.joblib est celui produit par train_text_classifier.py
(output_model/model_text.joblib, à copier et renommer). C'est un dictionnaire :
    {"model": <pipeline scikit-learn>, "threshold": <seuil d'écart>, "local_classes": [...], ...}

IMPORTANT : la version de scikit-learn du venv de l'API doit être identique à celle qui a
entraîné le modèle. Vérifie dans les deux environnements : python -m pip show scikit-learn
"""

import logging
import unicodedata
from pathlib import Path

import numpy as np

log = logging.getLogger("lafi.category")

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "category.joblib"

# Catégories que l'application sait afficher aujourd'hui.
LAFI_CATEGORIES = {"Alimentation", "Mode", "Beauté", "Électronique", "Maison", "Bébé"}

# Classe fine du modèle (31 classes locales)  ->  catégorie de l'application.
# None = pas de catégorie équivalente dans Lafi pour l'instant (on garde la classe fine).
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

# Repli simple si le modèle n'est pas disponible
KEYWORDS = {
    "Alimentation": ["riz", "huile", "tomate", "oignon", "poisson", "viande", "poulet", "attieke", "banane",
                     "igname", "manioc", "sucre", "farine", "lait", "cafe", "the", "jus", "eau", "biere", "epice"],
    "Mode": ["robe", "pagne", "wax", "chemise", "pantalon", "jupe", "sac", "chaussure", "sandale", "basket",
             "montre", "bijou", "collier", "bracelet", "casquette", "t-shirt", "tshirt", "boubou"],
    "Beauté": ["creme", "savon", "parfum", "huile de coco", "karite", "shampoing", "cheveux", "perruque",
               "mèche", "meche", "maquillage", "rouge a levres", "vernis", "lotion"],
    "Électronique": ["telephone", "smartphone", "iphone", "samsung", "tecno", "infinix", "tablette", "ecouteur",
                     "chargeur", "cable", "powerbank", "enceinte", "television", "tv", "ordinateur", "laptop"],
    "Maison": ["ventilateur", "mixeur", "casserole", "poele", "assiette", "drap", "rideau", "matelas",
               "lampe", "ampoule", "fer a repasser", "seau", "balai", "serpilliere"],
    "Bébé": ["biberon", "couche", "couches", "pampers", "lingette", "lait de croissance", "tetine",
             "poussette", "bavoir", "body bebe", "jouet bebe"],
}

_STATE = {"loaded": False, "bundle": None, "keep": None, "names": None}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _load():
    """Charge le modèle une seule fois. En cas d'échec, on garde le repli (l'API démarre quand même)."""
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
        log.info("Classifieur chargé : %s", bundle.get("model_name", "?"))
    except Exception:  # version de scikit-learn différente, fichier corrompu...
        log.exception("Impossible de charger le modèle : repli par mots-clés.")
        _STATE["bundle"] = None


def _by_keywords(title: str) -> dict:
    text = _normalize(title)
    words = set(text.replace("-", " ").split())
    best, best_hits = None, 0
    for category, keys in KEYWORDS.items():
        hits = sum(1 for k in keys if (k in words if " " not in k else k in text))
        if hits > best_hits:
            best, best_hits = category, hits
    return {"category": best, "sous_categorie": None, "accepte": best is not None,
            "propositions": [], "source": "keywords"}

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
        scores = bundle["model"].decision_function([title])[0][_STATE["keep"]]
    except Exception:
        log.exception("Échec de la prédiction : repli par mots-clés.")
        return _by_keywords(title)

    order = np.argsort(scores)[::-1][:3]
    names = [str(_STATE["names"][i]) for i in order]
    gap = float(scores[order[0]] - scores[order[1]])
    accepte = gap >= float(bundle["threshold"])
    fine = names[0]
    category = CATEGORY_MAP.get(fine)
    if category not in LAFI_CATEGORIES:
        category = None

    result = {
        "category": category,
        "sous_categorie": fine,
        "accepte": bool(accepte and category is not None),
        "propositions": [
            {"sous_categorie": n, "category": CATEGORY_MAP.get(n), "score": round(float(scores[i]), 3)}
            for n, i in zip(names, order)
        ],
        "source": "model",
    }

    # Le modèle hésite : on tente les mots-clés (produits locaux : attiéké, karité, pagne...)
    if not result["accepte"]:
        by_words = _by_keywords(title)
        if by_words["category"] is not None:
            return {
                "category": by_words["category"],
                "sous_categorie": None,
                "accepte": True,
                "propositions": result["propositions"],
                "source": "keywords",
            }

    return result


def load_model() -> None:
    """À appeler au démarrage du serveur pour ne pas faire attendre la première requête."""
    _load()