"""When a queued clip actually goes out.

Clips are not posted the moment they are made. Each account has a gap between posts and a cap on how many go
out in a day, so a batch is spread instead of dumped. The gap used to be the only thing deciding this, so a
day's posts could run off the end of the evening and keep going through the night: with a wide gap the fifth
and sixth of the day landed at two and five in the morning, when nobody is watching. Posts now wait for the
next morning rather than going out in the small hours.

Nothing here goes out to the internet and nothing is posted: only the times are worked out.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile, time
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-schedule-")
sys.path.insert(0, ".")
from studio import posting
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


ACC = "yt_test"
DAY = "2026-11-22"


def at(hhmm, day=DAY):
    """A time on a given day, from "14:30"."""
    h, m = (int(x) for x in hhmm.split(":"))
    y, mo, d = (int(x) for x in day.split("-"))
    return time.mktime((y, mo, d, h, m, 0, 0, 0, -1))


def given(times, now, cap=6, gap=150):
    """Pretend these posts are already on the books, and ask when the next one would go out."""
    posting._posts[:] = [{"id": "p%d" % i, "user": "u_local", "account": ACC, "status": "posted",
                          "due_at": t, "posted_at": t} for i, t in enumerate(times)]
    posting._mine = lambda: list(posting._posts)
    posting.time.time = lambda: now
    return posting._next_slot(ACC, gap, cap)


def when(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


# ---- the gap is kept
check("the first post of an empty queue goes out now", when(given([], at("10:00"))), DAY + " 10:00")
check("the next one waits the gap", when(given([at("10:00")], at("10:00"))), DAY + " 12:30")

# ---- the evening is the end of the day, not the start of the night
#      09:00 + five gaps of 150 minutes reaches 21:30, and the one after that must not be 00:00.
day = [at(h) for h in ("09:00", "11:30", "14:00", "16:30", "19:00", "21:30")]
got = given(day[:6], at("21:30"), cap=8)       # a cap high enough that only the hours can push it
check("the post after the last evening slot waits for the morning", when(got), "2026-11-23 09:00")
check("nothing is ever scheduled in the small hours",
      all(not (0 <= time.localtime(given(day[:n], at("09:00"), cap=20)).tm_hour < 9) for n in range(1, 7)), True)

# ---- a full day rolls over, as it always did
check("a day at its cap rolls to the next morning",
      when(given(day, at("09:00"), cap=6)), "2026-11-23 09:00")
check("a day one short of its cap does not roll",
      when(given(day[:5], at("19:00"), cap=6)), DAY + " 21:30")

# ---- asking in the middle of the night does not post in the middle of the night
check("a queue asked at 3am waits for 9am", when(given([], at("03:00"))), DAY + " 09:00")
check("a queue asked at 23:00 waits for the next morning", when(given([], at("23:00"))), "2026-11-23 09:00")

# ---- a whole batch, which is what this is really for
posting._posts[:] = []
posting._mine = lambda: list(posting._posts)
now = at("09:00")
posting.time.time = lambda: now
out = []
for _ in range(14):
    t = posting._next_slot(ACC, 150, 6)
    out.append(t)
    posting._posts.append({"id": "x%d" % len(out), "user": "u_local", "account": ACC, "status": "scheduled",
                           "due_at": t, "posted_at": None})
hours = [time.localtime(t).tm_hour for t in out]
check("a batch of 14 never lands outside the posting hours",
      all(posting.DAY_START <= h < posting.DAY_END for h in hours), True)
check("a batch of 14 spreads over three days", len({posting._day(t) for t in out}), 3)
check("the first day takes six of them",
      sum(1 for t in out if posting._day(t) == posting._day(out[0])), 6)
check("each day starts at nine",
      {time.strftime("%H:%M", time.localtime(t)) for t in out if posting._day(t) != posting._day(out[0])}
      >= {"09:00"}, True)

# ---- the hours belong to the viewers, not to the machine
#      A channel run from India for an American audience used to post all through the American night: 09:00 in
#      India is 22:30 the evening before in New York. Naming the viewers' timezone moves the whole window there.
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001
    ET = None      # a machine with no timezone database: these checks cannot run, the rest still can

check("no timezone set means this machine's own clock", posting._resolve_zone(""), None)
check("a name that is not a timezone falls back to this machine's clock", posting._resolve_zone("Nowhere/Fake"), None)

if ET is None:
    print("(no timezone database on this machine, so the viewers'-timezone checks were skipped)")
else:
    check("a real timezone name is used", posting._resolve_zone("America/New_York") is not None, True)
    posting.ZONE = ET

    def et(hhmm, day="2026-11-22"):
        h, m = (int(x) for x in hhmm.split(":"))
        y, mo, d = (int(x) for x in day.split("-"))
        return datetime(y, mo, d, h, m, tzinfo=ET).timestamp()

    def et_when(t):
        return datetime.fromtimestamp(t, ET).strftime("%Y-%m-%d %H:%M")

    check("the middle of the night where the viewers are waits for their morning",
          et_when(given([], et("03:00"))), "2026-11-22 09:00")
    check("after the evening where the viewers are, it waits for their next morning",
          et_when(given([], et("23:00"))), "2026-11-23 09:00")
    check("the middle of their afternoon is posted straight away",
          et_when(given([], et("14:00"))), "2026-11-22 14:00")

    posting._posts[:] = []
    posting._mine = lambda: list(posting._posts)
    now = et("09:00")
    posting.time.time = lambda: now
    out = []
    for _ in range(14):
        t = posting._next_slot(ACC, 150, 6)
        out.append(t)
        posting._posts.append({"id": "z%d" % len(out), "user": "u_local", "account": ACC, "status": "scheduled",
                               "due_at": t, "posted_at": None})
    hrs = [datetime.fromtimestamp(t, ET).hour for t in out]
    check("a batch of 14 stays inside the hours where the viewers are",
          all(posting.DAY_START <= h < posting.DAY_END for h in hrs), True)
    check("none of the 14 lands in the viewers' small hours", all(not (0 <= h < 9) for h in hrs), True)
    check("six land on the viewers' first day",
          sum(1 for t in out if posting._slot_day(t) == posting._slot_day(out[0])), 6)
    check("the first one is nine in the morning where the viewers are", et_when(out[0]), "2026-11-22 09:00")
    check("each later day starts at nine where the viewers are",
          {datetime.fromtimestamp(t, ET).strftime("%H:%M") for t in out
           if posting._slot_day(t) != posting._slot_day(out[0])} >= {"09:00"}, True)
    posting.ZONE = None

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
