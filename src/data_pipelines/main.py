"""Main application entry point."""
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Data Pipelines ETL API",
        description="LLM-powered ETL for unstructured data extraction, transformation, and loading",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    from data_pipelines.api.routes import router
    app.include_router(router)

    @app.get("/")
    async def root():
        return {
            "service": "Data Pipelines ETL",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    return app


app = create_app()

if __name__ == "__main__":
    from data_pipelines.config.settings import get_settings
    settings = get_settings()
    uvicorn.run("data_pipelines.main:app", host=settings.api.host, port=settings.api.port, reload=settings.api.reload)
