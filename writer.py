"""An AI model writes new lessons in the flow.py format, and every lesson gets checked before play.

Each lesson is run through lessons.validate. If it fails, the problems go back
to the model for a fix, up to `fix_attempts` times.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid

import lessons
import settings as settings_mod

log = logging.getLogger("flowpy.writer")

SYSTEM = """You write lessons for flow.py, a calm typing game that teaches Python.
The learner types every word on the screen, like a typing test. Flow matters more than anything:
short, clear, warm, no fluff, no jokes that need explaining. Write at a 5th-grade reading level.

A lesson is one topic in exactly four levels:
- lvl 1: "learn" (the idea, 1-3 short sentences), "task" (one sentence), "code" fully shown (no gaps). Teach the core idea.
- lvl 2: "learn" (one new detail), "task", "code" with 1-3 small [[gaps]]: a keyword, a method name, or one
  argument. Most of the code stays visible.
- lvl 3: no learn. "task" + "code" where whole lines are gaps. Keep the first line visible (usually the line that
  sets up the data); every other line is one gap from just after its indentation to the end of the line,
  like    [[print(parts[0])]]
  If a line ends in ], end the gap before the last bracket part so marks never touch:  [[ip = parts]][0]
  The learner can't see those lines, so the level 3 task names every variable they make, in order:
  "Split ip into parts, turn each part into n, and print n."
