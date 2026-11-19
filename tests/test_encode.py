"""How a finished clip is encoded.

A clip is a master for YouTube, which re-encodes whatever it is handed. So the encode here is spent on
surviving that second pass, not on being small: a quality target rather than a bitrate, a preset that is
slow enough to earn its bits, and the colour tagged so nothing has to guess. Runs ffmpeg for real.
"""
import os, subprocess, sys, tempfile
os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-enc-")
sys.path.insert(0, ".")
from pathlib import Path

from studio import config, render

fails = []
def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


work = Path(tempfile.mkdtemp(prefix="pc-enc-work-"))
# A moving, noisy picture: it does not compress away, so a change in the quality target shows in the file size.
src = work / "src.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "nullsrc=s=640x360:r=25,noise=alls=28:allf=t",
                "-frames:v", "50", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)],
               check=True)
ass = render.build_ass([{"w": "hello", "s": 0.2, "e": 0.8}], 0, 2, "HOOK", "bounce", [], 300, 1380)
render._qsv_ok = False                 # no Intel hardware here: check the libx264 path everyone falls back to


def encode_at(crf, name):
    """Render the clip with this quality target and give back the finished file."""
    was, out, wk = config.CRF, work / name, work / f"w-{name}"
    out.mkdir(exist_ok=True)
    wk.mkdir(exist_ok=True)                              # render_clip makes this short work folder itself
    config.CRF = crf
    try:
        render._render_in(wk, src, out, "clip", 0, 2, "crop", 1920, ass)
    finally:
        config.CRF = was
    return out / "clip.mp4"


def probe(path, fields):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        f"stream={fields}", "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return r.stdout.split()


# ---- the defaults a clip is encoded with
check("the quality target is a master's, not a small file's", config.CRF, 18)
check("the preset is slow enough to earn its bits", config.X264_PRESET, "medium")
args = dict(render._encoders(config.CRF, config.X264_PRESET))["x264"]
check("those reach libx264", "-crf" in args and args[args.index("-crf") + 1] == "18"
      and args[args.index("-preset") + 1] == "medium", True)

check("all three colour tags are set in the chain, where they actually take effect",
      render._subs_and_colour("clip").count("bt709"), 3)

# ---- and they are what the renderer actually uses. Burning captions needs an ffmpeg built with libass; some
# are not (Homebrew's ffmpeg 9 is one), and there is no point reporting a pass or a failure for a filter this
# machine does not have. Say so instead, loudly enough to be read.
has_ass = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
if " ass " not in has_ass:
    print("SKIP the encoded-file checks: this ffmpeg has no 'ass' filter, so no clip can be rendered here "
          "(install an ffmpeg built with libass, or point PEAKCUT_FFMPEG_DIR at one)")
    print("ALL PASSED" if not fails else f"{len(fails)} failed")
    import shutil; shutil.rmtree(work, ignore_errors=True); shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
    sys.exit(1 if fails else 0)

good = encode_at(config.CRF, "default")
check("a clip comes out as 1080x1920 h264", probe(good, "codec_name,width,height"), ["h264", "1080", "1920"])
check("the colour is tagged, so YouTube need not guess", probe(good, "color_space,color_primaries,color_transfer"),
      ["bt709", "bt709", "bt709"])

thrifty = encode_at(28, "thrifty")
check("the quality target reaches the encoder: a lower number spends more bits",
      good.stat().st_size > thrifty.stat().st_size * 1.2,
      True)

# ---- a typo in .env must not stop every clip from rendering
probe_env = dict(os.environ, PEAKCUT_X264_PRESET="not-a-preset", PEAKCUT_DATA=str(work / "env"))
out = subprocess.run([sys.executable, "-c", "from studio import config; print(config.X264_PRESET)"],
                     capture_output=True, text=True, env=probe_env, cwd=".")
check("an unknown preset falls back instead of failing", out.stdout.strip(), "medium")

print("ALL PASSED" if not fails else f"{len(fails)} failed")
import shutil; shutil.rmtree(work, ignore_errors=True); shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
