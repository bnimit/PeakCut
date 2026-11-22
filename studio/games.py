"""What game is this?

A gaming stream says which game it is: in its title, in the category Twitch shows,
in the channel name. Knowing the game changes two things:

- the AI is told what kind of moment it is looking at (a clutch in the same game
  means something different from a talking segment), and
- every post carries the tags people actually search for (#GTA6), not just
  #gaming.

The game is read from the title only. It is a hint for the copy, never a filter:
a stream whose title says GTA 6 but which is really a chat stream still gets
clips, they just get GTA tags on them.
"""

from __future__ import annotations

import re

# name, words that mean it, tags to put on the post
GAMES: list[tuple[str, list[str], list[str]]] = [
    ("Grand Theft Auto VI", ["grand theft auto vi", "grand theft auto 6", "gta vi", "gta 6", "gta6"],
     ["GTA6", "GTA6Game", "ViceCity", "RockstarGames", "GTA6Launch"]),
    ("Grand Theft Auto V", ["grand theft auto v", "grand theft auto 5", "gta online", "gta v", "gta 5", "gta5", "gtav"],
     ["GTA5", "GTAOnline", "RockstarGames", "GTA5RP"]),
    ("Grand Theft Auto IV", ["grand theft auto iv", "gta 4", "gta4"], ["GTA4", "RockstarGames"]),
    ("Fortnite", ["fortnite"], ["Fortnite", "FortniteOG", "BattleRoyale"]),
    ("Minecraft", ["minecraft"], ["Minecraft", "MinecraftGame"]),
    ("Valorant", ["valorant"], ["Valorant", "ValRadiant"]),
    ("League of Legends", ["league of legends", "league of legend"], ["LeagueOfLegends", "LoL", "RiotGames"]),
    ("Counter-Strike", ["counter-strike", "counter strike", "cs2", "csgo"], ["CS2", "CounterStrike", "Esports"]),
    ("Elden Ring", ["elden ring"], ["EldenRing", "SoulsLike", "FromSoftware"]),
    ("Palworld", ["palworld"], ["Palworld", "Survival"]),
    ("Call of Duty", ["call of duty", "warzone"], ["CallOfDuty", "Warzone", "COD"]),
    ("Helldivers 2", ["helldivers 2", "helldivers2"], ["Helldivers2", "StarshipTroopers", "CoOp"]),
    ("Cyberpunk 2077", ["cyberpunk 2077", "cyberpunk"], ["Cyberpunk2077", "NightCity"]),
    ("Starfield", ["starfield"], ["Starfield", "Bethesda"]),
    ("Black Myth Wukong", ["black myth", "wukong"], ["BlackMythWukong", "ActionRPG"]),
    ("Marvel Rivals", ["marvel rivals"], ["MarvelRivals", "Heroes"]),
    ("Overwatch 2", ["overwatch 2", "overwatch"], ["Overwatch2", "OW2", "Blizzard"]),
    ("ARK", ["ark: survival", "ark survival"], ["ARK", "Survival"]),
    ("Dead by Daylight", ["dead by daylight"], ["DeadByDaylight", "Asymmetric"]),
    ("Rocket League", ["rocket league"], ["RocketLeague", "CarSports"]),
    ("Apex Legends", ["apex legends"], ["ApexLegends", "EApex"]),
    ("PUBG", ["pubg", "playerunknown"], ["PUBG", "BattleRoyale"]),
    ("Grand Theft Auto: San Andreas", ["grand theft auto san andreas", "gta sa"], ["GTA", "SanAndreas"]),
    # "wow" on its own is deliberately not one of the words that mean this game: half the clip titles on YouTube
    # say "WOW" about something else entirely, and a Fortnite clip tagged #WorldOfWarcraft helps nobody.
    # The first tag is the one a clip is most likely to get, so it is the clearest one: "WoW" on its own reads
    # as the exclamation as often as the game.
    ("World of Warcraft", ["world of warcraft", "wow forever", "wow classic", "warcraft"],
     ["WorldOfWarcraft", "WoWForever", "WoW", "Warcraft", "MMORPG"]),
]

# for a stream whose game nobody can name
GENERIC = ["Gaming", "Gameplay", "GamingClips", "StreamHighlights"]

# What people actually type into YouTube search about a game, so the clip finder can prefer the moments that
# answer one of those questions. A clip that answers a question someone is looking for travels; one that
# explains something nobody asked about does not, however good the moment was.
#
# Only fill a game in here from real search data, not from a guess about what sounds popular. The GTA VI list
# below came from YouTube's own search suggestions on 21 November 2026, two days after the game came out, and
# the suggestions are worth reading again every few weeks: what a new player looks up in the first week is not
# what they look up in the second. A game that is not listed gets a general version of the same instruction.
LOOKED_UP: dict[str, list[str]] = {
    "Grand Theft Auto VI": ["how to make money", "where to find money", "how to buy a car", "where to sell a car",
                            "where a particular place is, like the airport", "how to get the good ending",
                            "what a particular named thing does, like the key cloner"],
    # From YouTube's own suggestions on 22 November 2026, three weeks after Forever came out. What people ask
    # about a long-running game is not what they ask about a brand new one: almost every suggestion was about
    # choosing and playing a class, not about the story.
    "World of Warcraft": ["which class or race to pick, and which is best at tanking, healing or damage",
                          "how to play a particular class", "how to make gold",
                          "where to level, often for a particular range like 20 to 30", "where to start",
                          "how to fish, cook or raise a profession",
                          "where a particular place or item is, like the Hall of Thanes",
                          "which addons and settings to use"],
}

# longest word first, so "gta 6" is read before "gta"
_ALIASES: list[tuple[str, str, list[str]]] = sorted(
    ((alias, name, tags) for name, aliases, tags in GAMES for alias in aliases),
    key=lambda a: -len(a[0]),
)

_WORD = re.compile(r"[^a-z0-9]+")


def _norm(text: str) -> str:
    return _WORD.sub(" ", str(text or "").lower()).strip()


def detect(*texts) -> tuple[str | None, list[str]]:
    """The game named in the text, and the tags that belong on its posts.

    Returns (None, []) when no known game is named."""
    hay = _norm(" ".join(str(t or "") for t in texts))
    if not hay:
        return None, []
    for alias, name, tags in _ALIASES:
        if re.search(r"(?:^| )" + re.escape(_norm(alias)) + r"(?: |$)", hay):
            return name, list(tags)
    return None, []


def name_of(game: str | None) -> str:
    """The game's proper name, from a name, a tag or a spelling of its own."""
    if not game:
        return ""
    g = _norm(game)
    for name, aliases, _tags in GAMES:
        if g == _norm(name) or g in {_norm(a) for a in aliases}:
            return name
    return str(game)[:40]


def looked_up(game: str | None) -> list[str]:
    """The things people search for about this game, or an empty list when nobody has filled them in yet."""
    return list(LOOKED_UP.get(name_of(game), []))


def tags_of(game: str | None) -> list[str]:
    """The tags for a game, whether it is named in full, short, or by one of its tags."""
    if not game:
        return []
    g = _norm(game)
    for name, aliases, tags in GAMES:
        if g == _norm(name) or g in {_norm(a) for a in aliases} or g in {_norm(t) for t in tags}:
            return list(tags)
    return [re.sub(r"\W", "", str(game))[:30]] if re.sub(r"\W", "", str(game)) else []
