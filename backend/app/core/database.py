from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_sqlite_columns() -> None:
    """Add new columns to existing SQLite DBs (create_all does not alter)."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(purchases)")).fetchall()}
        if "receipt_filename" not in cols:
            conn.execute(text("ALTER TABLE purchases ADD COLUMN receipt_filename VARCHAR(255)"))
        if "receipt_path" not in cols:
            conn.execute(text("ALTER TABLE purchases ADD COLUMN receipt_path VARCHAR(500)"))