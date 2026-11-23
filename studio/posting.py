"""Post queue: decides when each finished clip goes to which account, posts it, and tracks views."""
import secrets
import threading
import time
from pathlib import Path

import json

from . import accounts, alerts, config, creators, ctx, jobs, live

_lock = threading.RLock()
_FILE = config.DATA_DIR / "posts.json"
try:
    _posts: list = json.loads(_FILE.read_text(encoding="utf-8")) if _FILE.exists() else []
except ValueError:
    _posts = []


def _mine() -> list:
    u = ctx.uid()
    return [p for p in _posts if p.get("user") == u]
OPEN = ("scheduled", "posting")


def _save():
    with _lock:
        tmp = _FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_posts, indent=1), encoding="utf-8")
        tmp.replace(_FILE)


def forget(uid: str):
    """Drop everything queued or recorded for a deleted account, so nothing is posted or retried for it any more."""
    with _lock:
        for p in _posts:
            if p.get("user") == uid:
                p["status"] = "deleted"          # the posting loop may be holding this one already: it then skips it
        _posts[:] = [p for p in _posts if p.get("user") != uid]
        _save()


def _day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _mirror(p):
    """Copy the post's state onto its clip so the clip card can show it.

    Held under the lock because clips of one video are posted at the same time now: reading the video, changing
    one clip and writing the whole thing back is only safe one at a time, or two clips finishing together would
    each save a copy that does not know about the other."""
    with _lock:
        job = jobs.get(p["job"])
        clip = next((c for c in job["clips"] if c["id"] == p["clip"]), None) if job else None
        if clip is not None:
            clip.setdefault("posts", {})[p["id"]] = {k: p.get(k) for k in ("account_name", "platform", "status", "url", "due_at", "error")}
            jobs.save(job)


DAY_START, DAY_END = config.POST_START, config.POST_END    # posts go out between these hours


def _resolve_zone(name):
    """The timezone the posting hours are read in. Nothing set means this machine's own clock."""
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        # Not a timezone name, or this machine has no timezone database. Posting on this machine's clock is
        # better than not posting at all, so say so plainly and carry on.
        print(f"PEAKCUT_POST_TZ is not a timezone this machine knows: {name!r}. "
              f"Posting hours will follow this machine's clock instead.")
        return None


ZONE = _resolve_zone(config.POST_TZ)


def _there(t):
    """The wall clock where the viewers are. With no timezone set this is this machine's own clock."""
    from datetime import datetime
    return datetime.fromtimestamp(t, ZONE)


def _slot_day(t):
    """Which day a post belongs to where the viewers are, so a cap of six a day means six of their days.
    Kept apart from _day, which stays on this machine's clock because that is the one the dashboard shows you."""
    return _there(t).strftime("%Y-%m-%d")


def _at_hour(t, hour, tomorrow=False):
    """That hour of the clock where the viewers are, on their own day holding t, or on the day after it."""
    from datetime import timedelta
    d = _there(t) + timedelta(days=1 if tomorrow else 0)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()


def _next_slot(account_id, gap_min, cap):
    """Earliest time that respects the gap between posts, the daily cap, and the hours people are awake.

    The gap alone used to decide this, so a day's posts could run off the end of the evening and carry on
    through the night: with a wide gap the fifth and sixth of the day landed at two and five in the morning.
    A slot outside the posting hours now waits for the next morning instead.

    "Awake" means where the viewers are, not where this machine is. Those are the same place until you set
    PEAKCUT_POST_TZ; a channel watched from another country would otherwise post all day into an empty feed."""
    mine = [p for p in _mine() if p["account"] == account_id and p["status"] in OPEN + ("posted",)]
    t = max(time.time(), max((p.get("posted_at") or p["due_at"] for p in mine), default=0) + gap_min * 60)
    for _ in range(60):
        hour = _there(t).hour
        if hour < DAY_START:                 # the small hours: wait for this morning
            t = _at_hour(t, DAY_START)
            continue
        if hour >= DAY_END:                  # past the evening: wait for tomorrow morning
            t = _at_hour(t, DAY_START, tomorrow=True)
            continue
        if sum(1 for p in mine if _slot_day(p.get("posted_at") or p["due_at"]) == _slot_day(t)) < cap:
            break
        t = _at_hour(t, DAY_START, tomorrow=True)
    return t


