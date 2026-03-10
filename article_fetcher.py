"""
article_fetcher.py

Fetches a web page from a given URL and returns clean article body text
by stripping all HTML tags, filtering out non-meaningful content, and
applying a content-start heuristic to skip nav/promo noise at the top
of the page (e.g. TechCrunch site menus, event banners, tag clouds).
"""

import sys
import re
import urllib.request
import urllib.error
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Collect visible text while skipping script/style blocks."""

    # Tags whose entire subtree (including text) we want to discard
    SKIP_TAGS = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0   # nesting depth inside a SKIP_TAG subtree
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _strip_html(html: str) -> str:
    """Parse HTML and return the concatenated visible text."""
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.get_text()


def _clean_text(raw: str) -> str:
    """
    Normalise whitespace so the result is human-readable:
      • collapse runs of spaces/tabs into a single space
      • collapse more than two consecutive blank lines into one blank line
      • strip leading/trailing whitespace from every line
    """
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        lines.append(line)

    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 1:
                cleaned.append(line)
        else:
            blank_run = 0
            cleaned.append(line)

    return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# Content-start heuristic
# ---------------------------------------------------------------------------

# Patterns that signal "we are now at the article metadata block" —
# i.e. the byline or datestamp that appears just before the article body.
#
# re.IGNORECASE means upper/lowercase doesn't matter.
# re.VERBOSE means we can add comments inside the pattern (after #).
_BYLINE_RE = re.compile(
    r"""
    (                           # group 1 — any of these alternatives:
      \bby\s+[A-Z][a-z]+        #   "by Firstname" (capital first letter)
    | \b(Jan|Feb|Mar|Apr|May    #   month abbreviation
        |Jun|Jul|Aug|Sep|Oct
        |Nov|Dec)\b
    | \b\d{4}-\d{2}-\d{2}\b    #   ISO date  2025-01-05
    | \b(January|February       #   full month name
        |March|April|May|June
        |July|August|September
        |October|November
        |December)\s+\d{1,2}
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# How far into the cleaned text (in characters) we bother looking for signals.
# Nav/promo noise is almost always within the first 3000 chars.
_SEARCH_WINDOW = 3000

# A "substantive" line is one long enough to be a real sentence, not a nav label.
_MIN_SUBSTANTIVE_LINE = 150


def _find_content_start(text: str) -> str:
    """
    Scan the first _SEARCH_WINDOW characters of *text* looking for signals
    that mark the boundary between page furniture (nav, promo, menus) and
    real article content.

    Strategy (in priority order):
      1. Byline / datestamp pattern — slice from the line AFTER the signal.
      2. First line longer than _MIN_SUBSTANTIVE_LINE chars — slice from there.
      3. No signal found — return text unchanged (safe fallback).
    """
    # Work only on the lines that fall inside the search window.
    # We track a running character count so we know when we've passed
    # _SEARCH_WINDOW chars of source text.
    lines = text.splitlines()
    char_count = 0
    signal_index = None          # line index where a byline/date was found
    substantive_index = None     # line index of first long paragraph line

    for i, line in enumerate(lines):
        char_count += len(line) + 1   # +1 for the newline character

        # Stop scanning once we're past the search window
        if char_count > _SEARCH_WINDOW:
            break

        # --- Signal 1: byline or date pattern ---
        if signal_index is None and _BYLINE_RE.search(line):
            # The signal line itself is metadata (e.g. "by Sarah Perez  •  Jan 5")
            # so we want to start from the line AFTER it.
            signal_index = i + 1

        # --- Signal 2: first substantive paragraph line ---
        if substantive_index is None and len(line) >= _MIN_SUBSTANTIVE_LINE:
            substantive_index = i

    # --- Apply whichever signal fired first, preferring the byline ---
    if signal_index is not None and signal_index < len(lines):
        return "\n".join(lines[signal_index:]).strip()

    if substantive_index is not None:
        return "\n".join(lines[substantive_index:]).strip()

    # --- Fallback: no signal found, return unchanged ---
    return text


# ---------------------------------------------------------------------------
# Network fetch
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 15
MIN_CONTENT_CHARS = 100


def fetch_article(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    """
    Fetch *url*, strip HTML, apply content-start heuristic, and return
    clean article text.

    Raises:
        ValueError   – bad URL scheme or no meaningful text found
        TimeoutError – server did not respond within *timeout* seconds
        RuntimeError – non-200 HTTP response
        OSError      – any other network-level failure
    """

    # --- 1. Validate the URL scheme ----------------------------------------
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must start with http:// or https:// — got: {url!r}")

    # --- 2. Build request with browser-like User-Agent ---------------------
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; article-fetcher/1.0)"},
    )

    # --- 3. Fetch the page -------------------------------------------------
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.status
            if status != 200:
                raise RuntimeError(f"Server returned HTTP {status} for URL: {url}")

            raw_bytes = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                html = raw_bytes.decode(charset)
            except (UnicodeDecodeError, LookupError):
                html = raw_bytes.decode("latin-1")

    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP error {exc.code} fetching {url}: {exc.reason}") from exc

    except urllib.error.URLError as exc:
        reason = exc.reason
        if "timed out" in str(reason).lower():
            raise TimeoutError(f"Request timed out after {timeout}s fetching {url}") from exc
        raise OSError(f"Network error fetching {url}: {reason}") from exc

    # --- 4. Strip HTML and normalise whitespace ----------------------------
    raw_text = _strip_html(html)
    clean = _clean_text(raw_text)

    # --- 5. Apply content-start heuristic to remove nav/promo noise -------
    clean = _find_content_start(clean)

    # --- 6. Reject pages with no meaningful text content ------------------
    non_ws_chars = len(re.sub(r"\s", "", clean))
    if non_ws_chars < MIN_CONTENT_CHARS:
        raise ValueError(
            f"Page contains too little text ({non_ws_chars} non-whitespace chars). "
            "It may be a JavaScript-only SPA or a redirect page."
        )

    return clean


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) != 2:
        print("Usage: python article_fetcher.py <url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]

    try:
        text = fetch_article(url)
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