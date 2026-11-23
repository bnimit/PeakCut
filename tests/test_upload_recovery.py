"""A clip must never be put up twice because YouTube lost the receipt.

A resumable upload can go all the way through, publish the video, and then fail to tell us so: the last request
comes back as "408 Request Timeout", or the connection simply drops. The queue used to read that as "the upload
failed" and try again ten minutes later, which uploaded the same clip a second time. It happened on this channel
on 22 November 2026: six clips were sent, two of them answered with a 408 after the video was already live.

So an upload that does not answer is now asked about rather than assumed. YouTube keeps the answer against the
upload's own address, and it says either "here is the finished video" or "this much of it arrived".

Nothing here goes out to the internet: YouTube is a stand-in answering the way its documentation says.

Runs against the code directly, with its own empty data folder."""
import json, os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-recover-")
sys.path.insert(0, ".")
from pathlib import Path
from studio import accounts
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


SESSION = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc123"
CLIP = Path(os.environ["PEAKCUT_DATA"]) / "clip.mp4"
CLIP.write_bytes(b"\0" * 2048)
ACC = {"id": "yt_1", "platform": "youtube", "name": "Gaming Clips"}
accounts._yt_token = lambda acc: "a-token"          # no sign-in and no refresh in these checks


class R:
    def __init__(self, code, data=None, headers=None, text=None):
        self.status_code, self._d, self.headers = code, data, headers or {}
        self.text = text if text is not None else json.dumps(data)
    def json(self):
        if self._d is None:
            raise ValueError
        return self._d


class Timeout(Exception):
    """Stands in for httpx's own timeout: the request never came back at all."""


def youtube(send_answers):
    """Replace YouTube. send_answers is what the upload itself does, in order; the status question is answered
    from `landed`. Returns the log of what was asked."""
    log = []

    def post(url, data=None, json=None, headers=None, params=None, timeout=None, content=None):
        log.append(("start", url))
        return R(200, {}, headers={"Location": SESSION})

    def put(url, content=None, headers=None, timeout=None):
        asking = (headers or {}).get("Content-Range", "").endswith("*/2048")
        log.append(("ask" if asking else "send", len(content or b"")))
        answer = youtube.landed if asking else send_answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    accounts.httpx.post, accounts.httpx.put = post, put
    return log


# ---- the ordinary case still works, and nothing is asked when nothing went wrong
youtube.landed = R(200, {"id": "should-not-be-used"})
log = youtube([R(200, {"id": "vid_ok"})])
check("a clean upload returns the video", accounts.youtube_upload(ACC, CLIP, "T", "d", [], "public"),
      ("vid_ok", "https://www.youtube.com/shorts/vid_ok"))
check("a clean upload never asks about itself", [k for k, _ in log], ["start", "send"])

# ---- the bug: a 408 after the video is already live
youtube.landed = R(200, {"id": "vid_408"})
log = youtube([R(408, None, text="<!DOCTYPE html><title>Error 408 (Request Timeout)!!1</title>")])
check("a 408 after the video landed is not treated as a failure",
      accounts.youtube_upload(ACC, CLIP, "T", "d", [], "public"),
      ("vid_408", "https://www.youtube.com/shorts/vid_408"))
check("the upload was asked about exactly once", [k for k, _ in log], ["start", "send", "ask"])
check("the question carried no video with it", [n for k, n in log if k == "ask"], [0])

# ---- a dropped connection, where we never got any answer at all
youtube.landed = R(201, {"id": "vid_dropped"})
youtube([Timeout("read timed out")])
check("a dropped connection is asked about too",
      accounts.youtube_upload(ACC, CLIP, "T", "d", [], "public")[0], "vid_dropped")

# ---- and when the upload really did not arrive, it must still fail so the queue retries
def fails_with(landed, answer):
    youtube.landed = landed
    youtube([answer])
    try:
        accounts.youtube_upload(ACC, CLIP, "T", "d", [], "public")
        return "no error raised"
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


check("a part-way upload (308) still fails, so it is retried", fails_with(R(308, None, text=""), Timeout("x")), "Timeout")
check("a lost upload session (404) still fails, so it is retried",
      fails_with(R(404, None, text="gone"), R(500, None, text="boom")), "RuntimeError")
check("an answer with no video id still fails", fails_with(R(200, {}), R(500, None, text="boom")), "RuntimeError")
check("being unable to ask at all still fails", fails_with(Timeout("also down"), R(500, None, text="boom")),
      "RuntimeError")

