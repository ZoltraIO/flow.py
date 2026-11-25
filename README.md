# flow.py

Learn Python by typing. It's calm, keyboard-only, and black on black. You don't read about code, you type it until your fingers know it.

Each topic has four levels, and each level shows less code:

1. **type it all.** Type the lesson, the task, and the full code, then run it.
2. **fill the gaps.** Some of the code is hidden.
3. **mostly memory.** No lesson text, and most of the code is hidden.
4. **on your own.** You get only the task and write the code yourself.

⌘↵ (or ctrl↵) runs code, ⇧↵ adds a new line, and esc goes back. A short placement quiz at the start skips topics you already know.

## Run it

You need Python 3.10 or newer.

```
git clone https://github.com/ZoltraIO/flow.py.git
cd flow.py
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

Then open http://127.0.0.1:8770. Press ctrl+c to stop.

The 11 built-in lessons work with no setup and no account.

## The AI writer and teacher (optional)

The built-in lessons cover the basics. For the rest, an AI model writes lessons on the fly: while loops, try / except, classes, files. After the core path, a **teacher** picks every next lesson. It uses the goal you give it, how each level went, and its own notes about you.

To turn this on, get an [OpenCode Go](https://opencode.ai) API key, then:

```
cp .env.example .env     # then paste your key after OPENCODE_GO_API_KEY=
```

Restart the server. Press **m** on the home screen to pick which model writes your lessons. The default is `deepseek-v4.1-flash`.

Every lesson the AI writes goes through checks before you see it:
- Every code sample runs in real Python.
- Each level-4 answer has to pass its own grading checks.
- Gaps never make you guess: a hidden name or printed text has to appear somewhere on screen.

If a lesson fails, the problems go back to the model so it can fix them.

## How it fits together

| Piece | What it does |
|---|---|
| `static/index.html` | The whole game: the typer, the placement quiz, the levels. |
| `server.py` | Serves the game, runs code, saves progress, hands out lessons, and keeps logs. Listens on 127.0.0.1 only. |
| `runner.py` | Runs your code in a separate Python process. It has a 5 second limit, no API keys, and an empty temp folder. |
| `lessons.py` | Holds the lesson format, the topic order, and the checks every lesson must pass. |
| `lessons/*.json` | Hand-checked lessons for the 11 placement topics. |
| `writer.py` | Asks the AI model to write lessons for topics that have no file yet. |
| `teacher.py` | Picks each next lesson after the core path. Its memory is `data/teacher.json`. |
| `tools/build_lessons.py` | The source for the built-in lessons. It rewrites and re-checks them. |
| `config.yaml` | Every setting: port, default model, time limits. |

Run the tests with `python -m pytest -q tests`.

## Your data stays on your machine

These files are created as you play. They are never committed:
- `data/progress.json`: where you are, your xp, and your name and goal
- `data/events.jsonl`: one line per finished level
- `data/lessons/`: lessons the AI wrote, cached
- `data/teacher.json`: the teacher's notes about you
- `logs/server.jsonl`: errors, readable at `GET /api/logs?level=error`

The only thing that leaves your computer is the lesson writer's request to OpenCode Go, and only if you add a key.

**Safety note:** the server runs whatever Python you type, on your own computer. It only listens on 127.0.0.1, so keep it that way.

## License

MIT. See [LICENSE](LICENSE).
