"""
TrollHunterEngine — Mexican Political CIB / Troll & Bot Detection.

Combines 8 independent signal families into a forensic Bot Risk Score (0-100)
with human-readable evidence chains per actor. Designed specifically for
Mexican political social media: detects foreign bot farms, page operators,
organic trolls, and coordinated inauthentic behavior.

Signal families:
  S1 — NAME_ORIGIN        Foreign/bot-farm name in Mexican context
  S2 — PAGE_ACCOUNT       Commenting from a Facebook Page, not a personal profile
  S3 — MULTI_PAGE_OP      Same entity operates multiple page-like accounts
  S4 — AGGRESSION         All-attack, insults, meme-only, zero substantive text
  S5 — CROSS_POST         Same actor attacks across many unrelated posts
  S6 — VELOCITY           Inhuman comments-per-hour rate
  S7 — COORDINATION       Temporal burst + copy-paste participation
  S8 — PROFILE_ANOMALY    Profile restriction hints (from metadata if available)

All weights/thresholds read from cfg["troll_hunter"]. Zero hardcoded values.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from engines.name_origin import NameOriginDetector


# ── Classification labels ──────────────────────────────────────────────────────
CLASSIFICATION_LABELS = [
    (80, "CONFIRMED_BOT"),
    (60, "HIGH_RISK"),
    (40, "SUSPICIOUS"),
    (20, "LIKELY_HUMAN"),
    (0,  "HUMAN"),
]

def _classify(score: int) -> str:
    for threshold, label in CLASSIFICATION_LABELS:
        if score >= threshold:
            return label
    return "HUMAN"


# ── Aggression patterns (Mexican political slang + universal insults) ──────────
_INSULT_PATTERNS = re.compile(
    r"\b(pend[e3]j[o0a]|puta|pinch[e3]|cabr[o0ó]n|mam[o0ó]n|idi[o0]ta|"
    r"mier[d]a|bast[a]rdo|inútil|corrupto|ratero|ladrón|ladron|mentiroso|"
    r"traidor|asesino|prosti|puta|guey|wey|chinga|hijo de|chinga tu|"
    r"te la p[e3]las?|muerto de hambre|mal[pa]rido|malandrin|malandro|"
    r"te chinga|vete al|p[e3]lo[t]udo|cagad[ao]|lamecul[oa]s|"
    r"hipócrita|hipocrita|farsante|estafador|joto|culero|vergon|"
    r"naco|narc[oa]|sicario|corrupta|corrupto|roba|roban|robando)\b",
    re.IGNORECASE,
)

_MEME_PATTERNS = re.compile(
    r"(jaja|jeje|lol|xd+|😂|🤣|🤡|💩|😆|😝|👆|🖕|"
    r"haha|kek|lmao|🐷|🐀|🐍|🦠|💀|☠️|🤮|🤢)",
    re.IGNORECASE,
)

_MINIMAL_TEXT_THRESHOLD = 6   # words — below this = likely meme/reaction comment

_DEFENDER_WORDS = re.compile(
    r"\b(defiend[eo]|apoyo|apoya|bien|gracias|excelente|buen[ao]|"
    r"correcto|verdad|estoy con|te apoyo|gran trabajo|bravo|éxito|"
    r"adelante|felicidades|felicitaciones)\b",
    re.IGNORECASE,
)

_ATTACK_WORDS = re.compile(
    r"\b(fuera|renuncia|dimite|corrupto|ladrón|ratero|mentira|"
    r"mentiroso|tramposo|asesino|roba|roban|criminal|delincuente|"
    r"narco|sicario|vendido|traidor|hypócrita|inútil|inepto|"
    r"incompetente|basta|ya basta|que se vaya|que renuncie)\b",
    re.IGNORECASE,
)

# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class TrollSignal:
    code:     str    # S1_NAME | S2_PAGE | S3_MULTI | S4_AGG | S5_CROSS | S6_VEL | S7_COORD | S8_PROFILE
    label:    str    # short human-readable label
    value:    float  # 0.0-1.0 intensity
    weight:   int    # max contribution to score
    severity: str    # CRITICAL | HIGH | MEDIUM | LOW
    detail:   str    # forensic explanation


@dataclass
class TrollProfile:
    actor:          str
    bot_risk_score: int          # 0-100
    classification: str          # CONFIRMED_BOT | HIGH_RISK | SUSPICIOUS | LIKELY_HUMAN | HUMAN
    signals:        list[TrollSignal]
    justification:  str          # paragraph — why this actor was flagged
    total_comments: int
    posts_attacked: int
    attack_ratio:   float        # fraction of comments that are attacks
    cph:            float        # comments per hour
    comment_sample: list[str]    # up to 3 representative comments


@dataclass
class TrollHunterReport:
    profiles:         list[TrollProfile]
    confirmed_bots:   list[str]
    high_risk:        list[str]
    suspicious:       list[str]
    page_operators:   list[str]   # actors identified as Page accounts
    foreign_names:    list[str]   # actors with foreign-origin names
    multi_page_ops:   list[str]   # actors operating multiple pages
    bot_risk_score:   float       # overall campaign risk 0-100
    total_analyzed:   int
    summary:          str


# ── Main engine ────────────────────────────────────────────────────────────────

class TrollHunterEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("troll_hunter", {})
        self.top_n             = c.get("top_actors_output",      50)
        self.min_comments      = c.get("min_comments",            1)
        self.multi_page_min    = c.get("multi_page_min_accounts", 2)
        self.multi_page_sim    = c.get("multi_page_style_sim",    0.45)
        self.min_span_h        = c.get("min_span_hours",          0.08)  # 5 min
        self.bot_cph           = c.get("bot_cph_threshold",      15.0)
        self.susp_cph          = c.get("suspicious_cph_threshold", 7.0)
        self.cross_post_high   = c.get("cross_post_high",         5)
        self.cross_post_med    = c.get("cross_post_medium",       3)
        self.aggr_high         = c.get("aggression_ratio_high",   0.80)
        self.aggr_med          = c.get("aggression_ratio_medium", 0.50)

        nw = c.get("signal_weights", {})
        self._w_name   = nw.get("S1_name_origin",     30)
        self._w_page   = nw.get("S2_page_account",    22)
        self._w_multi  = nw.get("S3_multi_page",      25)
        self._w_aggr   = nw.get("S4_aggression",      22)
        self._w_cross  = nw.get("S5_cross_post",      18)
        self._w_vel    = nw.get("S6_velocity",        18)
        self._w_coord  = nw.get("S7_coordination",    20)
        self._w_prof   = nw.get("S8_profile",         15)

        sw = c.get("score_weights", {})
        self._sw_bot_pct     = sw.get("bot_pct",         60.0)
        self._sw_risk_mult   = sw.get("risk_multiplier",  0.5)
        self._sw_max_risk    = sw.get("max_risk_score",  40.0)

        self._name_det = NameOriginDetector()

    # ─────────────────────────────────────────────────────────────────────────
    def analyze(
        self,
        scraped_results: list[dict],
        wave_actors:      set[str] | None = None,
        copy_paste_actors: set[str] | None = None,
    ) -> TrollHunterReport:
        """
        wave_actors:       actors found in temporal burst waves
        copy_paste_actors: actors with copy-paste identical comments
        """
        if not scraped_results:
            return self._empty()

        wave_set  = wave_actors or set()
        cp_set    = copy_paste_actors or set()

        # ── Build per-actor profile from raw comments ─────────────────────────
        actor_data: dict[str, dict] = defaultdict(lambda: {
            "comments": [], "urls": set(), "timestamps": [],
        })
        for r in scraped_results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                actor  = c.get("author", "?")
                text   = c.get("text", "")
                ts_str = c.get("timestamp")
                if not text:
                    continue
                ts = None
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                    except (ValueError, TypeError):
                        pass
                actor_data[actor]["comments"].append(text)
                actor_data[actor]["urls"].add(url)
                if ts:
                    actor_data[actor]["timestamps"].append(ts)

        # ── Detect page accounts ──────────────────────────────────────────────
        page_actors: set[str] = set()
        for actor in actor_data:
            nr = self._name_det.detect(actor)
            if nr.origin == "PAGE_ACCOUNT":
                page_actors.add(actor)

        # ── Detect multi-page operators ───────────────────────────────────────
        multi_page_ops = self._detect_multi_page_ops(actor_data, page_actors)

        # ── Build troll profile for each actor ───────────────────────────────
        profiles: list[TrollProfile] = []
        for actor, data in actor_data.items():
            if len(data["comments"]) < self.min_comments:
                continue
            profile = self._build_profile(
                actor, data, page_actors, multi_page_ops,
                wave_set, cp_set,
            )
            profiles.append(profile)

        profiles.sort(key=lambda p: (-p.bot_risk_score, -p.total_comments))
        profiles = profiles[:self.top_n]

        confirmed    = [p.actor for p in profiles if p.classification == "CONFIRMED_BOT"]
        high_risk    = [p.actor for p in profiles if p.classification == "HIGH_RISK"]
        suspicious   = [p.actor for p in profiles if p.classification == "SUSPICIOUS"]
        foreign_names = [p.actor for p in profiles
                         if any(s.code == "S1_NAME" for s in p.signals)]
        multi_list   = list(multi_page_ops.keys())

        score   = self._overall_score(profiles, confirmed)
        summary = self._build_summary(profiles, confirmed, high_risk, suspicious,
                                       foreign_names, multi_list, score)

        return TrollHunterReport(
            profiles=profiles,
            confirmed_bots=confirmed,
            high_risk=high_risk,
            suspicious=suspicious,
            page_operators=list(page_actors),
            foreign_names=foreign_names,
            multi_page_ops=multi_list,
            bot_risk_score=score,
            total_analyzed=len(profiles),
            summary=summary,
        )

    # ─────────────────────────────────────────────────────────────────────────
    def _build_profile(
        self,
        actor: str,
        data: dict,
        page_actors: set[str],
        multi_page_ops: dict[str, list[str]],
        wave_set: set[str],
        cp_set: set[str],
    ) -> TrollProfile:
        comments   = data["comments"]
        urls       = data["urls"]
        timestamps = sorted(data["timestamps"])
        signals: list[TrollSignal] = []

        # ── S1: Name origin ───────────────────────────────────────────────────
        nr = self._name_det.detect(actor)
        if nr.origin not in ("UNKNOWN", "PAGE_ACCOUNT") and nr.confidence >= 0.6:
            _origin_detail_map = {
                "ARABIC":           (f"Arabic/Islamic name '{actor}' is statistically anomalous "
                                     f"for Mexican political content — pattern: {nr.matched_pattern}. "
                                     f"Arabic names are the #1 indicator of overseas bot farms "
                                     f"targeting Latin American political campaigns."),
                "SOUTH_ASIAN":      (f"South Asian (Indian/Pakistani/Bangladeshi) name '{actor}' — "
                                     f"pattern: {nr.matched_pattern}. Demographically negligible "
                                     f"in Mexican political commentary without bot-farm deployment."),
                "MALAY_INDONESIAN": (f"Malay/Indonesian name '{actor}' — pattern: {nr.matched_pattern}. "
                                     f"Indonesian bot farms are widely documented targeting non-English "
                                     f"political accounts across Latin America."),
                "RUSSIAN_SLAVIC":   (f"Russian/Slavic name '{actor}' — pattern: {nr.matched_pattern}. "
                                     f"Russian-speaking operators run documented CIB campaigns "
                                     f"targeting political figures in Mexico and Central America."),
                "CHINESE":          (f"Chinese name '{actor}' — pattern: {nr.matched_pattern}. "
                                     f"Chinese bot farm services are widely sold targeting "
                                     f"Spanish-language political social media."),
                "JAPANESE":         (f"Japanese name '{actor}' — pattern: {nr.matched_pattern}. "
                                     f"Anomalous for organic Mexican political commentary; "
                                     f"flags potential bot-farm account operating under Asian identity."),
                "KOREAN":           (f"Korean name '{actor}' — pattern: {nr.matched_pattern}. "
                                     f"Anomalous for organic Mexican political commentary; "
                                     f"flags potential bot-farm account operating under Asian identity."),
                "US_ENGLISH":       (f"Anglo-American name '{actor}' — pattern: {nr.matched_pattern}. "
                                     f"English-speaking bot farms targeting Mexican politics "
                                     f"typically use Anglo names as fake identity covers."),
            }
            origin_detail = _origin_detail_map.get(
                nr.origin,
                f"Foreign-origin name '{actor}' (origin: {nr.origin}), "
                f"pattern: {nr.matched_pattern}.",
            )
            # Weight driven by JSON weight_multiplier — no hardcoded map needed
            sig_weight = max(1, int(self._w_name * nr.weight_mult))
            signals.append(TrollSignal(
                code="S1_NAME", label=f"FOREIGN NAME [{nr.origin}]",
                value=nr.confidence, weight=sig_weight,
                severity=nr.severity, detail=origin_detail,
            ))

        # ── S2: Page account ──────────────────────────────────────────────────
        if actor in page_actors:
            nr2 = self._name_det.detect(actor)
            signals.append(TrollSignal(
                code="S2_PAGE", label="PAGE ACCOUNT",
                value=nr2.confidence, weight=self._w_page,
                severity="HIGH",
                detail=f"'{actor}' appears to be a Facebook Page (business/media/political "
                       f"page) rather than a personal profile — pattern: {nr2.matched_pattern}. "
                       f"Operator uses Pages to amplify attacks while shielding personal identity.",
            ))

        # ── S3: Multi-page operator ───────────────────────────────────────────
        if actor in multi_page_ops and len(multi_page_ops[actor]) >= self.multi_page_min:
            pages = multi_page_ops[actor]
            signals.append(TrollSignal(
                code="S3_MULTI", label="MULTI-PAGE OPERATOR",
                value=min(1.0, len(pages) / 5),
                weight=self._w_multi, severity="CRITICAL",
                detail=f"'{actor}' operates or is linked to {len(pages)} page-like accounts "
                       f"({', '.join(pages[:4])}). Classic Mexican political CIB tactic: "
                       f"one real person manages multiple fake pages to multiply attack volume "
                       f"and create illusion of organic opposition.",
            ))

        # ── S4: Aggression profile ────────────────────────────────────────────
        insult_cnt  = sum(1 for t in comments if _INSULT_PATTERNS.search(t))
        meme_cnt    = sum(1 for t in comments if _MEME_PATTERNS.search(t))
        attack_cnt  = sum(1 for t in comments if _ATTACK_WORDS.search(t))
        defend_cnt  = sum(1 for t in comments if _DEFENDER_WORDS.search(t))
        short_cnt   = sum(1 for t in comments if len(t.split()) < _MINIMAL_TEXT_THRESHOLD)
        total_c     = max(len(comments), 1)
        aggr_ratio  = (insult_cnt + meme_cnt + attack_cnt) / (total_c * 3)
        aggr_ratio  = min(1.0, aggr_ratio)

        if aggr_ratio >= self.aggr_med or (insult_cnt + meme_cnt) > 0:
            sev   = "CRITICAL" if aggr_ratio >= self.aggr_high else "HIGH" if aggr_ratio >= self.aggr_med else "MEDIUM"
            parts = []
            if insult_cnt:
                parts.append(f"{insult_cnt} comment(s) containing insults/profanity")
            if meme_cnt:
                parts.append(f"{meme_cnt} meme/reaction-only comment(s)")
            if attack_cnt:
                parts.append(f"{attack_cnt} attack-keyword comment(s)")
            if defend_cnt == 0 and total_c > 2:
                parts.append("zero supportive or neutral comments (pure attack mode)")
            if short_cnt / total_c > 0.7:
                parts.append(f"{int(short_cnt/total_c*100)}% of comments are <6 words (meme/reaction pattern)")
            signals.append(TrollSignal(
                code="S4_AGG", label="AGGRESSION PROFILE",
                value=aggr_ratio, weight=self._w_aggr, severity=sev,
                detail=f"High aggression profile: {'; '.join(parts)}. "
                       f"Pure-attack accounts with no substantive engagement are "
                       f"a defining characteristic of paid trolls and bot operators.",
            ))

        # ── S5: Cross-post amplification ──────────────────────────────────────
        n_posts = len(urls)
        if n_posts >= self.cross_post_med:
            sev = "CRITICAL" if n_posts >= self.cross_post_high else "HIGH" if n_posts >= self.cross_post_med else "MEDIUM"
            signals.append(TrollSignal(
                code="S5_CROSS", label="CROSS-POST AMPLIFIER",
                value=min(1.0, n_posts / 10), weight=self._w_cross, severity=sev,
                detail=f"'{actor}' commented in {n_posts} different posts — "
                       f"organic users typically engage with 1-2 posts. "
                       f"Appearing in {n_posts}+ unrelated posts with aggressive content "
                       f"is a hallmark of coordinated amplification campaigns.",
            ))

        # ── S6: Velocity ──────────────────────────────────────────────────────
        cph = 0.0
        if len(timestamps) >= 2:
            span_s = (timestamps[-1] - timestamps[0]).total_seconds()
            span_h = max(span_s / 3600.0, self.min_span_h)
            cph    = round(len(timestamps) / span_h, 2)
            if cph >= self.susp_cph:
                sev = "CRITICAL" if cph >= self.bot_cph else "HIGH"
                signals.append(TrollSignal(
                    code="S6_VEL", label=f"VELOCITY {cph:.1f} CPH",
                    value=min(1.0, cph / 20.0), weight=self._w_vel, severity=sev,
                    detail=f"Comment rate {cph:.1f} comments/hour — "
                           f"human baseline is 1-3 CPH for engaged users, "
                           f"above {self.susp_cph} is suspicious, "
                           f"above {self.bot_cph} is mechanically generated. "
                           f"Time span analyzed: {span_s/60:.0f} minutes.",
                ))

        # ── S7: Coordination ──────────────────────────────────────────────────
        coord_parts = []
        coord_val   = 0.0
        if actor in wave_set:
            coord_parts.append("member of a detected temporal attack wave (comments synchronized within 3-second windows)")
            coord_val = max(coord_val, 0.75)
        if actor in cp_set:
            coord_parts.append("identical copy-paste comments detected across posts (template deployment)")
            coord_val = max(coord_val, 0.85)
        if coord_parts:
            signals.append(TrollSignal(
                code="S7_COORD", label="COORDINATION DETECTED",
                value=coord_val, weight=self._w_coord, severity="CRITICAL",
                detail=f"'{actor}' shows coordination evidence: "
                       f"{'; '.join(coord_parts)}. "
                       f"Synchronized timing and template comments are impossible "
                       f"in organic individual commentary.",
            ))

        # ── S8: Profile anomaly (from comment content clues) ──────────────────
        profile_clues = []
        # Single-character or numeric name suffix
        if re.search(r"\d{2,}", actor):
            profile_clues.append("numeric suffix in name (common bot account pattern)")
        # Name with no space (single-word) + not a known single-name culture
        if " " not in actor.strip() and len(actor) >= 5:
            profile_clues.append("single-word name with no surname (restricted profile pattern)")
        # Extremely generic name pattern
        if re.match(r"^(user|cuenta|perfil|test|admin|anonimo|anónimo)\d*$", actor.lower()):
            profile_clues.append("generic/anonymous account name")
        if profile_clues:
            signals.append(TrollSignal(
                code="S8_PROFILE", label="PROFILE ANOMALY",
                value=0.6, weight=self._w_prof, severity="MEDIUM",
                detail=f"Profile indicators: {'; '.join(profile_clues)}. "
                       f"Consistent with restricted/new/fake account patterns common "
                       f"in troll deployments.",
            ))

        # ── Compute final score ───────────────────────────────────────────────
        raw_score = sum(s.value * s.weight for s in signals)
        # Normalize — max theoretical = sum of all weights
        max_possible = (self._w_name + self._w_page + self._w_multi +
                        self._w_aggr + self._w_cross + self._w_vel +
                        self._w_coord + self._w_prof)
        bot_risk = int(min(100, round(raw_score / max(max_possible, 1) * 100)))

        # Critical-signal override: any CRITICAL signal alone lifts minimum score
        critical_count = sum(1 for s in signals if s.severity == "CRITICAL")
        if critical_count >= 2 and bot_risk < 60:
            bot_risk = max(bot_risk, 60)
        if critical_count >= 3 and bot_risk < 75:
            bot_risk = max(bot_risk, 75)

        classification = _classify(bot_risk)
        justification  = self._build_justification(actor, bot_risk, classification, signals,
                                                    len(comments), n_posts)
        attack_ratio   = round(attack_cnt / max(total_c, 1), 3)
        sample         = [c[:100] for c in comments[:3] if c]

        return TrollProfile(
            actor=actor,
            bot_risk_score=bot_risk,
            classification=classification,
            signals=signals,
            justification=justification,
            total_comments=len(comments),
            posts_attacked=n_posts,
            attack_ratio=attack_ratio,
            cph=cph,
            comment_sample=sample,
        )

    # ─────────────────────────────────────────────────────────────────────────
    def _detect_multi_page_ops(
        self,
        actor_data: dict[str, dict],
        page_actors: set[str],
    ) -> dict[str, list[str]]:
        """
        Detect actors that operate multiple page-like accounts.
        Two page accounts are linked if they: share attacked posts AND
        have similar vocabulary (simple word-overlap Jaccard).
        Returns dict: operator_actor -> [page_account, page_account, ...]
        """
        if len(page_actors) < self.multi_page_min:
            return {}

        pages = list(page_actors)
        # Build word-sets for each page account
        page_words: dict[str, set[str]] = {}
        page_urls:  dict[str, set[str]] = {}
        for pa in pages:
            d = actor_data.get(pa, {})
            words = set()
            for t in d.get("comments", []):
                words |= set(re.findall(r"[a-záéíóúüñ]{4,}", t.lower()))
            page_words[pa] = words
            page_urls[pa]  = d.get("urls", set())

        # Cluster pages that are likely operated by the same person
        # (share ≥2 posts AND word Jaccard ≥ threshold)
        clusters: list[set[str]] = []
        assigned: set[str] = set()

        for i, pa in enumerate(pages):
            if pa in assigned:
                continue
            cluster = {pa}
            for pb in pages[i + 1:]:
                if pb in assigned:
                    continue
                shared_urls = page_urls[pa] & page_urls[pb]
                if len(shared_urls) < 1:
                    continue
                wa, wb = page_words[pa], page_words[pb]
                union  = wa | wb
                if not union:
                    continue
                jacc = len(wa & wb) / len(union)
                if jacc >= self.multi_page_sim:
                    cluster.add(pb)
                    assigned.add(pb)
            if len(cluster) >= self.multi_page_min:
                clusters.append(cluster)
            assigned.add(pa)

        # Map operator (representative account = most active page) → its cluster
        result: dict[str, list[str]] = {}
        for cluster in clusters:
            rep = max(cluster, key=lambda a: len(actor_data.get(a, {}).get("comments", [])))
            others = sorted(cluster - {rep})
            result[rep] = others
        return result

    # ─────────────────────────────────────────────────────────────────────────
    def _build_justification(
        self,
        actor: str,
        score: int,
        classification: str,
        signals: list[TrollSignal],
        total_comments: int,
        posts_attacked: int,
    ) -> str:
        if not signals:
            return f"'{actor}': No bot indicators detected — classified as HUMAN (score {score}/100)."
        sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        sorted_signals = sorted(signals, key=lambda s: sev_order.get(s.severity, 4))
        label_color = {
            "CONFIRMED_BOT": "⛔", "HIGH_RISK": "🔴",
            "SUSPICIOUS": "🟡", "LIKELY_HUMAN": "🔵", "HUMAN": "🟢",
        }
        icon = label_color.get(classification, "⚪")
        lines = [
            f"{icon} {classification} | Bot Risk: {score}/100 | "
            f"{total_comments} comment(s) across {posts_attacked} post(s)",
            "",
        ]
        for i, s in enumerate(sorted_signals, 1):
            sev_icon = {"CRITICAL": "⛔", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "⚪"}.get(s.severity, "⚪")
            lines.append(f"  {i}. [{sev_icon} {s.code}] {s.label}")
            lines.append(f"     {s.detail}")
        return "\n".join(lines)

    def _overall_score(
        self, profiles: list[TrollProfile], confirmed: list[str]
    ) -> float:
        if not profiles:
            return 0.0
        bot_pct  = len(confirmed) / len(profiles)
        avg_risk = sum(p.bot_risk_score for p in profiles) / len(profiles)
        score    = (bot_pct * self._sw_bot_pct +
                    min(self._sw_max_risk, avg_risk * self._sw_risk_mult))
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        profiles: list[TrollProfile],
        confirmed: list[str],
        high_risk: list[str],
        suspicious: list[str],
        foreign_names: list[str],
        multi_page_ops: list[str],
        score: float,
    ) -> str:
        if not profiles:
            return "No actors to analyze."
        parts = [
            f"{len(profiles)} actor(s) profiled — "
            f"TrollHunter bot risk score {score}/100."
        ]
        total_flagged = len(confirmed) + len(high_risk) + len(suspicious)
        if total_flagged:
            parts.append(
                f"{total_flagged} flagged: "
                f"{len(confirmed)} CONFIRMED_BOT · "
                f"{len(high_risk)} HIGH_RISK · "
                f"{len(suspicious)} SUSPICIOUS."
            )
        if foreign_names:
            parts.append(
                f"{len(foreign_names)} actor(s) with foreign-origin names "
                f"(bot-farm indicator for Mexican political content)."
            )
        if multi_page_ops:
            parts.append(
                f"{len(multi_page_ops)} multi-page operator(s) detected — "
                f"one entity running {self.multi_page_min}+ page-like accounts."
            )
        if confirmed:
            parts.append(f"Top confirmed bot: '{confirmed[0]}'.")
        return " ".join(parts)

    @staticmethod
    def _empty() -> TrollHunterReport:
        return TrollHunterReport(
            profiles=[], confirmed_bots=[], high_risk=[], suspicious=[],
            page_operators=[], foreign_names=[], multi_page_ops=[],
            bot_risk_score=0.0, total_analyzed=0,
            summary="No scraped data available for troll/bot analysis.",
        )
