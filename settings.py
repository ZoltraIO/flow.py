"""Loads the settings file. Every setting lives there, nowhere else.

The file is config.yaml next to this one. Set FLOWPY_CONFIG to use another file.
Paths inside it are relative to this folder.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("FLOWPY_CONFIG") or APP_DIR / "config.yaml")
ENV_PATH = Path(os.environ.get("FLOWPY_ENV_FILE") or APP_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    provider: str
    base_url: str
    api_key_var: str
    model: str
    request_timeout: float
    max_tokens: int
    fix_attempts: int
    run_timeout: float
    max_output_chars: int
    lessons_dir: Path
    data_dir: Path
    log_dir: Path


def load(path: Path | None = None) -> Settings:
    raw = yaml.safe_load((path or CONFIG_PATH).read_text()) or {}
    server, writer = raw.get("server", {}), raw.get("lesson_writer", {})
    runner, paths = raw.get("runner", {}), raw.get("paths", {})
    return Settings(
        host=str(server.get("host", "127.0.0.1")),
        port=int(server.get("port", 8770)),
        provider=str(writer.get("provider", "opencode-go")),
        base_url=str(writer["base_url"]),
        api_key_var=str(writer.get("api_key_var", "OPENCODE_GO_API_KEY")),
        model=str(writer["model"]),
        request_timeout=float(writer["request_timeout_seconds"]),
        max_tokens=int(writer.get("max_tokens", 16000)),
        fix_attempts=int(writer.get("fix_attempts", 2)),
        run_timeout=float(runner["timeout_seconds"]),
        max_output_chars=int(runner.get("max_output_chars", 20000)),
        lessons_dir=APP_DIR / paths.get("lessons_dir", "lessons"),
        data_dir=APP_DIR / paths.get("data_dir", "data"),
        log_dir=APP_DIR / paths.get("log_dir", "logs"),
    )
