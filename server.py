"""flow.py server: serves the game, runs code, saves progress, writes lessons, keeps logs.

Run:  .venv/bin/python flowpy-app/server.py      then open http://127.0.0.1:8770
Logs: GET /api/logs?n=200&level=error   (file: flowpy-app/logs/server.jsonl)
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lessons  # noqa: E402
import settings as settings_mod  # noqa: E402
import teacher as teacher_mod  # noqa: E402
import tutor as tutor_mod  # noqa: E402
import writer as writer_mod  # noqa: E402
from runner import run_python  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 256 * 1024
log = logging.getLogger("flowpy")


class JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
               "level": record.levelname.lower(), "src": getattr(record, "src", "server"),
               "msg": record.getMessage()}
        data = getattr(record, "data", None)
        if data is not None:
            row["data"] = data
        if record.exc_info:
            row["trace"] = "".join(traceback.format_exception(*record.exc_info))[-4000:]
        return json.dumps(row, default=str)


def setup_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "server.jsonl"
    fh = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3)
    fh.setFormatter(JsonLines())
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("[flowpy] %(levelname)s %(message)s"))
    root = logging.getLogger("flowpy")
    root.handlers[:] = [fh, sh]
    root.setLevel(logging.INFO)
    return path


class App:
    def __init__(self, s: settings_mod.Settings, writer=None):
        self.s = s
        s.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = s.log_dir / "server.jsonl"
        self.store = lessons.Store(s.lessons_dir, s.data_dir)
        self.writer = writer or writer_mod.Writer(s)
        self.teacher = teacher_mod.Teacher(s, self.writer, s.data_dir)
        self.tutor = tutor_mod.Tutor(self.writer, s.data_dir)
        self._checked: dict[str, float] = {}   # cached lesson file -> mtime that passed the current checks
        self.progress_path = s.data_dir / "progress.json"
        self.events_path = s.data_dir / "events.jsonl"
        self._file_lock = threading.Lock()
        self._topic_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ---- progress -------------------------------------------------------
    def read_progress(self) -> dict:
        if not self.progress_path.exists():
            return {}
        try:
            return json.loads(self.progress_path.read_text())
        except json.JSONDecodeError:
            log.error("progress file is not valid JSON; starting fresh", exc_info=True)
            return {}

    def write_progress(self, prog: dict) -> None:
        with self._file_lock:
            tmp = self.progress_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(prog, indent=1))
            tmp.replace(self.progress_path)

    def add_event(self, ev: dict) -> None:
        ev = {"t": int(time.time()), **ev}
        with self._file_lock, self.events_path.open("a") as f:
            f.write(json.dumps(ev) + "\n")

    def stats(self) -> dict:
        """A small picture of how the learner is doing, for the lesson writer."""
        if not self.events_path.exists():
            return {}
        rounds = []
        for line in self.events_path.read_text().splitlines()[-400:]:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "round":
                rounds.append(ev)
        if not rounds:
            return {}
        recent = rounds[-24:]
        lvl4 = [r for r in recent if r.get("lvl") == 4]
        return {
            "rounds_done": len(rounds),
            "avg_accuracy": round(sum(r.get("acc", 0) for r in recent) / len(recent)),
            "avg_level4_misses": round(sum(r.get("fails", 0) for r in lvl4) / len(lvl4), 1) if lvl4 else None,
        }

    def _rounds(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        out = []
        for line in self.events_path.read_text().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "round":
                out.append(ev)
        return out

    def topic_stats(self) -> dict:
        """How each topic went, for the teacher: levels done, accuracy, level-4 misses, errors, minutes."""
        by: dict[str, list[dict]] = {}
        for r in self._rounds():
            by.setdefault(str(r.get("topic")), []).append(r)
        out = {}
        for topic, rs in by.items():
            l4 = [r for r in rs if r.get("lvl") == 4]
            out[topic] = {"levels_done": sorted({r.get("lvl") for r in rs}),
                          "acc": round(sum(r.get("acc", 0) for r in rs) / len(rs)),
                          "l4_misses": sum(r.get("fails", 0) for r in l4),
                          "typing_errors": sum(r.get("errors", 0) for r in rs),
                          "mins": round(sum(r.get("secs", 0) for r in rs) / 60, 1)}
        return out

    def teacher_next(self) -> dict:
        goal = str((self.read_progress().get("profile") or {}).get("reason") or "")
        return self.teacher.next(goal, self.topic_stats(), self.chosen_model())

    def curriculum(self) -> dict:
        extra = [{"topic": e["id"], "title": e["title"], "why": e["why"], "kind": e["kind"], "teacher": True,
                  "ready": self.store.cached(e["id"]) is not None} for e in self.teacher.state()["path"]]
        return {"topics": self.store.status(), "extra": extra}

    def _still_good(self, topic: str, lesson: dict) -> bool:
        """Cached lessons are re-checked once per file version, so new rules reach old lessons too."""
        f = self.store.cache_dir / f"{lessons.slug(topic)}.json"
        mtime = f.stat().st_mtime if f.exists() else 0
        if self._checked.get(topic) == mtime:
            return True
        problems = lessons.validate(lesson, self.s.run_timeout, self.s.max_output_chars)
        if problems:
            log.warning("cached lesson fails current checks; rewriting", extra={"data": {"topic": topic, "problems": problems}})
            return False
        self._checked[topic] = mtime
        return True

    # ---- lessons --------------------------------------------------------
    def chosen_model(self) -> str:
        """The model the learner picked in the game, else the config default."""
        picked = self.read_progress().get("model")
        return picked if isinstance(picked, str) and picked.strip() else self.s.model

    def _lock_for(self, topic: str) -> threading.Lock:
        with self._locks_guard:
            return self._topic_locks.setdefault(topic, threading.Lock())

    def lesson(self, topic: str, fresh: bool) -> tuple[dict, str]:
        plan = None
        if topic not in lessons.TOPICS:
            plan = self.teacher.plan(topic)
            if plan is None:
                raise KeyError(topic)
        if not fresh:
            found = self.store.builtin(topic)
            if found:
                return found, "builtin"
        with self._lock_for(topic):
            if not fresh:
                found = self.store.cached(topic)
                if found and self._still_good(topic, found):
                    return found, "cache"
            prog = self.read_progress()
            profile = {**(prog.get("profile") or {}), "stats": self.stats()}
            example = self.store.builtin("for loops")
            t0 = time.monotonic()
            model = self.chosen_model()
            lesson = self.writer.write(topic, profile, example, model=model, plan=plan)
            self.store.save(lesson)
            log.info("lesson written", extra={"data": {"topic": topic, "model": model,
                                                       "secs": round(time.monotonic() - t0, 1)}})
            return lesson, "written"

    def read_logs(self, n: int, level: str | None) -> list[dict]:
        if not self.log_path.exists():
            return []
        rows = []
        for line in self.log_path.read_text().splitlines()[-5000:]:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if level and row.get("level") != level:
                continue
            rows.append(row)
        return rows[-n:]


def make_handler(app: App):
    allowed_hosts = {f"127.0.0.1:{app.s.port}", f"localhost:{app.s.port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "flowpy/1"

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
            if self.headers.get("Host") not in allowed_hosts:
                self._json(403, {"error": "bad host"})
                return False
            if write:
                origin = self.headers.get("Origin")
                if self.headers.get("X-Flowpy") != "1" or (origin and origin not in allowed_origins):
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

        # ---- routes ----
        def do_GET(self):
            try:
                if not self._guard(False):
                    return
                url = urlparse(self.path)
                q = {k: v[-1] for k, v in parse_qs(url.query).items()}
                if url.path in ("/", "/index.html"):
                    return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                if url.path == "/api/health":
                    return self._json(200, {"ok": True, "python": sys.version.split()[0],
                                            "writer": {"ready": app.writer.ready(), "model": app.chosen_model(),
                                                       "default": app.s.model, "provider": app.s.provider}})
                if url.path == "/api/curriculum":
                    return self._json(200, app.curriculum())
                if url.path == "/api/teacher":
                    return self._json(200, {**app.teacher.state(), "stats": app.topic_stats()})
                if url.path == "/api/models":
                    return self._json(200, {"default": app.s.model, "chosen": app.chosen_model(),
                                            "models": app.writer.models()})
                if url.path == "/api/progress":
                    return self._json(200, app.read_progress())
                if url.path == "/api/lesson":
                    topic = q.get("topic", "")
                    try:
                        lesson, source = app.lesson(topic, q.get("fresh") == "1")
                    except KeyError:
                        return self._json(404, {"error": "unknown topic", "topic": topic})
                    except writer_mod.WriterUnavailable as exc:
                        log.warning("lesson writer unavailable", extra={"data": {"topic": topic}})
                        return self._json(503, {"error": "no_key", "message": str(exc)})
                    except writer_mod.WriterFailed as exc:
                        log.error("lesson writer failed", extra={"data": {"topic": topic, "why": str(exc)}})
                        return self._json(502, {"error": "writer_failed", "message": str(exc)})
                    except Exception as exc:  # API/network trouble: log it, tell the page
                        log.error("lesson writer crashed", exc_info=exc, extra={"data": {"topic": topic}})
                        return self._json(502, {"error": "writer_failed", "message": f"{type(exc).__name__}: {exc}"})
                    return self._json(200, {"lesson": lesson, "from": source})
                if url.path == "/api/logs":
                    n = max(1, min(int(q.get("n", "200")), 2000))
                    return self._json(200, {"file": str(app.log_path), "rows": app.read_logs(n, q.get("level"))})
                self._json(404, {"error": "not found"})
            except Exception as exc:
                self._fail(exc)

        def do_POST(self):
            try:
                if not self._guard(True):
                    return
                data = self._body()
                if data is None:
                    return
                path = urlparse(self.path).path
                if path == "/api/run":
                    code = data.get("code")
                    if not isinstance(code, str) or len(code) > 20000:
                        return self._json(400, {"error": "code must be a string"})
                    return self._json(200, run_python(code, app.s.run_timeout, app.s.max_output_chars))
                if path == "/api/teacher/next":
                    try:
                        return self._json(200, {"entry": app.teacher_next()})
                    except writer_mod.WriterUnavailable as exc:
                        return self._json(503, {"error": "no_key", "message": str(exc)})
                    except writer_mod.WriterFailed as exc:
                        log.error("teacher failed", extra={"data": {"why": str(exc)}})
                        return self._json(502, {"error": "writer_failed", "message": str(exc)})
                if path == "/api/chat":
                    messages = tutor_mod.clean_messages(data.get("messages"))
                    if messages is None:
                        return self._json(400, {"error": "messages must be a list that ends with a user message"})
                    ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
                    try:
                        text = app.tutor.reply(messages, ctx, app.chosen_model(), str(data.get("chat") or ""))
                    except writer_mod.WriterUnavailable as exc:
                        return self._json(503, {"error": "no_key", "message": str(exc)})
                    except Exception as exc:  # model/API trouble: log it, tell the page
                        log.error("chat failed", exc_info=exc)
                        return self._json(502, {"error": "chat_failed", "message": f"{type(exc).__name__}: {exc}"})
                    return self._json(200, {"reply": text, "model": app.chosen_model()})
                if path == "/api/event":
                    app.add_event(data)
                    return self._json(200, {"ok": True})
                if path == "/api/log":
                    level = {"error": logging.ERROR, "warn": logging.WARNING}.get(str(data.get("level")), logging.INFO)
                    log.log(level, str(data.get("msg", ""))[:500],
                            extra={"src": "page", "data": data.get("extra")})
                    return self._json(200, {"ok": True})
                self._json(404, {"error": "not found"})
            except Exception as exc:
                self._fail(exc)

        def do_PUT(self):
            try:
                if not self._guard(True):
                    return
                data = self._body()
                if data is None:
                    return
                if urlparse(self.path).path == "/api/progress":
                    app.write_progress(data)
                    return self._json(200, {"ok": True})
                self._json(404, {"error": "not found"})
            except Exception as exc:
                self._fail(exc)

    return Handler


def main() -> None:
    s = settings_mod.load()
    log_path = setup_logging(s.log_dir)
    app = App(s)
    httpd = ThreadingHTTPServer((s.host, s.port), make_handler(app))
    log.info("server up", extra={"data": {"url": f"http://127.0.0.1:{s.port}", "log": str(log_path),
                                          "writer_ready": app.writer.ready(), "model": app.s.model}})
    print(f"flow.py is running: http://127.0.0.1:{s.port}  (ctrl+c to stop)", flush=True)
    if not app.writer.ready():
        print(f"No {s.api_key_var} found, so only the built-in lessons will load. See the README.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        log.info("server down")


if __name__ == "__main__":
    main()
