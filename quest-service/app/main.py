from fastapi import FastAPI

from app.routes import router

app = FastAPI(title="quest-service")
app.include_router(router)