def enqueue(job, clip, account_ids, now=False) -> list:
    c = creators.get(job["creator"]) or creators.DEFAULTS
    made = []
    with _lock:
        for aid in account_ids:
            acc = accounts.get(aid)
            if not acc:
                continue
            if any(p["job"] == job["id"] and p["clip"] == clip["id"] and p["account"] == aid
                   and p["status"] in OPEN + ("posted",) for p in _mine()):
                continue  # never post the same clip to the same account twice
            due = time.time() if now else _next_slot(aid, c["post_gap_min"], c["daily_cap"])
            p = {"id": secrets.token_hex(8), "user": ctx.uid(), "job": job["id"], "clip": clip["id"], "creator": job["creator"],
                 "account": aid, "account_name": acc["name"], "platform": acc["platform"], "status": "scheduled",
                 "due_at": due, "created": time.time(), "title": clip.get("title") or clip.get("hook") or "Clip",
                 "score": clip.get("score", 0), "tries": 0, "url": "", "remote_id": "", "error": None, "views": None}
            _posts.append(p)
            made.append(p)
        _save()
    for p in made:
        _mirror(p)
    return made


def on_clip_ready(job, clip):
    """Called once when a clip first finishes rendering."""
    c = creators.get(job["creator"])
    if not c or not c["autopost"] or not c["accounts"]:
        return
    if clip.get("score", 0) < c["post_min_score"]:
        return  # includes hand-made clips (score 0): those wait for you to press Post
    made = enqueue(job, clip, c["accounts"])
    if made:
        creators.log(c["id"], f"Queued for {len(made)} account(s): {clip.get('title') or clip.get('hook')}")


def _footer(creator, job) -> str:
    """The creator's own line, with {source} standing for whoever made the video this clip came from.

    A recording of a live stream, or a file somebody uploaded, has no such name. The line is then left out
    altogether rather than posted with a hole in it, so a credit never names nobody."""
    line = (creator.get("post_footer") or "").strip()
    if "{source}" not in line:
        return line
    who = ((job or {}).get("uploader") or "").strip()
    return line.replace("{source}", who) if who else ""


def _caption(clip, creator, job=None):
    # A description the person wrote themselves is posted as it is, without the AI's hashtags added to it, and
    # one that already ends with its hashtags does not get them twice.
    tags = "" if clip.get("fixed_description") or clip.get("hashtags_in_description") else " ".join("#" + h for h in clip.get("hashtags", []))
    return "\n\n".join(x for x in (clip.get("description", ""), tags, _footer(creator, job)) if x)


def _post(p):
    job = jobs.get(p["job"])
    clip = next((c for c in job["clips"] if c["id"] == p["clip"]), None) if job else None
    acc = accounts.get(p["account"])
    adopted = False          # true when a previous attempt had already put this clip up
    try:
        if not clip or clip.get("status") != "done":
            raise RuntimeError("The clip no longer exists or is not finished.")
        if not acc:
            raise RuntimeError("That account was disconnected.")
        path = Path(job["dir"]) / "clips" / clip["file"]
        creator = creators.get(job["creator"]) or dict(creators.DEFAULTS, name="clips")
        title, cap = clip.get("title") or clip.get("hook") or "Clip", _caption(clip, creator, job)
        if acc["platform"] == "youtube":
            # An attempt that failed may still have put the video up: the upload can go through and lose the
            # answer, and the question about it can be lost too. Look on the channel before sending it again.
            done = accounts.youtube_already_there(acc, title) if p.get("tries") else None
            # Two clips can end up with the same title. If some other post already claims that video, it is
            # that post's, not this one's, and this clip still has to go up.
            if done and any(q["remote_id"] == done[0] for q in _posts if q is not p and q.get("remote_id")):
                done = None
            if done:
                rid, url = done
                adopted = True
            else:
                rid, url = accounts.youtube_upload(acc, path, title, cap + "\n\n#Shorts", clip.get("hashtags", []), creator["privacy"])
        elif acc["platform"] == "instagram":
            rid, url = accounts.instagram_upload(acc, path, f"{title}\n\n{cap}", job["id"])
        elif acc["platform"] == "tiktok":
            rid, url = accounts.tiktok_upload(acc, path, f"{title}\n\n{cap}", creator["privacy"])
        else:
            raise RuntimeError("That kind of account is no longer supported.")
    except Exception as e:  # noqa: BLE001
        p["tries"] += 1
        p["error"] = str(e)[-300:]
        if p["tries"] < 3 and clip and acc:
            p.update(status="scheduled", due_at=time.time() + 600)  # try again in 10 minutes
        else:
            p["status"] = "failed"
            creators.log(p["creator"], f"Post failed on {p['account_name']}: {p['error']}")
            alerts.notify(f"post failed on {p['account_name']} ({p['title']}): {p['error'][:200]}", kind="post")
    else:
        # Marked posted only once the video is really up, and outside the try on purpose: anything that goes
        # wrong from here on (writing the log, saving) must never send the clip a second time. It used to be
        # inside, so a failure after a good upload put the queue back to "waiting" and the clip went up twice.
        p.update(status="posted", posted_at=time.time(), remote_id=rid, url=url, error=None)
        try:
            creators.log(p["creator"], (f"Already on {acc['name']} from the last try, not sent again: {title}"
                                        if adopted else f"Posted to {acc['name']}: {title}"))
        except Exception:  # noqa: BLE001
            pass                      # the video is up; a log line is not worth risking a second copy over
    _save()
    _mirror(p)


