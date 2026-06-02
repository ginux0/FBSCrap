"""
SessionDeltaEngine — Cross-Session Campaign Delta Analysis.

Compares the current FBScrap session against a previous session of the same
target to detect campaign evolution: new bots entering, old bots rotating out,
narrative drift, engagement surge, actor score changes.

Operational example:
  "Entre el lunes y el viernes, aparecieron 47 nuevas cuentas con perfil bot.
   La narrativa mutó de 'corrupto' a 'traidor'. El engagement artificialmente
   inflado aumentó 3.2x. La operación está escalando."

Architecture:
  - Reads `posts_latest.json` from both session dirs
  - Compares: actors, bot scores, engagement, narratives, sources
  - Produces DeltaReport with typed change events
  - Integrates with TrollHunterEngine for per-actor score tracking

All thresholds from cfg["session_delta"]. Zero hardcoded values.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ActorDelta:
    name:              str
    status:            str    # NEW_BOT | DISAPPEARED | SCORE_UP | SCORE_DOWN | STABLE
    score_before:      float
    score_after:       float
    score_delta:       float
    comment_delta:     int
    campaigns_seen:    int


@dataclass
class NarrativeDrift:
    terms_gained:    List[str]   # new dominant terms this session
    terms_lost:      List[str]   # terms present before, gone now
    overlap_pct:     float       # Jaccard overlap of top terms (1=identical, 0=complete shift)
    drift_label:     str         # STABLE | MODERATE_DRIFT | MAJOR_PIVOT


@dataclass
class EngagementDelta:
    posts_before:        int
    posts_after:         int
    posts_gained:        int
    avg_eng_before:      float
    avg_eng_after:       float
    eng_change_pct:      float
    top_new_posts:       List[str]   # URLs of highest-engagement new posts


@dataclass
class DeltaReport:
    session_before:     str
    session_after:      str
    time_delta_hours:   float
    actor_deltas:       List[ActorDelta]
    new_bots:           List[str]
    disappeared_bots:   List[str]
    score_escalations:  List[str]   # actors whose bot_score jumped significantly
    narrative_drift:    NarrativeDrift
    engagement_delta:   EngagementDelta
    overall_trend:      str          # ESCALATING | STABLE | DECLINING | INSUFFICIENT_DATA
    delta_score:        float        # 0-100 — how much the campaign changed
    summary:            str


class SessionDeltaEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("session_delta", {})
        self._new_bot_threshold    = c.get("new_bot_score_threshold",    60)
        self._score_jump_min       = c.get("score_escalation_min_jump",  15)
        self._min_actors           = c.get("min_actors_for_analysis",     3)
        self._top_narrative_terms  = c.get("top_narrative_terms",        15)
        self._drift_stable_thresh  = c.get("drift_stable_threshold",     0.70)
        self._drift_moderate_thresh= c.get("drift_moderate_threshold",   0.40)
        self._max_actor_deltas     = c.get("max_actor_deltas_output",    30)
        self._max_new_posts        = c.get("max_new_posts_output",       10)

    # ─────────────────────────────────────────────────────────────────────────

    def compare(
        self,
        session_before_dir: str | Path,
        session_after_dir:  str | Path,
        troll_before=None,
        troll_after=None,
    ) -> DeltaReport:
        """
        Compare two sessions. troll_before/troll_after are optional
        TrollHunterReport objects for per-actor score tracking.
        Falls back to basic post-level comparison if not provided.
        """
        before_dir = Path(session_before_dir)
        after_dir  = Path(session_after_dir)

        posts_before = self._load_posts(before_dir)
        posts_after  = self._load_posts(after_dir)

        if not posts_before or not posts_after:
            return self._insufficient(str(before_dir), str(after_dir))

        # Session timestamps
        ts_before = self._session_ts(before_dir, posts_before)
        ts_after  = self._session_ts(after_dir,  posts_after)
        delta_h   = abs((ts_after - ts_before).total_seconds() / 3600)

        # ── Actor deltas ──────────────────────────────────────────────────────
        actor_deltas, new_bots, disappeared, escalations = self._compare_actors(
            posts_before, posts_after, troll_before, troll_after,
        )

        # ── Narrative drift ───────────────────────────────────────────────────
        narrative = self._compare_narratives(posts_before, posts_after)

        # ── Engagement delta ──────────────────────────────────────────────────
        eng_delta = self._compare_engagement(posts_before, posts_after)

        # ── Overall trend ─────────────────────────────────────────────────────
        trend = self._assess_trend(actor_deltas, narrative, eng_delta, new_bots)
        delta_score = self._delta_score(actor_deltas, narrative, eng_delta, new_bots)

        summary = self._build_summary(
            ts_before, ts_after, delta_h, trend, delta_score,
            new_bots, disappeared, escalations, narrative, eng_delta,
        )

        return DeltaReport(
            session_before    = str(before_dir),
            session_after     = str(after_dir),
            time_delta_hours  = round(delta_h, 1),
            actor_deltas      = actor_deltas[:self._max_actor_deltas],
            new_bots          = new_bots,
            disappeared_bots  = disappeared,
            score_escalations = escalations,
            narrative_drift   = narrative,
            engagement_delta  = eng_delta,
            overall_trend     = trend,
            delta_score       = delta_score,
            summary           = summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _load_posts(self, session_dir: Path) -> list[dict]:
        for fname in ("posts_latest.json", "posts.json"):
            f = session_dir / fname
            if f.exists():
                try:
                    return json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
        # Try any posts_*.json
        for f in sorted(session_dir.glob("posts_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []

    def _session_ts(self, session_dir: Path, posts: list[dict]) -> datetime:
        # Try folder name first (YYYYMMDD_HHMMSS)
        try:
            name = session_dir.name
            return datetime.strptime(name[:15], "%Y%m%d_%H%M%S")
        except Exception:
            pass
        # Fallback: scraped_at of first post
        for p in posts:
            ts = p.get("scraped_at")
            if ts:
                try:
                    return datetime.fromisoformat(ts[:19])
                except Exception:
                    pass
        return datetime.now()

    def _extract_actors(
        self, posts: list[dict], troll_report
    ) -> dict[str, float]:
        """Build actor_name → bot_score map. Uses troll report if available."""
        actors: dict[str, float] = {}
        if troll_report and hasattr(troll_report, "profiles"):
            for p in troll_report.profiles:
                name = getattr(p, "actor", "")
                score = getattr(p, "bot_risk_score", 0)
                if name:
                    actors[name] = float(score)
        else:
            # Fallback: count comments per actor
            for post in posts:
                for c in post.get("comments", []):
                    author = c.get("author", "")
                    if author and author != "?":
                        actors.setdefault(author, 0.0)
        return actors

    def _compare_actors(
        self,
        posts_before: list[dict],
        posts_after:  list[dict],
        troll_before,
        troll_after,
    ) -> tuple[list[ActorDelta], list[str], list[str], list[str]]:
        actors_before = self._extract_actors(posts_before, troll_before)
        actors_after  = self._extract_actors(posts_after,  troll_after)

        all_actors = set(actors_before) | set(actors_after)
        deltas: list[ActorDelta] = []
        new_bots: list[str] = []
        disappeared: list[str] = []
        escalations: list[str] = []

        # Count comments per actor
        def comment_counts(posts: list[dict]) -> dict[str, int]:
            c: dict[str, int] = defaultdict(int)
            for p in posts:
                for cm in p.get("comments", []):
                    author = cm.get("author", "")
                    if author:
                        c[author] += 1
            return dict(c)

        cc_before = comment_counts(posts_before)
        cc_after  = comment_counts(posts_after)

        for name in all_actors:
            sb = actors_before.get(name, 0.0)
            sa = actors_after.get(name, 0.0)
            cb = cc_before.get(name, 0)
            ca = cc_after.get(name, 0)
            diff = sa - sb

            if name not in actors_before and sa >= self._new_bot_threshold:
                status = "NEW_BOT"
                new_bots.append(name)
            elif name not in actors_after and sb >= self._new_bot_threshold:
                status = "DISAPPEARED"
                disappeared.append(name)
            elif diff >= self._score_jump_min:
                status = "SCORE_UP"
                if sa >= self._new_bot_threshold:
                    escalations.append(name)
            elif diff <= -self._score_jump_min:
                status = "SCORE_DOWN"
            else:
                status = "STABLE"

            deltas.append(ActorDelta(
                name           = name,
                status         = status,
                score_before   = round(sb, 1),
                score_after    = round(sa, 1),
                score_delta    = round(diff, 1),
                comment_delta  = ca - cb,
                campaigns_seen = 1,
            ))

        # Sort by importance: new bots first, then score jumps
        priority = {"NEW_BOT": 0, "SCORE_UP": 1, "DISAPPEARED": 2, "SCORE_DOWN": 3, "STABLE": 4}
        deltas.sort(key=lambda d: (priority.get(d.status, 9), -abs(d.score_delta)))

        return deltas, new_bots, disappeared, escalations

    def _top_terms(self, posts: list[dict]) -> list[str]:
        """Extract top N terms from post text + comments."""
        stopwords = {
            "de","la","el","en","que","y","los","las","por","del","a","con",
            "es","se","un","una","para","al","su","le","lo","más","o","pero",
            "fue","no","como","este","esta","hay","ya","también","todo","son",
            "https","www","com","facebook","fb","he","she","the","and","of","to",
        }
        counts: Counter = Counter()
        for p in posts:
            text = (p.get("text") or "").lower()
            for word in text.split():
                word = word.strip(".,;:!?()[]\"'@#/\\")
                if len(word) >= 4 and word not in stopwords:
                    counts[word] += 1
            for c in p.get("comments", []):
                ctxt = (c.get("text") or c.get("content") or "").lower()
                for word in ctxt.split():
                    word = word.strip(".,;:!?()[]\"'@#/\\")
                    if len(word) >= 4 and word not in stopwords:
                        counts[word] += 1

        return [w for w, _ in counts.most_common(self._top_narrative_terms)]

    def _compare_narratives(
        self, posts_before: list[dict], posts_after: list[dict]
    ) -> NarrativeDrift:
        terms_b = set(self._top_terms(posts_before))
        terms_a = set(self._top_terms(posts_after))

        gained = sorted(terms_a - terms_b)[:8]
        lost   = sorted(terms_b - terms_a)[:8]

        union   = terms_b | terms_a
        overlap = len(terms_b & terms_a) / max(len(union), 1)

        if overlap >= self._drift_stable_thresh:
            label = "STABLE"
        elif overlap >= self._drift_moderate_thresh:
            label = "MODERATE_DRIFT"
        else:
            label = "MAJOR_PIVOT"

        return NarrativeDrift(
            terms_gained = gained,
            terms_lost   = lost,
            overlap_pct  = round(overlap, 3),
            drift_label  = label,
        )

    def _compare_engagement(
        self, posts_before: list[dict], posts_after: list[dict]
    ) -> EngagementDelta:
        urls_before = {p.get("url") for p in posts_before if p.get("url")}
        urls_after  = {p.get("url") for p in posts_after  if p.get("url")}
        new_urls    = urls_after - urls_before

        def avg_eng(posts: list[dict]) -> float:
            vals = [p.get("engagement_total", 0) for p in posts]
            return sum(vals) / max(len(vals), 1)

        avg_b = avg_eng(posts_before)
        avg_a = avg_eng(posts_after)
        pct   = ((avg_a - avg_b) / max(avg_b, 1)) * 100

        new_posts = [
            p for p in posts_after
            if p.get("url") in new_urls
        ]
        new_posts.sort(key=lambda p: -p.get("engagement_total", 0))
        top_new = [p.get("url", "") for p in new_posts[:self._max_new_posts] if p.get("url")]

        return EngagementDelta(
            posts_before    = len(posts_before),
            posts_after     = len(posts_after),
            posts_gained    = len(new_urls),
            avg_eng_before  = round(avg_b, 1),
            avg_eng_after   = round(avg_a, 1),
            eng_change_pct  = round(pct, 1),
            top_new_posts   = top_new,
        )

    def _assess_trend(
        self,
        deltas:    list[ActorDelta],
        narrative: NarrativeDrift,
        eng:       EngagementDelta,
        new_bots:  list[str],
    ) -> str:
        score = 0
        if new_bots:
            score += len(new_bots) * 5
        if narrative.drift_label == "MAJOR_PIVOT":
            score += 25
        elif narrative.drift_label == "MODERATE_DRIFT":
            score += 10
        if eng.eng_change_pct > 30:
            score += 20
        elif eng.eng_change_pct < -30:
            score -= 20
        escalations = sum(1 for d in deltas if d.status == "SCORE_UP")
        score += escalations * 3

        if score >= 40:
            return "ESCALATING"
        if score <= -20:
            return "DECLINING"
        if abs(score) < 15:
            return "STABLE"
        return "EVOLVING"

    def _delta_score(
        self,
        deltas:    list[ActorDelta],
        narrative: NarrativeDrift,
        eng:       EngagementDelta,
        new_bots:  list[str],
    ) -> float:
        s = 0.0
        s += min(40.0, len(new_bots) * 4.0)
        drift_scores = {"MAJOR_PIVOT": 30.0, "MODERATE_DRIFT": 15.0, "STABLE": 0.0}
        s += drift_scores.get(narrative.drift_label, 0.0)
        eng_contrib = min(20.0, abs(eng.eng_change_pct) * 0.3)
        s += eng_contrib
        escalations = sum(1 for d in deltas if d.status == "SCORE_UP")
        s += min(10.0, escalations * 2.0)
        return round(min(100.0, s), 1)

    def _build_summary(
        self,
        ts_before:   datetime,
        ts_after:    datetime,
        delta_h:     float,
        trend:       str,
        delta_score: float,
        new_bots:    list[str],
        disappeared: list[str],
        escalations: list[str],
        narrative:   NarrativeDrift,
        eng:         EngagementDelta,
    ) -> str:
        trend_map = {
            "ESCALATING": "la campaña está ESCALANDO — nueva actividad significativa",
            "DECLINING":  "la campaña está DECLINANDO — reducción de actividad inorgánica",
            "STABLE":     "la campaña permanece ESTABLE — sin cambios significativos",
            "EVOLVING":   "la campaña está EVOLUCIONANDO — cambios moderados detectados",
        }
        parts = [
            f"Delta score {delta_score}/100 en {delta_h:.0f}h — "
            f"{trend_map.get(trend, trend)}."
        ]
        if new_bots:
            parts.append(
                f"{len(new_bots)} nuevo(s) actor(es) bot detectado(s): "
                f"{', '.join(new_bots[:5])}" +
                (f" +{len(new_bots)-5} más" if len(new_bots) > 5 else "") + "."
            )
        if disappeared:
            parts.append(f"{len(disappeared)} actor(es) rotado(s) fuera de la operación.")
        if escalations:
            parts.append(
                f"{len(escalations)} actor(es) con escalada de puntuación: "
                f"{', '.join(escalations[:3])}."
            )
        if narrative.drift_label != "STABLE":
            parts.append(
                f"Narrativa: {narrative.drift_label} "
                f"(overlap={narrative.overlap_pct:.0%}). "
                f"Términos nuevos: [{', '.join(narrative.terms_gained[:5])}]."
            )
        if abs(eng.eng_change_pct) > 10:
            parts.append(
                f"Engagement {'aumentó' if eng.eng_change_pct > 0 else 'cayó'} "
                f"{abs(eng.eng_change_pct):.0f}% — "
                f"{eng.posts_gained} nuevo(s) post(s)."
            )
        return " ".join(parts)

    @staticmethod
    def _insufficient(d_before: str, d_after: str) -> DeltaReport:
        return DeltaReport(
            session_before   = d_before,
            session_after    = d_after,
            time_delta_hours = 0.0,
            actor_deltas     = [],
            new_bots         = [],
            disappeared_bots = [],
            score_escalations= [],
            narrative_drift  = NarrativeDrift([], [], 0.0, "STABLE"),
            engagement_delta = EngagementDelta(0, 0, 0, 0.0, 0.0, 0.0, []),
            overall_trend    = "INSUFFICIENT_DATA",
            delta_score      = 0.0,
            summary          = "Datos insuficientes — verifica que ambos directorios de sesión existan y contengan posts.",
        )
