from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import router as api_router
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.operations import router as operations_router
from app.api.anomalies import router as anomalies_router
from app.api.assistant import router as assistant_router
from app.api.reports import router as reports_router
from app.api.faces import router as faces_router


def create_app() -> FastAPI:
    settings.validate_runtime_security()

    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="HR Attendance Copilot Backend API",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    application.include_router(api_router)
    application.include_router(auth_router)
    application.include_router(admin_router)
    application.include_router(operations_router)
    application.include_router(anomalies_router)
    application.include_router(assistant_router)
    application.include_router(reports_router)
    application.include_router(faces_router)
    return application


app = create_app()
