"""flow.py app: runner, lesson checks, lesson writer, and the HTTP server end to end."""

from __future__ import annotations

import copy
import dataclasses
import json
import socket
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import lessons  # noqa: E402
import server  # noqa: E402
import settings as settings_mod  # noqa: E402
import writer as writer_mod  # noqa: E402
from runner import run_python  # noqa: E402

S = settings_mod.load()
FOR_LOOPS = json.loads((APP / "lessons" / "for-loops.json").read_text())


# ---------- runner ----------
def test_runner_ok_and_error_line():
    assert run_python('print("hi")', 5, 1000) == {"ok": True, "out": "hi"}
    res = run_python("x = 1\nprint(y)", 5, 1000)
    assert not res["ok"] and res["line"] == 2 and res["err"].startswith("NameError")


def test_runner_stops_endless_loops():
    res = run_python("while True:\n    pass", 1, 1000)
    assert not res["ok"] and res["timeout"]


def test_runner_hides_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    res = run_python("import os\nprint(sorted(k for k in os.environ if 'KEY' in k))", 5, 1000)
    assert res["out"] == "[]"


# ---------- lesson checks ----------
@pytest.mark.parametrize("path", sorted((APP / "lessons").glob("*.json")), ids=lambda p: p.stem)
def test_every_shipped_lesson_passes(path):
    assert lessons.validate(json.loads(path.read_text())) == []


def test_all_placement_topics_have_lessons():
    shipped = {p.stem for p in (APP / "lessons").glob("*.json")}
    quiz = ["print", "variables", "strings", "f-strings", "math", "lists", "if / else",
            "for loops", "dicts", "functions", "comprehensions"]
    assert {lessons.slug(t) for t in quiz} <= shipped


def _with_round(lvl, **changes):
    lesson = copy.deepcopy(FOR_LOOPS)
    lesson["rounds"][lvl - 1].update(changes)
    return lesson


@pytest.mark.parametrize("lvl,changes,needle", [
    (3, {"code": "nums = [[[1, 2]]]\nprint(nums)"}, "']]]'"),
    (2, {"code": 'x = {{your word|hi}}\nprint(x)'}, "inside a quoted string"),
    (1, {"code": "for n in [[range(3)]]:\n    print(n)"}, "level 1 shows all the code"),
    (2, {"code": "for n in range(3):\n    print(n)"}, "level 2 needs [[gaps]]"),
    (3, {"code": "print([[1]] + 1)"}, "hide more of the code than level 2"),
    (1, {"code": "print(undefined_name)"}, "code fails when run"),
    (4, {"solution": "print(5)"}, "does not pass its own check"),
    (3, {"learn": "extra text"}, "no learn text"),
    (3, {"code": "[[def add(a, b):]]\n    [[return a + b]]\n\nprint(add(2, 3))"}, "hides 'b'"),
])
def test_validate_catches_broken_lessons(lvl, changes, needle):
    problems = lessons.validate(_with_round(lvl, **changes))
    assert any(needle in p for p in problems), problems


def test_guessing_rule_allows_what_the_screen_shows():
    assert lessons.guess_problems("[[def add(a, b):]]\n    return a + b", "Write add.") == []  # a, b visible below
    assert lessons.guess_problems("nums.[[append]](4)\nprint([[len(nums)]])", "") == []  # methods, builtins
    assert lessons.guess_problems("print(mins [[// 60]])", "") == []  # numbers are worked out
    assert lessons.guess_problems('[[print("nope")]]', "Print nope.") == []
    assert lessons.guess_problems('[[print("nope")]]', "Print a message.") != []


def test_runnable_fills_samples_and_profile():
    code = 'goal = "<<reason>>"\nprint("[[hi]] {{your name|Ana}}")'
    assert lessons.runnable(code) == 'goal = "build my own tools"\nprint("hi Ana")'


# ---------- writer ----------
class FakeAPI:
    """Stands in for the OpenCode Go chat API: returns scripted replies in order."""

    def __init__(self, replies, models=None):
        self.replies, self.calls, self.model_ids = list(replies), [], models or []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if path == "/models":
            return {"data": [{"id": m} for m in self.model_ids]}
        return {"choices": [{"finish_reason": "stop", "message": {"content": self.replies.pop(0)}}]}


def _while_lesson():
    lesson = copy.deepcopy(FOR_LOOPS)
    lesson["topic"] = lesson["title"] = "while loops"
    return lesson


