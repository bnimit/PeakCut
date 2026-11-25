"""Check caption preferences and the subtitle events sent to the encoder."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, ".")
WORDS = [{"w": "spoken", "s": 1.0, "e": 1.5}]
FIXED = [{"w": "polished", "s": 1.0, "e": 1.5}]


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def has_dialogue(ass, style, text=""):
    return any(line.startswith("Dialogue: ") and f",{style}," in line and text in line
               for line in ass.splitlines())


def rejects_caption_value(call):
    try:
        call()
    except HTTPException as error:
        return error.status_code == 400 and "captions" in str(error.detail).lower()
    return False


def main(data):
    os.environ.update(PEAKCUT_DATA=data, DATABASE_URL="", PEAKCUT_ACCOUNTS="0")
    from studio import auth, brain, creators, ctx, db, jobs, render, roman, server

    db.init()
    try:
        user = auth.local_user().id
        source = {"type": "file", "name": "Caption test"}
        clip = {"id": "clip1", "start": 0.0, "end": 4.0, "status": "done", "hook": "KEEP THE HOOK",
                "title": "A clip", "description": "", "hashtags": [], "score": 95}

        with ctx.as_user(user):
            creator = creators.create({"name": "Caption test creator", "captions": False})
            inherited = jobs.create(source, {}, enqueue=False, creator=creator["id"])
            live_job = jobs.create(source, {}, enqueue=False, creator=creator["id"], kind="live")
            override = jobs.create(source, {"captions": True}, enqueue=False, creator=creator["id"])
            check("videos and live jobs inherit the creator's caption preference",
                  inherited["options"]["captions"] is False and live_job["options"]["captions"] is False)
            check("a job can override its creator's caption preference", override["options"]["captions"] is True)

            job = jobs.create(source, {}, enqueue=False)
            check("the default is to show captions", job["options"]["captions"] is True)
            job["options"].pop("captions")
            job.update(status="done", source_path=str(Path(data) / "source.mp4"), width=1920, height=1080,
                       duration=4.0, clips=[clip])
            jobs.save(job)

        with (ctx.as_user(user), patch.object(render, "_render_in", return_value={"file": "clip1.mp4"}) as encode,
              patch.object(brain, "english_captions", return_value=FIXED) as prepare,
              patch.object(roman, "words", wraps=roman.words) as romanize,
              patch.object(jobs._q, "put") as queue):
            jobs.render_one(job, clip, WORDS)
            ass = encode.call_args.args[-1]
            check("an older saved clip still renders spoken captions",
                  clip["status"] == "done" and has_dialogue(ass, "Cap", "POLISHED"))
            check("caption preparation is cached for the clip", prepare.call_count == 1 and clip["fixed_words"] == FIXED)

            for value in ("false", 0, None):
                check(f"the clip editor and creator settings reject {value!r} as a caption preference",
                      rejects_caption_value(lambda: server.rerender(job["id"], clip["id"], {"captions": value}))
                      and rejects_caption_value(lambda: server.new_creator({"name": "Invalid", "captions": value})))
            check("invalid caption changes do not queue a render", not queue.called)

            prepare.reset_mock()
            romanize.reset_mock()
            response = server.rerender(job["id"], clip["id"], {"captions": False})
            check("the clip editor can turn captions off", response["clips"][0]["captions"] is False)
            check("turning captions off queues the clip for rendering", queue.call_args.args[0] == ("clip", job["id"], clip["id"]))
            jobs.render_one(job, clip, WORDS)
            ass = encode.call_args.args[-1]
            check("turning off captions keeps the hook and skips caption processing",
                  clip["status"] == "done" and not has_dialogue(ass, "Cap") and has_dialogue(ass, "Hook", "KEEP THE HOOK")
                  and not prepare.called and not romanize.called)
            saved = json.loads((Path(job["dir"]) / "job.json").read_text(encoding="utf-8"))["clips"][0]
            check("the saved clip retains both the preference and the cached words",
                  saved["captions"] is False and saved["fixed_words"] == FIXED)

            response = server.rerender(job["id"], clip["id"], {"captions": True})
            check("the clip editor can turn captions back on", response["clips"][0]["captions"] is True)
            jobs.render_one(job, clip, WORDS)
            check("turning captions back on uses the cached words",
                  clip["status"] == "done" and has_dialogue(encode.call_args.args[-1], "Cap", "POLISHED")
                  and not prepare.called)

            render.render_clip(Path(data) / "source.mp4", Path(data) / "clips", "direct",
                               dict(clip, captions=False), WORDS, 1920, 1080)
            ass = encode.call_args.args[-1]
            check("the renderer honors captions off even when it receives spoken words",
                  not has_dialogue(ass, "Cap") and has_dialogue(ass, "Hook", "KEEP THE HOOK"))

            # The heading used to be pinned on screen for the clip's whole length, so a white slab covered the
            # video all the way through. It is up long enough to read and then it goes.
            hook = "How to get your loot back"
            check("the heading goes away well before a long clip ends",
                  0 < render.hook_hold(hook, 42.0) <= 4.0)
            check("a longer heading is given longer to be read",
                  render.hook_hold("one two three four five six seven eight", 42.0) > render.hook_hold("short one", 42.0))
            check("no heading outstays five seconds, however many words it has",
                  render.hook_hold(" ".join(["word"] * 60), 42.0) <= 5.0)
            check("on a short clip the heading takes at most half of it",
                  render.hook_hold(hook, 4.0) <= 2.0 and render.hook_hold(hook, 4.0) > 0)
            check("even a very short clip shows its heading", render.hook_hold(hook, 1.2) >= 1.0)
            check("a clip of unknown length still gets a readable heading", render.hook_hold(hook, 0) >= 1.0)

            ass = render.build_ass(WORDS, 0.0, 42.0, hook, "bounce", [], 300, 1380)
            heading = [x for x in ass.splitlines() if x.startswith("Dialogue: ") and ",Hook," in x]
            check("the heading is drawn and its box ends with it", len(heading) >= 2)
            check("the heading's lines do not run to the end of a 42 second clip",
                  all(",0:00:42" not in x for x in heading) and all("0:00:0" in x.split(",")[2] for x in heading))
            check("the heading fades out instead of blinking off", all("\\fad(160,260)" in x for x in heading))
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pc-captions-") as data:
        main(data)
