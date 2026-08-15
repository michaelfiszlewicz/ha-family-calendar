#!/usr/bin/env python3
"""
icloud_photos.py
================
Download the full-resolution photos from one or more **public iCloud Shared
Albums** and store them locally so Home Assistant can display them.

This uses Apple's *undocumented* "shared streams" web API — the same API the
https://www.icloud.com/sharedalbum/ web page uses. No Apple ID / password is
required because the albums are public (anyone with the link can view them).

------------------------------------------------------------------------------
HOW THE API WORKS (for future maintainers)
------------------------------------------------------------------------------
1. A shared album link looks like:
       https://www.icloud.com/sharedalbum/#B2d5n8hH47H6Qm
   The part after the '#' (here "B2d5n8hH47H6Qm") is the album *token*.

2. Base URL is derived from the token. Apple shards albums across a number of
   "partitions". We start at a well-known host and follow a redirect:
       POST https://p<NN>-sharedstreams.icloud.com/<token>/sharedstreams/webstream
       body: {"streamCtag": null}
   The first request may return HTTP 330 ("Moved") with a JSON body containing
   {"X-Apple-MMe-Host": "p123-sharedstreams.icloud.com"}. We then re-issue the
   request against that host.

3. /webstream returns JSON with a "photos" array. Each photo has a
   "derivatives" dict keyed by pixel height; each derivative has a "checksum",
   "fileSize" and "width"/"height". We pick the LARGEST derivative (highest
   resolution) for best quality on a TV.

4. To turn checksums into real download URLs we POST the checksums to:
       POST https://<host>/<token>/sharedstreams/webasseturls
       body: {"photoGuids": [...guids...]}
   The response "items" maps checksum -> {"url_location", "url_path"}. The
   final URL is  "https://<url_location><url_path>".

5. Download each URL and save to disk.

------------------------------------------------------------------------------
OUTPUT LAYOUT
------------------------------------------------------------------------------
    <OUTPUT_ROOT>/landscape/<checksum>.jpg     (all landscape-album photos)
    <OUTPUT_ROOT>/portrait/<checksum>.jpg      (all portrait-album photos)
    <OUTPUT_ROOT>/landscape/index.json         (ordered list of files + meta)
    <OUTPUT_ROOT>/portrait/index.json

OUTPUT_ROOT defaults to /config/www/family_photos (so the files are reachable
in Home Assistant at  /local/family_photos/...).

------------------------------------------------------------------------------
USAGE
------------------------------------------------------------------------------
    python3 icloud_photos.py                 # fetch both albums (defaults)
    python3 icloud_photos.py --output /tmp/x # custom output root
    OUTPUT_ROOT=/tmp/x python3 icloud_photos.py

Only the Python standard library is used, so it runs anywhere Python 3.7+ is
available (including inside the Home Assistant OS container).
"""

import json
import os
import sys
import ssl
import time
import argparse
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
# The two shared albums the user provided. The "token" is the part of the
# iCloud link after the '#'. Add / change albums here if you ever need to.
ALBUMS = {
    # Landscape family photos  -> Screen 1 full-screen slideshow
    "landscape": "B2d5n8hH47H6Qm",
    # Portrait family photos   -> Screen 2 & 3 side photo
    "portrait": "B2dG4TcsmGmq8Q7",
}

# Where to write the photos. In Home Assistant, anything under /config/www is
# served at http://<ha>/local/ , so /config/www/family_photos -> /local/family_photos
DEFAULT_OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "/config/www/family_photos")

# A browser-like User-Agent avoids the occasional 403 from Apple's edge.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

# Network tuning
REQUEST_TIMEOUT = 60          # seconds per HTTP request
MAX_REDIRECTS = 3             # how many times we follow the X-Apple-MMe-Host hop
DOWNLOAD_RETRIES = 3          # retries per photo download


# ---------------------------------------------------------------------------
# LOW-LEVEL HTTP HELPERS
# ---------------------------------------------------------------------------
def _base_url_for_token(token: str, partition: int = 1) -> str:
    """Build the initial shared-streams host for a token."""
    return f"https://p{partition:02d}-sharedstreams.icloud.com/{token}/sharedstreams"


