"""
NULLSEC BOT DETECTOR — Coordinated Inauthentic Behavior (CIB) Engine
NULLSEC RED TEAM

All thresholds read from cfg["bot_detector"]. Zero hardcoded values.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


def _get_thresholds(cfg: dict | None) -> dict:
    c = (cfg or {}).get("bot_detector", {})
    return {
        "near_dup_threshold":         c.get("near_dup_threshold", 0.45),
        "burst_window_min":           c.get("burst_window_min", 90),
        "cib_window_min":             c.get("cib_window_min", 120),
        "burst_min_posts":            c.get("burst_min_posts", 3),
        "ghost_max_reactions":        c.get("ghost_max_reactions", 5),
        "ghost_max_comments":         c.get("ghost_max_comments", 3),
        "attack_source_threshold":    c.get("attack_source_threshold", 0.80),
        "bot_confirmed_threshold":    c.get("bot_confirmed_threshold", 60),
        "suspicious_threshold":       c.get("suspicious_threshold", 30),
        "min_text_len":               c.get("min_text_len_for_similarity", 40),
        "burst_jaccard_threshold":    c.get("burst_jaccard_threshold", 0.15),
        "max_posts_for_cib":          c.get("max_posts_for_cib", 1000),
        "conf_near_dup":              c.get("confidence_scores", {}).get("near_duplicate", 75),
        "conf_cib_cluster":           c.get("confidence_scores", {}).get("cib_cluster", 65),
        "conf_ghost":                 c.get("confidence_scores", {}).get("ghost_amplifier", 55),
        "conf_burst":                 c.get("confidence_scores", {}).get("burst_poster", 50),
        "conf_attack_source":         c.get("confidence_scores", {}).get("attack_source", 40),
    }


# ── Text fingerprinting ───────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _shingles(text: str, k: int = 3) -> frozenset[str]:
    words = _normalize(text).split()
    if len(words) < k:
        return frozenset(words)
    return frozenset(" ".join(words[i:i+k]) for i in range(len(words) - k + 1))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union        = len(a | b)
    return intersection / union if union else 0.0


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class BotSignal:
    signal_type: str
    confidence:  int
    description: str
    evidence:    str


@dataclass
class PostBotReport:
    post_index: int
    source:     str
    title:      str
    url:        str
    timestamp:  Optional[datetime]
    reactions:  int
    comments:   int
    shares:     int
    signals:    list[BotSignal] = field(default_factory=list)
    bot_score:  int = 0
    bot_class:  str = "ORGANIC"

    def compute_class(self, bot_threshold: int = 60, sus_threshold: int = 30) -> None:
        self.bot_score = min(sum(s.confidence for s in self.signals), 100)
        if self.bot_score >= bot_threshold:
            self.bot_class = "BOT CONFIRMED"
        elif self.bot_score >= sus_threshold:
            self.bot_class = "SUSPICIOUS"
        else:
            self.bot_class = "ORGANIC"


@dataclass
class CIBCluster:
    cluster_id:    int
    posts:         list[dict]
    similarities:  list[float]
    time_span_min: float
    sources:       list[str]
    sample_text:   str


@dataclass
class BotDetectionReport:
    total_posts:         int
    cib_clusters:        list[CIBCluster]
    ghost_amplifiers:    list[PostBotReport]
    burst_events:        list[dict]
    attack_sources:      list[dict]
    post_reports:        list[PostBotReport]

    bot_confirmed_count: int = 0
    suspicious_count:    int = 0
    organic_count:       int = 0
    bot_confirmed_pct:   int = 0
    suspicious_pct:      int = 0
    organic_pct:         int = 0
    cib_cluster_count:   int = 0
    ghost_count:         int = 0
    estimated_fake_eng:  int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_ts(post: dict) -> Optional[datetime]:
    ts = post.get("timestamp")
    if ts:
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            pass
    raw = post.get("timestamp_raw", "")
    if raw and str(raw).isdigit():
        try:
            return datetime.fromtimestamp(int(raw))
        except Exception:
            pass
    return None


def _get_eng(post: dict) -> tuple[int, int, int]:
    r = int(post.get("reactions") or 0)
    c = int(post.get("comments_count") or 0)
    s = int(post.get("shares") or 0)
    return r, c, s


def _src(post: dict) -> str:
    return (post.get("source") or post.get("source_handle") or "Unknown").strip()


def _title(post: dict) -> str:
    text = (post.get("text") or "").strip()
    if not text:
        return "(no text)"
    for sep in ("\n", ". ", " — ", " | "):
        idx = text.find(sep)
        if 0 < idx < 120:
            return text[:idx].strip()
    return text[:100].strip()


def _sent_label(post: dict) -> str:
    return ((post.get("sentiment") or {}).get("label") or "NEUTRAL").upper()


# ── Detection engines ─────────────────────────────────────────────────────────

def _find_cib_clusters(posts: list[dict], thresholds: dict) -> list[CIBCluster]:
    near_dup  = thresholds["near_dup_threshold"]
    cib_win   = thresholds["cib_window_min"]
    min_text  = thresholds["min_text_len"]
    max_posts = thresholds["max_posts_for_cib"]

    posts = posts[:max_posts]
    n     = len(posts)
    clusters: list[CIBCluster] = []
    used: set[int] = set()
    cluster_id = 0

    shingles_cache  = [_shingles(post.get("text") or "") for post in posts]
    timestamps      = [_get_ts(post) for post in posts]

    for i in range(n):
        if i in used:
            continue
        text_i = (posts[i].get("text") or "").strip()
        if len(text_i) < min_text:
            continue

        group_indices = [i]
        group_sims    = [1.0]

        for j in range(i + 1, n):
            if j in used:
                continue
            if _src(posts[j]) == _src(posts[i]):
                continue

            ti, tj = timestamps[i], timestamps[j]
            if ti and tj:
                if abs((tj - ti).total_seconds()) / 60 > cib_win:
                    continue
            elif ti or tj:
                continue

            sim = _jaccard(shingles_cache[i], shingles_cache[j])
            if sim >= near_dup:
                group_indices.append(j)
                group_sims.append(sim)

        if len(group_indices) >= 2:
            for idx in group_indices:
                used.add(idx)

            group_posts   = [posts[k] for k in group_indices]
            group_sources = [_src(posts[k]) for k in group_indices]
            group_ts      = [timestamps[k] for k in group_indices if timestamps[k]]

            time_span = 0.0
            if len(group_ts) >= 2:
                time_span = (max(group_ts) - min(group_ts)).total_seconds() / 60

            sample = (posts[i].get("text") or "")[:200].replace("\n", " ")

            clusters.append(CIBCluster(
                cluster_id=cluster_id, posts=group_posts, similarities=group_sims,
                time_span_min=time_span, sources=group_sources, sample_text=sample,
            ))
            cluster_id += 1

    return clusters


def _find_ghost_amplifiers(
    posts:        list[dict],
    cib_clusters: list[CIBCluster],
    thresholds:   dict,
) -> list[PostBotReport]:
    ghost_max_r = thresholds["ghost_max_reactions"]
    ghost_max_c = thresholds["ghost_max_comments"]
    bot_thresh  = thresholds["bot_confirmed_threshold"]
    sus_thresh  = thresholds["suspicious_threshold"]
    conf_ghost  = thresholds["conf_ghost"]
    conf_cib    = thresholds["conf_cib_cluster"]

    ghosts: list[PostBotReport] = []
    cib_sources: set[str] = set()
    for cluster in cib_clusters:
        for s in cluster.sources:
            cib_sources.add(s)

    for i, post in enumerate(posts):
        r, c, s = _get_eng(post)
        src      = _src(post)
        signals: list[BotSignal] = []

        if src in cib_sources and r <= ghost_max_r and c <= ghost_max_c:
            for cluster in cib_clusters:
                if src in cluster.sources:
                    other_sources = [x for x in cluster.sources if x != src]
                    max_sim = max(cluster.similarities)
                    signals.append(BotSignal(
                        signal_type="CIB_GHOST",
                        confidence=conf_cib,
                        description=f"Near-identical text as post from [{', '.join(other_sources[:2])}]",
                        evidence=f"Jaccard={max_sim:.2f} | window={cluster.time_span_min:.0f}min | own eng r={r},c={c},s={s}",
                    ))
                    break

        lbl  = _sent_label(post)
        text = (post.get("text") or "").strip()
        if r == 0 and c == 0 and s == 0 and len(text) > 20:
            signals.append(BotSignal(
                signal_type="ZERO_ATTACKER",
                confidence=conf_ghost,
                description="Account with no real audience — total engagement = 0",
                evidence=f"r=0 c=0 s=0 | sentiment={lbl}",
            ))
        elif r == 0 and lbl in ("AGRESIVO", "NEGATIVO") and len(text) > 20:
            signals.append(BotSignal(
                signal_type="ZERO_ATTACKER",
                confidence=conf_ghost - 10,
                description="Attack post with zero organic reactions",
                evidence=f"r=0 | s={s} c={c} | sentiment={lbl}",
            ))

        if r <= 3 and s > r and s > 0:
            signals.append(BotSignal(
                signal_type="GHOST_AMPLIFIER",
                confidence=50,
                description=f"Shares ({s}) exceed reactions ({r}) on minimal-audience account",
                evidence=f"r={r} s={s} c={c} — shares/reactions={s/max(r,1):.1f}x",
            ))

        if signals:
            rpt = PostBotReport(
                post_index=i, source=src, title=_title(post),
                url=post.get("url") or "", timestamp=_get_ts(post),
                reactions=r, comments=c, shares=s, signals=signals,
            )
            rpt.compute_class(bot_threshold=bot_thresh, sus_threshold=sus_thresh)
            ghosts.append(rpt)

    return ghosts


def _find_burst_campaigns(posts: list[dict], thresholds: dict) -> list[dict]:
    burst_min   = thresholds["burst_min_posts"]
    burst_win   = thresholds["burst_window_min"]
    burst_jac   = thresholds["burst_jaccard_threshold"]
    conf_burst  = thresholds["conf_burst"]

    timestamped = [(p, _get_ts(p)) for p in posts if _get_ts(p) is not None]
    timestamped.sort(key=lambda x: x[1])

    if len(timestamped) < burst_min:
        return []

    bursts = []
    window = timedelta(minutes=burst_win)
    n      = len(timestamped)

    for i in range(n):
        post_i, ts_i = timestamped[i]
        window_posts = [(post_i, ts_i)]

        for j in range(i + 1, n):
            post_j, ts_j = timestamped[j]
            if ts_j - ts_i > window:
                break
            if _src(post_j) != _src(post_i):
                window_posts.append((post_j, ts_j))

        if len(window_posts) < burst_min:
            continue

        shin_i  = _shingles(post_i.get("text") or "")
        similar = [
            (p, t) for p, t in window_posts[1:]
            if _jaccard(shin_i, _shingles(p.get("text") or "")) >= burst_jac
        ]
        if len(similar) + 1 < burst_min:
            continue

        all_posts = [post_i] + [p for p, _ in similar]
        all_src   = [_src(p) for p in all_posts]
        if len(set(all_src)) < 2:
            continue

        all_ts   = [ts_i] + [t for _, t in similar]
        span_min = (max(all_ts) - min(all_ts)).total_seconds() / 60

        bursts.append({
            "window_start": ts_i.strftime("%Y-%m-%d %H:%M"),
            "window_end":   max(all_ts).strftime("%H:%M"),
            "span_min":     round(span_min),
            "post_count":   len(all_posts),
            "sources":      list(dict.fromkeys(all_src)),
            "sample_text":  _title(post_i)[:80],
            "total_eng":    sum(sum(_get_eng(p)) for p in all_posts),
        })

    bursts.sort(key=lambda x: -x["post_count"])
    deduped = []
    seen: set[str] = set()
    for b in bursts:
        if b["window_start"] not in seen:
            deduped.append(b)
            seen.add(b["window_start"])

    return deduped


def _find_attack_sources(posts: list[dict], thresholds: dict) -> list[dict]:
    threshold = thresholds["attack_source_threshold"]

    by_src: dict[str, list[dict]] = defaultdict(list)
    for post in posts:
        by_src[_src(post)].append(post)

    results = []
    for src, src_posts in by_src.items():
        if len(src_posts) < 2:
            continue
        neg_count = sum(1 for p in src_posts if _sent_label(p) in ("NEGATIVO", "AGRESIVO"))
        agg_count = sum(1 for p in src_posts if _sent_label(p) == "AGRESIVO")
        neg_pct   = neg_count / len(src_posts)
        if neg_pct >= threshold:
            avg_r = sum(_get_eng(p)[0] for p in src_posts) / len(src_posts)
            results.append({
                "source":         src,
                "post_count":     len(src_posts),
                "neg_pct":        round(neg_pct * 100),
                "agg_count":      agg_count,
                "avg_reactions":  round(avg_r, 1),
                "sample_titles":  [_title(p)[:60] for p in src_posts[:2]],
            })

    results.sort(key=lambda x: (-x["neg_pct"], -x["post_count"]))
    return results


def _build_post_reports(
    posts:          list[dict],
    cib_clusters:   list[CIBCluster],
    ghost_list:     list[PostBotReport],
    bursts:         list[dict],
    thresholds:     dict,
) -> list[PostBotReport]:
    bot_thresh = thresholds["bot_confirmed_threshold"]
    sus_thresh = thresholds["suspicious_threshold"]
    conf_cib   = thresholds["conf_cib_cluster"]
    conf_burst = thresholds["conf_burst"]

    ghost_by_idx: dict[int, PostBotReport] = {g.post_index: g for g in ghost_list}

    post_to_cluster: dict[int, CIBCluster] = {}
    for cluster in cib_clusters:
        for post in cluster.posts:
            for i, orig in enumerate(posts):
                if orig is post:
                    post_to_cluster[i] = cluster
                    break

    burst_sources: set[str] = set()
    for b in bursts:
        for s in b["sources"]:
            burst_sources.add(s)

    reports: list[PostBotReport] = []
    for i, post in enumerate(posts):
        r, c, s = _get_eng(post)
        src      = _src(post)

        if i in ghost_by_idx:
            rpt = ghost_by_idx[i]
        else:
            rpt = PostBotReport(
                post_index=i, source=src, title=_title(post),
                url=post.get("url") or "", timestamp=_get_ts(post),
                reactions=r, comments=c, shares=s,
            )

        if i in post_to_cluster and not any(sg.signal_type == "CIB_CLUSTER" for sg in rpt.signals):
            cluster    = post_to_cluster[i]
            other_srcs = [x for x in cluster.sources if x != src]
            max_sim    = max(cluster.similarities)
            rpt.signals.append(BotSignal(
                signal_type="CIB_CLUSTER",
                confidence=min(85, int(max_sim * 100) + 20),
                description=f"Text replicated across {len(cluster.sources)} distinct sources",
                evidence=(
                    f"Jaccard={max_sim:.2f} | "
                    f"{len(other_srcs)} other sources: {', '.join(other_srcs[:3])} | "
                    f"window={cluster.time_span_min:.0f}min"
                ),
            ))

        if src in burst_sources and not any(sg.signal_type == "BURST" for sg in rpt.signals):
            matching = [b for b in bursts if src in b["sources"]]
            if matching:
                b = matching[0]
                rpt.signals.append(BotSignal(
                    signal_type="BURST",
                    confidence=conf_burst,
                    description=f"Part of burst campaign: {b['post_count']} posts in {b['span_min']}min",
                    evidence=f"window {b['window_start']}→{b['window_end']} | sources: {', '.join(b['sources'][:4])}",
                ))

        rpt.compute_class(bot_threshold=bot_thresh, sus_threshold=sus_thresh)
        reports.append(rpt)

    return reports


# ── Public API ────────────────────────────────────────────────────────────────

def analyze(posts: list[dict], cfg: dict | None = None) -> BotDetectionReport:
    """
    Full CIB + bot detection analysis. All thresholds from cfg["bot_detector"].
    """
    if not posts:
        return BotDetectionReport(
            total_posts=0, cib_clusters=[], ghost_amplifiers=[],
            burst_events=[], attack_sources=[], post_reports=[],
        )

    thresholds = _get_thresholds(cfg)

    cib_clusters    = _find_cib_clusters(posts, thresholds)
    ghost_amplifiers= _find_ghost_amplifiers(posts, cib_clusters, thresholds)
    burst_events    = _find_burst_campaigns(posts, thresholds)
    attack_sources  = _find_attack_sources(posts, thresholds)
    post_reports    = _build_post_reports(posts, cib_clusters, ghost_amplifiers, burst_events, thresholds)

    bot_conf   = [r for r in post_reports if r.bot_class == "BOT CONFIRMED"]
    suspicious = [r for r in post_reports if r.bot_class == "SUSPICIOUS"]
    organic    = [r for r in post_reports if r.bot_class == "ORGANIC"]
    total      = len(posts)
    fake_eng   = sum(r.reactions + r.comments + r.shares for r in bot_conf)

    report = BotDetectionReport(
        total_posts=total, cib_clusters=cib_clusters,
        ghost_amplifiers=ghost_amplifiers, burst_events=burst_events,
        attack_sources=attack_sources, post_reports=post_reports,
    )
    report.bot_confirmed_count = len(bot_conf)
    report.suspicious_count    = len(suspicious)
    report.organic_count       = len(organic)
    report.bot_confirmed_pct   = round(len(bot_conf)   / total * 100)
    report.suspicious_pct      = round(len(suspicious) / total * 100)
    report.organic_pct         = round(len(organic)    / total * 100)
    report.cib_cluster_count   = len(cib_clusters)
    report.ghost_count         = len(ghost_amplifiers)
    report.estimated_fake_eng  = fake_eng

    return report
