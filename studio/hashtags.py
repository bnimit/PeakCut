"""Hashtags for a clip without asking an AI: free, instant, and the same every time.

Three to five tags, picked from what is really there:
  - the game's main tag (#GTA6), when it is known
  - the channel the video is from (#kaicenat)
  - the AI's own tags for the clip, when it wrote sensible ones
  - the words said most in the clip, and a game or product named in the title ("GTA 6" becomes #gta6)
  - what kind of moment it is (#funny, #fails, #clutch)
  - #shorts and #clips, only if too few others were found

A description the person wrote themselves is never touched: see apply().
"""
import re

from . import games

MOST, LEAST = 5, 3

STOP = set("""
about above after again against all also always among and another any anyone anything are around because been before being
between both but came can cannot come could did does doing done dont down each else even ever every everyone everything
find first for from gave get gets getting give going gone gonna good got great guys had has have having here him his how
into its just keep kind know last left let like little look looking made make makes many may maybe mean more most much must
myself need never next nobody not nothing now off okay once one only onto other our out over own people put really right
said same say says see she should since some someone something still such sure take than that the their them then there
these they thing things think this those though through time too took try under until upon use very want wanna was way we
well went were what when where whether which while who whole why will with without won would yeah yes you your
hai kya yaar nahi nahin bhai toh aur mein tha kar karo kiya ho hain bhi koi abhi main mera tera apna isko usko jab tab phir
woh wo ye yeh hum tum aap kuch sab bohot bahut matlab accha acha theek lekin par kyun kaise
actual actually literally basically honestly probably definitely obviously seriously totally bro dude man chat stream video
fuck fucking fucked shit damn bitch bitches ass dick pussy sex nigga nigger niggas porn rape
""".split())

CATEGORY_TAGS = {"funny": "funny", "fail": "fails", "clutch": "clutch", "rage": "rage", "shock": "shocking",
                 "take": "hottake", "story": "storytime"}
FILLER = ("shorts", "clips", "viral")
CHANNEL_NOISE = {"live", "official", "tv", "gaming", "clips", "channel", "highlights", "youtube", "twitch", "kick", "tiktok", "stream"}
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9']{2,19}")
_NUMBERED = re.compile(r"\b([A-Za-z]{2,12})\s+(\d{1,2})\b")
_TAG_IN_TEXT = re.compile(r"(?:^|\s)#\w+")


def _tag(s) -> str:
    """One tag: letters and digits only, lower case, not too short or long, never just a number or a stop word."""
    t = re.sub(r"[^A-Za-z0-9]", "", str(s or "")).lower()[:30]
    return "" if len(t) < 3 or t.isdigit() or t in STOP else t


def channel_tag(uploader) -> str:
    """The channel as one tag: "Kai Cenat Live" becomes kaicenat."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", str(uploader or "")) if w.lower() not in CHANNEL_NOISE]
    t = _tag("".join(words))
    return t if 3 <= len(t) <= 25 else ""


def numbered(title) -> list:
    """Names with a number in the title ("GTA 6", "Fortnite 2") as one tag each."""
    return [_tag(a + b) for a, b in _NUMBERED.findall(str(title or "")) if a.lower() not in STOP]


def keywords(text, title="", count=2) -> list:
    """The words worth searching for in what was said: a name (capitalised in the middle of a sentence), or a
    word the title uses too. Whichever it is, saying it often moves it up the list.

    Being said a lot is not on its own enough, and used to be: any word repeated twice could become a tag, so
    real posts went out wearing #instead, #hours, #character and #return. Nobody searches for those, and five
    of them on a post is a sign the thing was made by a machine. A word now has to be a name or in the title,
    which is what "worth searching for" actually looks like in a clip about one thing."""
    raw = str(text or "").split()
    in_title = {w.lower() for w in _WORD.findall(str(title or ""))}
    score = {}
    for i, r in enumerate(raw):
        m = _WORD.search(r)
        if not m:
            continue
        got = m.group(0)
        # "you'll" is not the word "youll": take what comes before the apostrophe and judge that, or the
        # contractions of ordinary words sail past the stop list in a shape it does not list.
        if "'" in got and got.split("'")[0].lower() in STOP:
            continue
        w = got.strip("'").lower()
        if w in STOP or len(w) < 4 or not _tag(w):
            continue
        name = r[:1].isupper() and i > 0 and raw[i - 1][-1:] not in ".?!"
        if not (name or w in in_title):
            continue
        score[w] = score.get(w, 0) + 1 + (2 if name else 0) + (2 if w in in_title else 0)
    best = sorted((w for w in score if score[w] >= 2), key=lambda w: (-score[w], -len(w), w))
    return best[:count]


def make(text="", title="", uploader="", game=None, category="other", ai_tags=(), limit=MOST) -> list:
    """Three to five tags for one clip, most relevant first."""
    out = []

    def add(t):
        t = _tag(t)
        if t and t not in out and len(out) < limit:
            out.append(t)

    # A word already sitting inside the game's own tag says nothing on its own: #WoWForever should not drag
    # #forever along behind it, nor #GTA6 bring #gta.
    inside_game_tag = {t.lower() for t in games.tags_of(game)}

    def spare(t):
        t = _tag(t)
        return bool(t) and not any(t != g and t in g for g in inside_game_tag)

    for t in games.tags_of(game)[:1]:       # the game's main tag; its look-alikes would only use up the room
        add(t)
    add(channel_tag(uploader))
    for t in list(ai_tags or [])[:2]:
        add(t)
    for t in keywords(text, title):
        if spare(t):
            add(t)
    for t in numbered(title)[:1]:
        add(t)
    add(CATEGORY_TAGS.get(str(category or "").lower(), ""))
    for t in FILLER:
        if len(out) < LEAST:
            add(t)
    return out


def apply(clip: dict, words: list, title="", uploader="", game=None) -> dict:
    """Give a clip its tags and put them at the end of its description, so the description is complete as it is.
    A description the person wrote themselves (`fixed_description`) is left exactly as written."""
    if clip.get("fixed_description"):
        return clip
    text = " ".join(w.get("w", "") for w in words if clip["start"] <= w.get("s", -1) <= clip["end"])
    tags = make(text, title, uploader, game, clip.get("category", "other"), clip.get("hashtags") or [])
    desc = _TAG_IN_TEXT.sub("", str(clip.get("description") or "")).strip()
    line = " ".join("#" + t for t in tags)
    clip.update(hashtags=tags, hashtags_in_description=True,
                description=(desc + "\n\n" + line).strip() if desc else line)
    return clip
