"""
Facebook GraphQL response extractor.
Parses intercepted /api/graphql/ POST responses to extract post data.

Facebook search results use serpResponse with SearchPostViewModel structure.
Data is deeply nested — we walk the graph and deduplicate by URL.

Verified JSON paths (reverse-engineered 2026-05-23):
  data.serpResponse.results.edges[*].rendering_strategy.view_model.click_model.story
    .permalink_url                                       → post URL
    .actors[0].name                                      → author name
    .comet_sections.timestamp.story.creation_time        → unix epoch
    .comet_sections.content.story.comet_sections.message
       .story.message.text                               → post text
  Engagement (recursive search anywhere in story):
    reaction_count.count
    comments.total_count
    share_count.count
"""
from __future__ import annotations
import re
from datetime import datetime
from typing import Any


# ── Field name constants ──────────────────────────────────────────────────────

_FB_POST_URL_RE = re.compile(
    r"https://(?:www\.|m\.)?facebook\.com/"
    r"[A-Za-z0-9_./@\-]+"
    r"(?:pfbid|/posts/|story_fbid=|/videos/|/photos/|/reel/|permalink\.php)"
    r"[A-Za-z0-9_./?=&%\-]*",
    re.IGNORECASE,
)


# ── Safe access ────────────────────────────────────────────────────────────────

def _get(obj: Any, *keys, default=None) -> Any:
    """Safe deep access. _get(d, 'a', 'b', 0, 'c') → d['a']['b'][0]['c']."""
    cur = obj
    for k in keys:
        if cur is None:
            return default
        try:
            cur = cur[k]
        except (KeyError, IndexError, TypeError):
            return default
    return cur if cur is not None else default


def _is_fb_post_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    return bool(_FB_POST_URL_RE.search(url))


# ── Recursive engagement finder ───────────────────────────────────────────────

def _find_engagement(obj: Any, depth: int = 0, _max: int = 20) -> tuple[int, int, int]:
    """Return (reactions, comments, shares) — recursively searches the whole tree."""
    if depth > _max:
        return 0, 0, 0
    r = c = s = 0
    if isinstance(obj, dict):
        rc = _get(obj, "reaction_count", "count")
        if isinstance(rc, int) and rc > r:
            r = rc
        arc = _get(obj, "cross_universe_feedback_info", "aggregated_reaction_count")
        if isinstance(arc, int) and arc > r:
            r = arc

        cc = _get(obj, "comments", "total_count")
        if isinstance(cc, int) and cc > c:
            c = cc
        acc = _get(obj, "cross_universe_feedback_info", "aggregated_comment_count")
        if isinstance(acc, int) and acc > c:
            c = acc

        sc = _get(obj, "share_count", "count")
        if isinstance(sc, int) and sc > s:
            s = sc

        for v in obj.values():
            if isinstance(v, (dict, list)):
                sr, sc2, ss = _find_engagement(v, depth + 1, _max)
                r = max(r, sr)
                c = max(c, sc2)
                s = max(s, ss)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                sr, sc2, ss = _find_engagement(item, depth + 1, _max)
                r = max(r, sr)
                c = max(c, sc2)
                s = max(s, ss)
    return r, c, s


# ── Text extraction helper ────────────────────────────────────────────────────

def _extract_text_deep(obj: Any, depth: int = 0, _max: int = 15) -> str:
    """
    Recursively find the longest 'text' field that looks like post content.
    Skips URLs and very short strings.
    """
    if depth > _max:
        return ""
    if isinstance(obj, dict):
        direct = obj.get("text", "")
        if isinstance(direct, str) and len(direct) > 20 and not direct.startswith("http"):
            return direct
        best = ""
        for v in obj.values():
            if isinstance(v, (dict, list)):
                t = _extract_text_deep(v, depth + 1, _max)
                if len(t) > len(best):
                    best = t
        return best
    elif isinstance(obj, list):
        best = ""
        for item in obj:
            t = _extract_text_deep(item, depth + 1, _max)
            if len(t) > len(best):
                best = t
        return best
    return ""


# ── Single story parser ───────────────────────────────────────────────────────

def _parse_story(story: dict) -> dict | None:
    """
    Parse a Story object from serpResponse edges into a post dict.

    Exact paths verified against real FB responses 2026-05-23.
    """
    # ── URL ─────────────────────────────────────────────────────────────────
    url = story.get("permalink_url", "")
    if not _is_fb_post_url(url):
        # Fallback: look inside comet_sections.timestamp.story.url
        url = _get(story, "comet_sections", "timestamp", "story", "url") or ""
    if not url:
        return None

    # ── Author ─────────────────────────────────────────────────────────────
    actors = story.get("actors", [])
    source = ""
    if isinstance(actors, list) and actors:
        a = actors[0]
        if isinstance(a, dict):
            source = a.get("name") or a.get("short_name") or ""
            source = source[:80]
    if not source:
        # Fallback: owning_profile in feedback
        source = _get(story, "feedback", "owning_profile", "name") or ""
        source = source[:80]

    # ── Timestamp ───────────────────────────────────────────────────────────
    ts_dt: datetime | None = None
    ts_raw = ""
    ctime = _get(story, "comet_sections", "timestamp", "story", "creation_time")
    if isinstance(ctime, int) and ctime > 0:
        ts_raw = str(ctime)
        try:
            ts_dt = datetime.fromtimestamp(ctime)
        except Exception:
            pass

    # ── Post text ────────────────────────────────────────────────────────────
    # Primary path:
    # comet_sections.content.story.comet_sections.message.story.message.text
    text = _get(
        story,
        "comet_sections", "content",
        "story", "comet_sections",
        "message", "story",
        "message", "text",
    )
    if not isinstance(text, str) or len(text) < 10:
        # Fallback A: sometimes the inner story is one level shallower
        text = _get(
            story,
            "comet_sections", "content",
            "story", "message", "text",
        )
    if not isinstance(text, str) or len(text) < 10:
        # Fallback B: recursive search for any 'text' field with real content
        text = _extract_text_deep(
            _get(story, "comet_sections", "content") or {}
        )
    if not isinstance(text, str) or len(text) < 10:
        # Fallback C: search entire story tree
        text = _extract_text_deep(story)
    if not isinstance(text, str):
        text = ""

    # ── Engagement ───────────────────────────────────────────────────────────
    reactions, comments_count, shares = _find_engagement(
        _get(story, "comet_sections", "feedback") or story
    )

    return {
        "url":            url,
        "text":           text[:5000],
        "source":         source,
        "timestamp_raw":  ts_raw,
        "timestamp":      ts_dt.isoformat() if ts_dt else None,
        "reactions":      reactions,
        "comments_count": comments_count,
        "shares":         shares,
    }


