"""
Multi-Platform Deep Researcher - FastAPI Backend
Run: uvicorn app:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import asyncio

from researcher import deep_research

app = FastAPI(
    title="Multi-Platform Deep Researcher API",
    description="Aggregates research results from Wikipedia, arXiv, Web, Books, and CrossRef simultaneously.",
    version="1.0.0",
)

# Allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────

class ResearchRequest(BaseModel):
    query: str
    platforms: Optional[List[str]] = None  # None = all platforms


class HealthResponse(BaseModel):
    status: str
    version: str
    platforms_available: List[str]


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
async def serve_frontend():
    """Serve the main UI."""
    return FileResponse("static/index.html")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return {
        "status": "running",
        "version": "1.0.0",
        "platforms_available": ["wikipedia", "arxiv", "web", "books", "crossref"],
    }


@app.post("/research")
async def research(request: ResearchRequest):
    """
    Main research endpoint.
    Accepts a query and optional list of platforms.
    Returns aggregated results from all selected platforms.
    """
    if not request.query or len(request.query.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters.")

    if len(request.query) > 300:
        raise HTTPException(status_code=400, detail="Query too long. Max 300 characters.")

    result = await deep_research(
        query=request.query.strip(),
        platforms=request.platforms,
    )
    return result


@app.get("/platforms")
async def list_platforms():
    """List all supported research platforms."""
    return {
        "platforms": [
            {"id": "wikipedia", "name": "Wikipedia", "icon": "📚", "description": "Free encyclopedia"},
            {"id": "arxiv", "name": "arXiv", "icon": "🎓", "description": "Academic preprints (CS, Physics, Math, Biology)"},
            {"id": "web", "name": "Web Search", "icon": "🌐", "description": "DuckDuckGo instant answers"},
            {"id": "books", "name": "Open Library", "icon": "📖", "description": "Internet Archive's book database"},
            {"id": "crossref", "name": "CrossRef", "icon": "🔬", "description": "Academic DOI and publications index"},
        ]
    }
