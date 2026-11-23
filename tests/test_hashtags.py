"""Hashtags made without an AI: three to five fitting ones, added to the description unless the person wrote their own.
Runs against the code directly; nothing leaves this machine."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-tags-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
from studio import db, hashtags as h, posting  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


TITLE = "Kai Cenat's First Time Playing GTA 6!"
SAID = "Yo they locked me up bro. Actual prison, actual Prison man. I'm not going back to the prison. Fuck that shit, the cop said stick up"

tags = h.make(SAID, TITLE, "Kai Cenat Live", "GTA 6", "funny", ["GTA6", "gaming", "x"])
check("three to five tags", 3 <= len(tags) <= 5, str(tags))
check("the game comes first", tags[0] == "gta6", str(tags))
check("the channel is a tag", "kaicenat" in tags, str(tags))
check("a word said again and again is a tag", "prison" in tags, str(tags))
check("no rude words and no filler words", not set(tags) & {"fuck", "shit", "actual", "they", "that"}, str(tags))
check("no tag repeats", len(set(tags)) == len(tags))
check("the AI's own sensible tags are used, its junk is not", "gaming" in tags and "x" not in tags, str(tags))
check("a name with a number in the title is a tag", "gta6" in h.make("", TITLE, "", None), str(h.make("", TITLE, "", None)))
check("with nothing to go on there are still three", len(h.make()) == 3, str(h.make()))
check("a clip's kind can be a tag", "fails" in h.make("hello there", "Some video", "Some Channel", None, "fail"))
check("every tag is plain letters and digits", all(t.isalnum() and t == t.lower() for t in tags), str(tags))
check("a channel name loses its Live and Official", (h.channel_tag("Kai Cenat Live"), h.channel_tag("Pewdiepie Official")) == ("kaicenat", "pewdiepie"))
check("at most five even with many to choose from", len(h.make(SAID, TITLE, "Kai Cenat", "GTA 6", "funny", ["a1b", "c2d", "e3f", "g4h", "i5j", "k6l"])) == 5)

# ---- a possessive is not a word of its own
#
# "Joey's" was being kept whole and then stripped of its apostrophe at the last moment, so real posts went out
# wearing #joeys, #lucias and #jasons next to #joey. It is the same name twice, and the second spelling is one
# nobody searches for. Seen on 23 November 2026 on a clip cut from a GTA 6 guide.
POSS = "You can hide cash at Joey's place. Joey's garage is safe, and Joey will keep it for you."
poss = h.make(POSS, "Where to hide cash in GTA 6", "", "GTA 6")
check("a possessive is not a tag of its own", not {"joeys", "lucias", "jasons"} & set(poss), str(poss))
check("the name itself is what gets used", "joey" in poss, str(poss))

# ---- the game's own tags are the ones worth searching for
#
# Cutting the game down to a single tag to stop #GTA6 dragging #GTA6Game along also threw away #ViceCity and
# #RockstarGames, which are not look-alikes at all, and the freed room went to words scraped out of the speech.
g = h.make("", "Some GTA 6 clip", "", "GTA 6")
check("the game's distinct tags are used, not only the first", {"vicecity", "rockstargames"} <= set(g), str(g))
check("but a near-copy of a tag already there is left out", "gta6launch" not in g and "gta6game" not in g, str(g))
check("the game still comes first", g[0] == "gta6", str(g))

# "the Better way", "the Fastest car": a comparison is not a thing anyone searches for by itself
cmp_tags = h.make("The Better route. Better every time, and the Fastest one is Better still.",
                  "A better faster clip", "", "GTA 6")
check("a comparison word is not a tag", not {"better", "fastest"} & set(cmp_tags), str(cmp_tags))

# with a channel and speech to go on, the game still gets its room and the junk stays out
mix = h.make(POSS, "Where to hide cash in GTA 6", "MrDalekJD", "GTA 6")
check("a clip from someone else's video is not mostly their name and possessives",
      "vicecity" in mix and not {"joeys", "lucias"} & set(mix), str(mix))

# ---- the AI's own tags get the same look-alike check as ours
#
# Only the tags picked here were being checked against each other, so when the AI wrote "GTA6Game" itself it
# went straight in next to #GTA6. Every clip of a GTA 6 job cut on 23 November 2026 went out that way, with a
# slot spent on a second spelling of the game.
ai = h.make("", "Some GTA 6 clip", "MrDalekJD", "GTA 6", "other", ["GTA6Game", "GTA6"])
check("a tag the AI spelled the game's name a second way is left out", "gta6game" not in ai, str(ai))
check("and the room goes to a tag that says something new", {"vicecity", "rockstargames"} & set(ai), str(ai))
check("the AI's genuinely different tag is still used",
      "slimjim" in h.make("", "Some GTA 6 clip", "", "GTA 6", "other", ["SlimJim"]), str(ai))

NL = chr(10)
words = [{"w": w, "s": 10 + i, "e": 10.5 + i} for i, w in enumerate(SAID.split())]
clip = {"start": 10, "end": 40, "category": "fail", "description": "Kai gets stuck up #gta", "hashtags": ["GTA6"]}
h.apply(clip, words, TITLE, "Kai Cenat Live", "GTA 6")
check("the tags end the description", clip["description"].startswith("Kai gets stuck up" + NL * 2 + "#gta6 ") and clip["description"].count("#") == len(clip["hashtags"]), clip["description"])
check("a tag the AI wrote into its sentence is not said twice", clip["description"].count("#gta ") == 0 and "#gta" not in clip["description"].split(NL * 2)[0])
check("the clip is marked, so posting does not add them again", clip["hashtags_in_description"] is True and posting._caption(clip, {"post_footer": ""}) == clip["description"])

own = {"start": 10, "end": 40, "description": "My own text #mine", "fixed_description": True, "hashtags": ["old"]}
h.apply(own, words, TITLE, "Kai Cenat Live", "GTA 6")
check("a description the person wrote is left exactly as it is", own["description"] == "My own text #mine" and own["hashtags"] == ["old"] and "hashtags_in_description" not in own)

empty = {"start": 10, "end": 40, "description": "", "hashtags": []}
h.apply(empty, words, TITLE, "Kai Cenat Live", "GTA 6")
check("with no description at all, the tags are the description", empty["description"].startswith("#") and NL not in empty["description"], empty["description"])
check("a clip made before this keeps posting as it did", posting._caption({"description": "D", "hashtags": ["a", "b"]}, {"post_footer": "F"}) == "D" + NL * 2 + "#a #b" + NL * 2 + "F")

print("ALL PASSED" if not fails else f"{len(fails)} failed")
import shutil  # noqa: E402

db.engine.dispose()
shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
