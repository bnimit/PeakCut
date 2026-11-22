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

# ---- the original problem, stated as the thing that must not happen
youtube.landed = R(200, {"id": "vid_once"})
log = youtube([R(408, None, text="timeout")])
vid, _ = accounts.youtube_upload(ACC, CLIP, "T", "d", [], "public")
check("a clip whose receipt was lost is uploaded once, not twice",
      sum(1 for k, n in log if k == "send" and n > 0), 1)
check("and the caller is told which video it is, so nothing re-posts it", vid, "vid_once")

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
