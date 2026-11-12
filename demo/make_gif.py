"""Render demo/demo.html frame by frame with headless Chrome and stitch a GIF (needs Pillow).

python demo/make_gif.py out/manifest.json calendar.json docs/demo.gif
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from font import GLYPHS  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def frames(m):
    col = m["cells"][0]["col"]
    cols = sorted({c["col"] for c in m["cells"]})
    by_date = sorted(m["cells"], key=lambda c: c["date"])
    out = [({"s": "edit", "text": "", "col": 3, "caret": True}, 700)]
    for i, t in enumerate(["P", "PO", "POO", "POOP"]):
        out.append(({"s": "edit", "text": t, "col": 3, "caret": True}, 230 if i < 3 else 700))
    steps = 9
    for i in range(steps + 1):
        c = 3 + round((col - 3) * i / steps)
        out.append(({"s": "edit", "text": "POOP", "col": c, "cursor": c + 2}, 80 if i < steps else 900))
    out.append(({"s": "edit", "text": "POOP", "col": col, "paint": True}, 800))

    head = ["$ python3 backtalk.py plan POOP --calendar calendar.json --email hi@ckai.co",
            f"POOP  {m['start']} -> {m['end']}  ({len(m['cells'])} cells, {m['total_commits']:,} commits)",
            "$ python3 backtalk.py paint out/manifest.json --repo ../poop --name \"Christian Kai\""]
    out.append(({"s": "paint", "lines": head, "fill": cols[0], "note": "Painting..."}, 700))
    log = list(head)
    n = 12
    for i in range(1, n + 1):
        upto = cols[0] + round(len(cols) * i / n)
        done = [c for c in by_date if c["col"] < upto]
        new = [c for c in done if f"{c['date']}  +{c['commits']} commits" not in log]
        log += [f"{c['date']}  +{c['commits']} commits" for c in new]
        made = sum(c["commits"] for c in done)
        out.append(({"s": "paint", "lines": log[-7:], "fill": upto,
                     "note": f"{made:,} of {m['total_commits']:,} backdated commits"}, 110))
    log += [f"created {m['total_commits']} commits, skipped 0 already present", "$ git push -u origin main",
            f"Writing objects: 100% ({m['total_commits'] + 1}/{m['total_commits'] + 1}), done."]
    out.append(({"s": "paint", "lines": log[-7:], "fill": 999, "note": "Pushed. The art shows once GitHub recounts."}, 1500))
    out.append(({"s": "done", "cap": "<b>Backtalk</b> · backtalk.ckai.co"}, 4000))
    return out


def main(manifest, calendar, dest):
    m = json.load(open(manifest))
    cal = json.load(open(calendar))
    days = cal["days"]
    first = dt.date.fromisoformat(days[0]["date"])
    first -= dt.timedelta(days=(first.weekday() + 1) % 7)
    last = dt.date.fromisoformat(days[-1]["date"])
    fr = frames(m)
    data = {"first": first.isoformat(), "ncols": (last - first).days // 7 + 1, "today": last.isoformat(),
            "counts": {d["date"]: d["contributionCount"] for d in days if d["contributionCount"]},
            "tall": GLYPHS, "perCell": m["per_cell"],
            "total": cal["total"] + m["total_commits"], "frames": [f for f, _ in fr]}
    data["col"] = min(c["col"] for c in m["cells"])
    tmp = tempfile.mkdtemp()
    page = os.path.join(tmp, "demo.html")
    open(page, "w").write(open(os.path.join(HERE, "demo.html")).read().replace("__DATA__", json.dumps(data)))
    imgs = []
    for i in range(len(fr)):
        png = os.path.join(tmp, f"{i:03d}.png")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--window-size=880,420", f"--screenshot={png}", f"file://{page}?f={i}"],
                       check=True, capture_output=True)
        imgs.append(Image.open(png).convert("RGB"))
        print(f"frame {i + 1}/{len(fr)}", end="\r", flush=True)
    pal = imgs[-1].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    q = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in imgs]
    q[0].save(dest, save_all=True, append_images=q[1:], duration=[d for _, d in fr], loop=0, optimize=True)
    print(f"\n{dest}: {len(fr)} frames, {os.path.getsize(dest) // 1024} KB")


if __name__ == "__main__":
    main(*sys.argv[1:4])