def test_writer_fixes_a_bad_draft():
    bad = _while_lesson()
    bad["rounds"][0]["code"] = "print(oops)"
    fake = FakeAPI(["```json\n" + json.dumps(bad) + "\n```", json.dumps(_while_lesson())])
    out = writer_mod.Writer(S, transport=fake).write("while loops", {"reason": "build tools"}, FOR_LOOPS,
                                                    model="claude-haiku-5-5")
    assert out["topic"] == "while loops" and out["source"]["by"] == "claude-haiku-5-5"
    assert len(fake.calls) == 2
    fix_request = fake.calls[1][2]["messages"][-1]["content"]
    assert "code fails when run" in fix_request
    first = fake.calls[0][2]
    assert first["model"] == "claude-haiku-5-5" and first["messages"][0]["role"] == "system"
    assert "build tools" in first["messages"][1]["content"]


def test_writer_defaults_to_config_model():
    fake = FakeAPI([json.dumps(_while_lesson())])
    writer_mod.Writer(S, transport=fake).write("while loops", {}, None)
    assert fake.calls[0][2]["model"] == S.model == "deepseek-v4.1-flash"


def test_writer_gives_up_after_fix_attempts():
    fake = FakeAPI(["not json"] * (1 + S.fix_attempts))
    with pytest.raises(writer_mod.WriterFailed):
        writer_mod.Writer(S, transport=fake).write("while loops", {}, None)


def test_writer_model_list_puts_default_first_and_drops_embeddings():
    fake = FakeAPI([], models=["glm-5.3", "deepseek-v4.1-flash", "claude-haiku-5-5", "text-embedding-3-small"])
    assert writer_mod.Writer(S, transport=fake).models() == ["deepseek-v4.1-flash", "glm-5.3", "claude-haiku-5-5"]


def test_writer_without_key(monkeypatch):
    s = dataclasses.replace(S, api_key_var="FLOWPY_TEST_NO_SUCH_KEY")
    monkeypatch.delenv("FLOWPY_TEST_NO_SUCH_KEY", raising=False)
    w = writer_mod.Writer(s)
    assert not w.ready()
    with pytest.raises(writer_mod.WriterUnavailable):
        w.write("while loops", {}, None)


def test_api_key_strips_inline_comment(monkeypatch):
    monkeypatch.setenv("FLOWPY_TEST_KEY", "sk-abc #someone@example.com")
    assert writer_mod.api_key("FLOWPY_TEST_KEY") == "sk-abc"


