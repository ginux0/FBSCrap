"""
MonitorEngine — Live Campaign Monitor Mode.

Polls a target (page or search query) on a configurable interval, detects
new activity, and fires Telegram alerts when bot campaigns are detected or
when CIB score crosses thresholds.

Operational example:
  fbscrap.py monitor --query "target name" --monitor-interval 300
  → Runs every 5 min. On spike: Telegram → "🚨 ALERT CIB: 23 new bots detected"

Delta detection per cycle:
  - New posts with engagement above threshold
  - New bot actors (score >= bot_threshold)
  - CIB score jump since last cycle
  - Narrative pivot (new terms entering top 10)

All thresholds, intervals, Telegram credentials from cfg["monitor"].
Zero hardcoded values.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class MonitorAlert:
    alert_id:        str
    triggered_at:    str          # ISO
    alert_type:      str          # NEW_BOTS | CIB_SPIKE | NARRATIVE_PIVOT | ENGAGEMENT_SURGE
    severity:        str          # CRITICAL | HIGH | MEDIUM | INFO
    cib_score_now:   float
    cib_score_prev:  float
    new_bot_count:   int
    new_bots:        List[str]
    new_post_count:  int
    top_new_post:    str | None
    pivot_terms:     List[str]
    message:         str          # human-readable alert text (Spanish)
    raw_summary:     str


@dataclass
class MonitorCycleResult:
    cycle_id:        int
    scanned_at:      str          # ISO
    posts_found:     int
    cib_score:       float
    alert:           MonitorAlert | None
    session_dir:     str


class MonitorEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("monitor", {})
        self._interval_s          = c.get("interval_seconds",            300)
        self._bot_threshold       = c.get("bot_score_threshold",          60)
        self._new_bot_alert_min   = c.get("new_bot_alert_min",             3)
        self._cib_spike_min       = c.get("cib_spike_threshold",          15.0)
        self._cib_alert_min       = c.get("cib_alert_minimum_score",      40.0)
        self._eng_surge_pct       = c.get("engagement_surge_pct",         50.0)
        self._pivot_terms_min     = c.get("narrative_pivot_terms_min",     4)
        self._telegram_token      = c.get("telegram_token",                "")
        self._telegram_chat       = c.get("telegram_chat_id",              "")
        self._telegram_enabled    = c.get("telegram_enabled",           False)
        self._state_file_suffix   = c.get("state_file",        "monitor_state.json")

    # ─────────────────────────────────────────────────────────────────────────

    def check_delta(
        self,
        current_posts:    list[dict],
        current_cib:      float,
        state_dir:        Path,
        troll_report=None,
    ) -> MonitorCycleResult:
        """
        Main delta check per monitoring cycle.
        Loads previous state from state_dir, compares, optionally fires alert.
        Returns MonitorCycleResult (alert may be None if nothing significant).
        """
        state_file = state_dir / self._state_file_suffix
        prev_state = self._load_state(state_file)
        now        = datetime.now().isoformat(timespec="seconds")

        cycle_id   = prev_state.get("cycle_id", 0) + 1
        session_dir= str(state_dir)

        # Extract current bots
        current_bots: set[str] = set()
        if troll_report and hasattr(troll_report, "profiles"):
            current_bots = {
                p.actor for p in troll_report.profiles
                if getattr(p, "bot_risk_score", 0) >= self._bot_threshold
            }
        prev_bots: set[str] = set(prev_state.get("known_bots", []))
        new_bots = sorted(current_bots - prev_bots)

        # Narrative terms
        current_terms  = set(self._extract_terms(current_posts, top_n=10))
        prev_terms     = set(prev_state.get("top_terms", []))
        pivot_terms    = sorted(current_terms - prev_terms)

        # Engagement
        avg_eng_now    = self._avg_engagement(current_posts)
        avg_eng_prev   = float(prev_state.get("avg_engagement", avg_eng_now))
        eng_change_pct = ((avg_eng_now - avg_eng_prev) / max(avg_eng_prev, 1)) * 100

        prev_cib       = float(prev_state.get("cib_score", 0.0))
        cib_delta      = current_cib - prev_cib

        # Determine if alert should fire
        alert = self._evaluate_alert(
            cycle_id       = cycle_id,
            now            = now,
            new_bots       = new_bots,
            cib_now        = current_cib,
            cib_prev       = prev_cib,
            cib_delta      = cib_delta,
            eng_change_pct = eng_change_pct,
            pivot_terms    = pivot_terms,
            current_posts  = current_posts,
        )

        # Persist state
        new_state = {
            "cycle_id":       cycle_id,
            "last_run":       now,
            "known_bots":     sorted(current_bots),
            "top_terms":      sorted(current_terms),
            "avg_engagement": avg_eng_now,
            "cib_score":      current_cib,
        }
        self._save_state(state_file, new_state)

        # Fire Telegram if alert and enabled
        if alert and self._telegram_enabled:
            self._send_telegram(alert.message)

        return MonitorCycleResult(
            cycle_id    = cycle_id,
            scanned_at  = now,
            posts_found = len(current_posts),
            cib_score   = current_cib,
            alert       = alert,
            session_dir = session_dir,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _evaluate_alert(
        self,
        cycle_id:       int,
        now:            str,
        new_bots:       list[str],
        cib_now:        float,
        cib_prev:       float,
        cib_delta:      float,
        eng_change_pct: float,
        pivot_terms:    list[str],
        current_posts:  list[dict],
    ) -> MonitorAlert | None:
        alert_type = None
        severity   = "INFO"
        parts: list[str] = []

        if len(new_bots) >= self._new_bot_alert_min:
            alert_type = "NEW_BOTS"
            severity   = "CRITICAL" if len(new_bots) >= 10 else "HIGH"
            parts.append(f"🤖 {len(new_bots)} new bot(s): {', '.join(new_bots[:5])}")

        if cib_delta >= self._cib_spike_min and cib_now >= self._cib_alert_min:
            alert_type = alert_type or "CIB_SPIKE"
            severity   = "CRITICAL" if cib_now >= 80 else "HIGH"
            parts.append(f"⚡ CIB score jumped {cib_delta:+.0f}pts → {cib_now:.0f}/100")

        if len(pivot_terms) >= self._pivot_terms_min:
            alert_type = alert_type or "NARRATIVE_PIVOT"
            severity   = severity if severity != "INFO" else "MEDIUM"
            parts.append(f"📌 Narrative pivot — new terms: {', '.join(pivot_terms[:5])}")

        if eng_change_pct >= self._eng_surge_pct:
            alert_type = alert_type or "ENGAGEMENT_SURGE"
            severity   = severity if severity != "INFO" else "MEDIUM"
            parts.append(f"📈 Engagement +{eng_change_pct:.0f}% vs previous cycle")

        if not alert_type:
            return None

        top_post = None
        if current_posts:
            top = max(current_posts, key=lambda p: p.get("engagement_total", 0))
            top_post = top.get("url")

        raw_sum = f"cycle={cycle_id} cib={cib_now:.0f} new_bots={len(new_bots)} " \
                  f"cib_delta={cib_delta:+.0f} pivot_terms={len(pivot_terms)}"
        message = (
            f"🚨 FBSCRAP MONITOR [{severity}] — {alert_type}\n"
            + "\n".join(f"  • {p}" for p in parts)
            + f"\n  📊 CIB score: {cib_now:.0f}/100 | Ciclo #{cycle_id}"
        )

        return MonitorAlert(
            alert_id       = f"MON-{cycle_id:04d}-{now[:10]}",
            triggered_at   = now,
            alert_type     = alert_type,
            severity       = severity,
            cib_score_now  = round(cib_now, 1),
            cib_score_prev = round(cib_prev, 1),
            new_bot_count  = len(new_bots),
            new_bots       = new_bots[:20],
            new_post_count = len(current_posts),
            top_new_post   = top_post,
            pivot_terms    = pivot_terms[:8],
            message        = message,
            raw_summary    = raw_sum,
        )

    def _send_telegram(self, message: str) -> bool:
        """Send alert via Telegram Bot API. Returns True on success."""
        if not self._telegram_token or not self._telegram_chat:
            return False
        try:
            import urllib.request
            import urllib.parse
            url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id":    self._telegram_chat,
                "text":       message,
                "parse_mode": "HTML",
            }).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False

    def format_alert_summary(self, results: list[MonitorCycleResult]) -> str:
        """Format a multi-cycle summary for display."""
        lines = [f"MONITOR STATUS — {len(results)} cycle(s)"]
        for r in results:
            alert_str = f"⚠ {r.alert.alert_type} [{r.alert.severity}]" if r.alert else "✓ clean"
            lines.append(
                f"  [{r.scanned_at[:16]}] cycle={r.cycle_id} "
                f"posts={r.posts_found} cib={r.cib_score:.0f}/100 — {alert_str}"
            )
        alerts = [r for r in results if r.alert]
        if alerts:
            lines.append(f"  TOTAL ALERTS: {len(alerts)}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_terms(posts: list[dict], top_n: int = 10) -> list[str]:
        from collections import Counter
        stopwords = {
            "de","la","el","en","que","y","los","las","por","del","a","con",
            "es","se","un","una","para","al","su","le","lo","más","o","pero",
            "https","www","com","facebook","fb",
        }
        counts: Counter = Counter()
        for p in posts:
            for word in (p.get("text") or "").lower().split():
                w = word.strip(".,;:!?()[]\"'@#/\\")
                if len(w) >= 4 and w not in stopwords:
                    counts[w] += 1
        return [w for w, _ in counts.most_common(top_n)]

    @staticmethod
    def _avg_engagement(posts: list[dict]) -> float:
        if not posts:
            return 0.0
        vals = [p.get("engagement_total", 0) for p in posts]
        return sum(vals) / len(vals)

    @staticmethod
    def _load_state(state_file: Path) -> dict:
        if state_file.exists():
            try:
                return json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    @staticmethod
    def _save_state(state_file: Path, state: dict) -> None:
        try:
            state_file.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