# ---- asking only once was not enough, and that is how a clip went up twice
#
# The thing that loses the upload's answer is a bad line, and a bad line swallows the question about it too. On
# 22 November 2026 the question failed, the queue read that as "it never arrived", and ten minutes later the
# same clip went up again: the video had been live for six minutes by then. So the question is now asked more
# than once before it is taken for a no.
accounts.PROBE_WAIT = 0            # no real waiting in a test

asked = []
def flaky_probe(n_failures, then):
    """A line that swallows the first n questions and then lets one through."""
    def put(url, content=None, headers=None, timeout=None):
        if (headers or {}).get("Content-Range", "").endswith("*/2048"):
            asked.append(1)
            if len(asked) <= n_failures:
                raise Timeout("question lost too")
            return then
        raise Timeout("the upload's answer was lost")
    accounts.httpx.post = lambda *a, **k: R(200, {}, headers={"Location": SESSION})
    accounts.httpx.put = put

asked.clear(); flaky_probe(2, R(200, {"id": "vid_flaky"}))
try:
    got = accounts.youtube_upload(ACC, CLIP, "T", "d", [], "public")[0]
except Exception as e:  # noqa: BLE001
    got = f"gave up after one question ({type(e).__name__})"
check("a question that is lost is asked again rather than taken for a no", got, "vid_flaky")
check("and it took more than one asking", len(asked) > 1, True)

asked.clear(); flaky_probe(99, R(200, {"id": "never"}))
try:
    accounts.youtube_upload(ACC, CLIP, "T", "d", [], "public")
    raised = "nothing"
except Exception as e:  # noqa: BLE001
    raised = type(e).__name__
check("a line that never comes back still fails, so the clip is not lost", raised, "Timeout")
check("and it gave up rather than asking for ever", len(asked), accounts.PROBE_TRIES)

# ---- the original problem, stated as the thing that must not happen
youtube.landed = R(200, {"id": "vid_once"})
log = youtube([R(408, None, text="timeout")])
vid, _ = accounts.youtube_upload(ACC, CLIP, "T", "d", [], "public")
check("a clip whose receipt was lost is uploaded once, not twice",
      sum(1 for k, n in log if k == "send" and n > 0), 1)
check("and the caller is told which video it is, so nothing re-posts it", vid, "vid_once")


# ---- the last line of defence: before sending a clip again, look at the channel
#
# Even asking several times can fail, and then the queue would send the clip again regardless. So a second
# attempt no longer starts by uploading: it starts by looking at what is already on the channel. This is what
# would have caught the real duplicate, whatever lost the answer.
import datetime as _dt
NOW = _dt.datetime.now(_dt.timezone.utc)


def channel_holding(title, ago_hours=0.2, vid="vid_on_channel"):
    """Replace YouTube's channel listing with one video of this title, uploaded this long ago."""
    when = (NOW - _dt.timedelta(hours=ago_hours)).isoformat().replace("+00:00", "Z")

    def get(url, params=None, headers=None, timeout=None):
        if "channels" in url:
            return R(200, {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_x"}}}]})
        return R(200, {"items": [{"snippet": {"title": title, "publishedAt": when},
                                  "contentDetails": {"videoId": vid}}]})
    accounts.httpx.get = get


channel_holding("Clip That Already Went Up")
check("a clip already on the channel is found, so it is not sent again",
      accounts.youtube_already_there(ACC, "Clip That Already Went Up"),
      ("vid_on_channel", "https://www.youtube.com/shorts/vid_on_channel"))
check("a different clip is not mistaken for it",
      accounts.youtube_already_there(ACC, "Some Other Clip"), None)

channel_holding("Old Clip", ago_hours=48)
check("a video from days ago is not mistaken for this attempt",
      accounts.youtube_already_there(ACC, "Old Clip"), None)

# the title is trimmed the same way the upload trims it, or a long title would never match itself
long_title = "x" * 150
channel_holding("x" * 100)
check("a long title still matches what was really uploaded",
      accounts.youtube_already_there(ACC, long_title) is not None, True)


def cannot_look(url, params=None, headers=None, timeout=None):
    raise Timeout("channel unreachable")


accounts.httpx.get = cannot_look
check("when the channel cannot be read, it says so rather than guessing",
      accounts.youtube_already_there(ACC, "Anything"), None)

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
