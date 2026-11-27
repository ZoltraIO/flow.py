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
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lessons  # noqa: E402
import routes  # noqa: E402
import settings as settings_mod  # noqa: E402
import teacher as teacher_mod  # noqa: E402
import tutor as tutor_mod  # noqa: E402
import writer as writer_mod  # noqa: E402

log = logging.getLogger("flowpy")


class JsonLines(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        row = {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname.lower(),
            "src": getattr(record, "src", "server"),
            "msg": record.getMessage(),
        }
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


def _json_line(line: str):
    """One row from the events file, or None when the line is not valid JSON."""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _topic_summary(rs: list[dict]) -> dict:
    """One topic's numbers: levels done, accuracy, level-4 misses, errors, minutes."""
    l4 = [r for r in rs if r.get("lvl") == 4]
    return {
        "levels_done": sorted({r["lvl"] for r in rs if isinstance(r.get("lvl"), int)}),
        "acc": round(sum(r.get("acc", 0) for r in rs) / len(rs)),
        "l4_misses": sum(r.get("fails", 0) for r in l4),
        "typing_errors": sum(r.get("errors", 0) for r in rs),
        "mins": round(sum(r.get("secs", 0) for r in rs) / 60, 1),
    }


class App:
    def __init__(self, s: settings_mod.Settings, writer=None):
        self.s = s
        s.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = s.log_dir / "server.jsonl"
        self.store = lessons.Store(s.lessons_dir, s.data_dir)
        self.writer = writer or writer_mod.Writer(s)
        self.teacher = teacher_mod.Teacher(s, self.writer, s.data_dir)
        self.tutor = tutor_mod.Tutor(self.writer, s.data_dir)
        self._checked: dict[
            str, float
        ] = {}  # cached lesson file -> mtime that passed the current checks
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
        rounds = self._rounds(tail=400)
        if not rounds:
            return {}
        recent = rounds[-24:]
        lvl4 = [r for r in recent if r.get("lvl") == 4]
        return {
            "rounds_done": len(rounds),
            "avg_accuracy": round(sum(r.get("acc", 0) for r in recent) / len(recent)),
            "avg_level4_misses": round(sum(r.get("fails", 0) for r in lvl4) / len(lvl4), 1)
            if lvl4
            else None,
        }

    def _event_rows(self, tail: int | None = None) -> list[dict]:
        if not self.events_path.exists():
            return []
        lines = self.events_path.read_text().splitlines()
        rows = [_json_line(line) for line in (lines[-tail:] if tail else lines)]
        return [row for row in rows if row is not None]

    def _rounds(self, tail: int | None = None) -> list[dict]:
        return [ev for ev in self._event_rows(tail) if ev.get("type") == "round"]

    def topic_stats(self) -> dict:
        """How each topic went, for the teacher.

        Per topic: levels done, accuracy, level-4 misses, errors, minutes.
        """
        by: dict[str, list[dict]] = {}
        for r in self._rounds():
            by.setdefault(str(r.get("topic")), []).append(r)
        return {topic: _topic_summary(rs) for topic, rs in by.items()}

    def teacher_next(self) -> dict:
        goal = str((self.read_progress().get("profile") or {}).get("reason") or "")
        return self.teacher.next(goal, self.topic_stats(), self.chosen_model())

    def curriculum(self) -> dict:
        extra = [
            {
                "topic": e["id"],
                "title": e["title"],
                "why": e["why"],
                "kind": e["kind"],
                "teacher": True,
                "ready": self.store.cached(e["id"]) is not None,
            }
            for e in self.teacher.state()["path"]
        ]
        return {"topics": self.store.status(), "extra": extra}

    def _still_good(self, topic: str, lesson: dict) -> bool:
        """Cached lessons are re-checked once per file version.

        That way new rules reach old lessons too.
        """
        f = self.store.cache_dir / f"{lessons.slug(topic)}.json"
        mtime = f.stat().st_mtime if f.exists() else 0
        if self._checked.get(topic) == mtime:
            return True
        problems = lessons.validate(lesson, self.s.run_timeout, self.s.max_output_chars)
        if problems:
            log.warning(
                "cached lesson fails current checks; rewriting",
                extra={"data": {"topic": topic, "problems": problems}},
            )
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
            log.info(
                "lesson written",
                extra={
                    "data": {
                        "topic": topic,
                        "model": model,
                        "secs": round(time.monotonic() - t0, 1),
                    }
                },
            )
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
    """The handler class for this app: same routes, bound to `app`."""
    return routes.make_handler(app)


def main() -> None:
    s = settings_mod.load()
    log_path = setup_logging(s.log_dir)
    app = App(s)
    httpd = ThreadingHTTPServer((s.host, s.port), make_handler(app))
    log.info(
        "server up",
        extra={
            "data": {
                "url": f"http://127.0.0.1:{s.port}",
                "log": str(log_path),
                "writer_ready": app.writer.ready(),
                "model": app.s.model,
            }
        },
    )
    print(f"flow.py is running: http://127.0.0.1:{s.port}  (ctrl+c to stop)", flush=True)
    if not app.writer.ready():
        print(
            f"No {s.api_key_var} found, so only the built-in lessons will load. See the README.",
            flush=True,
        )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        log.info("server down")


if __name__ == "__main__":
    main()
