"""MERROR backend — FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import MissingConfigError, get_settings, startup_report
from app.routers import chat, memories, voice

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("merror")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Print config state before serving, so a missing key is obvious in the
    # terminal rather than a surprise 503 twenty minutes later.
    print(startup_report(), flush=True)
    yield


app = FastAPI(
    title="MERROR",
    description="Local-first memory + chat backend.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(memories.router)
app.include_router(chat.router)
app.include_router(voice.router)


@app.exception_handler(MissingConfigError)
async def missing_config_handler(request: Request, exc: MissingConfigError):
    """Turn an unconfigured key into an actionable 503 rather than a 500."""
    logger.error("Configuration error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"error": "configuration_missing", "detail": str(exc)},
    )


@app.get("/")
async def root():
    return {"name": "MERROR", "status": "ok", "slice": 15}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/config/status")
async def config_status():
    """Report what is configured, so the UI can prompt for missing keys.

    Deliberately returns only booleans and non-secret values — key material
    must never cross this boundary.
    """
    missing = settings.missing_keys()
    return {
        "configured": not missing,
        "missing": missing,
        "features": {
            "chat": "ANTHROPIC_API_KEY" not in missing,
            "vision": "ANTHROPIC_API_KEY" not in missing,
            # Speech-to-text runs locally, so it needs no key at all.
            "voice_in": True,
            "voice_out": "ELEVENLABS_API_KEY" not in missing,
        },
        "model": settings.anthropic_model,
    }
