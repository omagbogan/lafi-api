from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, SQLModel

from ..agent import run_agent
from ..category_model import predict_category
from ..db import get_session
from ..geo import DEFAULT_LAT, DEFAULT_LNG
from ..image_model import predict_image
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

class AssistantRequest(SQLModel):
    message: str
    lat: float = DEFAULT_LAT
    lng: float = DEFAULT_LNG


class AssistantResponse(SQLModel):
    reply: str
    recommended_articles: list[ArticleOut] = []
    intent: str
    source: str = "agent-local"
    accepte: bool = True


@router.post("/assistant", response_model=AssistantResponse)
def ask_assistant(data: AssistantRequest, session: Session = Depends(get_session)):
    result = run_agent(data.message, session, data.lat, data.lng)
    return AssistantResponse(
        reply=result["reply"],
        recommended_articles=result["recommended_articles"],
        intent=result["intent"],
        source="agent-local",
        accepte=True,
    )
