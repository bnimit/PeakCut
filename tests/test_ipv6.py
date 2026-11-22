"""YouTube turning away the new-style address is not the same as YouTube turning us away.

Most home connections now have both an old-style address (IPv4) and a new-style one (IPv6), and the machine
reaches for the new one first. YouTube refuses whole ranges of new-style addresses with "sign in to confirm
you're not a bot", and serves the very same connection on the old one without complaint. On 22 November 2026
this machine was refused three times out of three on its new-style address and served three times out of three
on its old one, for the most harmless video on YouTube.

PeakCut used to read that as YouTube refusing the whole server and stop trying YouTube links for ten minutes,
which on such a connection meant for ever. It now moves to the old-style address and carries on, and only a
refusal that happens there too is treated as a real refusal.

Nothing here goes out to the internet: the refusals are the messages YouTube sends, checked against our rules.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-ipv6-")
os.environ["PEAKCUT_FORCE_IPV4"] = "0"          # the point here is that it learns, not that it is told
sys.path.insert(0, ".")
from studio import media
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


YT = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
BOT = ("ERROR: [youtube] jNQXAC9IVRw: Sign in to confirm you're not a bot. This helps protect our community. "
       "Use --cookies-from-browser or --cookies for the authentication.")
OTHER = "ERROR: [youtube] abc: Video unavailable. This video is private."


def fresh():
    media._use_ipv4 = False
    media._yt_refused_until = 0.0


# ---- to start with, nothing is forced and nothing is paused
fresh()
check("to start with, the machine's own choice of address is used", media.address_opts(), {})
check("to start with, YouTube is not paused", media.youtube_paused(), False)

# ---- the first refusal moves to the old-style address instead of giving up
fresh()
check("the first refusal is not treated as YouTube refusing us", media.note_refusal(YT, BOT), False)
check("it switched to the old-style address", media.address_opts(), {"source_address": "0.0.0.0"})
check("and YouTube was not paused, so the next link is tried", media.youtube_paused(), False)

# ---- a refusal on the old address too is a real refusal
check("a second refusal, now on the old address, is real", media.note_refusal(YT, BOT), True)
check("and YouTube is paused", media.youtube_paused(), True)

# ---- an ordinary error is not a refusal and changes nothing
fresh()
check("a private video is not a refusal", media.note_refusal(YT, OTHER), False)
check("and nothing was switched", media.address_opts(), {})
check("and nothing was paused", media.youtube_paused(), False)

# ---- a refusal from somewhere that is not YouTube is left alone
fresh()
check("a refusal on a Twitch link is not ours to act on",
      media.note_refusal("https://www.twitch.tv/someone", BOT), False)
check("and nothing was switched", media.address_opts(), {})

# ---- told to use the old address from the start, the first refusal is already a real one
fresh()
media.config.FORCE_IPV4 = True
try:
    check("when told to, the old-style address is used from the start",
          media.address_opts(), {"source_address": "0.0.0.0"})
    check("and then the first refusal is a real one", media.note_refusal(YT, BOT), True)
finally:
    media.config.FORCE_IPV4 = False
fresh()

# ---- the option reaches yt-dlp, which is the point of all this
media._use_ipv4 = True
opts = {}
class Spy:
    def __init__(self, o):
        opts.update(o)
import types
fake = types.ModuleType("yt_dlp"); fake.YoutubeDL = Spy
sys.modules["yt_dlp"] = fake
media._ydl({})
check("the address is handed to yt-dlp", opts.get("source_address"), "0.0.0.0")
check("and the usual options are still there", opts.get("noplaylist"), True)
fresh()

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
