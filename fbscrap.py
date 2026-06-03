#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   FBSCRAP — Social Media Threat Intelligence Platform               ║
║   ◈ NULLSEC RED TEAM  ·  Open-Source OSINT Framework               ║
║   Modes: login | page | search | comments | discover | full          ║
╚══════════════════════════════════════════════════════════════════════╝

Usage:
  fbscrap.py login
  fbscrap.py page    [--targets FILE] [--days N] [--out DIR]
  fbscrap.py search  --query QUERY [--days N] [--out DIR]
  fbscrap.py comments --url URL [--url URL ...] [--max-comments N]
  fbscrap.py discover --names "Page1,Page2" | --targets FILE
  fbscrap.py full    --query QUERY [--targets FILE] [--days N] [--top N]
  fbscrap.py report  --data FILE [--top N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# ── Banner ────────────────────────────────────────────────────────────────────

_BANNER = r"""
  ███████╗██████╗ ███████╗ ██████╗██████╗  █████╗ ██████╗
  ██╔════╝██╔══██╗██╔════╝██╔════╝██╔══██╗██╔══██╗██╔══██╗
  █████╗  ██████╔╝███████╗██║     ██████╔╝███████║██████╔╝
  ██╔══╝  ██╔══██╗╚════██║██║     ██╔══██╗██╔══██║██╔═══╝
  ██║     ██████╔╝███████║╚██████╗██║  ██║██║  ██║██║
  ╚═╝     ╚═════╝ ╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝

  ◈ NULLSEC RED TEAM  ·  Social Media Threat Intelligence Platform
  ─────────────────────────────────────────────────────────────────
  Open-Source OSINT  ·  CIB Detection  ·  Forensic Analysis  ·  v2.0
"""

BASE_DIR         = Path(__file__).parent
CONFIG_FILE      = BASE_DIR / "config.json"
DEFAULT_CFG_FILE = BASE_DIR / "config" / "default_config.json"
SESSIONS_DIR     = BASE_DIR / "sessions"


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """
    Config cascade (highest priority wins):
      1. Environment variables  FBSCRAP_<SECTION>_<KEY>=value
      2. config.json            user overrides
      3. config/default_config.json  shipped defaults (always present)

    Raises RuntimeError if default config is missing — never silently runs
    with an empty config.
    """
    import os, copy

    if not DEFAULT_CFG_FILE.exists():
        raise RuntimeError(
            f"[FATAL] Default config not found: {DEFAULT_CFG_FILE}\n"
            "Run from the fbscrap directory or restore config/default_config.json."
        )

    cfg: dict = json.loads(DEFAULT_CFG_FILE.read_text(encoding="utf-8"))

    # Strip internal _meta keys
    for k in list(cfg):
        if k.startswith("_"):
            cfg.pop(k)

    # Merge user overrides (config.json) — deep merge one level
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for section, values in user.items():
                if isinstance(values, dict) and isinstance(cfg.get(section), dict):
                    cfg[section] = {**cfg[section], **values}
                else:
                    cfg[section] = values
        except Exception as e:
            print(f"  [WARN] config.json parse error — using defaults: {e}", file=sys.stderr)

    # Resolve pattern file paths relative to BASE_DIR
    for section in cfg.values():
        if not isinstance(section, dict):
            continue
        for key, val in section.items():
            if key.endswith("_file") and isinstance(val, str) and not Path(val).is_absolute():
                section[key] = str(BASE_DIR / val)

    return cfg


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fbscrap",
        description="FBSCRAP — Social Media Threat Intelligence Platform | NULLSEC RED TEAM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
MODES:
  login     Open browser for manual Facebook login (saves persistent session)
  page      Scrape posts from target Facebook pages (last N days)
  search    Search Facebook for keyword posts (last N days)
  comments  Deep-scrape all comments on specific post URLs
  discover  Find Facebook page URLs for given media/organization names
  full      Run page + search + sentiment analysis + HTML report in one pass
  report    Generate report from existing JSON data file (no browser needed)

EXAMPLES:
  # First time: save your FB session
  python3 fbscrap.py login

  # Scrape pages from a target list
  python3 fbscrap.py page --targets targets/example_pages.json --days 7 --sentiment

  # Search Facebook for a keyword
  python3 fbscrap.py search --query "John Smith" --days 7 --sentiment

  # Scrape comments on specific posts
  python3 fbscrap.py comments --url "https://www.facebook.com/.../posts/..." --max-comments 500

  # Find FB pages for a list of media/org names
  python3 fbscrap.py discover --names "Page1,Page2,Page3"

  # Full analysis: all sources + search + sentiment + report
  python3 fbscrap.py full --query "target name" --targets targets/example_pages.json --days 7 --top 30

  # Scrape specific post URLs directly (forensic evidence collection)
  python3 fbscrap.py direct --url "https://www.facebook.com/.../posts/..." --max-comments 300

  # Re-generate report from saved session data
  python3 fbscrap.py report --data sessions/target_name/20260101_120000/posts_latest.json --top 30

  # Compare two sessions to detect campaign evolution
  python3 fbscrap.py delta --delta-before sessions/target/20260101/ --delta-after sessions/target/20260108/

  # Continuous monitoring with alerts
  python3 fbscrap.py monitor --query "target name" --monitor-interval 300

  # List all recorded sessions
  python3 fbscrap.py sessions
        """,
    )

    p.add_argument(
        "mode",
        choices=["login", "page", "search", "comments", "discover", "full", "report", "diagnose", "sessions", "direct", "monitor", "delta"],
        help="Operation mode ('sessions' lists all recorded sessions)",
    )

    # ── Target options ────────────────────────────────────────────────────────
    g_target = p.add_argument_group("Target Options")
    g_target.add_argument("--targets", "-t", metavar="FILE",
                          help="JSON file with target FB pages (default: targets/example_pages.json)")
    g_target.add_argument("--query", "-q", metavar="QUERY", action="append", dest="queries",
                          help="Search query (repeatable: --query 'Target A' --query 'Target B'). "
                               "Comma-separated also works: --query 'Target A,Target B'")
    g_target.add_argument("--url", "-u", metavar="URL", action="append", dest="urls",
                          help="Facebook post URL(s) — repeatable (comments/direct mode)")
    g_target.add_argument("--sources", metavar="PAGE1,PAGE2,...",
                          help="Comma-separated extra page handles/names for multi-source analysis "
                               "(combined with --targets for cross-page CIB detection)")
    g_target.add_argument("--names", "-n", metavar="NAMES",
                          help="Comma-separated media names for discover mode")
    g_target.add_argument("--filter", metavar="NAMES",
                          help="Only scrape/diagnose targets whose name contains these comma-separated strings (case-insensitive)")

    # ── Filter options ────────────────────────────────────────────────────────
    g_filter = p.add_argument_group("Filter Options")
    g_filter.add_argument("--days", "-d", type=int, default=7, metavar="N",
                          help="Days back to scrape (default: 7)")
    g_filter.add_argument("--max-posts", type=int, default=200, metavar="N",
                          help="Max posts per page/query (default: 200)")
    g_filter.add_argument("--max-comments", type=int, default=300, metavar="N",
                          help="Max comments per post (default: 300)")
    g_filter.add_argument("--min-engagement", type=int, default=0, metavar="N",
                          help="Minimum engagement (reactions+comments+shares) to include")
    g_filter.add_argument("--keywords", "-k", metavar="WORDS",
                          help="Comma-separated keywords to filter posts (page mode)")
    g_filter.add_argument("--loose-match", action="store_true",
                          help="ELITE: Enable semantic expansion for person names (initials, titles, variations)")
    g_filter.add_argument("--top", type=int, default=50, metavar="N",
                          help="Top N posts for report (default: 50)")

    # ── Analysis options ──────────────────────────────────────────────────────
    g_analysis = p.add_argument_group("Analysis Options")
    g_analysis.add_argument(
        "--sentiment", "-s",
        nargs="?", const="negative", default=None,
        metavar="MODE",
        choices=["negative", "positive", "neutral", "aggressive", "all"],
        help=(
            "Sentiment analysis mode targeting COMMENTS (text fallback).\n"
            "  negative   — hate, corruption, insults (default)\n"
            "  aggressive — threats, violence, extreme profanity\n"
            "  positive   — support, victim defense\n"
            "  neutral    — balanced / informational\n"
            "  all        — analyze + show all labels\n"
            "Combine with --comments-on-top N for real comment analysis."
        ),
    )
    g_analysis.add_argument("--top-per-source", type=int, default=100, metavar="N",
                            help="Keep top N posts per source ranked by negativity+engagement (default: 100)")
    g_analysis.add_argument("--comments-on-top", type=int, default=50, metavar="N",
                            help="After page/search scrape, deep-scrape TOP N posts' comments (default: 50)")

    # ── Output options ────────────────────────────────────────────────────────
    g_out = p.add_argument_group("Output Options")
    g_out.add_argument("--out", "-o", metavar="DIR", default=None,
                       help="Output directory (default: sessions/<query-slug>/<timestamp>/)")
    g_out.add_argument("--format", "-f", choices=["json", "csv", "html", "docx", "all"],
                       default="all", help="Output format (default: all)")
    g_out.add_argument("--data", metavar="FILE",
                       help="Existing data file for report mode")
    g_out.add_argument("--no-banner", action="store_true",
                       help="Suppress ASCII banner")

    # ── Monitor / Delta options ───────────────────────────────────────────────
    g_mon = p.add_argument_group("Monitor / Delta Options")
    g_mon.add_argument("--monitor-interval", type=int, default=300, metavar="N",
                       help="Monitor mode: polling interval in seconds (default: 300)")
    g_mon.add_argument("--monitor-cycles", type=int, default=0, metavar="N",
                       help="Monitor mode: max cycles to run, 0 = infinite (default: 0)")
    g_mon.add_argument("--delta-before", metavar="DIR",
                       help="Delta mode: path to previous session dir to compare against")
    g_mon.add_argument("--delta-after", metavar="DIR",
                       help="Delta mode: path to current session dir (defaults to latest)")

    # ── Browser options ───────────────────────────────────────────────────────
    g_browser = p.add_argument_group("Browser Options")
    g_browser.add_argument("--headless", action="store_true",
                           help="Run browser headless (not recommended for Facebook)")
    g_browser.add_argument("--profile", metavar="DIR",
                           help="Custom browser profile directory (overrides config)")
    g_browser.add_argument("--slow-mo", type=int, default=None, metavar="MS",
                           help="Slow browser actions by N ms (helps avoid detection)")
    g_browser.add_argument("--concurrent", type=int, default=1, metavar="N",
                           help="Concurrent page scrapers — keep at 1 for safety (default: 1)")
    g_browser.add_argument("--verbose", "-v", action="store_true",
                           help="Verbose debug output (scroll counts, article counts, parse errors)")

    return p


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_targets(targets_file: str | None, cfg: dict) -> list[dict]:
    candidates = [
        targets_file,
        cfg.get("default_targets_file"),
        str(BASE_DIR / "targets" / "example_pages.json"),
    ]
    for c in candidates:
        if c:
            f = Path(c)
            if f.exists():
                data = json.loads(f.read_text())
                return data.get("targets", data) if isinstance(data, dict) else data
    print("[!] No targets file found — use --targets or run 'discover' first", file=sys.stderr)
    return []


def _parse_csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _resolve_queries(args: argparse.Namespace) -> list[str]:
    """
    Normalize --query into a clean deduplicated list.
    Supports: --query "A" --query "B"  OR  --query "A,B"  OR  --query "A, B"
    """
    raw: list[str] = getattr(args, "queries", None) or []
    result: list[str] = []
    for item in raw:
        for part in item.split(","):
            q = part.strip()
            if q and q not in result:
                result.append(q)
    return result


def _query_slug(queries: list[str]) -> str:
    """Convert query list to a safe directory name slug."""
    import re
    combined = "_".join(q.strip() for q in queries) if queries else "general"
    slug = re.sub(r"[^\w]", "_", combined.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:50]


def _session_out_dir(queries: list[str]) -> Path:
    """Compute a new session directory path: sessions/<slug>/<YYYYMMDD_HHMMSS>/"""
    slug = _query_slug(queries)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    return SESSIONS_DIR / slug / ts


def _list_sessions() -> int:
    """Print all recorded sessions grouped by query slug."""
    if not SESSIONS_DIR.exists():
        print("  [SESSIONS] No sessions recorded yet.")
        return 0
    slugs = sorted(d for d in SESSIONS_DIR.iterdir() if d.is_dir())
    if not slugs:
        print("  [SESSIONS] No sessions recorded yet.")
        return 0
    w = 78
    print(f"\n  {'═'*w}")
    print(f"  {'FBSCRAP — RECORDED SESSIONS':^{w}}")
    print(f"  {'═'*w}")
    for slug_dir in slugs:
        sessions = sorted([s for s in slug_dir.iterdir() if s.is_dir()], reverse=True)
        if not sessions:
            continue
        print(f"\n  ▶  {slug_dir.name}   ({len(sessions)} session(s))")
        print(f"  {'─'*w}")
        for s in sessions:
            meta_f = s / "session.json"
            if meta_f.exists():
                try:
                    m = json.loads(meta_f.read_text())
                    q_str = ", ".join(m.get("queries") or [slug_dir.name])
                    print(
                        f"     {s.name}  "
                        f"posts={str(m.get('post_count','?')):>5}  "
                        f"neg={str(m.get('neg_count','?')):>5}  "
                        f"mode={m.get('mode','?'):<8}  "
                        f"query={q_str}"
                    )
                except Exception:
                    print(f"     {s.name}  [meta unreadable]")
            else:
                files = list(s.glob("posts_*.json"))
                p_count = "?"
                if files:
                    try:
                        p_count = str(len(json.loads(files[0].read_text())))
                    except Exception:
                        pass
                print(f"     {s.name}  posts={p_count}")
    print(f"\n  {'═'*w}")
    print(f"  Sessions stored in: {SESSIONS_DIR}\n")
    return 0


def _save_session_meta(
    session_dir: Path, queries: list[str], mode: str,
    days: int, post_count: int, neg_count: int
) -> None:
    """Persist session metadata for future listing and resumption."""
    meta = {
        "session_id": session_dir.name,
        "query_slug": session_dir.parent.name,
        "queries":    queries,
        "mode":       mode,
        "timestamp":  datetime.now().isoformat(),
        "days":       days,
        "post_count": post_count,
        "neg_count":  neg_count,
    }
    (session_dir / "session.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )


def _query_to_keywords(query: str, use_elite: bool = False, cfg: dict | None = None) -> list[str]:
    """
    Expand a search query into OR-keywords for page-scraper filtering.
    'John Smith Doe' → full phrase + bigrams + words >4 chars.
    Any match = include post.

    If use_elite=True, uses ELITE semantic expansion with initials, titles, etc.
    """
    if use_elite:
        try:
            from engines.entity_matcher import expand_query_elite
            expanded = expand_query_elite(query, cfg=cfg, strict=False)
            print(f"  [ELITE] Expanded '{query}' → {len(expanded)} variations")
            if len(expanded) <= 20:
                print(f"         {', '.join(expanded[:20])}")
            else:
                print(f"         {', '.join(expanded[:15])} +{len(expanded)-15} more")
            return expanded
        except Exception as e:
            print(f"  [ELITE] Warning: expansion failed ({e}) → fallback to basic")
            # Fallback to basic expansion

    # Basic expansion (original logic)
    q     = query.strip().lower()
    terms = [q]
    words = [w for w in q.split() if len(w) > 3]
    for i in range(len(words) - 1):
        terms.append(f"{words[i]} {words[i+1]}")
    terms.extend(words)
    return list(dict.fromkeys(terms))   # deduplicated, order preserved


def _sort_key(p: dict, mode: str = "negative") -> tuple:
    from engines.sentiment import SentimentEngine
    return SentimentEngine.sort_key(mode)(p)


def _top_per_source(posts: list[dict], top_n: int, sent_mode: str = "negative") -> tuple[list[dict], dict]:
    """
    Rank posts within each source by the given sentiment mode + engagement.
    Returns (combined_list, stats_per_source).
    """
    from collections import defaultdict
    from engines.sentiment import SentimentEngine
    key_fn = SentimentEngine.sort_key(sent_mode)

    by_src: dict[str, list] = defaultdict(list)
    for p in posts:
        by_src[p.get("source", "unknown")].append(p)

    combined: list[dict] = []
    stats: dict = {}
    for src, src_posts in sorted(by_src.items()):
        ranked  = sorted(src_posts, key=key_fn)
        top     = ranked[:top_n]
        combined.extend(top)
        neg_cnt = sum(1 for p in top if p.get("sentiment", {}).get("label") in ("NEGATIVO", "AGRESIVO"))
        agg_cnt = sum(1 for p in top if p.get("sentiment", {}).get("label") == "AGRESIVO")
        stats[src] = {"total": len(src_posts), "kept": len(top), "neg": neg_cnt, "agg": agg_cnt}
    return combined, stats


def _print_legacy_summary(posts: list[dict], top_n: int) -> None:
    w = 72
    print(f"\n  {'═'*w}")
    print(f"  {'TOP ' + str(min(top_n, len(posts))) + ' POSTS BY NEGATIVITY + ENGAGEMENT':^{w}}")
    print(f"  {'═'*w}")
    for i, p in enumerate(posts[:top_n], 1):
        sent  = p.get("sentiment", {})
        label = sent.get("label", "?????")[:8]
        neg   = sent.get("negative_score", 0)
        eng   = p.get("engagement_total", 0)
        src   = (p.get("source") or "unknown")[:28]
        url   = (p.get("url") or "")[:55]
        bar   = "█" * int(neg * 10)
        print(f"  {i:2d}. [{label}] neg={neg:.2f} {bar:<10} eng={eng:5,} | {src:<28} | {url}")
    print(f"  {'═'*w}\n")


def _print_per_source_summary(posts: list[dict], stats: dict, top_n: int, sent_mode: str = "negative") -> None:
    from collections import defaultdict
    from engines.sentiment import SentimentEngine
    key_fn = SentimentEngine.sort_key(sent_mode)

    w = 82
    mode_label = sent_mode.upper()
    print(f"\n  {'═'*w}")
    print(f"  {'INTEL REPORT — TOP ' + str(top_n) + ' POR FUENTE | MODE=' + mode_label:^{w}}")
    print(f"  {'═'*w}")

    by_src: dict[str, list] = defaultdict(list)
    for p in posts:
        by_src[p.get("source", "unknown")].append(p)

    global_rank = 0
    for src in sorted(by_src.keys()):
        src_posts = sorted(by_src[src], key=key_fn)
        st        = stats.get(src, {})
        kept      = st.get("kept", 0)
        neg_pct   = round(st.get("neg", 0) / max(kept, 1) * 100)
        agg_pct   = round(st.get("agg", 0) / max(kept, 1) * 100)

        print(f"\n  ▶ {src}")
        print(f"    scraped={st.get('total',0)}  kept={kept}  "
              f"NEGATIVO+AGRESIVO={neg_pct}%  AGRESIVO={agg_pct}%")
        print(f"  {'─'*w}")

        for p in src_posts[:top_n]:
            global_rank += 1
            sent  = p.get("sentiment", {})
            label = sent.get("label", "NEUTRAL")[:8]
            neg   = sent.get("negative_score", 0.0)
            agg   = sent.get("aggressive_score", 0.0)
            ncmt  = sent.get("neg_comments", 0)
            tcmt  = sent.get("comment_count", 0)
            eng   = p.get("engagement_total", 0)
            url   = (p.get("url") or "—")[:58]
            bar   = "█" * int(neg * 10)

            cmt_info = f"cmt:{ncmt}/{tcmt}" if tcmt else "no-cmt"
            print(f"  {global_rank:3d}. [{label:<8}] neg={neg:.2f} agg={agg:.2f} "
                  f"{bar:<10} eng={eng:6,} {cmt_info:<10} | {url}")

    print(f"\n  {'═'*w}\n")


def _print_config(args: argparse.Namespace, cfg: dict) -> None:
    """Print active configuration before scraping starts."""
    w = 70
    # Resolve targets count
    targets_file = getattr(args, "targets", None) or cfg.get(
        "default_targets_file", str(BASE_DIR / "targets" / "example_pages.json")
    )
    try:
        tdata = json.loads(Path(targets_file).read_text())
        t_list = tdata.get("targets", tdata) if isinstance(tdata, dict) else tdata
        t_count = len(t_list)
        t_label = f"{targets_file} ({t_count} targets)"
    except Exception:
        t_label = targets_file or "default"

    # Resolve keywords from query
    queries   = _resolve_queries(args)
    kw_preview = ""
    if queries and args.mode in ("page", "full"):
        all_kws: list[str] = []
        use_elite = getattr(args, "loose_match", False)
        for q in queries:
            all_kws.extend(_query_to_keywords(q, use_elite=use_elite, cfg=cfg))
        all_kws = list(dict.fromkeys(all_kws))
        kw_preview = ", ".join(f'"{k}"' for k in all_kws[:4])
        if len(all_kws) > 4:
            kw_preview += f" +{len(all_kws)-4} more"

    sent_mode = getattr(args, "sentiment", None) or ("negative" if args.mode == "full" else None)
    cmt_top   = getattr(args, "comments_on_top", 0)
    top_src   = getattr(args, "top_per_source", 30)

    yes = "✓"
    no  = "—"

    query_display = "  |  ".join(f'"{q}"' for q in queries) if queries else no

    rows = [
        ("Mode",              args.mode),
        ("Queries",           query_display),
        ("Post keywords",     kw_preview  if kw_preview else no),
        ("Days back",         str(getattr(args, "days", 7))),
        ("Max posts/page",    str(getattr(args, "max_posts", 150))),
        ("Min engagement",    str(getattr(args, "min_engagement", 0))),
        ("Sentiment mode",    sent_mode.upper() if sent_mode else no),
        ("Comment fetch",     f"top {cmt_top} posts" if cmt_top else "DISABLED (--comments-on-top 0)"),
        ("Top per source",    str(top_src)),
        ("Targets",           t_label),
        ("Output dir",        args.out or f"sessions/{_query_slug(_resolve_queries(args))}/<ts>/"),
        ("Headless",          yes if getattr(args, "headless", False) else no),
        ("Verbose",           yes if getattr(args, "verbose", False) else no),
    ]

    print(f"\n  ╔{'═'*(w-2)}╗")
    print(f"  ║{'  FBSCRAP — ACTIVE CONFIGURATION':^{w-2}}║")
    print(f"  ╠{'═'*(w-2)}╣")
    for key, val in rows:
        line = f"  {key:<20} {val}"
        print(f"  ║{line:<{w-2}}║")
    print(f"  ╚{'═'*(w-2)}╝\n")


# ── Main async runner ─────────────────────────────────────────────────────────

async def run(args: argparse.Namespace, cfg: dict) -> int:
    from engines.browser import BrowserManager
    from engines.logger import SessionLogger

    # ── sessions listing (no browser / output dir needed) ────────────────────
    if args.mode == "sessions":
        return _list_sessions()

    # ── resolve output directory: explicit --out OR auto session path ─────────
    if args.out:
        out_dir = Path(args.out)
    else:
        out_dir = _session_out_dir(_resolve_queries(args))
    out_dir.mkdir(parents=True, exist_ok=True)

    profile_dir = args.profile or cfg.get("profile_dir", str(BASE_DIR / ".fb_profile"))
    headless    = args.headless or cfg.get("headless", False)
    slow_mo     = args.slow_mo if args.slow_mo is not None else cfg.get("slow_mo", 0)

    logger = SessionLogger(out_dir, verbose=getattr(args, "verbose", False))

    _print_config(args, cfg)

    # ── report-only mode (no browser needed) ──────────────────────────────────
    if args.mode == "report":
        data_file = args.data
        if not data_file:
            print("[!] --data FILE required for report mode", file=sys.stderr)
            logger.close()
            return 1
        posts = json.loads(Path(data_file).read_text())
        _generate_outputs(posts, args, out_dir, cfg)
        logger.close()
        return 0

    # ── delta mode (no browser needed) ────────────────────────────────────────
    if args.mode == "delta":
        return _run_delta(args, cfg, logger)

    # ── monitor mode (loops internally) ───────────────────────────────────────
    if args.mode == "monitor":
        return await _run_monitor(args, cfg, out_dir, logger)

    # ── modes that need a browser ─────────────────────────────────────────────
    async with BrowserManager(profile_dir, headless=headless, slow_mo=slow_mo) as browser:

        # ── login ─────────────────────────────────────────────────────────────
        if args.mode == "login":
            await browser.do_login()
            return 0

        results: list[dict] = []

        # ── page scraping ─────────────────────────────────────────────────────
        if args.mode in ("page", "full"):
            from engines.page_scraper import PageScraper
            targets  = _load_targets(args.targets, cfg)
            keywords = _parse_csv_list(args.keywords)
            # OR-union keywords from all queries so a post matching ANY query is kept
            queries = _resolve_queries(args)
            if queries:
                use_elite = getattr(args, "loose_match", False)
                for q in queries:
                    keywords = list(dict.fromkeys(keywords + _query_to_keywords(q, use_elite=use_elite, cfg=cfg)))
                print(f"  [FILTER] Page keywords ({len(queries)} queries): "
                      f"{keywords[:6]}{'...' if len(keywords)>6 else ''}")
            ps = PageScraper(
                browser, cfg,
                days=args.days,
                max_posts=args.max_posts,
                min_engagement=args.min_engagement,
                keywords=keywords,
                verbose=getattr(args, "verbose", False),
                logger=logger,
            )

            if args.concurrent > 1:
                semaphore = asyncio.Semaphore(args.concurrent)
                async def scrape_with_sem(t):
                    async with semaphore:
                        return await ps.scrape(t)
                all_posts = await asyncio.gather(*[scrape_with_sem(t) for t in targets])
                for posts in all_posts:
                    results.extend(posts)
            else:
                for target in targets:
                    posts = await ps.scrape(target)
                    results.extend(posts)

        # ── search ────────────────────────────────────────────────────────────
        if args.mode in ("search", "full"):
            from engines.search_scraper import SearchScraper
            queries = _resolve_queries(args)
            if not queries:
                if args.mode == "search":
                    print("[!] --query required for search mode", file=sys.stderr)
                    return 1
            else:
                ss = SearchScraper(
                    browser, cfg,
                    days=args.days,
                    max_posts=args.max_posts,
                    min_engagement=args.min_engagement,
                    verbose=getattr(args, "verbose", False),
                    logger=logger,
                )
                for q in queries:
                    posts = await ss.scrape(q)
                    results.extend(posts)

        # ── comments ──────────────────────────────────────────────────────────
        if args.mode == "direct":
            return await _run_direct(args, cfg, out_dir, logger, browser)

        if args.mode == "comments":
            from engines.comment_scraper import CommentScraper
            if not args.urls:
                print("[!] --url required for comments mode", file=sys.stderr)
                return 1
            cs = CommentScraper(browser, cfg, max_comments=args.max_comments)
            for url in args.urls:
                post_data = await cs.scrape(url)
                results.append(post_data)
                n = len(post_data.get("comments", []))
                print(f"  [COMMENTS] {url[:55]} → {n} comments")

        # ── discover ──────────────────────────────────────────────────────────
        if args.mode == "discover":
            from engines.discovery import DiscoveryEngine
            names = _parse_csv_list(args.names)
            if not names and args.targets:
                targets = _load_targets(args.targets, cfg)
                names   = [t.get("name", "") for t in targets]
            if not names:
                print("[!] --names or --targets required for discover mode", file=sys.stderr)
                return 1
            de    = DiscoveryEngine(browser, cfg)
            pages = await de.discover(names)
            # Save discovered pages as a new targets file
            out_f = out_dir / "discovered_targets.json"
            discovered_targets = [
                {
                    "name":     p.get("title") or p.get("query"),
                    "handle":   p.get("handle", ""),
                    "url":      p.get("url", ""),
                    "category": "discovered",
                    "likes":    p.get("likes"),
                    "verified": p.get("verified", False),
                }
                for p in pages if p.get("url")
            ]
            out_f.write_text(json.dumps(
                {"description": "Auto-discovered FB pages", "targets": discovered_targets},
                ensure_ascii=False, indent=2
            ))
            print(f"\n  [DISCOVER] {len(discovered_targets)} pages found → {out_f}")
            return 0

        # ── deep-comment secondary pass ───────────────────────────────────────
        if args.comments_on_top > 0 and results:
            from engines.comment_scraper import CommentScraper
            cs          = CommentScraper(browser, cfg, max_comments=args.max_comments)
            top_urls    = [p["url"] for p in results[:args.comments_on_top] if p.get("url")]
            print(f"\n  [COMMENTS] Deep-scraping top {len(top_urls)} posts...")
            url_to_post = {p["url"]: p for p in results if p.get("url")}
            for url in top_urls:
                comment_data = await cs.scrape(url)
                if url in url_to_post:
                    url_to_post[url]["comments"]       = comment_data.get("comments", [])
                    url_to_post[url]["total_comments_found"] = comment_data.get("total_found", 0)
                n = len(comment_data.get("comments", []))
                print(f"  [COMMENTS] {url[:55]} → {n} comments")

    # ── No results ────────────────────────────────────────────────────────────
    if not results:
        logger.warn("No results collected — check login / targets / date range")
        logger.summary(0, 0, 0)
        logger.close()
        print("\n[!] No results collected. Check: (1) logged in? (2) targets valid? (3) date range?")
        return 1

    # ── Deduplication ─────────────────────────────────────────────────────────
    seen: set[str] = set()
    unique: list[dict] = []
    for p in results:
        key = p.get("url", "") or str(p.get("text", ""))[:80]
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    results = unique
    print(f"\n  [DEDUPE] {len(results)} unique posts after deduplication")

    # ── Sentiment analysis ────────────────────────────────────────────────────
    sent_mode = args.sentiment or ("negative" if args.mode == "full" else None)
    if sent_mode:
        from engines.sentiment import SentimentEngine
        se = SentimentEngine()
        se.batch(results)
        # Auto-warn if no comments loaded
        has_comments = any(p.get("comments") for p in results)
        if not has_comments and sent_mode:
            print(f"  [SENTIMENT] ⚠ No comments loaded — using text fallback. "
                  f"Add --comments-on-top {args.top} for real comment analysis.")
        # Filter by sentiment mode (remove irrelevant labels)
        if sent_mode != "all":
            before = len(results)
            results = SentimentEngine.filter_by_mode(results, sent_mode)
            print(f"  [FILTER] mode={sent_mode} → {len(results)}/{before} posts match")

    # ── Per-source TOP N ranking (sorted by sentiment mode) ───────────────────
    top_n_src = getattr(args, "top_per_source", 30)
    src_stats: dict = {}
    if sent_mode:
        results, src_stats = _top_per_source(results, top_n_src, sent_mode)
        print(f"  [RANK] top-{top_n_src} per source → {len(results)} posts | {len(src_stats)} sources")
        # Final global sort by same mode
        from engines.sentiment import SentimentEngine
        results.sort(key=SentimentEngine.sort_key(sent_mode))
    else:
        results.sort(key=lambda p: -(p.get("engagement_total", 0)))

    # ── Export ────────────────────────────────────────────────────────────────
    _generate_outputs(results, args, out_dir, cfg)

    # ── Console summary ───────────────────────────────────────────────────────
    if src_stats:
        _print_per_source_summary(results, src_stats, top_n_src, sent_mode or "negative")
    else:
        _print_legacy_summary(results, args.top)
    neg_count = sum(1 for p in results if p.get("sentiment", {}).get("label") in ("NEGATIVO", "AGRESIVO"))
    logger.summary(len(results), len(results), neg_count)
    logger.close()

    # ── persist session metadata ───────────────────────────────────────────────
    _save_session_meta(
        out_dir,
        _resolve_queries(args),
        args.mode,
        getattr(args, "days", 7),
        len(results),
        neg_count,
    )

    print(f"  Session saved: {out_dir}/\n")
    return 0


def _generate_outputs(posts: list[dict], args: argparse.Namespace, out_dir: Path, cfg: dict) -> None:
    from output.exporter import Exporter
    exp = Exporter(out_dir)

    ts_suffix = datetime.now().strftime("%Y%m%d_%H%M")

    if args.format in ("json", "all"):
        exp.to_json(posts, f"posts_{ts_suffix}.json")
        exp.to_json(posts, "posts_latest.json")  # always-current symlink equivalent

    if args.format in ("csv", "all"):
        exp.to_csv(posts, f"posts_{ts_suffix}.csv")

    if args.format in ("all",):
        exp.to_urls(posts, f"urls_{ts_suffix}.txt")

    if args.format in ("html", "all"):
        from output.reporter import Reporter
        rpt = Reporter(out_dir)
        _q_label = " | ".join(_resolve_queries(args)) if hasattr(args, "queries") else ""
        rpt.generate(
            posts,
            top_n    = args.top,
            query    = _q_label,
            filename = f"report_{ts_suffix}.html",
        )
        rpt.generate(posts, top_n=args.top, query=_q_label, filename="report_latest.html")

    if args.format in ("docx", "all"):
        from engines.docx_reporter import generate_docx_report
        _q_label = " | ".join(_resolve_queries(args)) if hasattr(args, "queries") else ""
        _days    = getattr(args, "days", 7)
        generate_docx_report(
            posts,
            output_path = out_dir / f"report_{ts_suffix}.docx",
            query       = _q_label,
            top_n       = args.top,
            days        = _days,
            cfg         = cfg,
        )
        generate_docx_report(
            posts,
            output_path = out_dir / "report_latest.docx",
            query       = _q_label,
            top_n       = args.top,
            days        = _days,
            cfg         = cfg,
        )


# ── Delta mode ────────────────────────────────────────────────────────────────

def _run_delta(args, cfg: dict, logger) -> int:
    """Compare two session dirs and print CIB evolution report."""
    from engines.session_delta_engine import SessionDeltaEngine
    from pathlib import Path

    before = getattr(args, "delta_before", None)
    after  = getattr(args, "delta_after",  None)

    if not before:
        # Auto-detect: find two most recent sessions for this query
        sessions_root = Path(cfg.get("output", {}).get("default_output_dir", "sessions"))
        queries = _resolve_queries(args)
        slug    = _to_slug(queries[0] if queries else "unknown")
        target_dir = sessions_root / slug
        if not target_dir.exists():
            print(f"[!] --delta-before required, or run scans first under sessions/{slug}/",
                  file=sys.stderr)
            logger.close()
            return 1
        all_sessions = sorted(
            [d for d in target_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
        )
        if len(all_sessions) < 2:
            print("[!] Need at least 2 sessions for delta. Run more scans first.",
                  file=sys.stderr)
            logger.close()
            return 1
        before = str(all_sessions[-2])
        after  = str(all_sessions[-1])

    after = after or before  # fallback: compare before against itself

    print(f"\n  [DELTA] Comparing sessions:")
    print(f"    BEFORE: {before}")
    print(f"    AFTER:  {after}")

    engine = SessionDeltaEngine(cfg=cfg)
    report = engine.compare(before, after)

    print(f"\n  [DELTA] Result:")
    print(f"    Overall trend:  {report.overall_trend}")
    print(f"    Delta score:    {report.delta_score}/100")
    print(f"    Time delta:     {report.time_delta_hours:.1f}h")
    print(f"    New bots:       {len(report.new_bots)}")
    print(f"    Disappeared:    {len(report.disappeared_bots)}")
    print(f"    Escalations:    {len(report.score_escalations)}")
    print(f"    Narrative:      {report.narrative_drift.drift_label} "
          f"(overlap {report.narrative_drift.overlap_pct:.0%})")
    if report.narrative_drift.terms_gained:
        print(f"    New terms:      {', '.join(report.narrative_drift.terms_gained[:8])}")
    print(f"\n  Summary: {report.summary}")

    logger.close()
    return 0


# ── Monitor mode ──────────────────────────────────────────────────────────────

async def _run_monitor(args, cfg: dict, out_dir: Path, logger) -> int:
    """Run continuous monitoring loop for a target query or page."""
    import asyncio as _asyncio
    from engines.monitor_engine import MonitorEngine
    from engines.browser import BrowserManager

    interval     = getattr(args, "monitor_interval", cfg.get("monitor", {}).get("interval_seconds", 300))
    max_cycles   = getattr(args, "monitor_cycles",   0)
    mon_engine   = MonitorEngine(cfg=cfg)
    cycle        = 0
    results      = []

    print(f"\n  [MONITOR] Starting — interval={interval}s "
          f"max_cycles={'∞' if not max_cycles else max_cycles}")

    profile_dir = args.profile or cfg.get("profile_dir", str(BASE_DIR / ".fb_profile"))
    headless    = args.headless or cfg.get("headless", False)
    slow_mo     = args.slow_mo if args.slow_mo is not None else cfg.get("slow_mo", 0)

    while True:
        cycle += 1
        print(f"\n  [MONITOR] Cycle #{cycle} — scraping...")
        try:
            async with BrowserManager(profile_dir, headless=headless, slow_mo=slow_mo) as browser:
                # Re-use standard run logic inline
                posts = await _scrape_for_monitor(args, cfg, browser)

            # Compute CIB score
            cib_score = 0.0
            try:
                from engines.cib_score_engine import CIBScoreEngine
                # Run TrollHunter for bot list
                from engines.troll_hunter_engine import TrollHunterEngine
                from engines.temporal_engine import TemporalEngine
                all_cr = [{"url": p.get("url",""), "comments": p.get("comments",[])}
                           for p in posts if p.get("comments")]
                troll_r  = TrollHunterEngine(cfg=cfg).analyze(all_cr)
                temp_r   = TemporalEngine(cfg=cfg).analyze(all_cr)
                cib_score = CIBScoreEngine(cfg=cfg).compute(
                    troll_report=troll_r, temporal_report=temp_r,
                ).overall_score
            except Exception:
                pass

            result = mon_engine.check_delta(posts, cib_score, out_dir, troll_report=None)
            results.append(result)

            status = f"cib={result.cib_score:.0f}/100 posts={result.posts_found}"
            if result.alert:
                print(f"  [MONITOR] ⚠ ALERT [{result.alert.severity}]: "
                      f"{result.alert.alert_type} — {status}")
                print(f"    {result.alert.message}")
            else:
                print(f"  [MONITOR] ✓ Clean — {status}")

        except Exception as e:
            print(f"  [MONITOR] Cycle #{cycle} error: {e}")

        if max_cycles and cycle >= max_cycles:
            break

        print(f"  [MONITOR] Sleeping {interval}s until next cycle...")
        await _asyncio.sleep(interval)

    print(f"\n  [MONITOR] Done — {cycle} cycle(s). Summary:")
    print(mon_engine.format_alert_summary(results))
    logger.close()
    return 0


async def _scrape_for_monitor(args, cfg: dict, browser) -> list[dict]:
    """Minimal scrape for monitor mode — returns posts list."""
    from engines.search_scraper import SearchScraper
    from engines.page_scraper import PageScraper
    queries = _resolve_queries(args)
    posts: list[dict] = []
    if queries:
        sc = SearchScraper(
            browser,
            days         = getattr(args, "days", 3),
            max_posts    = cfg.get("monitor", {}).get("max_posts_per_cycle", 50),
            min_engagement = 0,
        )
        for q in queries:
            posts += await sc.scrape(q)
    return posts


# ── Direct mode (scrape specific post URLs) ───────────────────────────────────

async def _run_direct(args, cfg: dict, out_dir: Path, logger, browser) -> int:
    """Scrape specific Facebook post URLs and run full CIB analysis pipeline."""
    from engines.comment_scraper import CommentScraper

    urls = getattr(args, "urls", None) or []
    if not urls:
        print("[!] --url URL required for direct mode", file=sys.stderr)
        logger.close()
        return 1

    max_comments = getattr(args, "max_comments", cfg.get("scraper", {}).get("max_comments", 300))
    print(f"\n  [DIRECT] Scraping {len(urls)} URL(s) with max {max_comments} comments each...")

    results: list[dict] = []
    cs = CommentScraper(browser, max_comments=max_comments)
    for url in urls:
        print(f"    → {url[:80]}")
        try:
            post = await cs.scrape(url)
            if post:
                post.setdefault("mode", "direct")
                post.setdefault("post_type", (
                    "reel"  if "/reel/"   in url else
                    "video" if "/videos/" in url else
                    "photo" if "/photos/" in url else "post"
                ))
                results.append(post)
        except Exception as e:
            print(f"    [!] Error scraping {url}: {e}")

    if not results:
        print("[!] No posts scraped from provided URLs.", file=sys.stderr)
        logger.close()
        return 1

    print(f"\n  [DIRECT] {len(results)} post(s) scraped — running full pipeline...")
    _generate_outputs(results, args, out_dir, cfg)
    print(f"  Session saved: {out_dir}/\n")
    logger.close()
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()
    cfg    = load_config()

    if not args.no_banner:
        print(_BANNER)

    sys.exit(asyncio.run(run(args, cfg)))


if __name__ == "__main__":
    main()
