from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlmodel import SQLModel

from ..category_model import predict_category
from ..image_model import predict_image

router = APIRouter(prefix="/ai")


# ---------- Catégorie à partir du titre ----------

class CategoryRequest(SQLModel):
    title: str


class Proposal(SQLModel):
    sous_categorie: str
    category: Optional[str] = None
    score: float


class CategoryResponse(SQLModel):
    category: Optional[str] = None
    sous_categorie: Optional[str] = None
    accepte: bool = False
    propositions: list[Proposal] = []
    source: str = "none"


@router.post("/category", response_model=CategoryResponse)
def suggest_category(data: CategoryRequest):
    return predict_category(data.title)


# ---------- Catégorie à partir de la photo ----------

class ImageProposal(SQLModel):
    classe_image: str
    category: Optional[str] = None
    probabilite: float


class ImageCategoryResponse(SQLModel):
    category: Optional[str] = None
    classe_image: Optional[str] = None
    confiance: float = 0.0
    accepte: bool = False
    propositions: list[ImageProposal] = []
    source: str = "image-model"


@router.post("/category-image", response_model=ImageCategoryResponse)
def category_from_image(file: UploadFile = File(...)):
    data = file.file.read()
    if len(data) > 8_000_000:
        raise HTTPException(413, "Image trop lourde (8 Mo maximum).")
    try:
        return predict_image(data)
    except ValueError as error:
        raise HTTPException(422, str(error))