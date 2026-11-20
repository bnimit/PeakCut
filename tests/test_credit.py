"""The line added to every post can name whoever made the video a clip came from.

Writing {source} in it puts that name in. A live recording or an uploaded file has no such name, so the line is
left out rather than posted with a hole in it.

Runs against the code directly, with its own empty data folder."""
import os, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-credit-")
sys.path.insert(0, ".")
from studio import posting
fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


CLIP = {"description": "A shark takes the fish.", "hashtags": ["GTA6", "ViceCity"]}
CREDIT = {"post_footer": "Clipped from {source}'s video. All credit to them."}
PLAIN = {"post_footer": "Clips from the original creators."}

# ---- the name goes in
check("the uploader's name replaces {source}",
      posting._footer(CREDIT, {"uploader": "GamingBolt"}), "Clipped from GamingBolt's video. All credit to them.")
check("a name with spaces works too",
      posting._footer(CREDIT, {"uploader": "Dylan Gaming"}), "Clipped from Dylan Gaming's video. All credit to them.")
check("spaces around the name are dropped",
      posting._footer(CREDIT, {"uploader": "  Betaz  "}), "Clipped from Betaz's video. All credit to them.")

# ---- no name: the whole line goes, never a hole
check("a live recording with no uploader drops the line", posting._footer(CREDIT, {}), "")
check("an empty uploader drops the line", posting._footer(CREDIT, {"uploader": ""}), "")
check("a blank uploader drops the line", posting._footer(CREDIT, {"uploader": "   "}), "")
check("no job at all drops the line", posting._footer(CREDIT, None), "")

# ---- a line without {source} is left exactly as it is
check("a plain line is kept when there is a name",
      posting._footer(PLAIN, {"uploader": "Betaz"}), "Clips from the original creators.")
check("a plain line is kept when there is none", posting._footer(PLAIN, {}), "Clips from the original creators.")
check("no line set means no line", posting._footer({}, {"uploader": "Betaz"}), "")

# ---- and the caption built from it
cap = posting._caption(CLIP, CREDIT, {"uploader": "GamingBolt"})
check("the caption ends with the credit", cap.endswith("Clipped from GamingBolt's video. All credit to them."), True)
check("the description is still first", cap.startswith("A shark takes the fish."), True)
check("the tags are still there", "#GTA6 #ViceCity" in cap, True)
check("a caption with no name has no empty tail", posting._caption(CLIP, CREDIT, {}).rstrip(), posting._caption(CLIP, CREDIT, {}))
check("a caption with no name ends on the tags", posting._caption(CLIP, CREDIT, {}).endswith("#ViceCity"), True)
check("the job may be left out entirely", posting._caption(CLIP, PLAIN).endswith("Clips from the original creators."), True)

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
