#!/usr/bin/env python3
"""Backtalk: make your GitHub contribution graph say something.

Commands
  fetch   USER                      Save the user's current contribution calendar (needs `gh`).
  plan    TEXT --calendar FILE      Pick a free spot, choose intensity, write manifest + visualizer.
  paint   MANIFEST --repo DIR       Create backdated art commits in a separate local repo (idempotent).
  verify  MANIFEST USER             After pushing, check GitHub shows the art cells.

Nothing here pushes. Pushing is a manual, separate step.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

from font import GLYPHS, MINI, SMALL, compose, render, render_text

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = "backtalk-cell"
COLORS = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]


# ---------- calendar ----------

def gh_calendar(user, frm=None, to=None):
    args = ""
    if frm:
        args = f'(from:"{frm}",to:"{to}")'
    q = ('query{user(login:"%s"){contributionsCollection%s{contributionCalendar{'
         'totalContributions weeks{contributionDays{date contributionCount contributionLevel weekday}}}}}}') % (user, args)
    out = subprocess.run(["gh", "api", "graphql", "-f", f"query={q}"], check=True, capture_output=True, text=True).stdout
    cal = json.loads(out)["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    return {"user": user, "fetched": dt.datetime.utcnow().isoformat() + "Z", "total": cal["totalContributions"], "days": days}


def to_grid(days):
    """Calendar days -> dict date->count, plus first Sunday and number of week columns."""
    counts = {d["date"]: d["contributionCount"] for d in days}
    first = dt.date.fromisoformat(days[0]["date"])
    first -= dt.timedelta(days=(first.weekday() + 1) % 7)  # back to Sunday
    last = dt.date.fromisoformat(days[-1]["date"])
    ncols = (last - first).days // 7 + 1
    return counts, first, last, ncols


def level(count, nonzero):
    """Approximate GitHub's shading: quartiles of the year's non-zero days. Not exact."""
    if count == 0:
        return 0
    s = sorted(nonzero)
    q = lambda p: s[min(len(s) - 1, int(p * len(s)))]
    q1, q2, q3 = q(0.25), q(0.5), q(0.75)
    return 1 if count < q1 else 2 if count < q2 else 3 if count < q3 else 4


# ---------- planning ----------

def pattern_rows(p):
    rows = p.split("/")
    if len(rows) != 7 or len({len(r) for r in rows}) != 1 or set("".join(rows)) - set(".1234#"):
        sys.exit("--pattern must be 7 equal-length rows of . 1 2 3 4 joined by /")
    return [r.replace("#", "4") for r in rows]


def find_spot(counts, first, last, ncols, width, margin):
    """Leftmost-centred run of empty week columns that fits the art. Never paints over real activity."""
    today = dt.date.today()
    free = []
    for c in range(ncols):
        dates = [first + dt.timedelta(days=7 * c + r) for r in range(7)]
        ok = all(counts.get(d.isoformat(), 0) == 0 for d in dates) and dates[-1] < today
        free.append(ok)
    best = None
    c = 0
    while c < ncols:
        if not free[c]:
            c += 1
            continue
        s = c
        while c < ncols and free[c]:
            c += 1
        run = c - s
        if run >= width + 2 * margin and (best is None or run > best[1]):
            best = (s, run)
    if not best:
        sys.exit(f"No empty stretch of {width + 2 * margin} weeks in the window. Try a shorter word or --start.")
    s, run = best
    return s + (run - width) // 2


def plan(args):
    cal = json.load(open(args.calendar))
    counts, first, last, ncols = to_grid(cal["days"])
    rows = (pattern_rows(args.pattern) if args.pattern
            else compose(args.text, args.icon, args.gap, args.spacing) if args.icon
            else [r.replace('#', '4') for r in render(args.text, args.font, args.row, args.spacing)])
    width = len(rows[0])
    if args.start:
        start = dt.date.fromisoformat(args.start)
        if start.weekday() != 6:
            sys.exit("--start must be a Sunday (top row of the graph).")
        col = (start - first).days // 7
    else:
        col = find_spot(counts, first, last, ncols, width, args.margin)
        start = first + dt.timedelta(days=7 * col)

    real_nonzero = [v for v in counts.values() if v]
    real_max = max(real_nonzero, default=0)
    per_cell = args.per_cell or max(real_max, 10)

    cells, clashes = [], []
    for c in range(width):
        for r in range(7):
            d = start + dt.timedelta(days=7 * c + r)
            if d >= dt.date.today():
                sys.exit(f"Art would reach {d}, which is today or later. Pick an earlier start.")
            b = 0 if rows[r][c] == "." else int(rows[r][c])
            lit = b > 0
            real = counts.get(d.isoformat(), 0)
            if real:
                clashes.append({"date": d.isoformat(), "real": real, "lit": lit})
            if lit:
                cells.append({"date": d.isoformat(), "row": r, "col": col + c, "commits": max(1, round(per_cell * b / 4))})

    after = dict(counts)
    for cell in cells:
        after[cell["date"]] = after.get(cell["date"], 0) + cell["commits"]
    after_nonzero = [v for v in after.values() if v]

    ident = hashlib.sha256(f"{'/'.join(rows)}|{start}|{per_cell}|{args.email}".encode()).hexdigest()[:12]
    manifest = {
        "backtalk": 1,
        "id": ident,
        "text": args.text.upper(),
        "user": cal["user"],
        "email": args.email,
        "commit_time_utc": "12:00",
        "start": start.isoformat(),
        "end": (start + dt.timedelta(days=7 * width - 1)).isoformat(),
        "weeks": width,
        "per_cell": per_cell,
        "cells": cells,
        "icon": args.icon,
        "pattern": "/".join(rows),
        "font": args.font,
        "row": args.row,
        "total_commits": sum(c["commits"] for c in cells),
        "clashes": clashes,
        "window": {"first": first.isoformat(), "last": last.isoformat(), "cols": ncols},
        "real_total": cal["total"],
        "real_max_day": real_max,
        "predicted_levels": {
            "art": sorted({level(c["commits"], after_nonzero) for c in cells}),
            "real_after": {d: level(v, after_nonzero) for d, v in counts.items() if v},
        },
    }
    os.makedirs(args.out, exist_ok=True)
    mpath = os.path.join(args.out, "manifest.json")
    json.dump(manifest, open(mpath, "w"), indent=2)
    write_visualizer(manifest, counts, first, ncols, os.path.join(args.out, "preview.html"), col)
    print_ascii(manifest, counts, first, ncols)
    print(f"\nmanifest: {mpath}\npreview:  {os.path.join(args.out, 'preview.html')}")


def print_ascii(m, counts, first, ncols):
    lit = {c["date"] for c in m["cells"]}
    print(f"{m['text']}  {m['start']} -> {m['end']}  ({len(m['cells'])} cells, {m['total_commits']} commits)")
    for r in range(7):
        line = ""
        for c in range(ncols):
            d = (first + dt.timedelta(days=7 * c + r)).isoformat()
            line += "█" if d in lit else ("▒" if counts.get(d) else "·")
        print("SMTWTFS"[r], line)
    print("  █ art   ▒ your real activity   · empty")


def visualizer_data(m, counts, first, ncols, col, site=False):
    return {"site": site, "user": m["user"], "email": m["email"], "text": m["text"],
            "font": m.get("font", "tall"), "row": m.get("row", 0), "perCell": m["per_cell"],
            "startCol": col, "first": first.isoformat(), "ncols": ncols,
            "today": dt.date.today().isoformat(), "counts": {d: v for d, v in counts.items() if v},
            "tall": GLYPHS, "small": SMALL, "mini": MINI}


def write_visualizer(m, counts, first, ncols, path, col, site=False):
    tpl = open(os.path.join(HERE, "visualizer.html")).read()
    open(path, "w").write(tpl.replace("__DATA__", json.dumps(visualizer_data(m, counts, first, ncols, col, site))))


# ---------- painting ----------

def git(repo, *a, env=None):
    return subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, text=True, env=env).stdout


DISCLOSURE = """# {text}

