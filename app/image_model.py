"""
lafi-api/app/image_model.py
---------------------------
Suggère la catégorie d'un article à partir de sa PHOTO (Bloc 2 — Modèle Vision).

Améliorations de performance :
  1. Test-Time Augmentation (TTA Multi-Vues) : combine un recadrage centré respectant
     les proportions (`Resize(256) + CenterCrop(224)`), une vue complète et un miroir horizontal
     pour éviter la déformation des photos prises au smartphone.
  2. Filtrage des classes hors-périmètre (`HOBBY_ARTS_STATIONERY`, `PET_SUPPLIES`) et rattachement
     de `SPORTS_OUTDOOR` (baskets, survêtements) vers `Mode`, avec renormalisation Softmax
     sur les 6 catégories officielles de Lafi.
  3. Renfort Multimodal Hybride lorsque la confiance de MobileNetV2 est inférieure au seuil
     (ex: plats locaux ivoiriens ou équipements spécifiques).
"""

import base64
import io
import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Optional

from .config import OPENROUTER_API_KEY

log = logging.getLogger("lafi.image")

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "image.pt"

# Catégories officielles de l'application Lafi (doivent rester identiques partout).
LAFI_CATEGORIES = {"Alimentation", "Mode", "Beauté", "Électronique", "Maison", "Bébé"}

# Classe du dataset d'images -> catégorie officielle Lafi
IMAGE_CATEGORY_MAP = {
    "GROCERY": "Alimentation",
    "CLOTHING_ACCESSORIES_JEWELLERY": "Mode",
    "SPORTS_OUTDOOR": "Mode",
    "BEAUTY_HEALTH": "Beauté",
    "ELECTRONICS": "Électronique",
    "BABY_PRODUCTS": "Bébé",
    "HOME_KITCHEN_TOOLS": "Maison",
    "HOBBY_ARTS_STATIONERY": None,
    "PET_SUPPLIES": None,
}

CATEGORY_TO_CLASS = {
    "Alimentation": "GROCERY",
    "Mode": "CLOTHING_ACCESSORIES_JEWELLERY",
    "Beauté": "BEAUTY_HEALTH",
    "Électronique": "ELECTRONICS",
    "Maison": "HOME_KITCHEN_TOOLS",
    "Bébé": "BABY_PRODUCTS",
}

_STATE = {
    "loaded": False,
    "model": None,
    "bundle": None,
    "tf_center": None,
    "tf_full": None,
    "torch": None,
}
_model = None


def _load():
    """Charge le modèle une seule fois ; en cas d'échec, la route répond « modèle indisponible »."""
    global _model
    if _STATE["loaded"]:
        return
    _STATE["loaded"] = True
    if not MODEL_PATH.is_file():
        log.warning("Modèle d'images absent (%s).", MODEL_PATH)
        return
    try:
        import torch
        import torch.nn as nn
        from torchvision import models
        from torchvision import transforms as T

        bundle = torch.load(MODEL_PATH, map_location="cpu")
        model = models.mobilenet_v2(weights=None)
        model.classifier = nn.Sequential(nn.Dropout(0.2), nn.Linear(1280, len(bundle["classes"])))
        model.load_state_dict(bundle["state_dict"])
        model.eval()

        norm = T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        tf_center = T.Compose([T.Resize(256), T.CenterCrop(224), T.ToTensor(), norm])
        tf_full = T.Compose([T.Resize((224, 224)), T.ToTensor(), norm])

        _STATE.update(
            model=model,
            bundle=bundle,
            torch=torch,
            tf_center=tf_center,
            tf_full=tf_full,
        )
        _model = model
        log.info("Modèle d'images chargé (%s).", bundle.get("approche", "?"))
    except Exception:
        log.exception("Impossible de charger le modèle d'images.")
        _STATE["model"] = None
        _model = None


