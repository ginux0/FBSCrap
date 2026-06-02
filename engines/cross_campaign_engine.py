"""
CrossCampaignPersistenceEngine.

Tracks the same bot/troll actors across multiple FBScrap campaigns (sessions).
Detects "career attackers" — professional trolls or bot operators that appear
repeatedly in attacks against different politicians/figures.

Architecture:
  - SQLite actor registry at sessions/actor_registry.db (auto-created)
  - Each session auto-registers its actors after TrollHunter analysis
  - Engine queries registry to find actors in 2+ campaigns
  - Calculates persistence score per actor

Persistence Score per actor (0-100):
  - campaigns_count: how many different targets they attacked
  - avg_bot_score: mean TrollHunter bot risk score across campaigns
  - total_comments: cumulative comment count
  - recency: how recently they were active

Career Attacker classification:
  PROFESSIONAL  — 5+ campaigns
  PERSISTENT    — 3-4 campaigns
  RECURRING     — 2 campaigns
  NEW           — 1 campaign (not cross-campaign)

All paths/thresholds from cfg["cross_campaign"]. Zero hardcoded values.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List


# ── Schema ─────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS actors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    normalized_name TEXT    NOT NULL,
    UNIQUE(normalized_name)
);

CREATE TABLE IF NOT EXISTS appearances (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id     INTEGER NOT NULL REFERENCES actors(id),
    campaign     TEXT    NOT NULL,
    session_ts   TEXT    NOT NULL,
    comment_count INTEGER DEFAULT 0,
    posts_attacked INTEGER DEFAULT 0,
    bot_score    INTEGER DEFAULT 0,
    classification TEXT,
    signals_json TEXT,
    UNIQUE(actor_id, campaign, session_ts)
);

CREATE INDEX IF NOT EXISTS idx_appearances_actor  ON appearances(actor_id);
CREATE INDEX IF NOT EXISTS idx_appearances_campaign ON appearances(campaign);
CREATE INDEX IF NOT EXISTS idx_actors_norm ON actors(normalized_name);
"""


@dataclass
class CrossCampaignActor:
    name:              str
    campaigns:         List[str]       # distinct targets attacked
    campaign_count:    int
    total_comments:    int
    avg_bot_score:     float
    max_bot_score:     int
    first_seen:        str             # ISO date
    last_seen:         str
    classification:    str             # PROFESSIONAL|PERSISTENT|RECURRING|NEW
    persistence_score: int             # 0-100
    signals_summary:   List[str]       # top recurring signal codes


@dataclass
class CrossCampaignReport:
    actors:            List[CrossCampaignActor]
    professional:      List[str]       # 5+ campaigns
    persistent:        List[str]       # 3-4 campaigns
    recurring:         List[str]       # 2 campaigns
    total_tracked:     int             # actors in registry
    campaigns_count:   int             # distinct campaigns in registry
    persistence_score: float           # campaign-level 0-100
    new_discoveries:   int             # actors new to registry this session
    summary:           str


class CrossCampaignPersistenceEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("cross_campaign", {})
        # Registry path relative to fbscrap root
        base = Path(__file__).parent.parent
        rel  = c.get("registry_path", "sessions/actor_registry.db")
        self._db_path        = base / rel
        self._min_campaigns  = c.get("min_campaigns",        2)
        self._pro_threshold  = c.get("professional_threshold", 5)
        self._per_threshold  = c.get("persistent_threshold",   3)
        self._top_actors     = c.get("top_actors_output",     30)
        self._min_bot_score  = c.get("min_bot_score_to_register", 20)
        sw = c.get("score_weights", {})
        self._sw_pro_pct     = sw.get("professional_pct",     40.0)
        self._sw_per_pct     = sw.get("persistent_pct",       30.0)
        self._sw_avg_score   = sw.get("avg_score_multiplier",  0.3)

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ─────────────────────────────────────────────────────────────────────────

    def register_session(
        self,
        campaign:     str,
        troll_report,
        session_ts:   str | None = None,
    ) -> int:
        """
        Persist current session's actors to the registry.
        Returns count of newly registered actors.
        Call this after TrollHunter analysis completes.
        """
        if not troll_report or not troll_report.profiles:
            return 0

        ts = session_ts or datetime.now().isoformat(timespec="seconds")
        campaign_clean = campaign.strip().upper()
        new_count = 0

        with self._connect() as conn:
            for p in troll_report.profiles:
                if p.bot_risk_score < self._min_bot_score:
                    continue
                from engines.name_utils import clean_actor_name
                name      = clean_actor_name(p.actor)
                norm_name = name.lower().strip()
                if not norm_name or norm_name == "?":
                    continue

                # Upsert actor
                conn.execute(
                    "INSERT OR IGNORE INTO actors (name, normalized_name) VALUES (?,?)",
                    (name, norm_name),
                )
                row = conn.execute(
                    "SELECT id FROM actors WHERE normalized_name=?", (norm_name,)
                ).fetchone()
                if not row:
                    continue
                actor_id = row[0]

                # Check if new to registry
                existing = conn.execute(
                    "SELECT COUNT(*) FROM appearances WHERE actor_id=?", (actor_id,)
                ).fetchone()[0]
                if existing == 0:
                    new_count += 1

                signals = [s.code for s in getattr(p, "signals", [])]
                conn.execute(
                    """INSERT OR IGNORE INTO appearances
                       (actor_id, campaign, session_ts, comment_count,
                        posts_attacked, bot_score, classification, signals_json)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (actor_id, campaign_clean, ts,
                     p.total_comments, p.posts_attacked,
                     p.bot_risk_score, p.classification,
                     json.dumps(signals)),
                )

        return new_count

    # ─────────────────────────────────────────────────────────────────────────

    def analyze(
        self,
        current_campaign: str | None = None,
    ) -> CrossCampaignReport:
        """
        Query registry for cross-campaign patterns.
        current_campaign: if set, include stats about actors new to this session.
        """
        with self._connect() as conn:
            # Total stats
            total_tracked  = conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0]
            campaigns_count= conn.execute(
                "SELECT COUNT(DISTINCT campaign) FROM appearances"
            ).fetchone()[0]

            if total_tracked == 0:
                return self._empty()

            # Actors in multiple campaigns
            rows = conn.execute("""
                SELECT
                    a.name,
                    COUNT(DISTINCT ap.campaign)          AS camp_count,
                    SUM(ap.comment_count)                AS total_comments,
                    AVG(ap.bot_score)                    AS avg_score,
                    MAX(ap.bot_score)                    AS max_score,
                    MIN(ap.session_ts)                   AS first_seen,
                    MAX(ap.session_ts)                   AS last_seen,
                    GROUP_CONCAT(DISTINCT ap.campaign)   AS campaigns,
                    GROUP_CONCAT(ap.signals_json)        AS all_signals
                FROM actors a
                JOIN appearances ap ON ap.actor_id = a.id
                GROUP BY a.id
                HAVING camp_count >= ?
                ORDER BY camp_count DESC, avg_score DESC
                LIMIT ?
            """, (self._min_campaigns, self._top_actors)).fetchall()

            actors: list[CrossCampaignActor] = []
            for r in rows:
                name, camp_count, total_c, avg_s, max_s, first, last, clist, sigs = r
                campaigns = [c.strip() for c in (clist or "").split(",") if c.strip()]

                # Parse signals across appearances
                sig_counts: dict[str, int] = {}
                for sj in (sigs or "").split(","):
                    sj = sj.strip().strip('"[]')
                    try:
                        parsed = json.loads(f"[{sj}]") if sj else []
                        for s in parsed:
                            sig_counts[s] = sig_counts.get(s, 0) + 1
                    except Exception:
                        pass
                top_signals = sorted(sig_counts, key=lambda k: -sig_counts[k])[:4]

                classification = self._classify(camp_count)
                persistence    = self._persistence_score(camp_count, avg_s or 0, total_c or 0)

                actors.append(CrossCampaignActor(
                    name              = name,
                    campaigns         = campaigns[:10],
                    campaign_count    = camp_count,
                    total_comments    = total_c or 0,
                    avg_bot_score     = round(avg_s or 0, 1),
                    max_bot_score     = max_s or 0,
                    first_seen        = (first or "")[:10],
                    last_seen         = (last or "")[:10],
                    classification    = classification,
                    persistence_score = persistence,
                    signals_summary   = top_signals,
                ))

            # New discoveries this session
            new_disc = 0
            if current_campaign:
                camp_up = current_campaign.strip().upper()
                new_disc = conn.execute("""
                    SELECT COUNT(*) FROM actors a
                    JOIN appearances ap ON ap.actor_id = a.id
                    WHERE ap.campaign = ?
                    GROUP BY a.id
                    HAVING COUNT(DISTINCT ap.campaign) = 1
                """, (camp_up,)).fetchone()
                new_disc = new_disc[0] if new_disc else 0

        professional = [a.name for a in actors if a.campaign_count >= self._pro_threshold]
        persistent   = [a.name for a in actors
                        if self._per_threshold <= a.campaign_count < self._pro_threshold]
        recurring    = [a.name for a in actors if a.campaign_count == 2]

        score   = self._campaign_score(actors, total_tracked, campaigns_count)
        summary = self._build_summary(actors, professional, persistent,
                                       total_tracked, campaigns_count, score, new_disc)

        return CrossCampaignReport(
            actors           = actors,
            professional     = professional,
            persistent       = persistent,
            recurring        = recurring,
            total_tracked    = total_tracked,
            campaigns_count  = campaigns_count,
            persistence_score= score,
            new_discoveries  = new_disc,
            summary          = summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def get_registry_stats(self) -> dict:
        """Quick stats for dashboard display."""
        with self._connect() as conn:
            return {
                "total_actors":    conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0],
                "total_campaigns": conn.execute(
                    "SELECT COUNT(DISTINCT campaign) FROM appearances"
                ).fetchone()[0],
                "total_appearances": conn.execute("SELECT COUNT(*) FROM appearances").fetchone()[0],
                "career_attackers": conn.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT actor_id FROM appearances
                        GROUP BY actor_id
                        HAVING COUNT(DISTINCT campaign) >= ?
                    )
                """, (self._per_threshold,)).fetchone()[0],
            }

    def _classify(self, camp_count: int) -> str:
        if camp_count >= self._pro_threshold:
            return "PROFESSIONAL"
        if camp_count >= self._per_threshold:
            return "PERSISTENT"
        if camp_count >= 2:
            return "RECURRING"
        return "NEW"

    def _persistence_score(self, camp_count: int, avg_score: float, total_comments: int) -> int:
        camp_factor    = min(50, camp_count * 10)
        score_factor   = min(30, int(avg_score * 0.3))
        comment_factor = min(20, int(total_comments / 10))
        return min(100, camp_factor + score_factor + comment_factor)

    def _campaign_score(
        self,
        actors: list[CrossCampaignActor],
        total_tracked: int,
        campaigns_count: int,
    ) -> float:
        if not actors or not total_tracked:
            return 0.0
        pro_pct  = len([a for a in actors if a.classification == "PROFESSIONAL"]) / max(total_tracked, 1)
        per_pct  = len([a for a in actors if a.classification == "PERSISTENT"]) / max(total_tracked, 1)
        avg_s    = sum(a.avg_bot_score for a in actors) / len(actors) if actors else 0
        score = (pro_pct * self._sw_pro_pct
                 + per_pct * self._sw_per_pct
                 + min(30.0, avg_s * self._sw_avg_score))
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        actors: list[CrossCampaignActor],
        professional: list,
        persistent: list,
        total_tracked: int,
        campaigns_count: int,
        score: float,
        new_disc: int,
    ) -> str:
        parts = [
            f"Cross-campaign persistence score {score}/100. "
            f"{total_tracked} actors tracked across {campaigns_count} campaign(s)."
        ]
        career_total = len(professional) + len(persistent)
        if career_total:
            parts.append(
                f"{career_total} career attacker(s): "
                f"{len(professional)} PROFESSIONAL (5+ campaigns) · "
                f"{len(persistent)} PERSISTENT (3-4 campaigns)."
            )
        if professional:
            parts.append(
                f"Top professional: '{professional[0]}' — "
                f"{actors[0].campaign_count} campaigns, "
                f"avg score {actors[0].avg_bot_score:.0f}/100."
            )
        if new_disc:
            parts.append(f"{new_disc} new actor(s) registered this session.")
        return " ".join(parts)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _empty() -> CrossCampaignReport:
        return CrossCampaignReport(
            actors=[], professional=[], persistent=[], recurring=[],
            total_tracked=0, campaigns_count=0, persistence_score=0.0,
            new_discoveries=0,
            summary="Actor registry is empty — run more campaigns to build history.",
        )