POST_WORKERS = 3    # uploads happening at once; see _run


def _post_one(p):
    """One post, on a thread of its own, so a slow upload holds up only itself.

    _post deals with anything the upload itself can throw. This catches what is left: if saving or writing the
    clip card fails, the post would otherwise sit on "posting" for ever, which is how a clip goes quiet and
    nobody notices. It goes back in the queue instead."""
    try:
        with ctx.as_user(p["user"]):
            _post(p)
    except Exception as e:  # noqa: BLE001
        with _lock:
            if p["status"] == "posting":
                p.update(status="scheduled", due_at=time.time() + 600, error=str(e)[-300:])
                _save()


def _run():
    """Send out whatever is due, a few at a time.

    This used to upload one post at a time and wait for each. One slow upload then held up every other post
    behind it: six clips sent together went out over a quarter of an hour, and a single stuck upload stopped
    the queue completely. Each upload now gets its own thread, with a few at once rather than all of them, so
    one bad one costs only itself and the channel is not flooded either."""
    running = []
    while True:
        time.sleep(15)
        running = [t for t in running if t.is_alive()]
        due = sorted((p for p in list(_posts)
                      if p["status"] == "scheduled" and p["due_at"] <= time.time() and p.get("user")),
                     key=lambda p: p["due_at"])            # oldest first, so nothing waits for ever
        for p in due:
            if len(running) >= POST_WORKERS:
                break
            try:
                with ctx.as_user(p["user"]):
                    if accounts.settings()["paused"]:
                        continue
                with _lock:
                    if p["status"] != "scheduled":          # already claimed by another pass
                        continue
                    p["status"] = "posting"
                    _save()        # saved, so the page shows it going out instead of looking like nothing happened
                t = threading.Thread(target=_post_one, args=(p,), daemon=True)
                t.start()
                running.append(t)
            except Exception:  # noqa: BLE001
                pass


def _stats_for(recent):
    for aid in {p["account"] for p in recent if p["platform"] == "youtube"}:
        acc = accounts.get(aid)
        if acc:
            views = accounts.youtube_views(acc, [p["remote_id"] for p in recent if p["account"] == aid])
            for p in recent:
                if p["account"] == aid and p["remote_id"] in views:
                    p["views"] = views[p["remote_id"]]
    for p in recent:
        acc = accounts.get(p["account"]) if p["platform"] == "instagram" else None
        if acc:
            v = accounts.instagram_views(acc, p["remote_id"])
            if v is not None:
                p["views"] = v


def _stats():
    while True:
        for uid in {p.get("user") for p in _posts if p.get("user")}:
            try:
                with ctx.as_user(uid):
                    _stats_for([p for p in _mine() if p["status"] == "posted" and time.time() - p["posted_at"] < 14 * 86400])
            except Exception:  # noqa: BLE001
                pass
        _save()
        time.sleep(1800)


def cancel(pid):
    with _lock:
        p = next((p for p in _mine() if p["id"] == pid), None)
        if not p or p["status"] != "scheduled":
            raise ValueError("Only posts that are still waiting can be cancelled.")
        p["status"] = "cancelled"
        _save()
    _mirror(p)


