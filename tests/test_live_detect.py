"""Telling a channel that is on air from one that is not.

PeakCut reads the channel's own /live page and looks for the mark YouTube puts there while a stream is running.
YouTube has used two different marks for this. In November 2026 it stopped writing the older one, and because only
that one was looked for, every channel suddenly looked offline and nothing was ever recorded automatically. Both
marks are accepted now, so a change like that can only break recording if YouTube drops both at once.

Nothing here goes out to the internet: the page is handed to the code directly.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-livedetect-")
sys.path.insert(0, ".")
from studio import profiles
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


VID = "X7utxgBSWS4"
CANON = '<link rel="canonical" href="https://www.youtube.com/watch?v=%s">' % VID


def page(body: str):
    """Serve this page instead of fetching the channel, and never let yt-dlp run."""
    profiles._get = lambda url, accept="text/html", limit=0: ("text/html", body.encode())
    profiles._ydl_info = lambda url: (_ for _ in ()).throw(RuntimeError("the test must not go to the network"))


def live_now():
    return profiles.live_now("YouTube", "https://www.youtube.com/@SomeChannel")


# ---- on air, however YouTube marks it
page('{"isLiveNow":true} ' + CANON)
check("the older mark means on air", live_now()["live"], True)
page('{"isLive":true} ' + CANON)
check("the newer mark means on air", live_now()["live"], True)
check("the video id is read from the page", live_now()["embed"], VID)

# ---- off air
page("<html>nothing happening here</html>")
check("a page with neither mark means off air", live_now()["live"], False)
check("an off-air answer carries no video id", live_now()["embed"], "")
check("an off-air answer carries no viewers", live_now()["viewers"], None)
page('{"isLive":false,"isLiveNow":false} ' + CANON)
check("a mark that says false is not on air", live_now()["live"], False)

# ---- the video id is still found when the canonical link is missing, as it now often is
page('{"isLive":true} "videoId":"%s"' % VID)
check("the video id is found without a canonical link", live_now()["embed"], VID)
page('{"isLive":true}')
check("on air is still reported when no video id can be found", live_now()["live"], True)

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