def _verify_category_with_vision_llm(image) -> Optional[str]:
    """
    Confirmation légère par Vision LLM lorsque MobileNetV2 hésite (confiance < seuil),
    par exemple sur des plats ivoiriens (attiéké, garba, alloco) ou des appareils spécifiques.
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    api_key = groq_key or (OPENROUTER_API_KEY or "").strip()
    if not api_key:
        return None

    try:
        thumb = image.copy()
        thumb.thumbnail((512, 512))
        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=78)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

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

        prompt = (
            "Classe cette photo de produit dans UNE SEULE des 6 catégories officielles de Lafi :\n"
            "Alimentation, Mode, Beauté, Électronique, Maison, Bébé.\n"
            'Réponds uniquement au format JSON strict : {"category": "..."}'
        )

        payload = {
            "model": vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 40,
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Lafi-Image-Classifier/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            parsed = json.loads(res_data["choices"][0]["message"]["content"])
            cat = parsed.get("category")
            if cat in LAFI_CATEGORIES:
                return cat
    except Exception:
        pass
    return None


def predict_image(data: bytes) -> dict:
    """
    Renvoie :
      category        catégorie Lafi (ex. "Alimentation") ou None
      classe_image    classe du dataset (ex. "GROCERY")
      confiance       probabilité de la 1re proposition (0 à 1)
      accepte         True = assez sûr pour pré-remplir ; False = montrer les propositions
      propositions    les 3 meilleures classes avec leur probabilité
      source          "image-model"
    Lève ValueError si le fichier n'est pas une image lisible.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as im:
            image = ImageOps.exif_transpose(im).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("Le fichier envoyé n'est pas une image lisible.")

    _load()
    if _STATE["model"] is None:
        return {
            "category": None,
            "classe_image": None,
            "confiance": 0.0,
            "accepte": False,
            "propositions": [],
            "source": "indisponible",
        }

    torch, bundle = _STATE["torch"], _STATE["bundle"]
    classes = list(bundle["classes"])

    # 1. Test-Time Augmentation (TTA sur 3 vues : CenterCrop, Vue complète, Miroir horizontal)
    flipped = ImageOps.mirror(image)
    batch = torch.stack([
        _STATE["tf_center"](image),
        _STATE["tf_full"](image),
        _STATE["tf_center"](flipped),
    ])

    with torch.no_grad():
        logits = _STATE["model"](batch)
        # Pondération : 50% CenterCrop (sans déformation), 25% Vue complète, 25% Miroir
        weights = torch.tensor([[0.50], [0.25], [0.25]])
        avg_logits = (logits * weights).sum(dim=0)

        # 2. Masquage des classes hors-périmètre Lafi (None) pour éviter qu'elles volent la probabilité
        for idx, cls_name in enumerate(classes):
            if IMAGE_CATEGORY_MAP.get(cls_name) is None:
                avg_logits[idx] = -1e9

        probs = torch.softmax(avg_logits, dim=0).tolist()

    # 3. Si MobileNetV2 hésite (confiance < seuil), confirmation intelligente pour recalibrer les scores
    threshold = float(bundle["threshold"])
    top_idx = max(range(len(classes)), key=lambda i: probs[i])
    if probs[top_idx] < threshold:
        confirmed_cat = _verify_category_with_vision_llm(image)
        if confirmed_cat and confirmed_cat in CATEGORY_TO_CLASS:
            target_cls = CATEGORY_TO_CLASS[confirmed_cat]
            if target_cls in classes:
                t_idx = classes.index(target_cls)
                avg_logits[t_idx] = avg_logits[top_idx] + 1.25
                probs = torch.softmax(avg_logits, dim=0).tolist()

    order = sorted(range(len(classes)), key=lambda i: probs[i], reverse=True)[:3]
    best = classes[order[0]]
    category = IMAGE_CATEGORY_MAP.get(best)
    if category not in LAFI_CATEGORIES:
        category = None

    # Acceptation si la probabilité dépasse le seuil OU si l'écart avec la 2e catégorie est franc (>= 0.22)
    gap = probs[order[0]] - probs[order[1]] if len(order) > 1 else probs[order[0]]
    accepte = (probs[order[0]] >= threshold or gap >= 0.22) and category is not None

    return {
        "category": category,
        "classe_image": best,
        "confiance": round(probs[order[0]], 3),
        "accepte": bool(accepte),
        "propositions": [
            {
                "classe_image": classes[i],
                "category": IMAGE_CATEGORY_MAP.get(classes[i]),
                "probabilite": round(probs[i], 3),
            }
            for i in order
        ],
        "source": "image-model",
    }


def enhance_image(data: bytes) -> dict:
    """
    Améliore réellement la photo d'un produit avec Pillow :
      1. Redressement de l'orientation EXIF
      2. Recadrage centré au format carré et redimensionnement propre (max 900x900)
      3. Égalisation automatique douce (autocontrast)
      4. Rehaussement de la luminosité (+6%), du contraste (+14%), de la saturation (+10%) et de la netteté (+30%)
      5. Sauvegarde dans uploads/ et renvoi de l'URL
    """
    from uuid import uuid4
    from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError
    from .config import UPLOAD_DIR

    try:
        with Image.open(io.BytesIO(data)) as im:
            image = ImageOps.exif_transpose(im).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("Le fichier envoyé n'est pas une image lisible.")

    # Recadrage centré au carré si nécessaire
    w, h = image.size
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        image = image.crop((left, top, left + side, top + side))

    if image.width > 900:
        image = image.resize((900, 900), Image.Resampling.LANCZOS)

    # Traitement visuel : autocontraste léger + rehaussement couleurs et netteté
    image = ImageOps.autocontrast(image, cutoff=1)
    image = ImageEnhance.Brightness(image).enhance(1.06)
    image = ImageEnhance.Contrast(image).enhance(1.14)
    image = ImageEnhance.Color(image).enhance(1.10)
    image = ImageEnhance.Sharpness(image).enhance(1.30)

    filename = f"enhanced_{uuid4().hex}.jpg"
    output_path = UPLOAD_DIR / filename
    image.save(output_path, format="JPEG", quality=90, optimize=True)

    return {
        "url": f"/uploads/{filename}",
        "source": "pillow-enhancer",
        "accepte": True,
    }


def load_model() -> None:
    """À appeler au démarrage du serveur pour ne pas faire attendre la première requête."""
    _load()
