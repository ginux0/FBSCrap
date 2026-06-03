"""
PSI CORE ENGINE — ARGOS-Ψ Main Detection Module

Likelihood-ratio nucleus for ARGOS-Ψ bot/inauthentic detection.
Computes Ψ(S) = log P(S|BOT) - log P(S|HUMAN) for each actor.

All parameters from cfg["psi_core"]. Zero hardcoded values.

Integration: PSICoreEngine output feeds into CIBScoreEngine as 12th engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from pathlib import Path

# Conditional imports — if psi_models not available, graceful fallback
try:
    from engines.psi_models.hawkes import HawkesModel
    from engines.psi_models.markov_ppm import MarkovPPMModel
    from engines.psi_models.likelihood_ratio import LikelihoodRatioCalculator, PSIResult
    _PSI_AVAILABLE = True
except ImportError:
    _PSI_AVAILABLE = False


@dataclass
class PSIActorScore:
    """Per-actor PSI result."""
    actor: str
    psi_score: float                    # -100 to +100
    confidence: float                   # 0-1
    interpretation: str
    hawkes_circadian: float             # 0-1 (human-like circadian)
    markov_entropy: float               # 0-1 (action diversity)
    action_diversity: float             # 0-1
    total_actions: int
    total_events: int
    event_span_hours: float


@dataclass
class PSICoreReport:
    """Output of PSICoreEngine.analyze()."""
    actor_scores: dict[str, PSIActorScore]
    overall_score: float                # 0-100 (aggregated for CIBScoreEngine)
    confidence_label: str               # STRONG_HUMAN | HUMAN | AMBIGUOUS | BOT | STRONG_BOT
    high_risk_actors: list[str]         # Ψ > threshold
    ambiguous_actors: list[str]         # abstention zone
    human_actors: list[str]             # Ψ < -threshold
    summary: str
    model_version: str = "ARGOS-Ψ v1.0"


class PSICoreEngine:
    """
    Likelihood-ratio nucleus detector.

    Two models trained per session:
    - Human model: learned from organic accounts
    - Bot model: learned from confirmed bots or parameterized

    Computes Ψ score per actor indicating bot probability.
    """

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        c = self.cfg.get("psi_core", {})

        # Model parameters
        self.hawkes_cfg = c.get("hawkes_params", {})
        self.markov_cfg = c.get("markov_params", {})

        # Scoring thresholds (all configurable)
        self.psi_threshold_high = c.get("psi_threshold_high_bot", 50)
        self.psi_threshold_low = c.get("psi_threshold_low_human", -50)
        self.psi_abstention_low = c.get("psi_abstention_zone_low", -20)
        self.psi_abstention_high = c.get("psi_abstention_zone_high", 20)

        # Minimum data requirements
        self.min_actions = c.get("min_actions_for_analysis", 3)
        self.min_events = c.get("min_events_for_analysis", 2)

        # Models (trained on first run, reused after)
        self.human_model = None
        self.bot_model = None
        self._model_trained = False

    def analyze(
        self,
        posts: list[dict],
        bot_suspects: list | None = None,
    ) -> PSICoreReport:
        """
        Main entry point: analyze posts and return PSI scores.

        Args:
            posts: list of post dicts with 'comments' arrays
            bot_suspects: list of suspected bots (for optional training)

        Returns:
            PSICoreReport with scores for all actors
        """
        if not _PSI_AVAILABLE:
            return self._empty_report("PSI models not available — install engines.psi_models")

        # Extract action streams per actor
        streams = self._extract_streams(posts)

        if not streams:
            return self._empty_report("No actor streams found")

        # Train models if needed
        if not self._model_trained:
            self._train_models(streams, bot_suspects or [])

        # Compute Ψ score per actor
        actor_scores: dict[str, PSIActorScore] = {}

        for actor, (timestamps, actions) in streams.items():
            if len(actions) < self.min_actions or len(timestamps) < self.min_events:
                continue

            psi_result = self._compute_psi(actor, timestamps, actions)
            actor_scores[actor] = PSIActorScore(
                actor=actor,
                psi_score=psi_result.psi_score,
                confidence=psi_result.confidence,
                interpretation=psi_result.interpretation,
                hawkes_circadian=psi_result.hawkes_score,
                markov_entropy=psi_result.markov_entropy,
                action_diversity=psi_result.action_diversity,
                total_actions=len(actions),
                total_events=len(timestamps),
                event_span_hours=self._span_hours(timestamps),
            )

        # Categorize actors
        high_risk = [a for a, s in actor_scores.items() if s.psi_score > self.psi_threshold_high]
        ambiguous = [
            a for a, s in actor_scores.items()
            if self.psi_abstention_low <= s.psi_score <= self.psi_abstention_high
        ]
        human = [a for a, s in actor_scores.items() if s.psi_score < self.psi_threshold_low]

        # Overall score (for CIBScoreEngine integration)
        overall = self._aggregate_score(actor_scores)
        label = self._confidence_label(overall, len(actor_scores), len(ambiguous))

        summary = self._build_summary(actor_scores, high_risk, ambiguous, human, overall)

        return PSICoreReport(
            actor_scores=actor_scores,
            overall_score=overall,
            confidence_label=label,
            high_risk_actors=high_risk,
            ambiguous_actors=ambiguous,
            human_actors=human,
            summary=summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _extract_streams(
        self,
        posts: list[dict],
    ) -> dict[str, tuple[list[datetime], list[str]]]:
        """
        Extract per-actor streams: (timestamps, action_sequence).

        Args:
            posts: [{url, comments: [{author, timestamp, text}, ...]}, ...]

        Returns:
            {actor: (timestamps, actions), ...}
        """
        streams: dict[str, tuple[list, list]] = {}

        for post in posts:
            for comment in post.get("comments", []):
                author = (comment.get("author") or "").strip()
                if not author or author == "?":
                    continue

                timestamp_str = comment.get("timestamp")
                if not timestamp_str:
                    continue

                try:
                    ts = datetime.fromisoformat(timestamp_str)
                except (ValueError, TypeError):
                    continue

                action = self._classify_action(comment)

                if author not in streams:
                    streams[author] = ([], [])

                streams[author][0].append(ts)
                streams[author][1].append(action)

        # Sort by timestamp per actor
        for actor in streams:
            ts_list, action_list = streams[actor]
            sorted_pairs = sorted(zip(ts_list, action_list), key=lambda x: x[0])
            streams[actor] = (
                [ts for ts, _ in sorted_pairs],
                [action for _, action in sorted_pairs],
            )

        return streams

    def _classify_action(self, comment: dict) -> str:
        """
        Classify a comment into action type.

        Returns: 'comment', 'reply', 'react', 'share', 'unknown'
        """
        text = (comment.get("text") or "").strip()

        if not text or len(text) < 2:
            return "react"

        if text.startswith("↪"):
            return "reply"

        if any(emoji in text for emoji in ["👍", "❤️", "😂", "😮", "😢", "😠"]):
            if len(text) < 5:
                return "react"

        return "comment"

    def _train_models(self, streams: dict, bot_suspects: list):
        """
        Train human and bot Hawkes/Markov models.

        Simple approach: use known bots for bot model, rest for human.
        """
        suspect_names = {s.author if hasattr(s, "author") else str(s) for s in bot_suspects}

        human_streams = []
        bot_streams = []

        for actor, (ts, actions) in streams.items():
            if len(ts) < self.min_events:
                continue

            if actor in suspect_names:
                bot_streams.append((ts, actions))
            else:
                human_streams.append((ts, actions))

        # Fallback: if no bots, use a parameterized bot model
        if not bot_streams and human_streams:
            bot_streams = [(human_streams[0][0], human_streams[0][1])]

        # Fit Hawkes models
        human_hawkes = HawkesModel(self.cfg)
        for ts, _ in human_streams:
            human_hawkes.fit(ts)

        bot_hawkes = HawkesModel(self.cfg)
        for ts, _ in bot_streams:
            bot_hawkes.fit(ts)
        # Parameterize bot to be flat (no self-excitation, 24/7)
        bot_hawkes.alpha = 0.05
        bot_hawkes.beta = 1.0

        # Fit Markov models
        human_markov = MarkovPPMModel(self.cfg, order=2)
        for _, actions in human_streams:
            human_markov.fit(actions)

        bot_markov = MarkovPPMModel(self.cfg, order=2)
        for _, actions in bot_streams:
            bot_markov.fit(actions)

        self.human_model = (human_hawkes, human_markov)
        self.bot_model = (bot_hawkes, bot_markov)
        self._model_trained = True

    def _compute_psi(
        self,
        actor: str,
        timestamps: list[datetime],
        actions: list[str],
    ) -> PSIResult:
        """
        Compute Ψ score for actor given trained models.
        """
        if not self._model_trained:
            raise RuntimeError("Models not trained")

        calculator = LikelihoodRatioCalculator(self.human_model, self.bot_model, self.cfg)
        result = calculator.compute(actor, timestamps, actions)

        return result

    def _span_hours(self, timestamps: list[datetime]) -> float:
        """Time span of activity in hours."""
        if len(timestamps) < 2:
            return 0.0
        span = (timestamps[-1] - timestamps[0]).total_seconds()
        return span / 3600.0

    def _aggregate_score(self, actor_scores: dict[str, PSIActorScore]) -> float:
        """
        Aggregate individual Ψ scores into overall report score (0-100).

        Higher Ψ (bot-like) → higher overall score.
        """
        if not actor_scores:
            return 0.0

        # Normalize Ψ scores to 0-100
        normalized = []
        for score in actor_scores.values():
            # Ψ in range -100 to +100 → normalize to 0-100
            norm = (score.psi_score + 100) / 2
            norm = max(0.0, min(100.0, norm))
            normalized.append(norm)

        if not normalized:
            return 0.0

        # Weighted average (higher activity → higher weight)
        total_weight = sum(s.total_events for s in actor_scores.values())
        if total_weight == 0:
            return sum(normalized) / len(normalized)

        weighted_sum = sum(
            norm * actor_scores[actor].total_events
            for actor, norm in zip(actor_scores.keys(), normalized)
        )

        return round(weighted_sum / total_weight, 1)

    def _confidence_label(self, score: float, num_actors: int, num_ambiguous: int) -> str:
        """Assign confidence label based on overall score and data quality."""
        if num_actors == 0:
            return "INSUFFICIENT_DATA"

        if num_ambiguous > num_actors * 0.5:
            return "INCONCLUSIVE"

        if score >= 70:
            return "STRONG_BOT"
        elif score >= 50:
            return "BOT"
        elif score >= 40:
            return "SUSPICIOUS"
        elif score >= 30:
            return "AMBIGUOUS"
        elif score >= 20:
            return "HUMAN"
        else:
            return "STRONG_HUMAN"

    def _build_summary(
        self,
        actor_scores: dict[str, PSIActorScore],
        high_risk: list[str],
        ambiguous: list[str],
        human: list[str],
        overall: float,
    ) -> str:
        """Generate human-readable summary."""
        parts = [
            f"PSI analysis across {len(actor_scores)} actors. "
            f"Overall Ψ score: {overall:.0f}/100. "
        ]

        if high_risk:
            parts.append(
                f"{len(high_risk)} high-risk bot-like actor(s): "
                f"{', '.join(high_risk[:5])}"
                f"{'...' if len(high_risk) > 5 else ''}"
            )

        if ambiguous:
            parts.append(
                f"{len(ambiguous)} ambiguous actor(s) in abstention zone — "
                f"recommend human review."
            )

        if human:
            parts.append(
                f"{len(human)} human-like actor(s) detected; "
                f"organically embedded behavior."
            )

        if not high_risk and not ambiguous and human:
            parts.append("No significant bot activity detected.")

        return " ".join(parts)

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _empty_report(reason: str) -> PSICoreReport:
        """Return empty report when analysis unavailable."""
        return PSICoreReport(
            actor_scores={},
            overall_score=0.0,
            confidence_label="INSUFFICIENT_DATA",
            high_risk_actors=[],
            ambiguous_actors=[],
            human_actors=[],
            summary=f"PSI analysis unavailable: {reason}",
        )
