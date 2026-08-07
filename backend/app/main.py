"""MERROR backend — FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="MERROR",
    description="Local-first memory + chat backend.",
    version="0.1.0",
)

# The frontend runs on a separate localhost port, so it needs explicit CORS
# permission. Origins stay hardcoded to localhost until Slice 3 moves them
# into config — nothing here is ever exposed beyond this machine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"name": "MERROR", "status": "ok", "slice": 2}


@app.get("/health")
async def health():
    return {"status": "healthy"}
