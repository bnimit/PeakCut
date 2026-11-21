"""Throwing away a moment that YouTube would age-restrict.

A short that dwells on realistic violence gets age-restricted: YouTube then hides it from everyone who is
signed out or under 18, and it earns almost nothing. So the clip finder is asked to mark such a moment, and a
marked one is dropped rather than rendered. Asking alone was not enough on its own: in testing the AI still
let one through about half the time, which is why the answer is also acted on here in code.

The question is new, so a model that ignores it must still produce clips: no answer at all means no. Anything
else that is not plainly a no counts as a yes, so a vague or odd answer never puts a restricted clip on the
channel.

Nothing here goes out to the internet: no AI is called.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-restricted-")
sys.path.insert(0, ".")
from studio import brain
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- a plain yes or no
check("marked true is dropped", brain._restricted({"restricted": True}), True)
check("marked false is kept", brain._restricted({"restricted": False}), False)

# ---- a model that never answers the question still gets its clips through
check("no answer at all means keep", brain._restricted({"hook": "THE SHOT"}), False)
check("an empty answer means keep", brain._restricted({"restricted": ""}), False)
check("null means keep", brain._restricted({"restricted": None}), False)

# ---- the words a model writes instead of true and false
for word in ("true", "True", "TRUE", "yes", "Yes", "1"):
    check("the word %r is dropped" % word, brain._restricted({"restricted": word}), True)
for word in ("false", "False", "FALSE", "no", "No", "0", "none", "  false  "):
    check("the word %r is kept" % word, brain._restricted({"restricted": word}), False)

# ---- anything unexpected is treated as a yes, never silently posted
check("a sentence is dropped", brain._restricted({"restricted": "probably, there is shooting"}), True)
check("a number that is not zero is dropped", brain._restricted({"restricted": 1}), True)
check("zero is kept", brain._restricted({"restricted": 0}), False)
check("a list is dropped", brain._restricted({"restricted": ["violence"]}), True)

# ---- the question is asked for, and explained, in the rules the AI gets
check("the rules ask for the mark", "restricted:" in brain.RULES, True)
check("the rules say a marked clip is thrown away", "thrown away" in brain.RULES, True)
check("the rules say to mark it when unsure", "not sure" in brain.RULES, True)
check("the rules say what to pass over", "shooting, beating or killing people" in brain.RULES, True)
check("the rules allow a gun inside a chase or a joke", "sustained fighting" in brain.RULES, True)
check("the mark is in the shape the AI answers in", "restricted" in brain.SCHEMA["items"]["properties"], True)

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
