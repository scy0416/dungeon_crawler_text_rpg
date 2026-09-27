from fastapi import FastAPI

from app.routes import router

app = FastAPI(title="character-service")
app.include_router(router)