- lvl 4: no learn, no code. "task" (exact enough that the output is clear), "hint" (a near-answer for after 2 misses),
  "solution" (working code), "checks" (how the page grades the learner's code; see below). Keep it small: 2-5 lines.
How much a level hides is counted in characters: hidden characters divided by all the code's characters.
The recipe above puts level 2 under about a third and level 3 over half, and level 3 must always hide a bigger
share than level 2.
Every round also has "say": one short line shown after it runs. It may use %out% (last output line), %name%, %reason%.

Code rules (the page breaks if you ignore these):
- Plain keyboard characters only. 4-space indents. No tabs, no trailing spaces, at most 9 lines, and it must print something.
- [[x]] marks hidden text. A gap never spans lines and never includes the indentation at the start of a line.
  Never let marks touch brackets: no "[[[" or "]]]" anywhere. Rewrite the line instead.
- {{label|sample}} is the learner's own words (e.g. {{your name|Sam}}). Only inside a quoted string, and always followed by shown text such as the closing quote.
- <<name>> and <<reason>> drop in what the learner told us. Only inside a quoted string.
- Never write two braces in a row except for those marks. f-strings use single braces like f"{n} cats".
- Only use Python the learner already knows (the topics before this one) plus this topic.
- Never make the learner guess. A gap may hide Python words, or names and text that are visible elsewhere
  (in the task, the learn text, or the shown code). If a gap hides a name you made up, like the a and b in
  def add(a, b), or the words of a printed message, say them in the task first. Numbers they can work out are fine.
- Lessons run in a sandbox: standard library only, no internet, no input(), 5 seconds max.

checks (level 4) is a list. Each item has "kind", its field, and "msg" (what to tell the learner when it fails):
- {"kind": "out_is", "text": "exact output", "msg": "..."}
- {"kind": "out_has", "text": "piece of output", "msg": "..."}
- {"kind": "first_line", "text": "hello", "msg": "..."}
- {"kind": "min_lines", "n": 2, "msg": "..."}
- {"kind": "code_has", "re": "python regex the code must match", "msg": "..."}
Use out_is when the task fixes the output, plus a code_has so they really use the topic.

Each round object has exactly these keys (every value is a non-empty string except lvl and checks):
- lvl 1 and 2: "lvl", "learn", "task", "code", "say"
- lvl 3: "lvl", "task", "code", "say"
- lvl 4: "lvl", "task", "hint", "solution", "checks", "say"
Length limits, in characters: "learn" 320, "task" 170, "say" 220. One short sentence fits a task.

Return only the lesson as one JSON object: {"topic": ..., "title": ..., "rounds": [4 objects with "lvl" 1-4]}.
No markdown, no commentary."""


class WriterUnavailable(RuntimeError):
    """No API key for the lesson writer on this machine."""


class WriterFailed(RuntimeError):
    """The model answered, but no version of the lesson passed its checks."""


def api_key(var: str) -> str:
    """The key comes from the .env file first, on purpose: the shell may export a different account's key."""
    value = ""
    try:
        from dotenv import dotenv_values

        value = dotenv_values(settings_mod.ENV_PATH).get(var) or ""
    except ImportError:
        pass
    value = value or os.environ.get(var, "")
    return value.split(" #")[0].split("\t#")[0].strip()


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return json.loads(text[start : end + 1])


def plan_for(topic: str) -> dict:
    """What a core topic covers and what came before it."""
    idx = lessons.TOPICS.index(topic)
    return {
        "title": topic,
        "covers": lessons.CURRICULUM[idx]["covers"],
        "before": lessons.TOPICS[:idx],
    }


def _brief(topic: str, profile: dict, example: dict | None, plan: dict | None = None) -> str:
    plan = plan or plan_for(topic)
    before = ", ".join(plan["before"]) or "nothing yet"
    lines = [
        f"Write the lesson {plan['title']!r} (title it {plan['title']!r}). It covers: {plan['covers']}.",
        f"The learner already met: {before}.",
    ]
    if plan.get("why"):
        lines.append(f"Their teacher picked this lesson because: {plan['why']}")
    if profile.get("reason"):
        lines.append(f"Their goal: {profile['reason']!r}. Pick examples that serve that goal.")
    stats = profile.get("stats") or {}
    if stats:
        lines.append(
            f"How they are doing so far: {json.dumps(stats)}. Pitch the difficulty to that."
        )
    if example:
        lines.append(
            "Here is a finished lesson in the exact format, for a different topic:\n"
            + json.dumps(example)
        )
    return "\n\n".join(lines)


class Writer:
    """Talks to an OpenAI-style chat API (OpenCode Go by default). `transport` is swappable for tests."""

    def __init__(self, settings, transport=None):
        self.s = settings
        self._transport = transport
        self._session = str(uuid.uuid4())  # OpenCode Go wants one x-opencode-session per client
        self._models: tuple[float, list[str]] | None = None
        self._models_lock = threading.Lock()

    def ready(self) -> bool:
        return self._transport is not None or bool(api_key(self.s.api_key_var))

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        if self._transport is not None:
            return self._transport(method, path, body)
        key = api_key(self.s.api_key_var)
        if not key:
            raise WriterUnavailable(
                f"No {self.s.api_key_var} in .env, so the lesson writer is off."
            )
        req = urllib.request.Request(
            self.s.base_url.rstrip("/") + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "flowpy/1.0",
                "x-opencode-session": self._session,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.s.request_timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode(errors="replace")
            raise WriterFailed(f"{self.s.provider} said HTTP {exc.code}: {detail}") from exc

    def models(self) -> list[str]:
        """Chat models on the account, cached for 10 minutes. Falls back to the default model."""
        with self._models_lock:
            if self._models and time.monotonic() - self._models[0] < 600:
                return self._models[1]
            try:
                ids = [m["id"] for m in self._call("GET", "/models").get("data", [])]
                ids = [i for i in ids if "embedding" not in i] or [self.s.model]
            except Exception as exc:  # offline or no key: still let the page show the default
                log.warning("model list failed", extra={"data": {"why": str(exc)[:200]}})
                return [self.s.model]
            if self.s.model in ids:
                ids.remove(self.s.model)
            ids.insert(0, self.s.model)
            self._models = (time.monotonic(), ids)
            return ids

    def chat(self, model: str, system: str, messages: list[dict]) -> str:
        resp = self._call(
            "POST",
            "/chat/completions",
            {
                "model": model,
                "max_tokens": self.s.max_tokens,
                "messages": [{"role": "system", "content": system}, *messages],
            },
        )
        choice = (resp.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise WriterFailed("The lesson came back cut off.")
        text = (choice.get("message") or {}).get("content") or ""
        if not text.strip():
            raise WriterFailed(f"{model} sent back an empty reply.")
        return text

    def _ask(self, model: str, messages: list[dict]) -> str:
        return self.chat(model, SYSTEM, messages)

    def write(
        self,
        topic: str,
        profile: dict,
        example: dict | None,
        model: str | None = None,
        plan: dict | None = None,
    ) -> dict:
        model = model or self.s.model
        messages = [{"role": "user", "content": _brief(topic, profile, example, plan)}]
        problems: list[str] = []
        for attempt in range(1 + self.s.fix_attempts):
            t0 = time.monotonic()
            text = self._ask(model, messages)
            try:
                lesson = _extract_json(text)
                problems = lessons.validate(lesson, self.s.run_timeout, self.s.max_output_chars)
            except (ValueError, json.JSONDecodeError) as exc:
                lesson, problems = None, [f"reply was not valid JSON: {exc}"]
            log.info(
                "lesson draft",
                extra={
                    "data": {
                        "topic": topic,
                        "model": model,
                        "attempt": attempt + 1,
                        "secs": round(time.monotonic() - t0, 1),
                        "problems": problems,
                    }
                },
            )
            if lesson is not None and not problems:
                lesson["topic"], lesson["source"] = topic, {"by": model, "at": int(time.time())}
                return lesson
            messages += [
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": "That lesson fails these checks. Fix every one and return the whole lesson again:\n- "
                    + "\n- ".join(problems),
                },
            ]
        raise WriterFailed("The lesson did not pass its checks: " + "; ".join(problems[:5]))
