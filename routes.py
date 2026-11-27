"""flow.py routes: the HTTP table, the request plumbing, and the handler class.

`server.py` owns settings, state, and the lesson pipeline; this module owns the
routes that point at it. Every function keeps the same status codes and bodies.
"""

from __future__ import annotations

import json
import logging
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tutor as tutor_mod  # noqa: E402
import writer as writer_mod  # noqa: E402
from runner import run_python  # noqa: E402

if TYPE_CHECKING:
    from server import App

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 256 * 1024
log = logging.getLogger("flowpy")


def _not_found(h: FlowpyHandler, app: App, arg) -> None:
    h._json(404, {"error": "not found"})


# ---- GET routes -------------------------------------------------------
def _get_page(h: FlowpyHandler, app: App, q: dict) -> None:
    h._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")


def _get_health(h: FlowpyHandler, app: App, q: dict) -> None:
    h._json(
        200,
        {
            "ok": True,
            "python": sys.version.split()[0],
            "writer": {
                "ready": app.writer.ready(),
                "model": app.chosen_model(),
                "default": app.s.model,
                "provider": app.s.provider,
            },
        },
    )


def _get_curriculum(h: FlowpyHandler, app: App, q: dict) -> None:
    h._json(200, app.curriculum())


def _get_teacher(h: FlowpyHandler, app: App, q: dict) -> None:
    h._json(200, {**app.teacher.state(), "stats": app.topic_stats()})


def _get_models(h: FlowpyHandler, app: App, q: dict) -> None:
    h._json(
        200,
        {
            "default": app.s.model,
            "chosen": app.chosen_model(),
            "models": app.writer.models(),
        },
    )


def _get_progress(h: FlowpyHandler, app: App, q: dict) -> None:
    h._json(200, app.read_progress())


def _get_lesson(h: FlowpyHandler, app: App, q: dict) -> None:
    topic = q.get("topic", "")
    try:
        lesson, source = app.lesson(topic, q.get("fresh") == "1")
    except KeyError:
        h._json(404, {"error": "unknown topic", "topic": topic})
    except writer_mod.WriterUnavailable as exc:
        log.warning("lesson writer unavailable", extra={"data": {"topic": topic}})
        h._json(503, {"error": "no_key", "message": str(exc)})
    except writer_mod.WriterFailed as exc:
        log.error("lesson writer failed", extra={"data": {"topic": topic, "why": str(exc)}})
        h._json(502, {"error": "writer_failed", "message": str(exc)})
    except Exception as exc:  # API/network trouble: log it, tell the page
        log.error("lesson writer crashed", exc_info=exc, extra={"data": {"topic": topic}})
        h._json(502, {"error": "writer_failed", "message": f"{type(exc).__name__}: {exc}"})
    else:
        h._json(200, {"lesson": lesson, "from": source})


def _get_logs(h: FlowpyHandler, app: App, q: dict) -> None:
    n = max(1, min(int(q.get("n", "200")), 2000))
    h._json(200, {"file": str(app.log_path), "rows": app.read_logs(n, q.get("level"))})


# ---- POST / PUT routes ------------------------------------------------
def _post_run(h: FlowpyHandler, app: App, data: dict) -> None:
    code = data.get("code")
    if not isinstance(code, str) or len(code) > 20000:
        h._json(400, {"error": "code must be a string"})
        return
    h._json(200, run_python(code, app.s.run_timeout, app.s.max_output_chars))


def _post_teacher_next(h: FlowpyHandler, app: App, data: dict) -> None:
    try:
        entry = app.teacher_next()
    except writer_mod.WriterUnavailable as exc:
        h._json(503, {"error": "no_key", "message": str(exc)})
    except writer_mod.WriterFailed as exc:
        log.error("teacher failed", extra={"data": {"why": str(exc)}})
        h._json(502, {"error": "writer_failed", "message": str(exc)})
    else:
        h._json(200, {"entry": entry})