def _post(url: str, payload: dict):
    """POST JSON and return (status_code, headers, parsed_json_or_bytes)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "text/plain;charset=UTF-8")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Origin", "https://www.icloud.com")
    req.add_header("Referer", "https://www.icloud.com/")

    # iCloud presents a valid cert, but be lenient about the container's CA set.
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
            body = resp.read()
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                parsed = body
            return resp.getcode(), dict(resp.headers), parsed
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            parsed = body
        return e.code, dict(e.headers), parsed


def _webstream(token: str):
    """
    Call /webstream, following the X-Apple-MMe-Host redirect (HTTP 330).
    Returns (host, webstream_json).
    """
    host = None
    url = _base_url_for_token(token) + "/webstream"
    payload = {"streamCtag": None}

    for _ in range(MAX_REDIRECTS + 1):
        status, headers, parsed = _post(url, payload)

        # 330 = Apple's "use this other host instead" redirect.
        if status == 330 and isinstance(parsed, dict) and parsed.get("X-Apple-MMe-Host"):
            host = parsed["X-Apple-MMe-Host"]
            url = f"https://{host}/{token}/sharedstreams/webstream"
            continue

        if status == 200 and isinstance(parsed, dict):
            # Remember which host actually served us (for the asseturls call).
            if host is None:
                # extract host from the URL we just used
                host = url.split("/")[2]
            return host, parsed

        raise RuntimeError(
            f"Unexpected response from webstream (status={status}): "
            f"{str(parsed)[:300]}"
        )

    raise RuntimeError("Too many redirects talking to iCloud shared streams API")


def _webasseturls(host: str, token: str, photo_guids):
    """Resolve photo GUIDs -> real download URLs via /webasseturls."""
    url = f"https://{host}/{token}/sharedstreams/webasseturls"
    status, headers, parsed = _post(url, {"photoGuids": photo_guids})
    if status != 200 or not isinstance(parsed, dict):
        raise RuntimeError(
            f"webasseturls failed (status={status}): {str(parsed)[:300]}"
        )
    return parsed.get("items", {})


def _download(url: str, dest_path: str) -> bool:
    """Download a URL to dest_path. Returns True on success."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
                tmp = dest_path + ".part"
                with open(tmp, "wb") as fh:
                    fh.write(resp.read())
                os.replace(tmp, dest_path)
                return True
        except Exception as e:  # noqa: BLE001 - we want to retry on anything
            print(f"    download attempt {attempt} failed: {e}", file=sys.stderr)
            time.sleep(1.5 * attempt)
    return False


# ---------------------------------------------------------------------------
# CORE LOGIC
# ---------------------------------------------------------------------------
def _pick_best_derivative(photo: dict):
    """
    Given a photo record, return (checksum, url_key, width, height, filesize)
    for the HIGHEST-resolution derivative available.

    Apple keys derivatives by pixel height as strings, e.g. "342", "1366",
    "2048". Some albums also expose an implicit full-size original. We simply
    choose the derivative with the largest (width * height), falling back to
    the largest declared fileSize.
    """
    derivatives = photo.get("derivatives", {})
    best = None
    best_area = -1
    best_size = -1
    for _key, d in derivatives.items():
        try:
            w = int(d.get("width", 0))
            h = int(d.get("height", 0))
            size = int(d.get("fileSize", 0))
        except (TypeError, ValueError):
            w = h = size = 0
        area = w * h
        # Prefer the biggest pixel area; tie-break on file size.
        if area > best_area or (area == best_area and size > best_size):
            if d.get("checksum"):
                best = d
                best_area = area
                best_size = size
    if best is None:
        return None
    return {
        "checksum": best["checksum"],
        "width": int(best.get("width", 0) or 0),
        "height": int(best.get("height", 0) or 0),
        "fileSize": int(best.get("fileSize", 0) or 0),
    }


