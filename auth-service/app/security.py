from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.db import settings
from app.schemas import VerifyResponse


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed_password.encode())


def create_access_token(user_id: int, username: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    claims = {"sub": str(user_id), "username": username, "exp": expire}
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> VerifyResponse | None:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return VerifyResponse(user_id=int(claims["sub"]), username=claims["username"])
    except (JWTError, KeyError, ValueError):
        return None
