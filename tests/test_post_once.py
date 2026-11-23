"""A clip goes up once, whatever goes wrong after it has gone up.

Two ways the queue used to send the same clip twice, both seen on this channel on 22 November 2026:

  - The upload went through and the answer was lost. The queue asked YouTube whether it had arrived, but it
    asked only once, and the bad line that lost the answer lost the question too. Ten minutes later the clip
    went up again. The first video had been live for six minutes by then.
  - Everything after a good upload sat inside the same "if this goes wrong, try again" block, down to writing
    a line in the creator's log. So a video that was already public could be put back in the queue because a
    log file would not open.

Now the post is marked done the moment the video is up, outside that block, and a second attempt starts by
looking at the channel rather than by uploading. Looking costs a couple of units; an upload costs 1600.

Nothing here goes out to the internet: the upload and the channel are stand-ins.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-once-")
os.environ.update(PEAKCUT_POST_TZ="", PEAKCUT_POST_START="9", PEAKCUT_POST_END="22")
sys.path.insert(0, ".")
from pathlib import Path
from studio import posting
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


DIR = Path(os.environ["PEAKCUT_DATA"]) / "job1"
(DIR / "clips").mkdir(parents=True, exist_ok=True)
(DIR / "clips" / "clip01.mp4").write_bytes(b"\0" * 32)
CLIP = {"id": "clip01", "file": "clip01.mp4", "status": "done", "title": "A Clip Worth Watching",
        "start": 0, "end": 30, "hashtags": ["gta6"], "description": "d"}
JOB = {"id": "job1", "dir": str(DIR), "creator": "c1", "clips": [CLIP]}
ACC = {"id": "yt_1", "platform": "youtube", "name": "Gaming Clips"}

uploads, looks = [], []


def reset(**kw):
    """A fresh post row, and a clean record of what was uploaded and what was looked up."""
    uploads.clear(); looks.clear()
    return {"id": "p1", "user": "u_local", "job": "job1", "clip": "clip01", "creator": "c1",
            "account": "yt_1", "account_name": "Gaming Clips", "platform": "youtube",
            "status": "posting", "tries": 0, "error": None, "url": "", "remote_id": "",
            "title": "A Clip Worth Watching", **kw}


def upload(acc, path, title, desc, tags, privacy):
    uploads.append(title)
    if upload.fail:
        raise RuntimeError("the line went down")
    return "vid_new", "https://www.youtube.com/shorts/vid_new"


def already_there(acc, title, within_hours=6.0):
    looks.append(title)
    return already_there.answer


upload.fail = False
already_there.answer = None
posting.jobs.get = lambda jid: JOB if jid == "job1" else None
posting.accounts.get = lambda aid: ACC if aid == "yt_1" else None
posting.accounts.youtube_upload = upload
posting.accounts.youtube_already_there = already_there
posting.creators.get = lambda cid: dict(posting.creators.DEFAULTS, name="clips")
posting._save = lambda: None
posting._mirror = lambda p: None
posting.alerts.notify = lambda *a, **k: None
posting.creators.log = lambda *a, **k: None


# ---- the ordinary case
p = reset()
posting._post(p)
check("a good upload is marked posted", p["status"], "posted")
check("and the video is recorded", p["remote_id"], "vid_new")
check("the first attempt never wastes units looking at the channel", looks, [])
check("and it uploaded exactly once", len(uploads), 1)

# ---- the bug: something after the upload throws
def log_explodes(*a, **k):
    raise OSError("log file is busy")


posting.creators.log = log_explodes
p = reset()
posting._post(p)
check("a video that is already up stays posted even if the log will not write", p["status"], "posted")
check("it is not put back in the queue to be sent again", p.get("due_at"), None)
check("and the video it became is still recorded", p["remote_id"], "vid_new")
posting.creators.log = lambda *a, **k: None

# ---- a second attempt looks at the channel first
already_there.answer = ("vid_from_last_try", "https://www.youtube.com/shorts/vid_from_last_try")
p = reset(tries=1)
posting._post(p)
check("a retry looks at the channel before sending anything", looks, ["A Clip Worth Watching"])
check("and when the clip is already there it is not uploaded again", uploads, [])
check("the post points at the video that really exists", p["remote_id"], "vid_from_last_try")
check("and it counts as posted", p["status"], "posted")

# ---- two clips with the same title must not be confused for each other
already_there.answer = ("vid_someone_elses", "https://www.youtube.com/shorts/vid_someone_elses")
posting._posts[:] = [{"id": "other", "remote_id": "vid_someone_elses", "status": "posted"}]
p = reset(tries=1)
posting._post(p)
check("a video another post already claims is not taken for this one", p["remote_id"], "vid_new")
check("so the clip really does go up", len(uploads), 1)
posting._posts[:] = []

# ---- a second attempt where the clip really is not there
already_there.answer = None
p = reset(tries=1)
posting._post(p)
check("a retry with nothing on the channel does upload", len(uploads), 1)
check("and it is posted", p["status"], "posted")

# ---- a genuine failure still retries, as it must
upload.fail = True
p = reset()
posting._post(p)
check("an upload that really fails is queued to try again", p["status"], "scheduled")
check("the failure is counted", p["tries"], 1)
check("and the reason is kept", "line went down" in str(p["error"]), True)

# ---- and it gives up rather than trying for ever
p = reset(tries=2)
posting._post(p)
check("after three tries it is marked failed", p["status"], "failed")
upload.fail = False

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
