from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    env_file_path: Path
    database_path: Path
    docs_dir: Path
    data_dir: Path
    api_key: str | None
    base_url: str
    model: str | None
    output_mode: str
    http_timeout: int
    max_body_chars: int
    http_max_retries: int = 3
    http_retry_delay: float = 1.0

    @classmethod
    def load(cls) -> "AppConfig":
        root = _project_root()
        env_file_path = Path(os.getenv("LORE_BUG_ENV_FILE", root / ".env")).expanduser()
        env_file_values = _read_env_file(env_file_path)

        def _get(name: str, default: str | Path | None = None) -> str | Path | None:
            if name in os.environ:
                return os.environ[name]
            if name in env_file_values:
                return env_file_values[name]
            return default

        data_dir = root / "data"
        docs_dir = _resolve_path(_get("LORE_BUG_DOCS_DIR", root / "docs"), root)
        database_path = _resolve_path(_get("LORE_BUG_DB_PATH", data_dir / "main.db"), root)
        return cls(
            project_root=root,
            env_file_path=env_file_path,
            database_path=database_path,
            docs_dir=docs_dir,
            data_dir=data_dir,
            api_key=_get("OPENAI_API_KEY"),
            base_url=str(_get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/"),
            model=_get("OPENAI_MODEL"),
            output_mode=str(_get("OPENAI_OUTPUT_MODE", "auto")),
            http_timeout=int(str(_get("LORE_BUG_HTTP_TIMEOUT", "60"))),
            max_body_chars=int(str(_get("LORE_BUG_MAX_BODY_CHARS", "12000"))),
            http_max_retries=int(str(_get("LORE_BUG_HTTP_MAX_RETRIES", "3"))),
            http_retry_delay=float(str(_get("LORE_BUG_HTTP_RETRY_DELAY", "1.0"))),
        )

    def ensure_runtime_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
