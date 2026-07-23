from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import Base, engine, ensure_development_columns
from .routers import admin, auth, feedback, imports, library, public
from . import models  # noqa: F401

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.environment == "development":
        Path(".data").mkdir(parents=True, exist_ok=True)
        Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(bind=engine)
        ensure_development_columns()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Public and private mystery-fiction archive API.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(imports.router, prefix="/api/v1")
app.include_router(library.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(feedback.maintenance_router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mystery-atlas-api"}
