from fastapi import FastAPI

from app.errors import register_error_handlers
from app.routes import router

app = FastAPI(title="character-service")
register_error_handlers(app)
app.include_router(router)
