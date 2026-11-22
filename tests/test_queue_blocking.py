"""One slow upload must not hold up every other post behind it.

The queue used to send one post at a time and wait for each to finish. That was fine until an upload stalled:
on 22 November 2026 six clips were sent together, the first one stopped answering, and the other five sat
waiting behind it for four minutes while nothing at all happened.

Each upload now runs on its own thread, a few at a time, so a stuck one costs only itself. A few at a time
rather than all of them, because a channel that fires everything at once looks like a machine.

Nothing here goes out to the internet and nothing is posted: the upload is a stand-in that can be told to hang.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile, threading, time
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-block-")
os.environ.update(PEAKCUT_POST_TZ="", PEAKCUT_POST_START="9", PEAKCUT_POST_END="22")
sys.path.insert(0, ".")
from studio import posting
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- a stand-in for the upload: clip "slow" hangs until we let it go, the rest finish at once
release = threading.Event()
started, finished = [], []
lock = threading.Lock()


def fake_post(p):
    with lock:
        started.append(p["clip"])
    if p["clip"] == "slow":
        release.wait(timeout=20)
    with lock:
        finished.append(p["clip"])
    p["status"] = "posted"


def posts(*clips):
    now = time.time() - 1
    return [{"id": c, "user": "u_local", "job": "j1", "clip": c, "creator": None, "account": "yt_1",
             "status": "scheduled", "due_at": now + i * 0.001, "tries": 0, "error": None}
            for i, c in enumerate(clips)]


posting._post = fake_post
posting._save = lambda: None
posting._mirror = lambda p: None
posting.accounts.settings = lambda: {"paused": False}
# The worker waits 15 seconds between passes. Shorten it, keeping hold of the real sleep first: posting.time is
# the time module itself, so a lambda that called time.sleep would be calling itself.
_sleep = time.sleep
posting.time.sleep = lambda s: _sleep(0.05)

posting._posts[:] = posts("slow", "a", "b", "c", "d", "e")
threading.Thread(target=posting._run, daemon=True).start()


def wait_for(cond, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        _sleep(0.05)
    return False


# ---- while the slow one hangs, the others must still go out
ok = wait_for(lambda: len(finished) >= 3)
check("other posts go out while one upload is stuck", ok, True)
check("the stuck one has started but not finished", "slow" in started and "slow" not in finished, True)
check("no more than the worker limit run at once", len(started) - len(finished) <= posting.POST_WORKERS, True)
check("the limit is small enough not to flood the channel", posting.POST_WORKERS <= 3, True)

# ---- everything else finishes, and only then do we let the slow one go
ok = wait_for(lambda: len([c for c in finished if c != "slow"]) == 5)
check("all five of the others finish while it is still stuck", ok, True)
check("the stuck one is still hanging", "slow" not in finished, True)
release.set()
check("the stuck one finishes once it is unblocked", wait_for(lambda: "slow" in finished), True)
check("every post went out exactly once", sorted(finished), ["a", "b", "c", "d", "e", "slow"])

# ---- a post is claimed once, even with several workers going
check("no post was started twice", len(started), len(set(started)))

# ---- and the oldest due post is taken first
posting._posts[:] = []
started.clear(); finished.clear()
old = posts("third", "first", "second")
old[0]["due_at"] = time.time() - 10
old[1]["due_at"] = time.time() - 300
old[2]["due_at"] = time.time() - 100
posting._posts[:] = old
check("the post that has waited longest goes first", wait_for(lambda: len(started) >= 1) and started[0], "first")

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
