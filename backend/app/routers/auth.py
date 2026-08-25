"""Login, session lifecycle and user administration."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, security
from ..security import audit, current_user, require

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    full_name: str = ""
    password: str
    role: str = "cashier"


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    active: bool | None = None


class PasswordReset(BaseModel):
    new_password: str


def _public(user) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "active": bool(user["active"]),
        "must_change_password": bool(user["must_change_password"]),
        "last_login_at": user["last_login_at"],
        "created_at": user["created_at"],
    }


@router.post("/login")
def login(body: LoginBody, request: Request):
    row = db.query_one("SELECT * FROM users WHERE username = ?", (body.username.strip(),))
    now = datetime.now(timezone.utc)

    # Uniform error text so probing cannot distinguish unknown user from bad password.
    invalid = HTTPException(status_code=401, detail="Invalid username or password")

    if row is None:
        # Spend comparable time so response latency does not leak user existence.
        security.hash_password(body.password)
        raise invalid

    if row["locked_until"] and row["locked_until"] > now.strftime("%Y-%m-%d %H:%M:%S"):
        raise HTTPException(
            status_code=423,
            detail="Account temporarily locked after repeated failed logins. Try again later.",
        )

    if not row["active"]:
        raise HTTPException(status_code=403, detail="Account disabled. Contact an administrator.")

    if not security.verify_password(
        body.password, row["password_hash"], row["salt"], row["iterations"]
    ):
        attempts = row["failed_attempts"] + 1
        locked_until = None
        if attempts >= MAX_FAILED_ATTEMPTS:
            locked_until = (now + timedelta(minutes=LOCKOUT_MINUTES)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            attempts = 0
        db.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, locked_until, row["id"]),
        )
        audit(dict(row), "login.failed", "user", row["id"])
        raise invalid

    db.execute(
        "UPDATE users SET failed_attempts = 0, locked_until = NULL, "
        "last_login_at = datetime('now') WHERE id = ?",
        (row["id"],),
    )
    token, expires_at = security.create_session(
        row["id"],
        request.client.host if request.client else "",
        request.headers.get("user-agent", ""),
    )
    audit(dict(row), "login.success", "user", row["id"])
    security.purge_expired_sessions()

    user = dict(row)
    return {
        "token": token,
        "expires_at": expires_at,
        "user": _public(user),
        "permissions": sorted(security.ROLE_PERMISSIONS.get(user["role"], set())),
    }


@router.post("/logout")
def logout(user=Depends(current_user)):
    security.revoke_session(user["token"])
    audit(user, "logout", "user", user["id"])
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return {"user": _public(user), "permissions": user["permissions"]}


@router.post("/change-password")
def change_password(body: PasswordChange, user=Depends(current_user)):
    row = db.query_one("SELECT * FROM users WHERE id = ?", (user["id"],))
    if not security.verify_password(
        body.current_password, row["password_hash"], row["salt"], row["iterations"]
    ):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    problems = security.password_problems(body.new_password)
    if problems:
        raise HTTPException(status_code=400, detail="Password " + "; ".join(problems))

    pw_hash, salt, iters = security.hash_password(body.new_password)
    db.execute(
        "UPDATE users SET password_hash = ?, salt = ?, iterations = ?, "
        "must_change_password = 0, updated_at = datetime('now') WHERE id = ?",
        (pw_hash, salt, iters, user["id"]),
    )
    # Force other devices to re-authenticate, keeping the current session alive.
    db.execute(
        "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND token_hash != ?",
        (user["id"], security._token_hash(user["token"])),
    )
    audit(user, "password.changed", "user", user["id"])
    return {"ok": True}


# ---------------------------------------------------------------- user admin

@router.get("/users")
def list_users(user=Depends(require("users.manage"))):
    rows = db.query("SELECT * FROM users ORDER BY username")
    return {"users": [_public(r) for r in rows]}


@router.post("/users")
def create_user(body: UserCreate, user=Depends(require("users.manage"))):
    if body.role not in security.ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of {list(security.ROLES)}")
    problems = security.password_problems(body.password)
    if problems:
        raise HTTPException(status_code=400, detail="Password " + "; ".join(problems))
    if db.query_one("SELECT id FROM users WHERE username = ?", (body.username,)):
        raise HTTPException(status_code=409, detail="That username is already taken")

    pw_hash, salt, iters = security.hash_password(body.password)
    cur = db.execute(
        "INSERT INTO users(username, full_name, password_hash, salt, iterations, role, "
        "must_change_password) VALUES(?,?,?,?,?,?,1)",
        (body.username.strip(), body.full_name.strip(), pw_hash, salt, iters, body.role),
    )
    audit(user, "user.created", "user", cur.lastrowid, {"username": body.username,
                                                        "role": body.role})
    row = db.query_one("SELECT * FROM users WHERE id = ?", (cur.lastrowid,))
    return {"user": _public(row)}


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, user=Depends(require("users.manage"))):
    row = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    if body.role is not None and body.role not in security.ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of {list(security.ROLES)}")

    # Never allow the last active administrator to be demoted or switched off.
    losing_admin = row["role"] == "admin" and (
        (body.role is not None and body.role != "admin") or body.active is False
    )
    if losing_admin:
        others = db.query_one(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = 1 AND id != ?",
            (user_id,),
        )["n"]
        if others == 0:
            raise HTTPException(
                status_code=400,
                detail="This is the last active administrator — promote someone else first.",
            )

    fields, params = [], []
    for column, value in (("full_name", body.full_name), ("role", body.role)):
        if value is not None:
            fields.append(f"{column} = ?")
            params.append(value)
    if body.active is not None:
        fields.append("active = ?")
        params.append(1 if body.active else 0)
    if not fields:
        return {"user": _public(row)}

    fields.append("updated_at = datetime('now')")
    params.append(user_id)
    db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", tuple(params))

    if body.active is False:
        security.revoke_user_sessions(user_id)
    audit(user, "user.updated", "user", user_id, body.model_dump(exclude_none=True))
    return {"user": _public(db.query_one("SELECT * FROM users WHERE id = ?", (user_id,)))}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: PasswordReset, user=Depends(require("users.manage"))):
    if db.query_one("SELECT id FROM users WHERE id = ?", (user_id,)) is None:
        raise HTTPException(status_code=404, detail="User not found")
    problems = security.password_problems(body.new_password)
    if problems:
        raise HTTPException(status_code=400, detail="Password " + "; ".join(problems))

    pw_hash, salt, iters = security.hash_password(body.new_password)
    db.execute(
        "UPDATE users SET password_hash = ?, salt = ?, iterations = ?, "
        "must_change_password = 1, failed_attempts = 0, locked_until = NULL, "
        "updated_at = datetime('now') WHERE id = ?",
        (pw_hash, salt, iters, user_id),
    )
    security.revoke_user_sessions(user_id)
    audit(user, "user.password_reset", "user", user_id)
    return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = 200, user=Depends(require("audit.view"))):
    rows = db.query(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(limit, 1000),)
    )
    return {"entries": [dict(r) for r in rows]}
