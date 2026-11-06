from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from .config import UPLOAD_DIR
from .db import engine, init_db
from .routers import ai, articles, orders, uploads
from .seed import seed

from .category_model import load_model

from .image_model import load_model as load_image_model


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as session:
        seed(session)
        load_model()
        load_image_model()
    yield


app = FastAPI(title="Lafi API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

app.include_router(articles.router)
app.include_router(orders.router)
app.include_router(uploads.router)
app.include_router(ai.router)


@app.get("/health")
def health():
    return {"status": "ok"}