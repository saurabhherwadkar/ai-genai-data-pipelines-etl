"""Main application entry point."""
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

def create_app() -> FastAPI:
    app = FastAPI(title="Data Pipelines ETL API", description="LLM-powered ETL for unstructured data", version="1.0.0")
    return app

app = create_app()

if __name__ == "__main__":
    from data_pipelines.config.settings import get_settings
    settings = get_settings()
    uvicorn.run("data_pipelines.main:app", host=settings.api.host, port=settings.api.port, reload=settings.api.reload)