# ── serpResponse extractor ────────────────────────────────────────────────────

def _extract_from_serp_edges(edges: list) -> list[dict]:
    """
    Extract posts from serpResponse.results.edges array.
    Each edge → rendering_strategy.view_model.click_model.story
    """
    posts: list[dict] = []
    for edge in edges:
        try:
            story = _get(edge,
                         "rendering_strategy", "view_model",
                         "click_model", "story")
            if not isinstance(story, dict):
                continue
            post = _parse_story(story)
            if post:
                posts.append(post)
        except Exception:
            continue
    return posts


# ── Fallback: walk all dicts looking for story-like nodes ─────────────────────

def _walk_all_dicts(obj: Any, depth: int = 0, _max: int = 25) -> list[dict]:
    """Return all dict objects in a JSON tree."""
    if depth > _max:
        return []
    result = []
    if isinstance(obj, dict):
        result.append(obj)
        for v in obj.values():
            result.extend(_walk_all_dicts(v, depth + 1, _max))
    elif isinstance(obj, list):
        for item in obj:
            result.extend(_walk_all_dicts(item, depth + 1, _max))
    return result


def _extract_fallback(json_data: dict) -> list[dict]:
    """
    Walk the entire JSON tree looking for objects with:
      - a FB post URL (permalink_url or url)
      - a creation_time
    Used when the response does not follow the serpResponse layout.
    """
    posts: list[dict] = []
    seen_urls: set[str] = set()
    for node in _walk_all_dicts(json_data, _max=25):
        try:
            url = node.get("permalink_url") or node.get("url", "")
            if not _is_fb_post_url(url):
                continue
            ctime = node.get("creation_time")
            if not isinstance(ctime, int) or ctime <= 0:
                continue
            # Looks like a story node
            key = url
            if key in seen_urls:
                continue
            seen_urls.add(key)

            actors = node.get("actors", [])
            source = ""
            if isinstance(actors, list) and actors and isinstance(actors[0], dict):
                source = actors[0].get("name") or actors[0].get("short_name") or ""

            text = _extract_text_deep(node)
            reactions, comments_count, shares = _find_engagement(node)

            posts.append({
                "url":            url,
                "text":           text[:5000],
                "source":         source[:80],
                "timestamp_raw":  str(ctime),
                "timestamp":      datetime.fromtimestamp(ctime).isoformat(),
                "reactions":      reactions,
                "comments_count": comments_count,
                "shares":         shares,
            })
        except Exception:
            continue
    return posts


# ── Public API ────────────────────────────────────────────────────────────────

def extract_posts_from_graphql(json_data: dict) -> list[dict]:
    """
    Parse a single Facebook /api/graphql/ JSON response and extract post data.

    Primary: serpResponse.results.edges  (search pages)
    Fallback: recursive scan for creation_time + fb_url nodes

    Returns list of dicts with keys:
      url, text, source, timestamp_raw, timestamp, reactions, comments_count, shares

    Never crashes.
    """
    if not isinstance(json_data, dict):
        return []

    seen_urls: set[str] = set()
    posts: list[dict] = []

    def _add(p: dict | None) -> None:
        if not p:
            return
        key = p.get("url") or p.get("text", "")[:100]
        if not key or key in seen_urls:
            return
        seen_urls.add(key)
        posts.append(p)

    # ── Path 1: serpResponse (search results) ────────────────────────────────
    try:
        edges = _get(json_data, "data", "serpResponse", "results", "edges")
        if isinstance(edges, list) and edges:
            for p in _extract_from_serp_edges(edges):
                _add(p)
    except Exception:
        pass

    # ── Path 2: fallback — walk entire tree ──────────────────────────────────
    if not posts:
        try:
            for p in _extract_fallback(json_data):
                _add(p)
        except Exception:
            pass

    return posts


def parse_fb_graphql_body(body_bytes: bytes) -> list[dict]:
    """
    Entry point for raw response bytes from the network intercept.
    Handles: single JSON, streaming NDJSON (multiple objects per response).
    Returns merged, deduplicated post list.
    Never crashes.
    """
    import json

    all_posts: list[dict] = []
    seen_urls: set[str] = set()

    def _try_add(data: dict) -> None:
        for p in extract_posts_from_graphql(data):
            key = p.get("url") or p.get("text", "")[:100]
            if key and key not in seen_urls:
                seen_urls.add(key)
                all_posts.append(p)

    try:
        text = body_bytes.decode("utf-8", errors="replace")
    except Exception:
        return []

    # Try parsing whole body first (most common)
    try:
        data = json.loads(text)
        _try_add(data)
        return all_posts
    except Exception:
        pass

    # Fallback: line-by-line NDJSON
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] not in ('{', '['):
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                _try_add(data)
        except Exception:
            continue

    return all_posts