def _post_chat(h: FlowpyHandler, app: App, data: dict) -> None:
    messages = tutor_mod.clean_messages(data.get("messages"))
    if messages is None:
        h._json(400, {"error": "messages must be a list that ends with a user message"})
        return
    raw_ctx = data.get("context")
    ctx = raw_ctx if isinstance(raw_ctx, dict) else {}
    try:
        text = app.tutor.reply(messages, ctx, app.chosen_model(), str(data.get("chat") or ""))
    except writer_mod.WriterUnavailable as exc:
        h._json(503, {"error": "no_key", "message": str(exc)})
    except Exception as exc:  # model/API trouble: log it, tell the page
        log.error("chat failed", exc_info=exc)
        h._json(502, {"error": "chat_failed", "message": f"{type(exc).__name__}: {exc}"})
    else:
        h._json(200, {"reply": text, "model": app.chosen_model()})


def _post_event(h: FlowpyHandler, app: App, data: dict) -> None:
    app.add_event(data)
    h._json(200, {"ok": True})


def _post_log(h: FlowpyHandler, app: App, data: dict) -> None:
    level = {"error": logging.ERROR, "warn": logging.WARNING}.get(
        str(data.get("level")), logging.INFO
    )
    log.log(
        level,
        str(data.get("msg", ""))[:500],
        extra={"src": "page", "data": data.get("extra")},
    )
    h._json(200, {"ok": True})


def _put_progress(h: FlowpyHandler, app: App, data: dict) -> None:
    app.write_progress(data)
    h._json(200, {"ok": True})


GET_ROUTES = {
    "/": _get_page,
    "/index.html": _get_page,
    "/api/health": _get_health,
    "/api/curriculum": _get_curriculum,
    "/api/teacher": _get_teacher,
    "/api/models": _get_models,
    "/api/progress": _get_progress,
    "/api/lesson": _get_lesson,
    "/api/logs": _get_logs,
}
POST_ROUTES = {
    "/api/run": _post_run,
    "/api/teacher/next": _post_teacher_next,
    "/api/chat": _post_chat,
    "/api/event": _post_event,
    "/api/log": _post_log,
}
PUT_ROUTES = {"/api/progress": _put_progress}


class FlowpyHandler(BaseHTTPRequestHandler):
    """One request's plumbing; `make_handler` binds the app and the allowed hosts."""

    server_version = "flowpy/1"
    app: ClassVar[App]
    allowed_hosts: ClassVar[set[str]]
    allowed_origins: ClassVar[set[str]]

    def log_message(self, fmt, *args):  # quiet the default stderr access log
        pass

    # ---- helpers ----
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _guard(self, write: bool) -> bool:
        # The server runs code, so only this page on this machine may talk to it.
        if self.headers.get("Host") not in self.allowed_hosts:
            self._json(403, {"error": "bad host"})
            return False
        if write:
            origin = self.headers.get("Origin")
            if self.headers.get("X-Flowpy") != "1" or (
                origin and origin not in self.allowed_origins
            ):
                self._json(403, {"error": "forbidden"})
                return False
        return True

    def _body(self) -> dict | None:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            self._json(413, {"error": "too big"})
            return None
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "bad json"})
            return None
        if not isinstance(data, dict):
            self._json(400, {"error": "expected an object"})
            return None
        return data

    def _fail(self, exc: BaseException) -> None:
        log.error("request failed %s %s", self.command, self.path, exc_info=exc)
        try:
            self._json(500, {"error": "server error", "message": str(exc)})
        except OSError:
            pass

    # ---- dispatch ----
    def _dispatch(self, routes: dict, *, write: bool, with_body: bool) -> None:
        try:
            if not self._guard(write):
                return
            url = urlparse(self.path)
            arg = self._body() if with_body else {k: v[-1] for k, v in parse_qs(url.query).items()}
            if arg is None:
                return
            routes.get(url.path, _not_found)(self, self.app, arg)
        except Exception as exc:
            self._fail(exc)

    def do_GET(self) -> None:
        self._dispatch(GET_ROUTES, write=False, with_body=False)

    def do_POST(self) -> None:
        self._dispatch(POST_ROUTES, write=True, with_body=True)

    def do_PUT(self) -> None:
        self._dispatch(PUT_ROUTES, write=True, with_body=True)


def make_handler(app: App):
    """The handler class for this app: same routes, bound to `app`."""
    allowed_hosts = {f"127.0.0.1:{app.s.port}", f"localhost:{app.s.port}"}

    class Handler(FlowpyHandler):
        pass

    Handler.app = app
    Handler.allowed_hosts = allowed_hosts
    Handler.allowed_origins = {f"http://{h}" for h in allowed_hosts}
    return Handler
