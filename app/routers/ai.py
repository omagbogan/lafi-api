from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, SQLModel

from ..agent import find_product_from_image, generate_product_description, run_agent
from ..category_model import predict_category
from ..db import get_session
from ..geo import DEFAULT_LAT, DEFAULT_LNG
from ..image_model import enhance_image, predict_image
from ..models import ArticleOut

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


# ---------- Assistant / Agent IA conversationnel (Bloc 4) ----------

class AssistantTurn(SQLModel):
    role: str
    content: str


class AssistantRequest(SQLModel):
    message: str
    lat: float = DEFAULT_LAT
    lng: float = DEFAULT_LNG
    history: list[AssistantTurn] = []


class AssistantResponse(SQLModel):
    reply: str
    recommended_articles: list[ArticleOut] = []
    intent: str
    source: str = "agent-local"
    accepte: bool = True


@router.post("/assistant", response_model=AssistantResponse)
def ask_assistant(data: AssistantRequest, session: Session = Depends(get_session)):
    history_dicts = [{"role": t.role, "content": t.content} for t in data.history]
    result = run_agent(data.message, session, data.lat, data.lng, history=history_dicts)
    return AssistantResponse(
        reply=result["reply"],
        recommended_articles=result["recommended_articles"],
        intent=result["intent"],
        source=result.get("source", "agent-local"),
        accepte=True,
    )


@router.post("/assistant-image", response_model=AssistantResponse)
def ask_assistant_image(file: UploadFile = File(...), session: Session = Depends(get_session)):
    data = file.file.read()
    if len(data) > 8_000_000:
        raise HTTPException(413, "Image trop lourde (8 Mo maximum).")
    result = find_product_from_image(data, session)
    return AssistantResponse(
        reply=result["reply"],
        recommended_articles=result["recommended_articles"],
        intent=result["intent"],
        source=result.get("source", "agent-local-vision"),
        accepte=True,
    )


# ---------- Générateur de description commerciale IA (Commerçant) ----------

class DescriptionRequest(SQLModel):
    title: str
    category: Optional[str] = None
    price: Optional[int] = None
    negotiable: bool = False


class DescriptionResponse(SQLModel):
    description: str
    source: str = "local-template"
    accepte: bool = True


@router.post("/generate-description", response_model=DescriptionResponse)
def generate_description_route(data: DescriptionRequest):
    if not data.title.strip():
        raise HTTPException(422, "Le titre de l'article est requis pour générer une description.")
    result = generate_product_description(
        title=data.title,
        category=data.category,
        price=data.price,
        negotiable=data.negotiable,
    )
    return DescriptionResponse(**result)


# ---------- Amélioration et recadrage photo réel (Pillow) ----------

class ImproveImageResponse(SQLModel):
    url: str
    source: str = "pillow-enhancer"
    accepte: bool = True


@router.post("/improve-image", response_model=ImproveImageResponse)
def improve_image_route(file: UploadFile = File(...)):
    data = file.file.read()
    if len(data) > 8_000_000:
        raise HTTPException(413, "Image trop lourde (8 Mo maximum).")
    try:
        result = enhance_image(data)
        return ImproveImageResponse(**result)
    except ValueError as error:
        raise HTTPException(422, str(error))
