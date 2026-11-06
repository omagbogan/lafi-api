"""
lafi-api/app/image_model.py
---------------------------
Suggère la catégorie d'un article à partir de sa PHOTO.

Le fichier models/image.pt est celui produit par train_image_classifier.py
(output_image_model8/model_image.pt, à copier et renommer).

Dépendances de l'API (en plus de FastAPI) :  pip install torch torchvision pillow
(la version CPU suffit : l'API n'a besoin que de prédire, pas d'entraîner)

Utilisation dans une route (exemple pour routers/ai.py) :

    from fastapi import APIRouter, File, HTTPException, UploadFile
    from app.image_model import predict_image

    @router.post("/ai/category-image")
    async def category_from_image(file: UploadFile = File(...)):
        data = await file.read()
        if len(data) > 8_000_000:
            raise HTTPException(413, "Image trop lourde (8 Mo maximum).")
        try:
            return predict_image(data)
        except ValueError as error:
            raise HTTPException(422, str(error))
"""

import io
import logging
from pathlib import Path

log = logging.getLogger("lafi.image")

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "image.pt"

# Catégories que l'application sait afficher aujourd'hui.
LAFI_CATEGORIES = {"Alimentation", "Mode", "Beauté", "Électronique", "Maison", "Bébé"}

# Classe du dataset d'images -> catégorie de l'application (None = pas d'équivalent pour l'instant)
IMAGE_CATEGORY_MAP = {
    "GROCERY": "Alimentation",
    "CLOTHING_ACCESSORIES_JEWELLERY": "Mode",
    "BEAUTY_HEALTH": "Beauté",
    "ELECTRONICS": "Électronique",
    "BABY_PRODUCTS": "Bébé",
    "HOME_KITCHEN_TOOLS": "Maison",
    "HOBBY_ARTS_STATIONERY": None,
    "PET_SUPPLIES": None,
    "SPORTS_OUTDOOR": None,
}

_STATE = {"loaded": False, "model": None, "bundle": None, "tf": None, "torch": None}


def _load():
    """Charge le modèle une seule fois ; en cas d'échec, la route répond « modèle indisponible »."""
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
        _STATE.update(model=model, bundle=bundle, torch=torch, tf=T.Compose([
            T.Resize((224, 224)), T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]))
        log.info("Modèle d'images chargé (%s).", bundle.get("approche", "?"))
    except Exception:
        log.exception("Impossible de charger le modèle d'images.")
        _STATE["model"] = None


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
        return {"category": None, "classe_image": None, "confiance": 0.0, "accepte": False,
                "propositions": [], "source": "indisponible"}

    torch, bundle = _STATE["torch"], _STATE["bundle"]
    with torch.no_grad():
        x = _STATE["tf"](image).unsqueeze(0)
        probs = torch.softmax(_STATE["model"](x), dim=1)[0].tolist()
    classes = bundle["classes"]
    order = sorted(range(len(classes)), key=lambda i: probs[i], reverse=True)[:3]
    best = classes[order[0]]
    category = IMAGE_CATEGORY_MAP.get(best)
    if category not in LAFI_CATEGORIES:
        category = None
    accepte = probs[order[0]] >= float(bundle["threshold"]) and category is not None
    return {
        "category": category,
        "classe_image": best,
        "confiance": round(probs[order[0]], 3),
        "accepte": bool(accepte),
        "propositions": [{"classe_image": classes[i], "category": IMAGE_CATEGORY_MAP.get(classes[i]),
                          "probabilite": round(probs[i], 3)} for i in order],
        "source": "image-model",
    }

def load_model() -> None:
    """À appeler au démarrage du serveur pour ne pas faire attendre la première requête."""
    _load()