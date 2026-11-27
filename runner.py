"""Runs a learner's Python in a separate process with a time limit.

The child gets a bare environment (no API keys), an empty temp folder,
no stdin, and Python's isolated mode.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile

_LINE_RE = re.compile(r'File "<string>", line (\d+)')


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def run_python(code: str, timeout: float, max_chars: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="flowpy-run-") as tmp:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": tmp,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code],
                cwd=tmp,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "timeout": True,
                "line": None,
                "out": _text(exc.stdout)[:max_chars],
                "err": (
                    f"This ran for {timeout:g} seconds, so I stopped it. A loop that never ends?"
                ),
            }
    out = proc.stdout
    if len(out) > max_chars:
        out = out[:max_chars] + "\n… (cut off)"
    if proc.returncode == 0:
        return {"ok": True, "out": out.rstrip("\n")}
    lines = [ln for ln in proc.stderr.strip().splitlines() if ln.strip()]
    hits = _LINE_RE.findall(proc.stderr)
    return {
        "ok": False,
        "out": out.rstrip("\n"),
        "err": lines[-1] if lines else f"Python stopped (exit {proc.returncode}).",
        "line": int(hits[-1]) if hits else None,
    }
