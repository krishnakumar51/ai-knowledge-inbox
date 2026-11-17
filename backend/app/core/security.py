import base64
import hashlib
import hmac
import json
import secrets
import time
from uuid import UUID

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _secret() -> bytes:
    value = get_settings().jwt_secret_key
    if not value or len(value) < 32:
        raise ServiceUnavailableError(
            "Authentication is not configured; set JWT_SECRET_KEY to a random value of at least 32 characters"
        )
    return value.encode()


def require_auth_configuration() -> None:
    _secret()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode(),
            salt=base64.urlsafe_b64decode(salt + "=="),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
        return hmac.compare_digest(derived, base64.urlsafe_b64decode(expected + "=="))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: UUID) -> str:
    settings = get_settings()
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(
        json.dumps(
            {
                "sub": str(user_id),
                "iss": settings.jwt_issuer,
                "iat": now,
                "exp": now + settings.jwt_expire_minutes * 60,
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    signature = _b64(hmac.new(_secret(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def decode_access_token(token: str) -> UUID:
    try:
        header, payload, signature = token.split(".")
        if json.loads(base64.urlsafe_b64decode(header + "==")).get("alg") != "HS256":
            raise ValueError
        signing_input = f"{header}.{payload}".encode()
        expected = _b64(hmac.new(_secret(), signing_input, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
        if claims.get("iss") != get_settings().jwt_issuer or int(claims.get("exp", 0)) <= int(time.time()):
            raise ValueError
        return UUID(claims["sub"])
    except ServiceUnavailableError:
        raise
    except Exception as exc:
        raise ValueError("Invalid or expired access token") from exc
