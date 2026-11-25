"""Writes the hand-made lessons to flowpy-app/lessons/*.json and checks every one.

Run: .venv/bin/python flowpy-app/tools/build_lessons.py
"""
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import lessons  # noqa: E402


def L(topic, title, r1, r2, r3, r4):
    return {"topic": topic, "title": title, "rounds": [{"lvl": 1, **r1}, {"lvl": 2, **r2}, {"lvl": 3, **r3}, {"lvl": 4, **r4}]}


def has(re_, msg):
    return {"kind": "code_has", "re": re_, "msg": msg}


def out(text, msg):
    return {"kind": "out_is", "text": text, "msg": msg}


ALL = [
    L("print", "print()",
      {"learn": "print() shows something on the screen. Text goes inside quotes. Python calls text in quotes a string.",
       "task": "Finish the sentence with your real reason. Then run it.",
       "code": 'print("I want to learn Python so I can {{your reason|build my own tools}}")',
       "save": "reason",
       "say": '"%reason%." Good. Everything we build from here points at that.'},
      {"learn": "Each print() makes its own line. Python runs your code from the top down.",
       "task": "Print hello. Then print your name on the next line.",
       "code": 'print("hello")\n[[print(]]"{{your name|Sam}}"[[)]]',
       "save": "name",
       "say": "Two print() calls, two lines. The gaps you just filled were print( and ). You knew them."},
      {"task": "Print three lines: ready, then set, then go.",
       "code": '[[print]]("ready")\n[[print("set")]]\n[[print("go")]]',
       "say": "Most of that came from memory. That is the whole trick."},
      {"task": "Print two lines. The first says hello. The second says anything you want.",
       "hint": 'Two print() lines. The first one is print("hello").',
       "solution": 'print("hello")\nprint("I did it")',
       "checks": [{"kind": "min_lines", "n": 2, "msg": "Close. I need two lines, and the first one has to be hello."},
                  {"kind": "first_line", "text": "hello", "msg": "Close. I need two lines, and the first one has to be hello."}],
       "say": "No ghost text, no gaps. You wrote that yourself."}),

    L("variables", "variables",
      {"learn": "A variable is a name that holds a value. The = sign puts the value into the name. After that, you use the name instead of the value.",
       "task": "Save your reason in a variable called goal. Then print goal.",
       "code": 'goal = "<<reason>>"\nprint(goal)',
       "say": "Look at print(goal). No quotes. Without quotes, Python looks up the name and prints what it holds."},
      {"learn": "A variable can change. If you set it again, the newest value wins.",
       "task": "Set mood to tired. Then set it to focused. Print it.",
       "code": 'mood = "tired"\n[[mood]] = "focused"\n[[print]](mood)',
       "say": "focused. The second = replaced tired."},
      {"task": "Make tool hold hammer. Change it to drill. Print it.",
       "code": 'tool = [["hammer"]]\n[[tool = "drill"]]\n[[print(tool)]]',
       "say": "drill wins. Newest value, every time."},
      {"task": "Make a variable called name that holds your name. Then print it.",
       "hint": 'Two lines. name = "..." with your name in the quotes. Then print(name), with no quotes around name.',
       "solution": 'name = "Sam"\nprint(name)',
       "checks": [has(r"\bname\s*=", "Make a variable called name first, with name = ..."),
                  has(r"print\s*\(\s*name\s*\)", "Now print the variable itself: print(name), no quotes."),
                  {"kind": "min_lines", "n": 1, "msg": "Nothing printed yet."}],
       "say": "Hi, %out%. You just used a variable with nothing to copy from."}),

    L("strings", "strings",
      {"learn": "Strings have methods. A method is a small action you run with a dot. .upper() turns every letter into a capital. .lower() makes them small.",
       "task": "Save a word in shout. Print it in capitals.",
       "code": 'shout = "{{any word|hey}}"\nprint(shout.upper())',
       "say": "%out%. The dot reached into the string and ran upper() on it."},
      {"learn": "A + between two strings glues them together. len() counts the characters in a string, spaces too.",
       "task": "Glue two words into one. Print it, then print how long it is.",
       "code": 'first = "tool"\nsecond = "box"\nword = first [[+]] second\nprint(word)\nprint([[len]](word))',
       "say": "toolbox, 7 letters. + glued them, len() counted."},
      {"task": "Glue py and thon. Print the word in capitals. Then print its length.",
       "code": 'word = "py" [[+ "thon"]]\nprint([[word.upper()]])\n[[print(len(word))]]',
       "say": "PYTHON, then 6. Three moves, all from memory."},
      {"task": "Make a variable called tool that holds hammer. Print it in capitals.",
       "hint": 'tool = "hammer" on one line. Then print(tool.upper()).',
       "solution": 'tool = "hammer"\nprint(tool.upper())',
       "checks": [out("HAMMER", "I need HAMMER, all capitals."),
                  has(r"\.upper\(\)", "Let .upper() do the capitals for you.")],
       "say": "HAMMER. You called a method with nothing to copy."}),

    L("f-strings", "f-strings",
      {"learn": "An f-string is a string with an f in front of the quotes. Inside it, a name in curly braces gets swapped for its value.",
       "task": "Put your name in a variable. Then say hi to it with an f-string.",
       "code": 'name = "<<name>>"\nprint(f"hi, {name}")',
       "say": "%out%. The {name} got swapped for what name holds."},
      {"learn": "You can put math inside the braces too. Python works out the answer first, then drops it in.",
       "task": "You have 3 tools. Print that, then print how many you will have after you buy one more.",
       "code": 'tools = 3\nprint([[f]]"I have {tools} tools")\nprint(f"next week: [[{tools + 1}]]")',
       "say": "3, then 4. The braces did the math for you."},
      {"task": "Make city hold Paris. Print I live in Paris, using an f-string.",
       "code": 'city = [["Paris"]]\nprint([[f"I live in {city}"]])',
       "say": "%out%. One f, one pair of braces."},
      {"task": "Make item hold drill and price hold 40. Print exactly: drill costs 40 dollars",
       "hint": 'item = "drill" and price = 40. Then print(f"{item} costs {price} dollars").',
       "solution": 'item = "drill"\nprice = 40\nprint(f"{item} costs {price} dollars")',
       "checks": [out("drill costs 40 dollars", "I need exactly: drill costs 40 dollars"),
                  has(r"""\bf["']""", 'Use an f-string, with f right before the quote.'),
                  has(r"\{\s*price\s*\}", "Let the braces fill in price for you.")],
       "say": "%out%. Two names, one sentence, zero gluing."}),

    L("math", "math",
      {"learn": "Python does math like a calculator. + adds, - subtracts, * multiplies, / divides. / always gives a decimal, like 3.5.",
       "task": "Print four sums and watch what comes back.",
       "code": "print(2 + 3)\nprint(10 - 4)\nprint(6 * 7)\nprint(7 / 2)",
       "say": "5, 6, 42, 3.5. See how 7 / 2 gave a decimal."},
      {"learn": "// divides and throws the decimal away. % gives what is left over. 7 // 2 is 3, and 7 % 2 is 1.",
       "task": "Split 17 cookies between 5 people. Print how many each person gets, then how many are left.",
       "code": "cookies = 17\nprint(cookies [[//]] 5)\nprint(cookies [[%]] 5)",
       "say": "3 each, 2 left over. // is the share, % is the leftovers."},
      {"task": "Turn 135 minutes into hours and minutes.",
       "code": "mins = 135\nprint(mins [[// 60]])\n[[print(mins % 60)]]",
       "say": "2 hours and 15 minutes. That is // and % doing real work."},
      {"task": "Make days hold 23. Print how many full weeks that is. Then print how many days are left over.",
       "hint": "Two prints. days // 7 gives the weeks. days % 7 gives the days left.",
       "solution": "days = 23\nprint(days // 7)\nprint(days % 7)",
       "checks": [out("3\n2", "I need two lines: 3, then 2."),
                  has(r"//", "Use // for the full weeks."),
                  has(r"%", "Use % for the days left over.")],
       "say": "3 weeks and 2 days. You split time with nothing to copy."}),

    L("lists", "lists",
      {"learn": "A list holds many values in order, inside square brackets. Every value has a spot number. Counting starts at 0, so the first value is at [0].",
       "task": "Make a list of tools. Print the first one.",
       "code": 'tools = ["hammer", "saw", "drill"]\nprint(tools[0])',
       "say": "hammer. Spot 0 is the first one."},
      {"learn": ".append() adds a value to the end of a list. len() tells you how many values the list has.",
       "task": "Add a drill to the end. Print the list, then how long it is.",
       "code": 'tools = ["hammer", "saw"]\ntools.[[append]]("drill")\nprint(tools)\nprint([[len(tools)]])',
       "say": "The drill landed at the end, and len() counted 3."},
      {"task": "Add 16 to the end of nums. Print the second number.",
       "code": "nums = [4, 8, 15]\n[[nums.append(16)]]\n[[print(nums[1])]]",
       "say": "8. Spot 1 is the second number, because counting starts at 0."},
      {"task": "Make a list called jobs with two jobs in it. Add a third job with append. Print how many jobs there are.",
       "hint": 'jobs = ["cook", "clean"], then jobs.append("code"), then print(len(jobs)).',
       "solution": 'jobs = ["cook", "clean"]\njobs.append("code")\nprint(len(jobs))',
       "checks": [out("3", "I need it to print 3."),
                  has(r"\.append\(", "Add the third job with .append()."),
                  has(r"\blen\(", "Count them with len().")],
       "say": "3. You built, grew and measured a list."}),

    L("if / else", "if / else",
      {"learn": "if runs code only when something is true. The if line ends with a colon, and the code under it moves in 4 spaces. else runs when it is not true.",
       "task": "Check the battery. Warn if it is low.",
       "code": 'battery = 15\nif battery < 20:\n    print("charge me")\nelse:\n    print("all good")',
       "say": "charge me. 15 is less than 20, so the if part ran and else got skipped."},
      {"learn": "== asks if two things are equal. One = stores a value. Two == compare.",
       "task": "Check a password.",
       "code": 'word = "open sesame"\nif word [[==]] "open sesame":\n    print("come in")\n[[else]]:\n    print("nope")',
       "say": "come in. Two == compared, and they matched."},
      {"task": "If score is 90 or more, print great. Otherwise print keep going.",
       "code": 'score = 72\n[[if score >= 90:]]\n    [[print("great")]]\n[[else:]]\n    [[print("keep going")]]',
       "say": "keep going. 72 is not 90 or more, so else ran."},
      {"task": "Make temp hold 30. If temp is over 25, print hot. Otherwise print cool.",
       "hint": 'temp = 30, then if temp > 25: and print("hot") under it, then else: and print("cool").',
       "solution": 'temp = 30\nif temp > 25:\n    print("hot")\nelse:\n    print("cool")',
       "checks": [out("hot", "With temp at 30, it should print hot."),
                  has(r"\bif\b", "Use an if."),
                  has(r"\belse\s*:", "Add an else: for the cool side.")],
       "say": "hot. Your code made a choice."}),

    L("for loops", "for loops",
      {"learn": "A for loop runs the same code once for each item in a list. Each time around, the name after for holds the next item.",
       "task": "Print every tool, one per line.",
       "code": 'for tool in ["hammer", "saw", "drill"]:\n    print(tool)',
       "say": "Three lines from two lines of code. That is the point of a loop."},
      {"learn": "range(1, 4) gives the numbers from 1 up to 4, but not 4 itself. So you get 1, 2 and 3.",
       "task": "Count from 1 to 3.",
       "code": "for n in [[range]](1, 4):\n    [[print(n)]]",
       "say": "1, 2, 3. It stopped before 4."},
      {"task": "Add up the numbers 1 to 5 with a loop. Call each number n.",
       "code": "total = 0\n[[for n in range(1, 6):]]\n    [[total = total + n]]\nprint([[total]])",
       "say": "15. The loop added 1, 2, 3, 4 and 5 into total."},
      {"task": "Use a loop to print 2, 4 and 6, each on its own line.",
       "hint": "for n in range(1, 4): and under it print(n * 2).",
       "solution": "for n in range(1, 4):\n    print(n * 2)",
       "checks": [out("2\n4\n6", "I need 2, 4 and 6 on separate lines."),
                  has(r"\bfor\b", "Use a for loop for this one.")],
       "say": "2, 4, 6. One line inside a loop did all of it."}),

    L("dicts", "dicts",
      {"learn": "A dict stores pairs. Each key points to a value, like a word and its meaning. You look up a value by putting its key in square brackets.",
       "task": "Look up the price of a saw.",
       "code": 'prices = {"hammer": 12, "saw": 20}\nprint(prices["saw"])',
       "say": "20. You looked it up by its key."},
      {"learn": "Set a key with = to add a new pair, or to change one that is already there.",
       "task": "Add a drill to the price list. Then look it up.",
       "code": 'prices = {"hammer": 12}\nprices["drill"] [[=]] 40\nprint([[prices]]["drill"])',
       "say": "40. New key, new pair."},
      {"task": "Ana is 30. Add one to her age. Print it.",
       "code": 'ages = {"ana": 30}\n[[ages["ana"] = ages["ana"] + 1]]\n[[print(ages["ana"])]]',
       "say": "31. Read the old value, add one, store it back."},
      {"task": "Make a dict called stock where apples is 5. Change apples to 8. Print the apples value.",
       "hint": 'stock = {"apples": 5}, then stock["apples"] = 8, then print(stock["apples"]).',
       "solution": 'stock = {"apples": 5}\nstock["apples"] = 8\nprint(stock["apples"])',
       "checks": [out("8", "It should print 8."),
                  has(r"\bstock\s*=\s*\{", "Start with stock = { ... }."),
                  has(r"""stock\[\s*["']apples["']\s*\]\s*=""", 'Change it with stock["apples"] = 8.')],
       "say": "8. Keys and values, from memory."}),

    L("functions", "functions",
      {"learn": "A function is a named recipe. def makes one. The code inside only runs when you call the function by its name with ().",
       "task": "Make a greet function. Call it twice.",
       "code": 'def greet():\n    print("hello")\n\ngreet()\ngreet()',
       "say": "hello, twice. One recipe, used two times."},
      {"learn": "A function can take inputs, called parameters. return hands an answer back to whoever called it.",
       "task": "Make double. Use it on 21.",
       "code": "def double(n):\n    [[return]] n * 2\n\nprint([[double]](21))",
       "say": "42. double got 21 and handed back 42."},
      {"task": "Write add, which takes a and b and returns their sum. Print add(2, 3).",
       "code": "[[def add(a, b):]]\n    [[return a + b]]\n\n[[print(add(2, 3))]]",
       "say": "5. You wrote a function and used it."},
      {"task": "Write a function called square that returns a number times itself. Print square(9).",
       "hint": "def square(n): and under it return n * n. Then print(square(9)).",
       "solution": "def square(n):\n    return n * n\n\nprint(square(9))",
       "checks": [out("81", "square(9) should print 81."),
                  has(r"def\s+square\s*\(", "Make it with def square(...):"),
                  has(r"\breturn\b", "Hand the answer back with return.")],
       "say": "81. Your own recipe, written from nothing."}),

    L("comprehensions", "comprehensions",
      {"learn": "A list comprehension builds a new list in one line. Read [n * 2 for n in nums] like this: n times 2, for each n in nums.",
       "task": "Double every number in a list.",
       "code": "nums = [1, 2, 3]\ndoubled = [n * 2 for n in nums]\nprint(doubled)",
       "say": "[2, 4, 6]. A whole loop in one line."},
      {"learn": "Add an if at the end to keep only some items. [n for n in nums if n > 2] keeps the numbers bigger than 2.",
       "task": "Keep only the big numbers.",
       "code": "nums = [1, 5, 2, 8]\nbig = [n for n in nums [[if]] n > 2]\n[[print]](big)",
       "say": "[5, 8]. The if threw out 1 and 2."},
      {"task": "Make every word in words loud, in one line.",
       "code": 'words = ["saw", "drill"]\nloud = [w.upper() [[for w in]] words]\n[[print(loud)]]',
       "say": "['SAW', 'DRILL']. upper() ran once per word."},
      {"task": "Use a list comprehension to make the squares of 1, 2, 3 and 4. Print the list.",
       "hint": "print([n * n for n in range(1, 5)])",
       "solution": "squares = [n * n for n in range(1, 5)]\nprint(squares)",
       "checks": [out("[1, 4, 9, 16]", "I need [1, 4, 9, 16]."),
                  has(r"\[[^\]]*\bfor\b[^\]]*\]", "Build it with [ ... for ... ] in one line.")],
       "say": "%out%. That is the fancy one, done from memory."}),
]


def main() -> int:
    out_dir = APP / "lessons"
    bad = 0
    for lesson in ALL:
        problems = lessons.validate(lesson)
        status = "ok" if not problems else "FAIL"
        print(f"{status:4} {lesson['topic']}")
        for p in problems:
            print("     -", p)
        bad += bool(problems)
        (out_dir / f"{lessons.slug(lesson['topic'])}.json").write_text(json.dumps(lesson, indent=2) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
