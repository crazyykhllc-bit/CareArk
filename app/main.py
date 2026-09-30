from pathlib import Path

from fastapi import Depends, FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_model_settings
from app.api import admin, archive, auth, drafts, export, medications, uploads, batches, encounters, metrics, overview, costs, test_sessions, care_history, care_hierarchy, profiles


def create_app() -> FastAPI:
    app = FastAPI(title="个人健康档案工作台")
    app.include_router(auth.router)
    app.include_router(profiles.router)
    app.include_router(admin.router)
    app.include_router(uploads.router)
    app.include_router(drafts.router)
    app.include_router(archive.router)
    app.include_router(medications.router)
    app.include_router(export.router)
    app.include_router(batches.router)
    app.include_router(encounters.router)
    app.include_router(care_history.router)
    app.include_router(care_hierarchy.router)
    app.include_router(metrics.router)
    app.include_router(overview.router)
    app.include_router(costs.router)
    app.include_router(test_sessions.router)
    web_dir = Path(__file__).parent / "web"
    app.mount("/assets", StaticFiles(directory=web_dir), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(web_dir / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/system/status")
    def system_status(response: Response, settings: Settings = Depends(get_model_settings)) -> dict[str, dict[str, bool]]:
        response.headers["Cache-Control"] = "no-store"
        return {"model": {
            "configured": bool(settings.model_api_key and settings.model_name),
            "fallback_configured": bool(settings.model_fallback_base_url and
                                        settings.model_fallback_api_key and settings.model_fallback_name),
            "fallback2_configured": bool(settings.model_fallback2_base_url and
                                         settings.model_fallback2_api_key and settings.model_fallback2_name),
        }}

    return app


app = create_app()
