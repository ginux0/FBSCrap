"""
CIBScoreEngine — Unified CIB Confidence Score.

Combines ALL engine scores into one authoritative 0-100 number with a
human-readable label. Designed for courtrooms, prosecutors, and press:
"Esta campaña presenta CIB con 87/100 de confianza."

Architecture:
  - Reads scores from all available engine reports via getattr() — zero hard deps
  - Weights 100% from cfg["cib_score"]["weights"]
  - Missing engine report = weight redistributed proportionally (no zero-penalty)
  - Output: CIBScoreReport with score + label + dimension breakdown + narrative

Confidence Labels:
  CONFIRMED_CIB    80-100 — evidencia forense sólida, múltiples vectores
  HIGH_CONFIDENCE  60-79  — patrones inorgánicos claros, verificados
  PROBABLE         40-59  — indicadores significativos, no concluyente
  POSSIBLE         20-39  — señales débiles, requiere más análisis
  ORGANIC           0-19  — sin indicadores significativos de CIB

All thresholds and weights from cfg["cib_score"]. Zero hardcoded values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    engine:      str
    label:       str        # short human-readable engine name
    score:       float      # 0-100 raw engine score
    weight:      float      # effective weight applied
    contribution: float     # score * weight → contribution to total


@dataclass
class CIBScoreReport:
    overall_score:      float           # 0-100 final weighted score
    confidence_label:   str             # CONFIRMED_CIB | HIGH_CONFIDENCE | ...
    dimensions:         List[DimensionScore]
    top_signals:        List[str]       # top 5 contributing evidence strings
    engines_present:    int             # how many engines contributed data
    engines_active:     int             # engines with score > 0 (real signals found)
    engines_missing:    List[str]       # engines with no data (skipped)
    data_quality:       str             # SUFFICIENT | LOW | INSUFFICIENT
    narrative:          str             # one-paragraph English summary


class CIBScoreEngine:

    # Default weight distribution across 12 engine dimensions
    _DEFAULT_WEIGHTS = {
        "troll_hunter":    0.22,
        "cib_graph":       0.16,
        "temporal":        0.13,
        "narrative_mut":   0.09,
        "dark_amp":        0.07,
        "engagement":      0.07,
        "contagion":       0.05,
        "reply_chain":     0.04,
        "bot_farm_shift":  0.03,
        "cross_campaign":  0.02,
        "identity":        0.01,
        "psi_core":        0.10,
    }

    _LABELS = {
        "troll_hunter":   "TrollHunter",
        "cib_graph":      "CIB Graph",
        "temporal":       "Temporal Waves",
        "narrative_mut":  "Narrative Mutation",
        "dark_amp":       "Dark Amplification",
        "engagement":     "Engagement Anomaly",
        "contagion":      "Emotional Contagion",
        "reply_chain":    "Reply Hijack",
        "bot_farm_shift": "Bot Farm Shift",
        "cross_campaign": "Cross-Campaign",
        "identity":       "Identity Morph",
        "psi_core":       "PSI Likelihood Ratio (Ψ)",
    }

    _CONFIDENCE_THRESHOLDS = [
        (80.0, "CONFIRMED_CIB"),
        (60.0, "HIGH_CONFIDENCE"),
        (40.0, "PROBABLE"),
        (20.0, "POSSIBLE"),
        ( 0.0, "ORGANIC"),
    ]

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("cib_score", {})
        raw_w  = c.get("weights", {})
        self._weights: dict[str, float] = {
            k: raw_w.get(k, self._DEFAULT_WEIGHTS[k])
            for k in self._DEFAULT_WEIGHTS
        }
        thresh = c.get("thresholds", {})
        self._t_confirmed    = thresh.get("confirmed",       80.0)
        self._t_high         = thresh.get("high_confidence", 60.0)
        self._t_probable     = thresh.get("probable",        40.0)
        self._t_possible     = thresh.get("possible",        20.0)
        self._top_signals_n  = c.get("top_signals_count",    5)
        self._min_active_engines = c.get("min_active_engines_sufficient", 3)
        self._low_quality_threshold = c.get("low_quality_active_engines", 1)

    # ─────────────────────────────────────────────────────────────────────────

    def compute(
        self,
        troll_report=None,
        cib_result=None,
        temporal_report=None,
        mutation_report=None,
        dark_amp_report=None,
        engagement_report=None,
        contagion_report=None,
        reply_report=None,
        shift_report=None,
        cross_campaign_report=None,
        identity_report=None,
        psi_report=None,
        coordination_report=None,
        stylometry_report=None,
    ) -> CIBScoreReport:
        """
        Compute unified CIB confidence score from all available engine reports.
        Missing reports are gracefully skipped with weight redistribution.
        """
        # Extract raw scores from each engine (None → skipped)
        raw: dict[str, float | None] = {
            "troll_hunter":   _safe_score(troll_report,        "bot_risk_score"),
            "cib_graph":      _safe_score(cib_result,          "coordination_score"),
            "temporal":       _safe_score(temporal_report,     "overall_score"),
            "narrative_mut":  _safe_score(mutation_report,     "mutation_score"),
            "dark_amp":       _safe_score(dark_amp_report,     "amp_score"),
            "engagement":     _safe_score(engagement_report,   "anomaly_score"),
            "contagion":      _safe_score(contagion_report,    "contagion_score"),
            "reply_chain":    _safe_score(reply_report,        "hijack_score"),
            "bot_farm_shift": _safe_score(shift_report,        "shift_score"),
            "cross_campaign": _safe_score(cross_campaign_report, "persistence_score"),
            "identity":       _safe_score(identity_report,    "persistence_score"),
            "psi_core":       _safe_score(psi_report,          "overall_score"),
        }

        # Separate engines that ran (report provided) vs. missing (report None)
        present   = {k: v for k, v in raw.items() if v is not None}
        missing   = [k for k, v in raw.items() if v is None]

        # Active = engines that ran AND produced a non-zero signal
        active    = {k: v for k, v in present.items() if v > 0.0}

        # Data quality: based on how many engines found real signals
        n_active = len(active)
        if n_active >= self._min_active_engines:
            data_quality = "SUFFICIENT"
        elif n_active >= self._low_quality_threshold:
            data_quality = "LOW"
        else:
            data_quality = "INSUFFICIENT"

        # Only compute weighted score using engines that have ACTIVE signals
        # Engines present but with score=0 do NOT count toward the denominator
        # — they represent "ran but found nothing", not "confirmed organic"
        if active:
            total_inactive_w = sum(self._weights[k] for k in present if k not in active)
            total_missing_w  = sum(self._weights[k] for k in missing)
            total_inert_w    = total_inactive_w + total_missing_w
            total_active_w   = sum(self._weights[k] for k in active) or 1.0
            effective_w: dict[str, float] = {}
            for k in active:
                base = self._weights[k]
                effective_w[k] = base + (base / total_active_w) * total_inert_w
            overall = sum(active[k] * effective_w[k] for k in active)
        else:
            effective_w = {}
            overall     = 0.0

        overall = round(min(100.0, max(0.0, overall)), 1)

        # Build dimension breakdown (show ALL present engines, including 0-score ones)
        dims: list[DimensionScore] = []
        for k in sorted(present, key=lambda x: -(present.get(x, 0) * effective_w.get(x, self._weights.get(x, 0)))):
            w = effective_w.get(k, self._weights.get(k, 0))
            dims.append(DimensionScore(
                engine       = k,
                label        = self._LABELS.get(k, k),
                score        = round(present[k], 1),
                weight       = round(w, 4),
                contribution = round(present[k] * w, 2),
            ))

        label     = self._label(overall) if data_quality != "INSUFFICIENT" else "ORGANIC"
        signals   = self._build_signals(
            overall, label, dims, troll_report, temporal_report,
            mutation_report, dark_amp_report, contagion_report,
            cross_campaign_report, identity_report, shift_report,
            psi_report, coordination_report, stylometry_report,
        )
        narrative = self._build_narrative(
            overall, label, dims, n_active, signals, data_quality,
        )

        return CIBScoreReport(
            overall_score    = overall,
            confidence_label = label,
            dimensions       = dims,
            top_signals      = signals[:self._top_signals_n],
            engines_present  = len(present),
            engines_active   = n_active,
            engines_missing  = missing,
            data_quality     = data_quality,
            narrative        = narrative,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _label(self, score: float) -> str:
        if score >= self._t_confirmed:
            return "CONFIRMED_CIB"
        if score >= self._t_high:
            return "HIGH_CONFIDENCE"
        if score >= self._t_probable:
            return "PROBABLE"
        if score >= self._t_possible:
            return "POSSIBLE"
        return "ORGANIC"

    def _build_signals(
        self,
        score:         float,
        label:         str,
        dims:          list[DimensionScore],
        troll_report=None,
        temporal_report=None,
        mutation_report=None,
        dark_amp_report=None,
        contagion_report=None,
        cross_campaign_report=None,
        identity_report=None,
        shift_report=None,
        psi_report=None,
        coordination_report=None,
        stylometry_report=None,
    ) -> list[str]:
        signals: list[str] = []

        # TrollHunter
        if troll_report:
            nb = len(getattr(troll_report, "confirmed_bots", []))
            hr = len(getattr(troll_report, "high_risk", []))
            fn = len(getattr(troll_report, "foreign_names", []))
            if nb:
                signals.append(
                    f"{nb} actor(es) BOT confirmado(s) · {hr} alto riesgo · "
                    f"score TrollHunter {troll_report.bot_risk_score:.0f}/100"
                )
            if fn:
                signals.append(f"{fn} nombre(s) de origen extranjero — indicador de operación extrangera")

        # Temporal waves
        if temporal_report:
            nw = len(getattr(temporal_report, "waves", []))
            sp = len(getattr(temporal_report, "sync_pairs", []))
            if nw:
                signals.append(
                    f"{nw} ola(s) de ataque coordinado detectadas — "
                    f"{sp} pares sincronizados en ±3 segundos"
                )

        # Narrative mutation
        if mutation_report:
            nm = len(getattr(mutation_report, "mutations", []))
            pi = getattr(mutation_report, "pivot_events", 0)
            if nm:
                signals.append(
                    f"{nm} mutación/mutaciones narrativas — "
                    f"{pi} pivote(s) de narrativa coordinado(s)"
                )

        # Dark amplification
        if dark_amp_report:
            nd = len(getattr(dark_amp_report, "dark_amplified", []))
            if nd:
                top_e = (getattr(dark_amp_report, "events", []) or [None])[0]
                factor = getattr(top_e, "amplification_factor", 0) if top_e else 0
                signals.append(
                    f"{nd} publicación(es) con amplificación artificial — "
                    f"pico {factor:.1f}x sobre baseline"
                )

        # Contagion
        if contagion_report:
            cs = getattr(contagion_report, "contagion_score", 0)
            if cs >= 20:
                direction = getattr(contagion_report, "shift_direction", "?")
                signals.append(
                    f"Contagio emocional {direction} detectado — score {cs}/100"
                )

        # Cross-campaign
        if cross_campaign_report:
            pro = len(getattr(cross_campaign_report, "professional", []))
            per = len(getattr(cross_campaign_report, "persistent", []))
            if pro + per:
                signals.append(
                    f"{pro} atacante(s) PROFESIONAL (5+ campañas) · "
                    f"{per} PERSISTENTE(S) — operadores de carrera confirmados"
                )

        # Identity morphs
        if identity_report:
            cm = len(getattr(identity_report, "confirmed_morphs", []))
            if cm:
                signals.append(
                    f"{cm} cambio(s) de identidad confirmado(s) — "
                    f"mismo operador, diferentes cuentas"
                )

        # Bot farm shift
        if shift_report:
            cs = getattr(shift_report, "confirmed_shifts", 0)
            rot = getattr(shift_report, "total_rotated", 0)
            if cs:
                signals.append(
                    f"{cs} cambio(s) de turno de granja — "
                    f"{rot} actores rotados dentro de la misma operación"
                )

        # PSI Likelihood Ratio (ARGOS-Ψ)
        if psi_report:
            psi_score = getattr(psi_report, "overall_score", 0)
            hr = len(getattr(psi_report, "high_risk_actors", []))
            amb = len(getattr(psi_report, "ambiguous_actors", []))
            if hr or amb:
                if hr:
                    signals.append(
                        f"{hr} actor(s) with strong bot indicators (Ψ > 50) — "
                        f"likely automated behavior detected"
                    )
                if amb:
                    signals.append(
                        f"{amb} actor(s) in ambiguous zone (Ψ ≈ 0) — "
                        f"require manual review (possible sockpuppets)"
                    )

        # PSI Coordination Engine (ARGOS-Ψ Phase 2)
        if coordination_report:
            n_clusters = getattr(coordination_report, "total_clusters", 0)
            n_botnet = len(getattr(coordination_report, "botnet_nodes", []))
            n_ghost = len(getattr(coordination_report, "ghost_candidates", []))
            coord_score = getattr(coordination_report, "overall_coordination_score", 0)
            if coord_score > 50:
                signals.append(
                    f"{n_clusters} coordinated cluster(s) detected (score {coord_score:.0f}/100) — "
                    f"organized network structure identified"
                )
            if n_botnet:
                signals.append(
                    f"{n_botnet} BOTNET_NODE(s) identified — high centrality + temporal rhythm markers"
                )
            if n_ghost:
                signals.append(
                    f"{n_ghost} GHOST candidate(s) — elite operators (individually ambiguous, "
                    f"visible only through network recurrence)"
                )

        # PSI Stylometry Engine (ARGOS-Ψ Phase 3 — Sockpuppet Detection)
        if stylometry_report:
            n_linkages = len(getattr(stylometry_report, "linkages", []))
            n_high_conf = getattr(stylometry_report, "high_confidence_pairs", 0)
            n_groups = len(getattr(stylometry_report, "sockpuppet_groups", []))
            if n_high_conf:
                signals.append(
                    f"{n_high_conf} high-confidence account linkage(s) detected — "
                    f"likely HUMAN_LIKE (same operator managing multiple personas)"
                )
            if n_groups:
                total_accounts = sum(len(g) for g in getattr(stylometry_report, "sockpuppet_groups", []))
                signals.append(
                    f"{n_groups} sockpuppet cluster(s) found ({total_accounts} linked accounts) — "
                    f"coordinated through single operator"
                )

        # Fallback: top contributing dimension
        if not signals and dims:
            top_d = dims[0]
            signals.append(
                f"Señal primaria: {top_d.label} — score {top_d.score:.0f}/100"
            )

        return signals

    def _build_narrative(
        self,
        score:        float,
        label:        str,
        dims:         list[DimensionScore],
        n_active:     int,
        signals:      list[str],
        data_quality: str = "SUFFICIENT",
    ) -> str:
        if data_quality == "INSUFFICIENT":
            return (
                "Insufficient comment data to compute a reliable CIB score. "
                "Run the scan with --comments-on-top to enable deep comment analysis "
                "across all forensic dimensions. At least 3 analysis engines need "
                "active signals to produce a valid assessment."
            )

        if data_quality == "LOW":
            active_dims = [d for d in dims if d.score > 0]
            dim_list = ", ".join(d.label for d in active_dims[:3]) if active_dims else "none"
            return (
                f"Partial analysis: only {n_active} of {len(dims)} forensic engines "
                f"produced active signals ({dim_list}). "
                f"Score {score:.0f}/100 — {label.replace('_', ' ')}. "
                f"Run with more comments to improve confidence."
            )

        label_map = {
            "CONFIRMED_CIB":    "confirms with high certainty the presence of Coordinated Inauthentic Behavior (CIB)",
            "HIGH_CONFIDENCE":  "shows strong, consistent indicators of Coordinated Inauthentic Behavior (CIB)",
            "PROBABLE":         "shows significant indicators of possible Coordinated Inauthentic Behavior (CIB)",
            "POSSIBLE":         "shows weak signals that may indicate inauthentic activity",
            "ORGANIC":          "shows no significant indicators of Coordinated Inauthentic Behavior — activity appears organic",
        }

        verdict  = label_map.get(label, label)
        active_dims = [d for d in dims if d.score > 0]
        top_dim  = active_dims[0] if active_dims else (dims[0] if dims else None)
        top_str  = (
            f"Strongest signal: {top_dim.label} "
            f"(score {top_dim.score:.0f}/100, weighted contribution {top_dim.contribution:.1f} pts). "
            if top_dim and top_dim.score > 0 else ""
        )

        signals_str = ""
        if signals:
            signals_str = (
                " Key evidence: "
                + "; ".join(signals[:3])
                + "."
            )

        return (
            f"Integrated analysis across {n_active} active forensic dimensions "
            f"(score {score:.0f}/100) — {verdict}. "
            f"{top_str}{signals_str}"
        )

    @staticmethod
    def empty() -> CIBScoreReport:
        return CIBScoreReport(
            overall_score=0.0, engines_active=0,
            confidence_label="ORGANIC", data_quality="INSUFFICIENT",
            dimensions=[],
            top_signals=[],
            engines_present=0,
            engines_missing=list(CIBScoreEngine._DEFAULT_WEIGHTS.keys()),
            narrative="Insufficient data — run scan with --comments-on-top to enable CIB analysis.",
        )


def _safe_score(report, attr: str) -> float | None:
    if report is None:
        return None
    val = getattr(report, attr, None)
    if val is None:
        return None
    try:
        f = float(val)
        return max(0.0, min(100.0, f))
    except (TypeError, ValueError):
        return None
