"""Tags taken from what was said have to be worth searching for.

The tag maker picks, among other things, the words said most in a clip. Saying a word twice is a low bar: the
first real batch it ran on, 22 November 2026, came out with #youll, #instead, #hours, #character, #return and
#turn on it. Those are not things anybody looks for, and a post wearing five of them looks automated.

A word from the clip now has to earn its place: it is a name, or the title says it too. Repetition alone is
not enough. Contractions are no longer mistaken for words ("you'll" is not the word "youll"), and a word that
is already inside the game's own tag is left out, so #WoWForever does not drag #forever along with it.

What the game, the channel and the AI contribute is unchanged. Nothing here goes out to the internet.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-tagq-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
from studio import hashtags as h
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- the real clip that produced #instead and #youll
TITLE = "WoW Forever Bank Alt: Instant Mail and Enchanting at Level 1"
SAID = ("So you'll want a bank alt for this. You'll mail everything instead of walking back, "
        "and you'll return to town way less. It saves hours. Instead of hours you spend minutes. "
        "Your character stays out in the world. Instead, just mail it.")
tags = h.make(SAID, TITLE, "WillE", "World of Warcraft", "other", [])

check("a repeated filler word is not a tag: #instead", "instead" not in tags)
check("a word the title also uses is still a tag: #mail", "mail" in tags)

# Each of these was on a real post. Given text where the word is the most repeated thing in the clip, it must
# still be refused: only a name, or a word the title also uses, is worth searching for.
for bad in ("instead", "youll", "hours", "character", "return", "turn", "points", "trying", "experience"):
    word = {"youll": "you'll"}.get(bad, bad)
    text = f"Right so {word} is the thing. {word.capitalize()} again, and {word} once more, {word} too."
    check(f"#{bad} is refused even when it is the most repeated word",
          bad not in h.keywords(text, "A title about something else entirely"))
check("still three to five tags", 3 <= len(tags) <= 5, True)
check("the game still comes first", tags[0], "wow")
check("the channel is still a tag", "wille" in tags, True)

# ---- contractions are not words
said = "You'll see. You'll know. You'll regret it. Didn't I say so? Didn't I?"
check("you'll never becomes a tag", "youll" not in h.keywords(said, "Some title"))
check("didn't never becomes a tag", "didnt" not in h.keywords(said, "Some title"))

# ---- a name said twice is still a tag, which is what the older checks rely on
PRISON = ("Yo they locked me up bro. Actual prison, actual Prison man. "
          "I'm not going back to the prison.")
check("a name said again and again is still a tag",
      "prison" in h.keywords(PRISON, "Kai Cenat's First Time Playing GTA 6!"))
check("and a word the title uses is a tag even said once",
      "enchanting" in h.keywords("We get enchanting going early here.", TITLE))

# ---- a word already inside the game's own tag adds nothing
wow = h.make("Forever is the new one. Forever changed leveling. Forever.", "WoW Forever leveling guide",
             "GuideMMO", "World of Warcraft", "other", [])
check("#forever is not added next to #wowforever", "forever" not in wow)
check("the game's own tag is there instead", any(t.startswith("wow") for t in wow), True)

# ---- the rest of the maker is untouched
check("the AI's sensible tags are still used",
      "gaming" in h.make(SAID, TITLE, "WillE", "World of Warcraft", "other", ["gaming", "x"]))
check("a clip's kind can still be a tag", "fails" in h.make("hello there", "Some video", "Some Channel", None, "fail"))
check("with nothing to go on there are still three", len(h.make()), 3)
check("every tag is still plain letters and digits",
      all(t.isalnum() and t == t.lower() for t in tags), True)
check("no tag repeats", len(set(tags)), len(tags))

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
