"""The big text on the video: a person can set their own, for every clip of a video or as a creator's standing text,
for a campaign that asks for a set line. Runs against the code directly with its own empty data folder."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-bigtext-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

from studio import auth, creators, ctx, db, jobs, posting, render  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


check("the text is kept as typed, links and names included", creators.clean_hook("  Clipped from  @kai #ad  ") == "Clipped from @kai #ad")
check("it is one line", creators.clean_hook("a\nb\x00c") == "a b c")
check("it is short enough for the box", len(creators.clean_hook("x" * 200)) == 60)
check("nothing typed is nothing", creators.clean_hook(None) == "" and creators.clean_hook("   ") == "")
check("what is typed reaches the picture whole", "@kai #ad" in "\n".join(render._hook_events(render._clean("Clipped from @kai #ad"), 10, 300)))

u, _ = auth._create("bt@example.com", "Bt", password_hash="x")
with ctx.as_user(u.id):
    check("a video with no text asks the AI for one, as before", jobs.clean_options({}).get("hook_text") is None)
    check("the text given for a video is kept", jobs.clean_options({"hook_text": " SUBSCRIBE "})["hook_text"] == "SUBSCRIBE")
    check("an empty text is kept too, so it can clear a creator's", jobs.clean_options({"hook_text": ""}) == {"hook_text": ""})

    plain = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False)
    check("by default there is no custom text", plain["options"]["hook_text"] == "")
    own = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"hook_text": "WATCH THIS"}, enqueue=False)
    check("a video can carry its own text", own["options"]["hook_text"] == "WATCH THIS")

    c = creators.create({"name": "Streamer", "hook_text": "Clipped from @streamer"})
    check("a creator keeps a standing text", creators.get(c["id"])["hook_text"] == "Clipped from @streamer")
    from_creator = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False, creator=c["id"])
    check("a video of that creator uses it", from_creator["options"]["hook_text"] == "Clipped from @streamer")
    over = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"hook_text": "ONLY THIS ONE"}, enqueue=False, creator=c["id"])
    check("a video can use another text than the creator's", over["options"]["hook_text"] == "ONLY THIS ONE")
    cleared = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"hook_text": ""}, enqueue=False, creator=c["id"])
    check("...or none, and the AI writes them", cleared["options"]["hook_text"] == "")
    creators.update(c["id"], {"hook_text": ""})
    check("a creator's text can be removed", creators.get(c["id"])["hook_text"] == "")

# ---- the description: written once, used for every clip
NL = chr(10)
check("a description keeps its line breaks and its links", creators.clean_description("Follow @kai" + chr(13) + chr(10) + "https://example.com #ad  ") == "Follow @kai" + NL + "https://example.com #ad")
check("it is cut at 2000 characters", len(creators.clean_description("x" * 5000)) == 2000)
check("nothing typed is nothing", creators.clean_description(None) == "" and creators.clean_description(" " + NL + " ") == "")
with ctx.as_user(u.id):
    check("a video can carry its own description", jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"description_text": "Set text"}, enqueue=False)["options"]["description_text"] == "Set text")
    check("by default there is none", jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False)["options"]["description_text"] == "")
    c2 = creators.create({"name": "Other", "description_text": "Line 1" + NL + "Line 2"})
    got = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False, creator=c2["id"])["options"]["description_text"]
    check("a creator's description is the start of each of their videos", got == "Line 1" + NL + "Line 2", repr(got))
    check("...and one video can use another, or none", (jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"description_text": "Mine"}, enqueue=False, creator=c2["id"])["options"]["description_text"],
          jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"description_text": ""}, enqueue=False, creator=c2["id"])["options"]["description_text"]) == ("Mine", ""))

clip = {"description": "My set text", "hashtags": ["gta", "clip"]}
check("the AI's hashtags are added to the AI's description", posting._caption(clip, {"post_footer": ""}) == "My set text" + NL * 2 + "#gta #clip")
check("a description the person wrote is posted as it is", posting._caption(dict(clip, fixed_description=True), {"post_footer": "Clipped from @x"}) == "My set text" + NL * 2 + "Clipped from @x")

with patch.object(render, "_render_in", return_value={"file": "a.mp4"}) as encode:
    render.render_clip(Path("x.mp4"), Path(os.environ["PEAKCUT_DATA"]) / "out", "a", {"start": 0, "end": 5, "title": "T", "description": "D text"}, [], 1920, 1080)
    check("the title and description are written into the file as well", encode.call_args.kwargs["meta"]["description"] == "D text" and encode.call_args.kwargs["meta"]["title"] == "T")


# ---- the closing line: the ask in the last couple of seconds, where the heading used to sit all along
def hook_lines(ass, text):
    return [x for x in ass.splitlines() if x.startswith("Dialogue: ") and ",Hook," in x and text in x]


def ends_at(ass, text):
    """The second the given line leaves the screen."""
    rows = hook_lines(ass, text)
    h, m, s = rows[0].split(",")[2].split(":")
    return round(int(h) * 3600 + int(m) * 60 + float(s), 2)


def starts_at(ass, text):
    rows = hook_lines(ass, text)
    h, m, s = rows[0].split(",")[1].split(":")
    return round(int(h) * 3600 + int(m) * 60 + float(s), 2)


HOOK, ASK = "WHY THIS BRIDGE?", "@gamingclips"
# The white box behind a line is a drawing with no words in it, so of the pair only one carries the text.
ass = render.build_ass([], 0.0, 40.0, HOOK, "bounce", [], 300, 1380, ASK)
plain = render.build_ass([], 0.0, 40.0, HOOK, "bounce", [], 300, 1380)
check("the closing line is drawn, box and words", len(hook_lines(ass, ASK)) == 1
      and len(hook_lines(ass, "")) == len(hook_lines(plain, "")) + 2, ass)
check("a closing line too wide for the box is split over two lines, not cut off",
      len(hook_lines(render.build_ass([], 0.0, 40.0, HOOK, "bounce", [], 300, 1380,
                                      "@gamingclips - more GTA 6 fixes every day"), "")) == 5)
check("it comes up in the last seconds, not at the start", starts_at(ass, ASK) >= 37.0, starts_at(ass, ASK))
check("it runs to the very end of the clip", ends_at(ass, ASK) == 40.0)
check("the heading still goes early and does not meet it", ends_at(ass, HOOK) < starts_at(ass, ASK))
check("a clip with no closing line set gets only the heading", len(hook_lines(plain, "")) == 2
      and len(hook_lines(render.build_ass([], 0.0, 40.0, HOOK, "bounce", [], 300, 1380, ""), "")) == 2)

# A 3 second clip has only just finished saying its heading; there is no room to ask for anything after it.
check("a clip too short for both keeps the heading and drops the closing line",
      render.end_card_span("@gamingclips", 3.0, HOOK) is None, render.end_card_span("@gamingclips", 3.0, HOOK))
check("a clip with room gets it", render.end_card_span("@gamingclips", 30.0, HOOK) == (27.8, 30.0))
check("a long heading pushes the closing line later rather than under it",
      render.end_card_span("@gamingclips", 8.0, " ".join(["word"] * 30))[0] > render.hook_hold(" ".join(["word"] * 30), 8.0))
check("nothing set means nothing shown", render.end_card_span("", 30.0) is None
      and render.end_card_span("   ", 30.0) is None and render.end_card_span(None, 30.0) is None)

check("the closing line is kept as typed, like the big text",
      creators.clean_hook("  @gamingclips  -  more GTA 6 fixes ") == "@gamingclips - more GTA 6 fixes")
with ctx.as_user(u.id):
    c3 = creators.create({"name": "Asker", "end_card": "@gamingclips"})
    check("a creator can set a standing closing line", creators.get(c3["id"])["end_card"] == "@gamingclips")
    job = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False, creator=c3["id"])
    check("their videos inherit it", job["options"]["end_card"] == "@gamingclips")
    check("one video can use its own, or none",
          (jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"end_card": "@other"}, enqueue=False, creator=c3["id"])["options"]["end_card"],
           jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"end_card": ""}, enqueue=False, creator=c3["id"])["options"]["end_card"]) == ("@other", ""))
    check("by default there is no closing line",
          jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False)["options"]["end_card"] == "")
    check("it is cut to fit the box", len(creators.clean_hook("x" * 200)) == 60)

with patch.object(render, "_render_in", return_value={"file": "a.mp4"}) as encode:
    render.render_clip(Path("x.mp4"), Path(os.environ["PEAKCUT_DATA"]) / "out", "b",
                       {"start": 0, "end": 30, "hook": "WHY THIS BRIDGE?", "end_card": "@gamingclips"}, [], 1920, 1080)
    check("the renderer puts the clip's closing line on the video",
          len(hook_lines(encode.call_args.args[-1], "@gamingclips")) == 1, encode.call_args.args[-1])

print("ALL PASSED" if not fails else f"{len(fails)} failed")
import shutil  # noqa: E402

db.engine.dispose()
shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
