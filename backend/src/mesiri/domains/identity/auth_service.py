import os
from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# The fallback is public (it is in this repository), so a server running on it
# accepts tokens anyone can forge. jwt_secret_is_default() lets startup say so.
_DEFAULT_SECRET = "mesiri-temp-secret-key-change-in-production"
SECRET_KEY = os.environ.get("MESIRI_JWT_SECRET") or _DEFAULT_SECRET
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week


def jwt_secret_is_default() -> bool:
    """True when logins are signed with the public fallback secret (BE-31)."""
    return SECRET_KEY == _DEFAULT_SECRET


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
