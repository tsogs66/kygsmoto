"""Password hashing, session tokens and role-based access control."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request

from . import db

PBKDF2_ITERATIONS = 240_000
TOKEN_BYTES = 32

# Every capability the API can gate on, granted per role.
ROLE_PERMISSIONS = {
    "admin": {
        "pos.sell", "pos.discount", "pos.void", "pos.refund",
        "inventory.view", "inventory.edit", "inventory.adjust", "inventory.stocktake",
        "purchasing.view", "purchasing.edit", "purchasing.receive",
        "reports.view", "reports.financial", "analytics.view",
        "users.manage", "settings.manage", "audit.view", "data.import",
    },
    "manager": {
        "pos.sell", "pos.discount", "pos.void", "pos.refund",
        "inventory.view", "inventory.edit", "inventory.adjust", "inventory.stocktake",
        "purchasing.view", "purchasing.edit", "purchasing.receive",
        "reports.view", "reports.financial", "analytics.view",
        "settings.manage", "audit.view",
    },
    "cashier": {
        "pos.sell", "inventory.view", "reports.view",
    },
}

ROLES = tuple(ROLE_PERMISSIONS)


def hash_password(password: str, salt: str | None = None, iterations: int = PBKDF2_ITERATIONS):
    """Derive a PBKDF2-SHA256 hash; returns (hash_hex, salt_hex, iterations)."""
    if salt is None:
        salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    )
    return derived.hex(), salt, iterations


def verify_password(password: str, password_hash: str, salt: str, iterations: int) -> bool:
    candidate, _, _ = hash_password(password, salt, iterations)
    return hmac.compare_digest(candidate, password_hash)


def password_problems(password: str) -> list[str]:
    """Return a list of policy violations; empty means the password is acceptable."""
    problems = []
    if len(password) < 8:
        problems.append("must be at least 8 characters")
    if not any(c.isalpha() for c in password):
        problems.append("must contain a letter")
    if not any(c.isdigit() for c in password):
        problems.append("must contain a digit")
    if password.lower() in {"password", "12345678", "kygs1234", "admin123"}:
        problems.append("is too common")
    return problems


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int, ip: str = "", user_agent: str = "") -> tuple[str, str]:
    """Issue a session token for a user; returns (token, expiry ISO string)."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    hours = float(db.get_setting("session_hours", "12"))
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    expires_at = expires.strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO sessions(user_id, token_hash, expires_at, ip, user_agent) VALUES(?,?,?,?,?)",
        (user_id, _token_hash(token), expires_at, ip, user_agent[:250]),
    )
    return token, expires_at


def revoke_session(token: str):
    db.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (_token_hash(token),))


def revoke_user_sessions(user_id: int):
    db.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user_id,))


def purge_expired_sessions():
    db.execute("DELETE FROM sessions WHERE expires_at < datetime('now') OR revoked = 1")


def audit(user, action: str, entity: str = "", entity_id="", detail=""):
    """Record an action in the tamper-evident audit trail."""
    if not isinstance(detail, str):
        detail = json.dumps(detail, default=str)
    db.execute(
        "INSERT INTO audit_log(user_id, username, action, entity, entity_id, detail) "
        "VALUES(?,?,?,?,?,?)",
        (
            user["id"] if user else None,
            user["username"] if user else "system",
            action,
            entity,
            str(entity_id),
            detail,
        ),
    )


async def current_user(request: Request, authorization: str = Header(default="")):
    """Resolve the caller from their bearer token, or reject the request."""
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        token = request.cookies.get("kygs_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    row = db.query_one(
        """SELECT u.*, s.token_hash, s.expires_at
             FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.revoked = 0""",
        (_token_hash(token),),
    )
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid session")
    if row["expires_at"] < datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"):
        raise HTTPException(status_code=401, detail="Session expired")
    if not row["active"]:
        raise HTTPException(status_code=403, detail="Account disabled")

    user = dict(row)
    user["permissions"] = sorted(ROLE_PERMISSIONS.get(user["role"], set()))
    user["token"] = token
    return user


def require(*permissions: str):
    """Dependency factory: caller must hold every listed permission."""
    async def guard(user=Depends(current_user)):
        granted = ROLE_PERMISSIONS.get(user["role"], set())
        missing = [p for p in permissions if p not in granted]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Your role ({user['role']}) lacks permission: {', '.join(missing)}",
            )
        return user

    return guard


def has_permission(user, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(user["role"], set())
