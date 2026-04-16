"""FastAPI application for MobilityTwin."""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_dir = Path(__file__).resolve().parent
_frontend_dist = _dir / "frontend" / "dist"

load_dotenv(_dir / ".env")

app = FastAPI(title="MobilityTwin", docs_url="/docs")

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers import api, chat  # noqa: E402

app.include_router(api.router, prefix="/api")
app.include_router(chat.router, prefix="/api")

# Serve compiled React frontend
if _frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="frontend-assets")

    @app.get("/{rest:path}")
    async def serve_frontend():
        return FileResponse(_frontend_dist / "index.html")
else:
    # Fallback: serve legacy Jinja templates when frontend is not built
    from fastapi.templating import Jinja2Templates

    app.mount("/static", StaticFiles(directory=_dir / "static"), name="static")
    templates = Jinja2Templates(directory=_dir / "templates")

    from routers import pages  # noqa: E402
    app.include_router(pages.router)