# ---------- server ----------
def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def live(tmp_path, monkeypatch):
    port = _free_port()
    s = dataclasses.replace(S, port=port, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    server.setup_logging(s.log_dir)
    fake = SimpleNamespace(calls=[])

    def write(topic, profile, example, model=None, plan=None):
        fake.calls.append(topic)
        fake.models_used.append(model)
        if fake.fail:
            raise writer_mod.WriterUnavailable("no key")
        return {**_while_lesson(), "source": {"by": "fake"}}

    def chat(model, system, messages):
        fake.chats.append(messages[-1]["content"])
        fake.systems.append(system)
        return fake.teacher_replies.pop(0)

    fake.fail, fake.write, fake.models_used, fake.chat, fake.chats = False, write, [], chat, []
    fake.teacher_replies, fake.systems = [], []
    fake.ready = lambda: False
    fake.models = lambda: [S.model, "claude-haiku-5-5"]
    app = server.App(s, writer=fake)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", port), server.make_handler(app))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield SimpleNamespace(base=f"http://127.0.0.1:{port}", port=port, app=app, writer=fake)
    httpd.shutdown()
    httpd.server_close()


def call(live, method, path, body=None, headers=None):
    hdrs = {"X-Flowpy": "1", **(headers or {})}
    data = None
    if body is not None:
        data, hdrs["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(live.base + path, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_server_page_and_health(live):
    with urllib.request.urlopen(live.base + "/") as r:
        assert b"flow" in r.read() and r.headers["Cache-Control"] == "no-store"
    code, body = call(live, "GET", "/api/health")
    assert code == 200 and body["ok"] and body["writer"]["ready"] is False


def test_server_blocks_other_sites(live):
    assert call(live, "POST", "/api/run", {"code": "print(1)"}, {"X-Flowpy": ""})[0] == 403
    assert call(live, "POST", "/api/run", {"code": "print(1)"}, {"Origin": "https://evil.example"})[0] == 403
    assert call(live, "GET", "/api/health", headers={"Host": "evil.example"})[0] == 403


def test_server_runs_code(live):
    code, body = call(live, "POST", "/api/run", {"code": "print(6 * 7)"})
    assert code == 200 and body == {"ok": True, "out": "42"}


def test_server_saves_progress_and_events(live):
    assert call(live, "GET", "/api/progress") == (200, {})
    prog = {"v": 1, "profile": {"name": "Sam"}, "at": {"topic": "math", "lvl": 2}, "xp": 40}
    assert call(live, "PUT", "/api/progress", prog)[0] == 200
    assert call(live, "GET", "/api/progress") == (200, prog)
    call(live, "POST", "/api/event", {"type": "round", "topic": "math", "lvl": 4, "acc": 90, "fails": 1})
    assert live.app.stats() == {"rounds_done": 1, "avg_accuracy": 90, "avg_level4_misses": 1.0}


def test_server_lessons_builtin_written_cached_and_no_key(live):
    code, body = call(live, "GET", "/api/lesson?topic=math")
    assert code == 200 and body["from"] == "builtin" and live.writer.calls == []
    code, body = call(live, "GET", "/api/lesson?topic=while%20loops")
    assert code == 200 and body["from"] == "written"
    code, body = call(live, "GET", "/api/lesson?topic=while%20loops")
    assert body["from"] == "cache" and live.writer.calls == ["while loops"]
    live.writer.fail = True
    code, body = call(live, "GET", "/api/lesson?topic=classes")
    assert code == 503 and body["error"] == "no_key"
    assert call(live, "GET", "/api/lesson?topic=nope")[0] == 404
    assert live.writer.models_used == [S.model, S.model]


def test_server_model_choice(live):
    code, body = call(live, "GET", "/api/models")
    assert code == 200 and body == {"default": S.model, "chosen": S.model, "models": [S.model, "claude-haiku-5-5"]}
    call(live, "PUT", "/api/progress", {"v": 1, "model": "claude-haiku-5-5"})
    assert call(live, "GET", "/api/health")[1]["writer"]["model"] == "claude-haiku-5-5"
    call(live, "GET", "/api/lesson?topic=classes")
    assert live.writer.models_used == ["claude-haiku-5-5"]


def test_server_log_endpoint_keeps_page_errors(live):
    call(live, "POST", "/api/log", {"level": "error", "msg": "page broke", "extra": {"where": "test"}})
    code, body = call(live, "GET", "/api/logs?level=error&n=5")
    assert code == 200 and any(r["msg"] == "page broke" and r["src"] == "page" for r in body["rows"])


# ---------- teacher ----------
def _pick(title, kind="new", notes="likes tools"):
    return json.dumps({"notes": notes, "next": {"title": title, "covers": "reading csv text",
                                                "why": "You want to build tools, and tools read data.", "kind": kind}})


def test_teacher_picks_remembers_and_feeds_the_writer(live):
    call(live, "PUT", "/api/progress", {"v": 1, "profile": {"reason": "automate my spreadsheets"}})
    call(live, "POST", "/api/event", {"type": "round", "topic": "dicts", "lvl": 4, "acc": 88, "fails": 3, "secs": 60})
    live.writer.teacher_replies = ["oops", _pick("dicts"), _pick("csv basics")]
    code, body = call(live, "POST", "/api/teacher/next", {})
    assert code == 200 and body["entry"]["id"] == "t1-csv-basics" and body["entry"]["title"] == "csv basics"
    brief = live.writer.chats[0]
    assert "automate my spreadsheets" in brief and '"l4_misses": 3' in brief
    assert "already on the path" in live.writer.chats[2]     # "dicts" was rejected, then fixed
    # not played yet: asking again hands back the same pick, no new model call
    assert call(live, "POST", "/api/teacher/next", {})[1]["entry"]["id"] == "t1-csv-basics"
    assert len(live.writer.chats) == 3
    st = call(live, "GET", "/api/teacher")[1]
    assert st["notes"] == "likes tools" and [e["id"] for e in st["path"]] == ["t1-csv-basics"]
    assert call(live, "GET", "/api/curriculum")[1]["extra"][0]["topic"] == "t1-csv-basics"
    code, body = call(live, "GET", "/api/lesson?topic=t1-csv-basics")
    assert code == 200 and live.writer.calls == ["t1-csv-basics"]
    # once played, the teacher picks again, and never two reviews in a row
    call(live, "POST", "/api/event", {"type": "round", "topic": "t1-csv-basics", "lvl": 1, "acc": 95})
    live.writer.teacher_replies = [_pick("csv again", "review"), _pick("csv more", "review"), _pick("json files")]
    assert call(live, "POST", "/api/teacher/next", {})[1]["entry"]["kind"] == "review"
    call(live, "POST", "/api/event", {"type": "round", "topic": "t2-csv-again", "lvl": 1, "acc": 95})
    assert call(live, "POST", "/api/teacher/next", {})[1]["entry"]["id"] == "t3-json-files"


def test_cached_lesson_that_breaks_new_rules_is_rewritten(live):
    bad = _while_lesson()
    bad["rounds"][2]["code"] = 'n = 3\n[[while n > 0:]]\n    [[print("go now")]]\n    [[n = n - 1]]'
    live.app.store.save(bad)
    code, body = call(live, "GET", "/api/lesson?topic=while%20loops")
    assert code == 200 and body["from"] == "written" and live.writer.calls == ["while loops"]


def test_chat_sees_the_screen_and_saves_the_talk(live):
    live.writer.teacher_replies.append("Split each row with .split(), then add int(parts[1]).")
    ctx = {"lesson": "split lines into fields", "level": 3, "task": "Add up the numbers.",
           "answer": 'rows = ["tea 2"]\ntotal = 0\nprint(total)', "typed": "rows = [\"tea 2\"]\n_____",
           "last_run": {"ok": False, "err": "NameError: name 'totl' is not defined"}, "misses": 2}
    msgs = [{"role": "user", "content": "im dying over here bro"}]
    code, body = call(live, "POST", "/api/chat", {"messages": msgs, "context": ctx, "chat": "c1"})
    assert code == 200 and body["reply"].startswith("Split each row")
    system = live.writer.systems[-1]
    for needle in ("split lines into fields", "level 3", "total = 0", "_____", "totl", "Failed runs on this level so far: 2"):
        assert needle in system, needle
    row = json.loads((live.app.s.data_dir / "chats.jsonl").read_text().splitlines()[-1])
    assert row["q"] == "im dying over here bro" and row["lesson"] == "split lines into fields" and row["chat"] == "c1"


def test_chat_rejects_bad_messages_and_handles_menus(live):
    assert call(live, "POST", "/api/chat", {"messages": []})[0] == 400
    assert call(live, "POST", "/api/chat", {"messages": [{"role": "system", "content": "x"}]})[0] == 400
    assert call(live, "POST", "/api/chat", {"messages": [{"role": "assistant", "content": "hi"}]})[0] == 400
    live.writer.teacher_replies.append("A list holds many things in order.")
    code, _ = call(live, "POST", "/api/chat", {"messages": [{"role": "user", "content": "what is a list"}],
                                                "context": {"screen": "the home screen"}})
    assert code == 200 and "the home screen, not inside a lesson" in live.writer.systems[-1]


def test_chat_without_key_says_so(live):
    def no_key(model, system, messages):
        raise writer_mod.WriterUnavailable("No key")
    live.writer.chat = no_key
    code, body = call(live, "POST", "/api/chat", {"messages": [{"role": "user", "content": "help"}]})
    assert code == 503 and body["error"] == "no_key"


def test_chat_sees_the_placement_quiz(live):
    live.writer.teacher_replies.append("Your loop adds 1 before it prints.")
    ctx = {"quiz": True, "topic": "for loops", "number": "9 of 12", "kind": "write code",
           "question": "Write a loop that prints 1, 2 and 3, each on its own line.",
           "typed": "n = 0\nfor n in range(1, 4):\n    n += 1\n    print(n)",
           "last_run": {"ok": False, "output": "2\n3\n4", "error": ""}}
    code, _ = call(live, "POST", "/api/chat", {"messages": [{"role": "user", "content": "why not 1 2 3"}], "context": ctx})
    system = live.writer.systems[-1]
    assert code == 200
    for needle in ("placement quiz, question 9 of 12", "prints 1, 2 and 3", "n += 1", "2\\n3\\n4", "don't write the passing answer"):
        assert needle in system, needle