The commits in this repo are backdated on purpose. Their dates were set so they
spell "{text}" on {user}'s GitHub contribution graph, {start} to {end}. They don't
record when any work happened, and there is no real work in them.

{total} commits across {n} squares. Art id `{id}`.

Make your own at [backtalk.ckai.co](https://backtalk.ckai.co). Code: [ckaico/backtalk](https://github.com/ckaico/backtalk).
"""


def paint(args):
    m = json.load(open(args.manifest))
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        os.makedirs(repo, exist_ok=True)
        git(repo, "init", "-b", "main")
    # Safety: only ever touch a repo that is ours (empty, or already a Backtalk art repo for this manifest).
    marker = os.path.join(repo, ".backtalk")
    has_commits = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "HEAD"], capture_output=True).returncode == 0
    if has_commits and (not os.path.exists(marker) or open(marker).read().strip() != m["id"]):
        sys.exit(f"{repo} has commits and is not the Backtalk art repo for {m['id']}. Refusing to touch it.")

    existing = set()
    if has_commits:
        for line in git(repo, "log", "--format=%(trailers:key=" + MARK + ",valueonly)").splitlines():
            if line.strip():
                existing.add(line.strip())

    base_env = dict(os.environ)
    base_env.update({"GIT_AUTHOR_NAME": args.name, "GIT_AUTHOR_EMAIL": m["email"],
                     "GIT_COMMITTER_NAME": args.name, "GIT_COMMITTER_EMAIL": m["email"]})

    if not has_commits:
        open(marker, "w").write(m["id"] + "\n")
        open(os.path.join(repo, "README.md"), "w").write(DISCLOSURE.format(
            text=m["text"], user=m["user"], start=m["start"], end=m["end"], id=m["id"],
            n=len(m["cells"]), per=m["per_cell"], total=m["total_commits"]))
        json.dump(m, open(os.path.join(repo, "manifest.json"), "w"), indent=2)
        git(repo, "add", ".backtalk", "README.md", "manifest.json")
        # The disclosure commit is dated now, so it lands on today's square, not in the art.
        git(repo, "commit", "-m", "Backtalk: disclosure and manifest (art commits are backdated)", env=base_env)

    canvas = os.path.join(repo, "canvas.txt")
    made = skipped = 0
    for cell in sorted(m["cells"], key=lambda c: c["date"]):
        before = made
        for k in range(cell["commits"]):
            key = f"{m['id']}:{cell['date']}:{k}"
            if key in existing:
                skipped += 1
                continue
            stamp = f"{cell['date']}T12:{k // 60:02d}:{k % 60:02d}+00:00"
            with open(canvas, "a") as f:
                f.write(f"{cell['date']} {k}\n")
            env = dict(base_env, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
            git(repo, "add", "canvas.txt")
            git(repo, "commit", "-q", "-m", f"{m['text']} pixel {cell['date']} #{k + 1}\n\n"
                f"Backdated contribution-graph art, not real work.\n\n{MARK}: {key}", env=env)
            made += 1
        if made > before:
            print(f"{cell['date']}  +{made - before} commits", flush=True)
    print(f"created {made} commits, skipped {skipped} already present, repo {repo}")


# ---------- verify ----------

def verify(args):
    m = json.load(open(args.manifest))
    cal = gh_calendar(args.user, m["start"] + "T00:00:00Z", m["end"] + "T23:59:59Z")
    counts = {d["date"]: (d["contributionCount"], d["contributionLevel"]) for d in cal["days"]}
    bad = [(c["date"], counts.get(c["date"], (0, None))) for c in m["cells"] if counts.get(c["date"], (0,))[0] < c["commits"]]
    lit = {c["date"] for c in m["cells"]}
    stray = [d for d, (v, _) in counts.items() if v and d not in lit and m["start"] <= d <= m["end"]]
    print(f"{len(m['cells']) - len(bad)}/{len(m['cells'])} art cells showing full count")
    for d, v in bad[:10]:
        print("  missing/low", d, v)
    if stray:
        print("  activity in blank cells (blurs letters):", stray)
    print("GitHub can take time to recount; rerun later if cells are missing.")


def site(args):
    """Public page: blank last-year graph, no personal data."""
    today = dt.date.today()
    first = today - dt.timedelta(days=364)
    first -= dt.timedelta(days=(first.weekday() + 1) % 7)
    ncols = (today - first).days // 7 + 1
    width = len(render_text("POOP")[0])
    m = {"user": "you", "email": "", "text": "POOP", "font": "tall", "row": 0, "per_cell": 20}
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "index.html")
    write_visualizer(m, {}, first, ncols, path, (ncols - width) // 2, site=True)
    title = "Backtalk: write words on your GitHub contribution graph"
    desc = ("Type a word or draw pixel art, preview it on your real GitHub contribution graph, "
            "then paint it in with backdated commits in a separate repo. Free and open source.")
    site_url, img = "https://backtalk.ckai.co/", "https://backtalk-eta.vercel.app/og.png"
    icon = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
            "%3Crect width='16' height='16' rx='3' fill='%230d1117'/%3E"
            "%3Crect x='3' y='3' width='4' height='4' rx='1' fill='%2339d353'/%3E"
            "%3Crect x='9' y='3' width='4' height='4' rx='1' fill='%23006d32'/%3E"
            "%3Crect x='3' y='9' width='4' height='4' rx='1' fill='%2326a641'/%3E"
            "%3Crect x='9' y='9' width='4' height='4' rx='1' fill='%2339d353'/%3E%3C/svg%3E")
    ld = json.dumps({"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "Backtalk",
                     "description": desc, "url": site_url, "applicationCategory": "DeveloperApplication",
                     "operatingSystem": "macOS, Linux, Windows", "offers": {"@type": "Offer", "price": "0"},
                     "author": {"@type": "Person", "name": "Christian Kai", "url": "https://github.com/ckaico"},
                     "codeRepository": "https://github.com/ckaico/backtalk"})
    meta = (f'<link rel="canonical" href="{site_url}">\n'
            f'<link rel="icon" href="{icon}">\n'
            '<meta name="theme-color" content="#0d1117">\n'
            '<meta property="og:type" content="website">\n'
            '<meta property="og:site_name" content="Backtalk">\n'
            f'<meta property="og:title" content="{title}">\n'
            f'<meta property="og:description" content="{desc}">\n'
            f'<meta property="og:url" content="{site_url}">\n'
            f'<meta property="og:image" content="{img}">\n'
            '<meta property="og:image:width" content="1200">\n'
            '<meta property="og:image:height" content="630">\n'
            '<meta property="og:image:alt" content="A GitHub contribution graph with the word POOP spelled out in green squares">\n'
            '<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:title" content="{title}">\n'
            f'<meta name="twitter:description" content="{desc}">\n'
            f'<meta name="twitter:image" content="{img}">\n'
            f'<script type="application/ld+json">{ld}</script>\n</head>')
    html = open(path).read().replace("</head>", meta, 1)
    html = html.replace("<title>Backtalk</title>", f"<title>{title}</title>", 1)
    html = html.replace('content="Make your GitHub contribution graph say something."', f'content="{desc}"', 1)
    open(path, "w").write(html)
    open(os.path.join(args.out, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\nSitemap: {site_url}sitemap.xml\n")
    open(os.path.join(args.out, "sitemap.xml"), "w").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{site_url}</loc><lastmod>{dt.date.today()}</lastmod></url></urlset>\n")
    print("site:", os.path.join(args.out, "index.html"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    f = s.add_parser("fetch"); f.add_argument("user"); f.add_argument("--out", default="calendar.json")
    pl = s.add_parser("plan"); pl.add_argument("text"); pl.add_argument("--calendar", required=True)
    pl.add_argument("--email", required=True); pl.add_argument("--start"); pl.add_argument("--per-cell", type=int)
    pl.add_argument("--spacing", type=int, default=1); pl.add_argument("--margin", type=int, default=2)
    pl.add_argument("--out", default="out"); pl.add_argument("--icon"); pl.add_argument("--pattern", help="7 rows of .1234 joined by /, from the visualizer"); pl.add_argument("--font", choices=["tall", "small", "mini"], default="tall"); pl.add_argument("--row", type=int, default=0); pl.add_argument("--gap", type=int, default=2)
    pa = s.add_parser("paint"); pa.add_argument("manifest"); pa.add_argument("--repo", required=True)
    pa.add_argument("--name", required=True)
    st = s.add_parser("site"); st.add_argument("--out", default="site")
    v = s.add_parser("verify"); v.add_argument("manifest"); v.add_argument("user")
    a = p.parse_args()
    if a.cmd == "fetch":
        json.dump(gh_calendar(a.user), open(a.out, "w"), indent=2)
        print("saved", a.out)
    elif a.cmd == "site":
        site(a)
    else:
        {"plan": plan, "paint": paint, "verify": verify}[a.cmd](a)


if __name__ == "__main__":
    main()
