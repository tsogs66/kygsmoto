from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "KYGSMOTO Sales & Inventory"
    app_version: str = "1.0.0"
    secret_key: str = "kygsmoto-change-me-in-production"
    database_url: str = f"sqlite:///{Path(__file__).resolve().parents[2] / 'data' / 'kygsmoto.db'}"
    upload_dir: Path = Path(__file__).resolve().parents[2] / "uploads"
    cors_origins: list[str] = ["*"]
    currency: str = "PHP"
    shop_name: str = "KYGSMOTO"
    shop_tagline: str = "Motorshop Sales & Inventory"


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
Path(settings.database_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)