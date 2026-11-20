"""How each posted short actually did on YouTube, read from YouTube Analytics.

Run it with: python -m studio.yt_report [days]   (90 days by default)

It lists every short PeakCut posted to a connected YouTube channel, worst retention first, and then where the
channel's views came from. The number that matters is "kept": how much of the short an average viewer watched.
Below about 50% YouTube stops showing a short to new people, so a low "kept" is a hook problem, not a reach problem.

The channel has to be connected in Settings, Connected apps, with permission to read its numbers. That permission
was added after the first version, so a channel connected before it has to be connected again (DEPLOY.md says how).
"""
import json
import sys
from datetime import date, timedelta

from . import accounts, auth, config, ctx


def _posts(uid: str) -> list:
    f = config.DATA_DIR / "posts.json"
    if not f.exists():
        return []
    try:
        rows = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return [p for p in rows if p.get("user") == uid and p.get("platform") == "youtube"
            and p.get("status") == "posted" and p.get("remote_id")]


def report(days: int = 90) -> str:
    end, start = date.today(), date.today() - timedelta(days=days)
    out = []
    for acc in [a for a in accounts._all() if a["platform"] == "youtube"]:
        posted = [p for p in _posts(ctx.uid()) if p["account"] == acc["id"]]
        out.append(f"\n{acc['name']}  ({len(posted)} shorts posted by PeakCut, last {days} days)")
        if not posted:
            out.append("  Nothing posted to this channel yet.")
            continue
        stats = accounts.youtube_analytics(acc, [p["remote_id"] for p in posted], str(start), str(end))
        rows = [(stats.get(p["remote_id"], {}), p) for p in posted]
        rows.sort(key=lambda r: r[0].get("avg_view_pct", 0))
        out.append(f"  {'kept':>6} {'views':>7} {'subs':>5}  title")
        for s, p in rows:
            if not s:
                out.append(f"  {'no data':>6} {'':>7} {'':>5}  {p['title'][:60]}")
                continue
            out.append(f"  {s['avg_view_pct']:>5.0f}% {s['views']:>7} {s['subs_gained']:>5}  {p['title'][:60]}")
        shown = [s for s, _ in rows if s]
        if shown:
            avg = sum(s["avg_view_pct"] for s in shown) / len(shown)
            out.append(f"  Average kept: {avg:.0f}%  (under 50% is why a short stops being shown)")
        traffic = accounts.youtube_traffic(acc, str(start), str(end))
        if traffic:
            out.append("  Views came from: " + ", ".join(f"{k} {v}" for k, v in list(traffic.items())[:6]))
    return "\n".join(out) or "No YouTube channel is connected."


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 90
    if config.ACCOUNTS:
        sys.exit("Sign-in is on here, so there is no single owner to report on. Run this where PEAKCUT_ACCOUNTS is off.")
    with ctx.as_user(auth.local_user().id):
        print(report(days))


if __name__ == "__main__":
    main()
