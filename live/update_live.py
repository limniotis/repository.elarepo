#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Refresh the git-hosted live channel data from the maintained upstreams and apply local
overrides, so plugin.video.iparhotv can fetch it from raw.githubusercontent instead of
depending on Enhance hosting.

Runs on GitHub Actions (see .github/workflows/update-live.yml), whose runner can reach the
Greek CDNs and probe stream URLs - something the dev sandbox cannot. Writes live/gr_ch.json
(the rich channel list, passed through from the gist) and live/greek.m3u (the playlist, with
overrides applied). The workflow commits whatever changed.

ponytail: overrides only touch the M3U. The JSON is passed through verbatim - it is the
upstream author's maintained list; the add-on merges the M3U on top for the extras and fixes.
"""

import json
import sys
import urllib.request

HERE = __file__.rsplit("/", 1)[0]
GIST_JSON = "https://gist.githubusercontent.com/Twilight0/c52b15df1d738d01a84a4d46ff74b4bf/raw/gr_ch.json"
KOMHSGR_M3U = "https://raw.githubusercontent.com/komhsgr/m3u/refs/heads/main/Greekstreamtv.m3u"
UA = "Mozilla/5.0 (iparho-live-updater)"


def fetch(url, binary=False, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def reachable(url, timeout=12):
    """True if the URL answers < 400 with a non-empty body. Best effort - a geo-locked
    stream can still 403 from a US runner, which just means we can't confirm it here."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 400 and bool(r.read(64))
    except Exception as exc:
        print("    probe fail:", url, "->", repr(exc))
        return False


def first_working(candidates):
    for url in candidates:
        if reachable(url):
            print("    OK:", url)
            return url
        print("    dead:", url)
    return None


def m3u_entries(text):
    """Yield (extinf_line, url_line) pairs; tolerates blank lines and the #EXTM3U header."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            url = lines[i + 1] if i + 1 < len(lines) else ""
            yield lines[i], url
            i += 2
        else:
            i += 1


def display_name(extinf):
    return extinf.split(",", 1)[1].strip() if "," in extinf else ""


def apply_overrides(m3u_text, overrides):
    entries = list(m3u_entries(m3u_text))

    # replace: swap the URL of an existing channel with the first working candidate
    replace = overrides.get("replace", {})
    for idx, (extinf, url) in enumerate(entries):
        key = display_name(extinf).upper().strip()
        if key in {k.upper() for k in replace}:
            cand = next(v for k, v in replace.items() if k.upper() == key)
            print("replace", key)
            new = first_working(cand if isinstance(cand, list) else [cand])
            if new:
                entries[idx] = (extinf, new)
            else:
                print("    no working candidate; keeping existing url")

    # add: append a new channel if a candidate works and it is not already present
    present = {display_name(e).upper().strip() for e, _ in entries}
    for item in overrides.get("add", []):
        name = item["name"].strip()
        if name.upper() in present:
            print("add", name, "- already present, skipping")
            continue
        print("add", name)
        url = first_working(item.get("candidates", []))
        if not url:
            print("    no working candidate; not adding")
            continue
        logo = (item.get("logo") or "").replace('"', "")
        group = (item.get("group") or "WEB TV").replace('"', "")
        extinf = '#EXTINF:-1 group-title="{0}" tvg-logo="{1}",{2}'.format(group, logo, name)
        entries.append((extinf, url))

    out = ["#EXTM3U"]
    for extinf, url in entries:
        out.append(extinf)
        out.append(url)
    return "\n".join(out) + "\n"


def main():
    overrides = json.load(open(HERE + "/overrides.json", encoding="utf-8"))

    print("Fetching gist JSON...")
    gr_ch = fetch(GIST_JSON)
    json.loads(gr_ch)  # validate; a broken gist must fail the run, not commit garbage
    open(HERE + "/gr_ch.json", "w", encoding="utf-8").write(gr_ch)

    print("Fetching komhsgr M3U...")
    m3u = fetch(KOMHSGR_M3U)
    if "#EXTINF" not in m3u:
        raise SystemExit("upstream M3U looks invalid; aborting")

    print("Applying overrides...")
    m3u = apply_overrides(m3u, overrides)
    open(HERE + "/greek.m3u", "w", encoding="utf-8").write(m3u)

    print("Done. channels in M3U:", m3u.count("#EXTINF"))


if __name__ == "__main__":
    sys.exit(main())