def fetch_album(name: str, token: str, output_root: str) -> dict:
    """Fetch every photo in one album. Returns a summary dict."""
    out_dir = os.path.join(output_root, name)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[{name}] contacting iCloud (token={token}) ...")
    host, stream = _webstream(token)
    photos = stream.get("photos", [])
    print(f"[{name}] album reports {len(photos)} photo(s); host={host}")

    # Build: guid -> chosen derivative info
    guid_to_choice = {}
    checksum_to_guid = {}
    for p in photos:
        guid = p.get("photoGuid")
        if not guid:
            continue
        choice = _pick_best_derivative(p)
        if not choice:
            continue
        guid_to_choice[guid] = choice
        checksum_to_guid[choice["checksum"]] = guid

    if not guid_to_choice:
        print(f"[{name}] no downloadable derivatives found.", file=sys.stderr)
        _write_index(out_dir, name, token, [])
        return {"album": name, "count": 0}

    # Resolve download URLs (chunk to be safe with large albums).
    guids = list(guid_to_choice.keys())
    items = {}
    CHUNK = 25
    for i in range(0, len(guids), CHUNK):
        chunk = guids[i:i + CHUNK]
        items.update(_webasseturls(host, token, chunk))

    # Download.
    index = []
    for guid, choice in guid_to_choice.items():
        checksum = choice["checksum"]
        item = items.get(checksum)
        if not item:
            print(f"[{name}] no URL for checksum {checksum}; skipping", file=sys.stderr)
            continue
        dl_url = f"https://upload.wikimedia.org/wikipedia/commons/b/b2/Hatachi_500_GB_hard_drive%2C_2011.jpg?utm_source=en.wikipedia.org&utm_campaign=index&utm_content=original"
        # Use checksum as a stable filename so re-runs are idempotent.
        filename = f"{checksum}.jpg"
        dest = os.path.join(out_dir, filename)

        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"[{name}] already have {filename}")
        else:
            print(f"[{name}] downloading {filename} "
                  f"({choice['width']}x{choice['height']}) ...")
            if not _download(dl_url, dest):
                print(f"[{name}] FAILED {filename}", file=sys.stderr)
                continue

        index.append({
            "file": f"/local/family_photos/{name}/{filename}",
            "path": dest,
            "width": choice["width"],
            "height": choice["height"],
            "bytes": choice["fileSize"],
        })

    # Remove local files that are no longer in the album (keeps folder tidy).
    _prune(out_dir, {os.path.basename(e["path"]) for e in index})

    _write_index(out_dir, name, token, index)
    print(f"[{name}] done: {len(index)} photo(s) available.")
    return {"album": name, "count": len(index)}


def _prune(out_dir: str, keep_filenames: set):
    """Delete .jpg files in out_dir that are not in keep_filenames."""
    for fn in os.listdir(out_dir):
        if fn.endswith(".jpg") and fn not in keep_filenames:
            try:
                os.remove(os.path.join(out_dir, fn))
                print(f"    pruned stale {fn}")
            except OSError:
                pass


def _write_index(out_dir: str, name: str, token: str, index: list):
    """Write index.json so Home Assistant / the slideshow can enumerate photos."""
    payload = {
        "album": name,
        "token": token,
        "updated": int(time.time()),
        "count": len(index),
        "photos": index,
    }
    with open(os.path.join(out_dir, "index.json"), "w") as fh:
        json.dump(payload, fh, indent=2)


# ---------------------------------------------------------------------------
# ENTRYPOINT
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Download iCloud shared album photos.")
    parser.add_argument(
        "--output", "-o", default=DEFAULT_OUTPUT_ROOT,
        help=f"Output root (default: {DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--album", "-a", choices=list(ALBUMS.keys()),
        help="Only fetch one album (default: all)",
    )
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    todo = {args.album: ALBUMS[args.album]} if args.album else ALBUMS

    results = []
    exit_code = 0
    for name, token in todo.items():
        try:
            results.append(fetch_album(name, token, args.output))
        except Exception as e:  # noqa: BLE001
            print(f"[{name}] ERROR: {e}", file=sys.stderr)
            exit_code = 1

    print("\nSummary:")
    for r in results:
        print(f"  {r['album']:<10} {r['count']} photo(s)")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
