"""Configuration loading and validation.

Settings come from the repo-root `.env` (gitignored). Secrets live here and
only here — they are read by the backend and sent directly to Anthropic and
ElevenLabs, never to the browser and never anywhere else.

Missing keys do not crash the process. They are reported loudly at startup and
surfaced through /config/status, and any route that actually needs a key raises
a clear 503 via `require_key`. This keeps the app reachable so a future settings
screen can write the keys in, rather than locking the user out of the only UI
that could fix the problem.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> repo root
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Typed view of the environment.

    Secret fields default to empty rather than being required, so the app can
    boot un-configured. Use `require_key` before making an external call.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Secrets -----------------------------------------------------------
    anthropic_api_key: str = ""
    elevenlabs_api_key: str = ""

    # --- Models & voice ----------------------------------------------------
    anthropic_model: str = "claude-opus-5"
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model: str = "eleven_multilingual_v2"

    # Whisper size. "base" transcribes faster than real time on CPU and is
    # accurate enough for dictation; "small" is noticeably better on accents
    # and background noise at roughly 3x the time.
    whisper_model: str = "base"

    # --- Local storage -----------------------------------------------------
    chroma_dir: Path = Field(default=Path("data/chroma"))
    uploads_dir: Path = Field(default=Path("data/uploads"))
    whisper_cache_dir: Path = Field(default=Path("data/models"))

    # --- Networking --------------------------------------------------------
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:3000"

    @property
    def chroma_path(self) -> Path:
        """Absolute path to the vector store directory."""
        return self._resolve(self.chroma_dir)

    @property
    def uploads_path(self) -> Path:
        """Absolute path to the uploaded-media directory."""
        return self._resolve(self.uploads_dir)

    def _resolve(self, value: Path) -> Path:
        """Interpret relative storage paths against backend/, not the CWD.

        Without this, running uvicorn from the repo root and from backend/
        would silently use two different databases.
        """
        return value if value.is_absolute() else BACKEND_DIR / value

    @property
    def whisper_cache_path(self) -> Path:
        """Where the downloaded Whisper weights live."""
        return self._resolve(self.whisper_cache_dir)

    @property
    def cors_origins(self) -> list[str]:
        """Allowed browser origins, covering both localhost spellings."""
        origins = {self.frontend_origin}
        if "localhost" in self.frontend_origin:
            origins.add(self.frontend_origin.replace("localhost", "127.0.0.1"))
        return sorted(origins)

    def missing_keys(self) -> list[str]:
        """Names of unset secrets, in the order features will need them."""
        missing = []
        if not self.anthropic_api_key.strip():
            missing.append("ANTHROPIC_API_KEY")
        if not self.elevenlabs_api_key.strip():
            missing.append("ELEVENLABS_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Restart the server to pick up .env edits."""
    return Settings()


class MissingConfigError(RuntimeError):
    """Raised when a feature is invoked without the key it depends on."""


def require_key(name: str) -> str:
    """Return a secret's value, or explain precisely what to do about it.

    Call this at the point of use so an unconfigured key fails with an
    actionable message instead of a confusing 401 from the vendor.
    """
    settings = get_settings()
    value = getattr(settings, name.lower(), "")
    if not value or not value.strip():
        raise MissingConfigError(
            f"{name} is not set. Add it to {ENV_FILE} and restart the backend. "
            f"See .env.example for the expected format."
        )
    return value.strip()


def startup_report() -> str:
    """A human-readable banner describing config state at boot."""
    settings = get_settings()
    lines = ["", "=" * 62, "  MERROR backend"]

    if not ENV_FILE.exists():
        lines += [
            "=" * 62,
            f"  !! No .env file found at {ENV_FILE}",
            "  !! Run:  cp .env.example .env   then add your keys.",
        ]
    else:
        lines.append("=" * 62)

    missing = settings.missing_keys()
    if missing:
        lines.append("  !! Missing keys — related features will return 503:")
        for key in missing:
            feature = {
                "ANTHROPIC_API_KEY": "chat, image understanding",
                "ELEVENLABS_API_KEY": "voice output",
            }[key]
            lines.append(f"       - {key}  ({feature})")
    else:
        lines.append("  All API keys present.")

    lines += [
        f"  Model:   {settings.anthropic_model}",
        f"  Storage: {settings.chroma_path}",
        f"  CORS:    {', '.join(settings.cors_origins)}",
        "=" * 62,
        "",
    ]
    return "\n".join(lines)
