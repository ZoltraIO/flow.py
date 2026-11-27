"""Lesson format, curriculum, and the checks every lesson must pass.

A lesson is one topic in four levels:
  1  learn + task + full code        (type it all)
  2  learn + task + code with gaps   (fill the gaps)
  3  task + code with bigger gaps    (mostly memory)
  4  task only, write it yourself    (on your own)

Code strings use three marks:
  [[x]]            hidden text you type from memory
  {{label|sample}} your own words (always inside quotes); sample is used for checks
  <<reason>>, <<name>>   filled from the learner's profile, or asked for if unknown
"""

from __future__ import annotations

import builtins
import json
import keyword
import re
from pathlib import Path

from runner import run_python

CURRICULUM: list[dict] = [
    {"topic": "print", "covers": "print() shows text; strings in quotes; one print per line"},
    {"topic": "variables", "covers": "name = value; reassigning; using a name without quotes"},
    {"topic": "strings", "covers": ".upper() .lower(), + to join, len()"},
    {"topic": "f-strings", "covers": 'f"..." with {name} and {math} inside'},
    {"topic": "math", "covers": "+ - * /, // floor division, % remainder"},
    {"topic": "lists", "covers": "[a, b], index from 0, .append(), len()"},
    {"topic": "if / else", "covers": "if/else, colon + 4-space indent, == vs =, < > >= <="},
    {"topic": "for loops", "covers": "for x in list, range(n), range(a, b), running totals"},
    {"topic": "while loops", "covers": "while condition:, counting up/down, stopping a loop"},
    {"topic": "dicts", "covers": '{"key": value}, d["key"], adding/changing keys'},
    {"topic": "functions", "covers": "def, parameters, return, calling"},
    {
        "topic": "try / except",
        "covers": "try/except to catch errors like ValueError and ZeroDivisionError",
    },
    {"topic": "comprehensions", "covers": "[expr for x in items], with if filter"},
    {"topic": "classes", "covers": "class, __init__, self, attributes, one simple method"},
    {
        "topic": "files",
        "covers": 'with open(..., "w") as f: f.write(); reading it back with .read()',
    },
]
TOPICS = [c["topic"] for c in CURRICULUM]
SAMPLES = {"reason": "build my own tools", "name": "Sam"}

_SEG_RE = re.compile(r"\[\[([\s\S]*?)\]\]|\{\{([\s\S]*?)\}\}|<<(reason|name)>>")
_CHECK_KINDS = {"code_has", "out_is", "out_has", "first_line", "min_lines"}
MAX_LEARN, MAX_TASK, MAX_SAY, MAX_CODE_LINES = 320, 170, 220, 9


def slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")


def segments(code: str) -> list[dict]:
    """Same split the page does: given (g), hidden (b), free (f), profile (p)."""
    segs, last = [], 0
    for m in _SEG_RE.finditer(code):
        if m.start() > last:
            segs.append({"t": "g", "s": code[last : m.start()]})
        if m.group(1) is not None:
            segs.append({"t": "b", "s": m.group(1)})
        elif m.group(2) is not None:
            label, _, sample = m.group(2).partition("|")
            segs.append({"t": "f", "ph": label.strip(), "sample": sample.strip() or "x"})
        else:
            segs.append({"t": "p", "key": m.group(3)})
        last = m.end()
    if last < len(code):
        segs.append({"t": "g", "s": code[last:]})
    return segs


def runnable(code: str) -> str:
    """The code a learner ends up with, using sample answers for their own words."""
    return "".join(
        s["s"] if s["t"] in "gb" else s["sample"] if s["t"] == "f" else SAMPLES[s["key"]]
        for s in segments(code)
    )


