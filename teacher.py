"""The teacher: once the core path is done, it picks every next lesson.

It looks at the learner's goal, how each level went, and its own notes, then
returns the next step: a new lesson toward the goal, or a review of a weak spot.
Its notes and the path it built live in data/teacher.json, so it remembers.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

import lessons
from writer import WriterFailed, _extract_json

log = logging.getLogger("flowpy.teacher")

MAX_NOTES, MAX_TITLE, MAX_COVERS, MAX_WHY = 800, 40, 200, 180

SYSTEM = """You are the teacher inside flow.py, a calm typing game that teaches Python.
Every lesson is one small idea in four levels: type it all, fill the gaps, mostly from memory, write it yourself.
The learner finished the core path. Now you pick their next lesson, one at a time, forever.

How to pick:
- Serve the learner's goal. Each new lesson is one small, concrete step toward it, small enough for one lesson.
- Build on what they know. Introduce at most one new idea per lesson.
- Read the numbers. If a topic looks weak (accuracy under 90, 3+ misses on level 4, or slow), you may pick a
  "review" lesson: the same idea again in a fresh example tied to the goal. Never two reviews in a row.
- Lessons run in a sandbox: Python standard library only, no internet, no input(), 5 seconds max, and the code
  must print something. Pick ideas that work there (string methods, json, csv text kept in a string, datetime,
  random with a seed, pathlib and files in the current folder, collections, sorting, small classes, and so on).
- Never reuse a title from the path so far.

Return only one JSON object:
{"notes": "...", "next": {"title": "...", "covers": "...", "why": "...", "kind": "new" or "review"}}
- notes: your memory of this learner, at most 600 characters. Keep what still matters and add what you noticed
  (strengths, weak spots, pace, how the goal is shaping up).
- title: 2-5 plain lowercase words. covers: what the lesson teaches, one line.
- why: one short, warm sentence to the learner about why this is next, at a 5th-grade reading level."""


def _plain(text, limit: int) -> bool:
    return (
        isinstance(text, str)
        and 0 < len(text.strip()) <= limit
        and text.isascii()
        and "\n" not in text
    )


def _title_problem(nxt: dict, st: dict) -> str:
    title = nxt.get("title")
    if not _plain(title, MAX_TITLE) or not re.search(r"[a-z]", str(title or "").lower()):
        return f"title must be plain text, at most {MAX_TITLE} characters"
    taken = {e["title"] for e in st["path"]} | set(lessons.TOPICS)
    if str(title).strip().lower() in taken:
        return "that title is already on the path; pick something new"
    return ""


def _covers_problem(nxt: dict) -> str:
    if not _plain(nxt.get("covers"), MAX_COVERS):
        return f"covers must be one plain line, at most {MAX_COVERS} characters"
    return ""


def _why_problem(nxt: dict) -> str:
    if not _plain(nxt.get("why"), MAX_WHY):
        return f"why must be one plain sentence, at most {MAX_WHY} characters"
    return ""


def _kind_problem(nxt: dict) -> str:
    if nxt.get("kind") not in ("new", "review"):
        return 'kind must be "new" or "review"'
    return ""


def _review_problem(nxt: dict, st: dict) -> str:
    path = st["path"]
    if nxt.get("kind") == "review" and path and path[-1]["kind"] == "review":
        return "never two reviews in a row; pick a new lesson"
    return ""


def _notes_problem(notes) -> str:
    return "" if isinstance(notes, str) else "notes must be a string"


class Teacher:
    def __init__(self, s, writer, data_dir: Path):
        self.s, self.writer = s, writer
        self.path = data_dir / "teacher.json"
        self._lock = threading.Lock()

    # ---- memory ---------------------------------------------------------
    def state(self) -> dict:
        try:
            st = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            st = {}
        return {"notes": st.get("notes", ""), "path": st.get("path", [])}

    def _write(self, st: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=2))
        tmp.replace(self.path)

    def entry(self, topic_id: str) -> dict | None:
        return next((e for e in self.state()["path"] if e["id"] == topic_id), None)

    def plan(self, topic_id: str) -> dict | None:
        """What the writer needs to write this teacher lesson."""
        st = self.state()
        ids = [e["id"] for e in st["path"]]
        if topic_id not in ids:
            return None
        e = st["path"][ids.index(topic_id)]
        before = lessons.TOPICS + [x["title"] for x in st["path"][: ids.index(topic_id)]]
        return {"title": e["title"], "covers": e["covers"], "why": e["why"], "before": before}

    # ---- picking the next lesson ---------------------------------------
    def _brief(self, goal: str, topic_stats: dict, st: dict) -> str:
        path = [
            {
                "title": e["title"],
                "kind": e["kind"],
                "how_it_went": topic_stats.get(e["id"], "not played yet"),
            }
            for e in st["path"]
        ]
        core = {
            t: topic_stats.get(t, "skipped (knew it from the placement quiz)")
            for t in lessons.TOPICS
        }
        return "\n\n".join(
            [
                f"The learner's goal: {goal!r}."
                if goal
                else "The learner has not said a goal yet. Pick broadly useful skills for writing small scripts and tools.",
                "Your notes so far: " + (st["notes"] or "(none yet, this is your first pick)"),
                "Core path results per topic (acc = typing accuracy %, l4_misses = wrong runs on level 4):\n"
                + json.dumps(core),
                "Lessons you picked so far, in order:\n"
                + (json.dumps(path) if path else "(none yet)"),
                "Pick the next lesson.",
            ]
        )

    def next(self, goal: str, topic_stats: dict, model: str) -> dict:
        """The next lesson on the path. If the last pick was never played, hand that one back."""
        with self._lock:
            st = self.state()
            if st["path"] and st["path"][-1]["id"] not in topic_stats:
                return st["path"][-1]
            messages = [{"role": "user", "content": self._brief(goal, topic_stats, st)}]
            problem, nxt, notes = "not asked yet", {}, ""
            for _ in range(1 + self.s.fix_attempts):
                text = self.writer.chat(model, SYSTEM, messages)
                try:
                    reply = _extract_json(text)
                    nxt, notes = reply.get("next") or {}, reply.get("notes", "")
                    problem = self._problem(nxt, notes, st)
                except (ValueError, json.JSONDecodeError) as exc:
                    problem = f"reply was not valid JSON: {exc}"
                if not problem:
                    break
                messages += [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": f"That reply has a problem: {problem}. Send the whole JSON again.",
                    },
                ]
            if problem:
                raise WriterFailed("The teacher's pick did not pass its checks: " + problem)
            title = nxt["title"].strip().lower()
            entry = {
                "id": f"t{len(st['path']) + 1}-{lessons.slug(title)}",
                "title": title,
                "covers": nxt["covers"].strip(),
                "why": nxt["why"].strip(),
                "kind": nxt["kind"],
                "by": model,
                "at": int(time.time()),
            }
            st["path"].append(entry)
            st["notes"] = str(notes).strip()[:MAX_NOTES]
            self._write(st)
            log.info("teacher picked", extra={"data": {"entry": entry, "notes": st["notes"]}})
            return entry

    @staticmethod
    def _problem(nxt: dict, notes, st: dict) -> str:
        if not isinstance(nxt, dict):
            return '"next" must be an object'
        problems = [
            _title_problem(nxt, st),
            _covers_problem(nxt),
            _why_problem(nxt),
            _kind_problem(nxt),
            _review_problem(nxt, st),
            _notes_problem(notes),
        ]
        return next((p for p in problems if p), "")
