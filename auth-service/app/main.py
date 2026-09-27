import logging

from fastapi import FastAPI

from app.db import DEV_JWT_SECRET, settings
from app.errors import register_error_handlers
from app.observability import add_correlation_middleware, setup_logging
from app.routes import SERVICE_NAME, router

setup_logging(SERVICE_NAME)

if settings.jwt_secret == DEV_JWT_SECRET:
    logging.getLogger(__name__).warning(
        "JWT_SECRET is not set: using the insecure development default. Set it as a secret in deployment."
    )

app = FastAPI(title=SERVICE_NAME)
add_correlation_middleware(app)
register_error_handlers(app)
app.include_router(router)