def norm_out(text: str) -> list[str]:
    lines = [ln.rstrip() for ln in (text or "").replace("\r", "").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def check_fails(check: dict, code: str, out: str) -> bool:
    kind, lines = check.get("kind"), norm_out(out)
    if kind == "code_has":
        return not re.search(check["re"], code)
    if kind == "out_is":
        return lines != norm_out(check["text"])
    if kind == "out_has":
        return check["text"] not in "\n".join(lines)
    if kind == "first_line":
        return not lines or lines[0].strip().lower() != str(check["text"]).strip().lower()
    if kind == "min_lines":
        return len([ln for ln in lines if ln.strip()]) < int(check["n"])
    return True


def _typable(text: str, allow_newline: bool) -> bool:
    return all(32 <= ord(c) <= 126 or (allow_newline and c == "\n") for c in text)


def _char_problems(code: str) -> list[str]:
    if _typable(code, True):
        return []
    return ["code must be plain keyboard characters (no tabs, smart quotes or emoji)"]


def _bracket_problems(code: str) -> list[str]:
    return [
        f"code contains {bad!r}; put a space or move the gap so marks never touch a bracket"
        for bad in ("[[[", "]]]", "{{{", "}}}")
        if bad in code
    ]


def _line_problems(code: str) -> list[str]:
    p = []
    if any(ln != ln.rstrip() for ln in code.split("\n")):
        p.append("code lines must not end in spaces")
    if len(code.split("\n")) > MAX_CODE_LINES:
        p.append(f"code is longer than {MAX_CODE_LINES} lines; keep it short")
    return p


def _gap_problems(text: str, before: str) -> list[str]:
    p = []
    if "\n" in text:
        p.append("a [[gap]] may not span lines; use one gap per line")
    if not before.strip() and text[:1].isspace():
        p.append("indentation must stay outside [[gaps]]")
    if not text.strip():
        p.append("empty [[gap]]")
    return p


def _free_problems(segs: list[dict], i: int, before: str) -> list[str]:
    p = []
    if (before.count('"') % 2 == 0) and (before.count("'") % 2 == 0):
        p.append("{{your words}} and <<profile>> marks must sit inside a quoted string")
    nxt = segs[i + 1] if i + 1 < len(segs) else None
    if not nxt or nxt["t"] != "g":
        p.append("{{your words}} must be followed by shown text (like the closing quote)")
    return p


def _segment_problems(segs: list[dict]) -> list[str]:
    p: list[str] = []
    for i, s in enumerate(segs):
        before = "".join(x.get("s", "") for x in segs[:i]).split("\n")[-1]
        if s["t"] == "b":
            p += _gap_problems(s["s"], before)
        elif s["t"] in "fp":
            p += _free_problems(segs, i, before)
    return p


def _gap_level_problems(lvl: int, hidden: int) -> list[str]:
    if lvl == 1 and hidden:
        return ["level 1 shows all the code; no [[gaps]]"]
    if lvl in (2, 3) and not hidden:
        return [f"level {lvl} needs [[gaps]]"]
    return []


def _code_problems(code: str, lvl: int) -> tuple[list[str], float]:
    segs = segments(code)
    hidden = sum(len(s["s"]) for s in segs if s["t"] == "b")
    total = sum(len(s.get("s", "")) for s in segs) or 1
    p = (
        _char_problems(code)
        + _bracket_problems(code)
        + _line_problems(code)
        + _segment_problems(segs)
        + _gap_level_problems(lvl, hidden)
    )
    return p, hidden / total


_WORD_RE = re.compile(r"(?<![\w.])[A-Za-z_]\w*")
_ALWAYS_KNOWN = set(keyword.kwlist) | set(dir(builtins)) | {"self"}


def guess_problems(code: str, shown: str) -> list[str]:
    """Gaps may only hide what the learner can work out.

    That means Python words, or names and values on screen.

    A name the lesson made up (like the a, b in def add(a, b)) must show up in the task,
    the learn text, or the visible code. Otherwise the learner is guessing, not remembering.
    Words right after a dot (.append, .upper) are Python's own, so they are fair game.
    Numbers are fair game too: working out range(1, 6) from "1 to 5" is the skill being practiced.
    """
    segs = segments(code)
    visible = shown + "\n" + "".join(s["s"] for s in segs if s["t"] == "g")
    known = _ALWAYS_KNOWN | set(_WORD_RE.findall(visible))
    out = []
    for i, s in enumerate(segs):
        if s["t"] != "b":
            continue
        after_dot = i > 0 and segs[i - 1]["t"] == "g" and segs[i - 1]["s"].endswith(".")
        words = dict.fromkeys(_WORD_RE.findall(("." if after_dot else "") + s["s"]))
        out.extend(
            f"the gap [[{s['s']}]] hides {w!r}, which the learner cannot know. "
            "Name it in the task (or leave it visible in the code), "
            "or keep it out of the gap"
            for w in words
            if w not in known
        )
    return out


def _shape_problems(lesson: dict) -> list[str]:
    p: list[str] = []
    if not isinstance(lesson.get("topic"), str) or not lesson["topic"].strip():
        p.append("topic is required")
    if not str(lesson.get("title", "")).strip():
        p.append("title is required")
    return p


def _four_rounds(rounds: list) -> bool:
    return [r.get("lvl") for r in rounds if isinstance(r, dict)] == [1, 2, 3, 4]


def _check_learn(r: dict) -> list[str]:
    learn = r.get("learn")
    if r["lvl"] <= 2:
        if not learn or not _typable(learn, False) or len(learn) > MAX_LEARN:
            return [
                f"learn is required, one paragraph, plain characters, at most {MAX_LEARN} chars"
            ]
        return []
    return ["levels 3 and 4 have no learn text"] if learn else []


def _check_task(r: dict) -> list[str]:
    task = r.get("task")
    if not task or not _typable(task, False) or len(task) > MAX_TASK:
        return [f"task is required, plain characters, at most {MAX_TASK} chars"]
    return []


def _check_say(r: dict) -> list[str]:
    say = r.get("say")
    if not say or not _typable(say, False) or len(say) > MAX_SAY:
        return [f"say is required, plain characters, at most {MAX_SAY} chars"]
    return []


def _check_lvl123(
    r: dict, timeout: float, max_chars: int, fractions: dict[int, float]
) -> list[str]:
    p = _check_learn(r) + _check_task(r) + _check_say(r)
    code = r.get("code")
    if not isinstance(code, str) or not code.strip():
        return p + ["code is required"]
    cp, fractions[r["lvl"]] = _code_problems(code, r["lvl"])
    p += cp
    p += guess_problems(code, f"{r.get('task') or ''}\n{r.get('learn') or ''}")
    res = run_python(runnable(code), timeout, max_chars)
    if not res["ok"]:
        p.append(f"code fails when run: {res['err']}")
    elif not res["out"].strip():
        p.append("code prints nothing; every level should print something")
    return p


def _check_item(c, sol: str, out: str) -> list[str]:
    if not isinstance(c, dict) or c.get("kind") not in _CHECK_KINDS or not c.get("msg"):
        return [f"each check needs kind (one of {sorted(_CHECK_KINDS)}) and msg"]
    try:
        if check_fails(c, sol, out):
            return [f"solution does not pass its own check {c}"]
    except (KeyError, re.error, ValueError) as exc:
        return [f"broken check {c}: {exc}"]
    return []


def _check_lvl4(r: dict, timeout: float, max_chars: int) -> list[str]:
    p = _check_learn(r) + _check_task(r) + _check_say(r)
    hint, sol, checks = r.get("hint"), r.get("solution"), r.get("checks")
    if not hint or not _typable(hint, False):
        p.append("hint is required")
    if not isinstance(sol, str) or not sol.strip() or not _typable(sol, True):
        return p + ["solution is required"]
    if not isinstance(checks, list) or not checks:
        return p + ["checks are required"]
    res = run_python(sol, timeout, max_chars)
    if not res["ok"]:
        return p + [f"solution fails when run: {res['err']}"]
    for c in checks:
        p += _check_item(c, sol, res["out"])
    return p


def _gap_growth_problems(fractions: dict[int, float]) -> list[str]:
    if 2 in fractions and 3 in fractions and fractions[3] <= fractions[2]:
        return [
            "level 3 must hide more of the code than level 2 "
            f"(level 2 hides {fractions[2]:.0%} of its characters, "
            f"level 3 hides {fractions[3]:.0%}). In level 3, keep only the first "
            "line visible and make every other line one whole-line gap; "
            "in level 2, hide 1-3 small pieces"
        ]
    return []


def validate(lesson: dict, timeout: float = 5, max_chars: int = 20000) -> list[str]:
    """Every problem with a lesson, in plain words. Empty list = good to play."""
    if not isinstance(lesson, dict):
        return ["lesson must be a JSON object"]
    p = _shape_problems(lesson)
    rounds = lesson.get("rounds")
    if not isinstance(rounds, list) or not _four_rounds(rounds):
        return p + ["rounds must be exactly four objects with lvl 1, 2, 3, 4 in order"]
    fractions: dict[int, float] = {}
    for r in rounds:
        tag = f"level {r['lvl']}: "
        if r["lvl"] < 4:
            p += [tag + x for x in _check_lvl123(r, timeout, max_chars, fractions)]
        else:
            p += [tag + x for x in _check_lvl4(r, timeout, max_chars)]
    return p + _gap_growth_problems(fractions)


class Store:
    """Hand-checked lessons ship in lessons_dir; written ones are cached in data_dir."""

    def __init__(self, lessons_dir: Path, data_dir: Path):
        self.lessons_dir, self.cache_dir = lessons_dir, data_dir / "lessons"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def builtin(self, topic: str) -> dict | None:
        f = self.lessons_dir / f"{slug(topic)}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def cached(self, topic: str) -> dict | None:
        f = self.cache_dir / f"{slug(topic)}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def save(self, lesson: dict) -> None:
        f = self.cache_dir / f"{slug(lesson['topic'])}.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(lesson, indent=2))
        tmp.replace(f)

    def status(self) -> list[dict]:
        return [
            {
                **c,
                "slug": slug(c["topic"]),
                "ready": bool(
                    (self.lessons_dir / f"{slug(c['topic'])}.json").exists()
                    or (self.cache_dir / f"{slug(c['topic'])}.json").exists()
                ),
            }
            for c in CURRICULUM
        ]
