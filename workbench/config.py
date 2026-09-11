from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    root: Path
    data_root: Path
    db_path: Path
    deepseek_api_key: str | None = field(repr=False)
    deepseek_base_url: str
    deepseek_model: str
    deepseek_vision_model: str = "deepseek-v4-flash-vision-exp"
    deepseek_review_model: str = "deepseek-v4-pro"
    deepseek_timeout: float = 120.0
    deepseek_trust_env: bool = True
    deepseek_proxy: str | None = field(default=None, repr=False)
    commission_rate: str = "0.35"
    referral_rate: str = "0.10"
    max_image_calls: int = 5
    max_pdf_pages: int = 60

    @property
    def deepseek_enabled(self) -> bool:
        return bool(self.deepseek_api_key)


def load_settings() -> Settings:
    _load_env_file(ROOT / ".env.local")
    data_root = Path(os.getenv("WORKBENCH_DATA_ROOT", "project_data"))
    db_path = Path(os.getenv("WORKBENCH_DB_PATH", "workbench.db"))
    if not data_root.is_absolute():
        data_root = ROOT / data_root
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    data_root.mkdir(parents=True, exist_ok=True)
    return Settings(
        root=ROOT,
        data_root=data_root.resolve(),
        db_path=db_path.resolve(),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
        deepseek_base_url=os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ).rstrip("/"),
        deepseek_model=os.getenv(
            "DEEPSEEK_DEFAULT_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        ),
        deepseek_vision_model=os.getenv(
            "DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp"
        ),
        deepseek_review_model=os.getenv("DEEPSEEK_REVIEW_MODEL", "deepseek-v4-pro"),
        deepseek_timeout=float(os.getenv("DEEPSEEK_TIMEOUT", "120")),
        deepseek_trust_env=os.getenv("DEEPSEEK_TRUST_ENV", "true").lower() == "true",
        deepseek_proxy=os.getenv("DEEPSEEK_PROXY") or None,
        commission_rate=os.getenv("PLATFORM_COMMISSION_RATE", "0.35"),
        referral_rate=os.getenv("REFERRAL_COMMISSION_RATE", "0.10"),
        max_image_calls=int(os.getenv("MAX_IMAGE_CALLS", "5")),
        max_pdf_pages=int(os.getenv("MAX_PDF_PAGES", "60")),
    )


settings = load_settings()
