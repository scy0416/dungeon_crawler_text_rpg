from fastapi import FastAPI

from app.errors import register_error_handlers
from app.observability import add_correlation_middleware, setup_logging
from app.routes import SERVICE_NAME, router

setup_logging(SERVICE_NAME)

app = FastAPI(title=SERVICE_NAME)
add_correlation_middleware(app)
register_error_handlers(app)
app.include_router(router)