def retry(pid):
    with _lock:
        p = next((p for p in _mine() if p["id"] == pid), None)
        if not p or p["status"] not in ("failed", "cancelled"):
            raise ValueError("Only failed or cancelled posts can be retried.")
        p.update(status="scheduled", due_at=time.time(), tries=0, error=None)
        _save()
    _mirror(p)


def overview() -> dict:
    today = _day(time.time())
    _posts = _mine()  # everything below is about the signed-in user only
    rows = []
    all_cs, all_js = creators.all_creators(), jobs.list_jobs()
    for c in all_cs:
        js = [j for j in all_js if j["creator"] == c["id"]]
        clips = [k for j in js for k in j["clips"] if k.get("status") == "done"]
        ps = [p for p in _posts if p["creator"] == c["id"]]
        views = sum(p["views"] or 0 for p in ps)
        rows.append({
            "id": c["id"], "name": c["name"],
            "state": "recording" if live.active_for(c["id"]) else "waiting" if c["auto_watch"] and c["channel"] else "idle",
            "autopost": c["autopost"] and bool(c["accounts"]),
            "clips_today": sum(1 for k in clips if _day(k.get("made_at", 0)) == today), "clips_total": len(clips),
            "posted_today": sum(1 for p in ps if p["status"] == "posted" and _day(p["posted_at"]) == today),
            "posted_total": sum(1 for p in ps if p["status"] == "posted"),
            "queued": sum(1 for p in ps if p["status"] in OPEN), "failed": sum(1 for p in ps if p["status"] == "failed"),
            "views": views, "earnings": round(views / 1000 * c["rate_per_1k"], 2)})
    names = {c["id"]: c["name"] for c in all_cs}
    queue = sorted((p for p in _posts if p["status"] in OPEN), key=lambda p: p["due_at"])
    done = sorted((p for p in _posts if p["status"] in ("posted", "failed")), key=lambda p: -(p.get("posted_at") or p["due_at"]))[:15]
    show = [{**{k: v for k, v in p.items() if k != "user"}, "creator_name": names.get(p["creator"], "")} for p in queue + done]
    # last 14 days, oldest first, for the home graph
    days = [_day(time.time() - 86400 * i) for i in range(13, -1, -1)]
    made, posted, views = {d: 0 for d in days}, {d: 0 for d in days}, {d: 0 for d in days}
    for j in all_js:
        for k in j["clips"]:
            d = _day(k.get("made_at") or j["created"])
            if k.get("status") == "done" and d in made:
                made[d] += 1
    for p in _posts:
        if p["status"] == "posted" and _day(p["posted_at"]) in posted:
            posted[_day(p["posted_at"])] += 1
            views[_day(p["posted_at"])] += p["views"] or 0
    daily = [{"day": d, "clips": made[d], "posted": posted[d], "views": views[d]} for d in days]
    return {"paused": accounts.settings()["paused"], "creators": rows, "posts": show, "daily": daily,
            "alerts": alerts.configured(), "recording": len(live.active_mine())}


def digest_text() -> str:
    o = overview()
    lines = ["PeakCut daily summary"]
    for r in o["creators"]:
        lines.append(f"- {r['name']}: {r['state']}, {r['clips_today']} clips today, {r['posted_today']} posted today, "
                     f"{r['queued']} waiting, {r['failed']} failed, {r['views']} views")
    if not o["creators"]:
        lines.append("No creators set up yet.")
    if o["paused"]:
        lines.append("Posting is paused.")
    return "\n".join(lines)


def start():
    with _lock:
        for p in _posts:
            if p["status"] == "posting":  # interrupted mid-upload last time
                # Not retried on its own: an upload stopped halfway may still have finished at the other end,
                # and retrying it blind would put the same clip up twice.
                p.update(status="failed", error="The studio closed during this upload. The clip may already be "
                                                "on the channel, so look there before posting it again.")
        _save()
    jobs.on_clip_ready.append(on_clip_ready)
    threading.Thread(target=_run, daemon=True).start()
    threading.Thread(target=_stats, daemon=True).start()
    threading.Thread(target=alerts.digest_loop, args=(digest_text,), daemon=True).start()
    threading.Thread(target=alerts.keep_awake_loop,
                     args=(lambda: bool(live.active()) or any(p["status"] in OPEN for p in _posts),), daemon=True).start()
