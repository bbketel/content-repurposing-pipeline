"""
youtube_fetcher.py

Fetches the transcript from a YouTube video URL and returns clean plain text
by downloading subtitles (manual or auto-generated) via yt-dlp and stripping
all timestamps and formatting markup.
"""

import sys
import re
import json
import urllib.request
import urllib.error

import yt_dlp


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 15
MIN_CONTENT_CHARS = 100

# Subtitle format preference order (json3 is YouTube-native, cleanest)
_FORMAT_PREFS = ["json3", "vtt", "srt"]

# English language variants to try, in priority order
_LANG_PREFS = ["en", "en-US", "en-GB", "en-orig"]


# ---------------------------------------------------------------------------
# Subtitle parsers
# ---------------------------------------------------------------------------

def _parse_json3(data: str) -> str:
    """Extract plain text from YouTube's json3 subtitle format.

    json3 is YouTube's native caption format -- each event has a list of
    text segments ('segs'), giving us clean text without rolling-caption
    duplication artifacts.
    """
    obj = json.loads(data)
    parts = []
    for event in obj.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(seg.get("utf8", "") for seg in segs)
        parts.append(text)
    return "".join(parts)


def _parse_vtt(vtt: str) -> str:
    """Extract plain text from a WebVTT subtitle string."""
    lines = []
    for line in vtt.splitlines():
        line = line.strip()
        # Skip WEBVTT header and metadata lines
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        # Skip timestamp lines (may have trailing position attributes)
        if re.match(r"[\d:\.]+\s*-->\s*[\d:\.]+", line):
            continue
        # Skip bare cue-identifier numbers
        if re.match(r"^\d+$", line):
            continue
        # Strip VTT inline tags: <c>, <b>, <i>, <00:00:00.000>, etc.
        line = re.sub(r"<[^>]+>", "", line)
        lines.append(line)
    return "\n".join(lines)


def _parse_srt(srt: str) -> str:
    """Extract plain text from an SRT subtitle string."""
    lines = []
    for line in srt.splitlines():
        line = line.strip()
        # Skip sequence numbers
        if re.match(r"^\d+$", line):
            continue
        # Skip timestamp lines
        if re.match(r"[\d:,]+\s*-->\s*[\d:,]+", line):
            continue
        # Strip HTML-like tags sometimes present in SRT
        line = re.sub(r"<[^>]+>", "", line)
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def _clean_transcript(raw: str) -> str:
    """Deduplicate consecutive identical lines and normalise whitespace.

    YouTube auto-captions use a rolling display style that causes adjacent
    cues to repeat the previous line -- deduplication removes those artifacts.
    """
    # Deduplicate consecutive identical lines
    lines = raw.splitlines()
    deduped: list[str] = []
    prev = object()  # sentinel -- never equals any real string
    for line in lines:
        if line != prev:
            deduped.append(line)
            prev = line

    # Collapse horizontal whitespace; cap consecutive blank lines at one
    cleaned: list[str] = []
    blank_run = 0
    for line in deduped:
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line == "":
            blank_run += 1
            if blank_run <= 1:
                cleaned.append(line)
        else:
            blank_run = 0
            cleaned.append(line)

    return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# Network fetch
# ---------------------------------------------------------------------------

def fetch_transcript(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    """
    Fetch the transcript of a YouTube video at *url* and return clean plain text.

    Raises:
        ValueError   -- non-YouTube URL or no transcript available
        TimeoutError -- request timed out
        RuntimeError -- yt-dlp error (private/removed/unavailable video)
        OSError      -- network-level failure
    """

    # --- 1. Validate URL ---------------------------------------------------
    if not re.search(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)", url):
        raise ValueError(f"URL does not appear to be a YouTube video: {url!r}")

    # --- 2. Extract info via yt-dlp ----------------------------------------
    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": _LANG_PREFS,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": timeout,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc).lower()
        if "timed out" in msg or "timeout" in msg:
            raise TimeoutError(f"Request timed out fetching transcript for: {url}") from exc
        if any(k in msg for k in ("private", "removed", "unavailable", "404")):
            raise RuntimeError(f"Video unavailable: {exc}") from exc
        raise RuntimeError(f"yt-dlp error fetching {url}: {exc}") from exc
    except OSError as exc:
        raise OSError(f"Network error fetching transcript for {url}: {exc}") from exc

    # --- 3. Select a subtitle track ----------------------------------------
    subtitles = info.get("subtitles") or {}
    auto_captions = info.get("automatic_captions") or {}

    # Prefer manual subtitles over auto-captions, then English variants
    sub_formats = None
    for lang in _LANG_PREFS:
        if lang in subtitles:
            sub_formats = subtitles[lang]
            break

    if sub_formats is None:
        for lang in _LANG_PREFS:
            if lang in auto_captions:
                sub_formats = auto_captions[lang]
                break

    if sub_formats is None:
        # Last resort: any available manual subtitle language
        for fmts in subtitles.values():
            sub_formats = fmts
            break

    if sub_formats is None:
        raise ValueError(
            f"No transcript available for: {url}\n"
            "The video may have captions disabled or none in English."
        )

    # --- 4. Pick the best available format ---------------------------------
    sub_url: str | None = None
    sub_ext: str = "vtt"

    for pref in _FORMAT_PREFS:
        for fmt in sub_formats:
            if fmt.get("ext") == pref:
                sub_url = fmt["url"]
                sub_ext = pref
                break
        if sub_url:
            break

    if sub_url is None and sub_formats:
        sub_url = sub_formats[0].get("url")
        sub_ext = sub_formats[0].get("ext", "vtt")

    if not sub_url:
        raise ValueError(f"No usable subtitle URL found for: {url}")

    # --- 5. Download the subtitle file -------------------------------------
    req = urllib.request.Request(
        sub_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; youtube-fetcher/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw_bytes = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                raw_text = raw_bytes.decode(charset)
            except (UnicodeDecodeError, LookupError):
                raw_text = raw_bytes.decode("latin-1")
    except urllib.error.URLError as exc:
        reason = exc.reason
        if "timed out" in str(reason).lower():
            raise TimeoutError(f"Timed out downloading subtitle file for: {url}") from exc
        raise OSError(f"Network error downloading subtitle: {reason}") from exc

    # --- 6. Parse to plain text --------------------------------------------
    if sub_ext == "json3":
        parsed = _parse_json3(raw_text)
    elif sub_ext == "srt":
        parsed = _parse_srt(raw_text)
    else:
        parsed = _parse_vtt(raw_text)

    # --- 7. Clean and validate ---------------------------------------------
    clean = _clean_transcript(parsed)

    non_ws_chars = len(re.sub(r"\s", "", clean))
    if non_ws_chars < MIN_CONTENT_CHARS:
        raise ValueError(
            f"Transcript contains too little text ({non_ws_chars} non-whitespace chars). "
            "The video may have no meaningful captions."
        )

    return clean


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) != 2:
        print("Usage: python youtube_fetcher.py <url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]

    try:
        text = fetch_transcript(url)
        print(text)
    except TimeoutError as exc:
        print(f"[timeout] {exc}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as exc:
        print(f"[http error] {exc}", file=sys.stderr)
        sys.exit(3)
    except ValueError as exc:
        print(f"[content error] {exc}", file=sys.stderr)
        sys.exit(4)
    except OSError as exc:
        print(f"[network error] {exc}", file=sys.stderr)
        sys.exit(5)


if __name__ == "__main__":
    main()
