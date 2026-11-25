"""The chat helper in the side panel.

Every question comes with a snapshot of the learner's screen: the lesson, the level,
the full answer code (even the hidden parts), what they typed so far, and their last
run. The helper sees what the learner sees, plus the answer key, so it can nudge.
Each exchange is saved to data/chats.jsonl for the learner (and later the teacher).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("flowpy.tutor")

MAX_TURNS, MAX_MSG, MAX_FIELD = 24, 4000, 6000

SYSTEM = """You are the helper inside flow.py, a calm typing game that teaches Python.
The learner opened the side chat while playing. You can see their screen through the snapshot below.

How to help:
- Talk like a friendly older sibling: short, warm, plain words (5th-grade reading level). Usually 2-6 sentences.
- Answer what they asked. If they're stuck on a gap or a level-4 task, nudge first: explain the idea,
  point at the line, give a hint. Give the exact answer only if they ask for it straight out, or they're
  clearly frustrated or stuck after a hint.
- The snapshot is the truth about what's on screen right now. Talk about THIS lesson, not an older one.
- In "what they typed": _ is a hidden character not typed yet, ▌ is their cursor, [[...]] is a spot where they
  type their own words, and plain text after the cursor is still waiting to be typed. Wrong letters show as typed.
- Use small code examples in ```python fences when they help. Keep them short.
- The placement quiz finds which lessons they can skip. There, explain what their code does and why, but
  don't write the passing answer for them. If they don't know it, tell them tab ("don't know") is fine: that
  topic just gets taught. Once they've answered, explain freely.
- Python questions beyond the lesson are welcome too. Keep it about learning Python."""

LEVELS = {1: "type it all", 2: "fill the gaps", 3: "mostly memory", 4: "on your own (writes all the code)"}


def _clip(v, n: int = MAX_FIELD) -> str:
    s = v if isinstance(v, str) else json.dumps(v) if v is not None else ""
    return s if len(s) <= n else s[:n] + " …(cut)"


def snapshot_text(ctx: dict) -> str:
    """Turn the page's screen snapshot into plain text for the model."""
    if isinstance(ctx, dict) and ctx.get("quiz"):
        parts = [f"The placement quiz, question {_clip(ctx.get('number'), 20)} (topic: {_clip(ctx.get('topic'), 60)}). "
                 f"Kind: {_clip(ctx.get('kind'), 60)}.",
                 f"The question on screen:\n```\n{_clip(ctx.get('question'))}\n```",
                 f"What they typed:\n```\n{_clip(ctx.get('typed'))}\n```"]
        if isinstance(ctx.get("last_run"), dict):
            parts.append("Their last run: " + _clip(ctx["last_run"], 2000))
        if ctx.get("answered"):
            parts.append("They already answered this one and are looking at the feedback.")
        return "\n\n".join(parts)
    if not isinstance(ctx, dict) or not ctx.get("lesson"):
        where = ctx.get("screen", "a menu") if isinstance(ctx, dict) else "a menu"
        return f"Right now the learner is on {where}, not inside a lesson."
    lvl = ctx.get("level")
    parts = [f"Lesson: {_clip(ctx.get('lesson'), 200)}  |  level {lvl}: {LEVELS.get(lvl, '?') if isinstance(lvl, int) else '?'}"]
    for key, label in (("learn", "Lesson text on screen"), ("task", "Task on screen")):
        if ctx.get(key):
            parts.append(f"{label}:\n{_clip(ctx[key])}")
    if ctx.get("answer"):
        parts.append("Answer key (the full correct code, including the hidden parts; the learner can't see the hidden parts):\n"
                     f"```python\n{_clip(ctx['answer'])}\n```")
    if ctx.get("typed"):
        parts.append(f"What they typed so far:\n```\n{_clip(ctx['typed'])}\n```")
    if ctx.get("step"):
        parts.append(f"Where they are: {_clip(ctx['step'], 300)}")
    run = ctx.get("last_run")
    if isinstance(run, dict):
        parts.append("Their last run: " + _clip(run, 2000))
    if ctx.get("misses"):
        parts.append(f"Failed runs on this level so far: {ctx['misses']}")
    if ctx.get("hint"):
        parts.append(f"The lesson's own hint (shown after 2 misses): {_clip(ctx['hint'], 500)}")
    return "\n\n".join(parts)


def clean_messages(messages) -> list[dict] | None:
    if not isinstance(messages, list) or not messages:
        return None
    out = []
    for m in messages[-MAX_TURNS:]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
            return None
        out.append({"role": m["role"], "content": m["content"][:MAX_MSG]})
    if out[-1]["role"] != "user" or not out[-1]["content"].strip():
        return None
    return out


class Tutor:
    def __init__(self, writer, data_dir: Path):
        self.writer = writer
        self.path = data_dir / "chats.jsonl"
        self._lock = threading.Lock()

    def reply(self, messages: list[dict], ctx: dict, model: str, chat_id: str = "") -> str:
        system = SYSTEM + "\n\n--- The learner's screen right now ---\n" + snapshot_text(ctx)
        t0 = time.monotonic()
        text = self.writer.chat(model, system, messages).strip()
        row = {"at": int(time.time()), "chat": str(chat_id)[:40], "model": model,
               "lesson": ctx.get("lesson") if isinstance(ctx, dict) else None,
               "level": ctx.get("level") if isinstance(ctx, dict) else None,
               "q": messages[-1]["content"], "a": text, "secs": round(time.monotonic() - t0, 1)}
        with self._lock, self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        log.info("chat reply", extra={"data": {"model": model, "secs": row["secs"], "lesson": row["lesson"]}})
        return text
