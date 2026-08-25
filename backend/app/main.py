"""KYGS POS — application entrypoint.

Serves the JSON API under /api and the single-page front end from /.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, security
from .routers import (analytics_api, auth, catalog, inventory, jobs, pos,
                      purchasing, reports, settings_api)

FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend"
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    security.purge_expired_sessions()
    bootstrap_admin()
    yield


app = FastAPI(
    title="KYGS POS & Inventory Management",
    version="1.0.0",
    description="Point of sale, stock control and demand forecasting for a motorcycle "
                "parts and service shop.",
    lifespan=lifespan,
)


def bootstrap_admin():
    """Create the first administrator if the user table is empty.

    The password comes from KYGS_ADMIN_PASSWORD, or is generated and printed once
    so a fresh install is never left with a guessable default.
    """
    if db.query_one("SELECT id FROM users LIMIT 1"):
        return

    import secrets

    password = os.environ.get("KYGS_ADMIN_PASSWORD") or (secrets.token_urlsafe(12) + "1a")
    pw_hash, salt, iters = security.hash_password(password)
    db.execute(
        "INSERT INTO users(username, full_name, password_hash, salt, iterations, role, "
        "must_change_password) VALUES('admin', 'Shop Administrator', ?, ?, ?, 'admin', 1)",
        (pw_hash, salt, iters),
    )
    print("\n" + "=" * 62)
    print("  First run — administrator account created")
    print("  username: admin")
    print(f"  password: {password}")
    print("  You must change this password at first login.")
    print("=" * 62 + "\n", flush=True)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Turn schema errors into a single readable sentence for the till operator."""
    problems = []
    for error in exc.errors():
        field = " → ".join(str(p) for p in error["loc"] if p not in ("body", "query"))
        problems.append(f"{field}: {error['msg']}" if field else error["msg"])
    return JSONResponse(status_code=422, content={"detail": "; ".join(problems)})


# jobs must come before pos: its /api/pos/jobs routes would otherwise be
# shadowed by pos's /api/pos/sales/{sale_id}-style paths at the same prefix.
for module in (auth, catalog, jobs, pos, inventory, purchasing, analytics_api,
               reports, settings_api):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "kygs-pos"}


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
