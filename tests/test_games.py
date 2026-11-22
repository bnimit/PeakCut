"""Gaming streams say which game they are. Knowing it changes the rules the AI reads and the tags every
post carries.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-games-")
sys.path.insert(0, ".")
from studio import brain, games, live
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


def _session(title, game=""):
    """A live session that is not recording anything: only the game reading is wanted."""
    d = tempfile.mkdtemp(prefix="pc-games-live-")
    s = live.Session({"title": title, "uploader": "someone", "dir": d, "creator": "", "ai": {},
                      "source": {"url": "", "name": title}},
                     {"game": game})
    return s

# ---- the game is read from the title
check("GTA 6 in a title is GTA VI", games.detect("CLICK THIS STREAM IF YOU WANT GTA 6!")[0], "Grand Theft Auto VI")
check("spelled out is GTA VI", games.detect("grand theft auto vi lets go")[0], "Grand Theft Auto VI")
check("GTA 5 is GTA V", games.detect("GTA V RP tonight")[0], "Grand Theft Auto V")
check("gta5 and gta online are GTA V", games.detect("gta5 gta online")[0], "Grand Theft Auto V")
check("another game is found", games.detect("Fortnite ranked")[0], "Fortnite")
check("a chat stream has no game", games.detect("just chatting with friends")[0], None)
check("GTA 60 seconds is not a game", games.detect("GTA 60 seconds of gameplay")[0], None)

# ---- the tags belong on the post
check("a GTA VI post carries the GTA VI tags", "GTA6" in games.tags_of("gta 6"), True)
check("the tags do not double up", games.tags_of("GTA6Launch") == games.tags_of("gta 6"), True)
check("an unknown game has no tags", games.tags_of("Hades II"), ["HadesII"])
# a hashtag cannot contain a space, so a game tag with one in it would arrive broken
tagged = brain._tidy({"hashtags": []}, 0, 1, game="cyberpunk 2077")["hashtags"]
check("every tag a post carries is one word", all(t and " " not in t and "#" not in t for t in tagged), True)

# ---- the tags go on every post, whatever the AI wrote
tidy = brain._tidy({"start": 1, "end": 9, "score": 80, "category": "clutch", "hook": "one vs three",
                     "title": "He got them all", "description": "three of them", "hashtags": ["Gaming", "FPS"],
                     "highlight_words": ["three"]}, 1, 9, game="gta 6")
check("the game's tags are added to the post", "GTA6" in tidy["hashtags"], True)
check("the AI's own tags are kept", "Gaming" in tidy["hashtags"] and "FPS" in tidy["hashtags"], True)
check("the game's tags are not written twice", tidy["hashtags"].count("GTA6"), 1)
plain = brain._tidy({"start": 1, "end": 9, "score": 80, "category": "clutch", "hook": "x", "title": "t",
                     "description": "d", "hashtags": ["Gaming"], "highlight_words": []}, 1, 9)
check("a stream with no game gets no game tags", "GTA6" in plain["hashtags"], False)

# ---- the AI is told which game it is looking at
rules = brain._game_rules("gta 6")
check("the game is named in the extra rules", "Grand Theft Auto VI" in rules, True)
check("the tags are named in the extra rules", "GTA6" in rules, True)
check("a stream with no game gets no extra rules", brain._game_rules(""), "")

# ---- a live session finds its game in the stream's title
check("a live session finds the game in its title", _session("CLICK THIS STREAM IF YOU WANT GTA 6!")._game(),
      "Grand Theft Auto VI")
check("the creator's own setting wins over the title", _session("just chatting", "gta 6")._game(), "Grand Theft Auto VI")
check("a live stream with no game in it says so", _session("morning everyone")._game(), "")

# ---- a short name that means something else is not a game
check("'rust' is not read as the game Rust", games.detect("Rust removal and restoration")[0], None)
check("'the finals' is not read as a game", games.detect("The finals of the world cup")[0], None)

# ---- the people in chat are read under the lock, as a copy
s = _session("morning everyone")
s.chat_users[5] = {"someone"}
people = s.chat_people()
people[5].add("not really there")
check("the people in chat are a copy", s.chat_users[5], {"someone"})

# ---- a slow AI answer must not stop the recording
import time as _time
s = _session("morning everyone")
s._ai_check = lambda *a, **k: _time.sleep(2)      # a model that takes its time
t0 = _time.time()
s._ask_ai()
check("asking the AI does not hold up the recording", _time.time() - t0 < 0.5, True)
t0 = _time.time()
s._ask_ai()                                       # a second ask while the first is still out
check("a second ask does not pile up", _time.time() - t0 < 0.5 and s.ai_busy > 0, True)

# ---- a hand-picked clip is made even when the AI cannot answer
from unittest.mock import patch
added = []
s = _session("morning everyone")
s.words = [{"w": "hello", "s": 0.5, "e": 0.9, "p": 0}]
s.t_done, s.samples = 10.0, 10 * 16000
s._add_clip = added.append
s.manual.append({"start": 0.0, "end": 2.0})
with patch.object(brain, "describe", side_effect=RuntimeError("The AI did not answer")):
    s._manual_step()
check("a hand-picked clip is made when the AI fails", len(added), 1)
check("it is made without a hook rather than not at all", added and added[0]["hook"], "")
check("the failure is remembered", "AI did not answer" in (s.job["ai"]["last_error"] or ""), True)

# ---- an eight-hour stream must not keep a name for every second of it
users, kept = {}, 0
for t in range(0, 3000):
    users.setdefault(t, set()).add(f"person{t}")
    kept = live._trim_names(users, t, kept)
check("the chat names of a whole stream are not kept", len(users) <= 700, True)
check("the last few minutes of them still are", 2999 in users and min(users) >= 2999 - 660, True)
check("the dict is not walked on every message", live._trim_names(users, 3005, 2999), 2999)

# ---- the things people search for about a game, so the clip finder can aim at them
# A clip that answers a question somebody is looking for travels; one that explains what nobody asked does not.
# The list is only filled in for a game whose real search terms someone has looked up, so an unlisted game has
# to get a general version of the same instruction rather than nothing or a made-up list.
check("a game with real search terms has them", "how to make money" in games.looked_up("Grand Theft Auto VI"), True)
check("its short name finds them too", games.looked_up("gta 6"), games.looked_up("Grand Theft Auto VI"))
check("one of its tags finds them too", games.looked_up("GTA6"), games.looked_up("Grand Theft Auto VI"))
check("a game nobody has filled in has none", games.looked_up("Elden Ring"), [])
check("no game at all has none", games.looked_up(None), [])
check("an unknown game has none", games.looked_up("Some Game That Does Not Exist"), [])
check("the list handed out is a copy, so the real one cannot be edited by accident",
      (lambda l: (l.append("junk"), "junk" not in games.looked_up("gta 6"))[1])(games.looked_up("gta 6")), True)

gta, elden = brain._game_rules("gta 6"), brain._game_rules("Elden Ring")
check("the searched-for rule reaches the AI for GTA 6", "how to make money" in gta, True)
check("GTA 6 is told to write the title as the answer", "as the answer, not as a tease" in gta, True)
check("a game with no list still gets the general rule", "where to find something" in elden, True)
check("a game with no list is not given invented searches", "how to make money" in elden, False)
check("both still get the rest of the game rules", ("sticky" not in gta) and ("The hashtags include" in elden), True)
check("no game means no game rules at all", brain._game_rules(None), "")
check("the rule leaves no empty gap behind it", "\n\n-" in gta, False)


# ---- World of Warcraft, added 22 Nov 2026 as a second game for the clips channel. Its search terms came from
#      YouTube's own suggestions, which were overwhelmingly about picking and playing a class.
check("World of Warcraft is recognised by its full name", games.name_of("world of warcraft"), "World of Warcraft")
check("and by the expansion people are playing", games.name_of("WoW Forever"), "World of Warcraft")
check("and by WoW Classic", games.name_of("wow classic"), "World of Warcraft")
check("it carries its own tags", "WorldOfWarcraft" in games.tags_of("World of Warcraft"), True)
check("including the expansion's tag", "WoWForever" in games.tags_of("wow forever"), True)
check("a title naming the game is detected", games.detect("WoW Forever leveling guide 1-60")[0], "World of Warcraft")
check("so is the full name in a title", games.detect("World of Warcraft Forever: best class")[0], "World of Warcraft")
# the point of leaving "wow" out on its own
check("a clip that just says wow is not called World of Warcraft",
      games.detect("WOW! This GTA 6 chase was insane")[0], "Grand Theft Auto VI")
check("and wow with nothing else is no game at all", games.detect("wow that was close")[0], None)
check("its search terms are filled in", len(games.looked_up("World of Warcraft")) >= 6, True)
check("they are about classes, which is what people actually ask",
      any("class" in t for t in games.looked_up("wow forever")), True)
check("and about gold", any("gold" in t for t in games.looked_up("World of Warcraft")), True)
rules = brain._game_rules("World of Warcraft")
check("the game rules name it", "World of Warcraft" in rules, True)
check("the rules carry its real search terms, not the general wording",
      "gold" in rules and "nobody asked about" not in rules, True)
check("and still tell the AI to write the title as the answer", "not as a tease" in rules, True)

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
