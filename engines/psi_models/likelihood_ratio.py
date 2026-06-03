"""
Likelihood Ratio Calculator — Ψ(S) = log P(S|A) - log P(S|H)

The heart of ARGOS-Ψ: probabilistic comparison of behavior under bot vs human model.

Ψ >> 0  ⇒ bot-like (stream better explained by bot model)
Ψ ≈ 0   ⇒ ambiguous (could be either)
Ψ << 0  ⇒ human-like (stream better explained by human model)
"""
from __future__ import annotations

import math
from datetime import datetime
from dataclasses import dataclass


@dataclass
class PSIResult:
    """Output of PSI calculation per actor."""
    actor: str
    psi_score: float                # the Ψ value
    log_likelihood_bot: float       # log P(S|A)
    log_likelihood_human: float     # log P(S|H)
    hawkes_score: float             # circadian + burstiness (0-1, higher=more human)
    markov_entropy: float           # action diversity (higher=more human)
    action_diversity: float         # unique actions ratio (0-1)
    interpretation: str             # brief explanation
    confidence: float               # 0-1, how sure are we


class LikelihoodRatioCalculator:
    """
    Compute Ψ score for an actor given:
    - Human model (Hawkes + Markov trained on human behavior)
    - Bot model (Hawkes + Markov trained on/parameterized for bots)
    """

    def __init__(self, human_model: tuple, bot_model: tuple, cfg: dict | None = None):
        """
        Args:
            human_model: (HawkesModel, MarkovPPMModel) trained on humans
            bot_model: (HawkesModel, MarkovPPMModel) trained on/parameterized for bots
            cfg: config dict with psi_core settings
        """
        self.human_hawkes, self.human_markov = human_model
        self.bot_hawkes, self.bot_markov = bot_model

        c = (cfg or {}).get("psi_core", {})
        self.weight_temporal = c.get("weight_temporal", 0.4)
        self.weight_action = c.get("weight_action", 0.4)
        self.weight_circadian = c.get("weight_circadian", 0.2)

    def compute(
        self,
        actor: str,
        timestamps: list[datetime],
        action_sequence: list[str],
    ) -> PSIResult:
        """
        Compute Ψ(S) for this actor's stream.

        Args:
            actor: account name (for reporting)
            timestamps: sorted timestamps of events
            action_sequence: parallel list of action types

        Returns:
            PSIResult with detailed breakdown
        """
        # Temporal (Hawkes) log-likelihoods
        ll_human_temporal = self.human_hawkes.log_likelihood(timestamps)
        ll_bot_temporal = self.bot_hawkes.log_likelihood(timestamps)

        # Action sequence (Markov/PPM) log-likelihoods
        ll_human_action = self.human_markov.log_likelihood(action_sequence)
        ll_bot_action = self.bot_markov.log_likelihood(action_sequence)

        # Circadian score (0-1, higher = human-like)
        circadian = self.human_hawkes.circadian_score(timestamps)

        # Markov entropy (higher = diverse/human-like)
        entropy = self.human_markov.entropy(action_sequence)
        max_entropy = math.log2(len(self.human_markov.vocab)) if self.human_markov.vocab else 5.0
        entropy_normalized = min(1.0, entropy / max(max_entropy, 1.0))

        # Action diversity
        diversity = self.human_markov.diversity(action_sequence)

        # Weighted log-likelihoods
        ll_human = (
            ll_human_temporal * self.weight_temporal +
            ll_human_action * self.weight_action +
            circadian * self.weight_circadian
        )

        ll_bot = (
            ll_bot_temporal * self.weight_temporal +
            ll_bot_action * self.weight_action +
            (1.0 - circadian) * self.weight_circadian  # bots don't sleep
        )

        # Core Ψ score
        psi = ll_bot - ll_human

        # Normalize Ψ to roughly -100 to +100 range
        psi_normalized = min(100.0, max(-100.0, psi / max(abs(psi), 10.0) * 50))

        # Confidence: how well-separated are the models?
        margin = abs(ll_bot - ll_human)
        confidence = min(1.0, margin / max(10.0, margin))

        # Interpretation
        interpretation = self._interpret(psi_normalized, circadian, entropy_normalized, diversity)

        return PSIResult(
            actor=actor,
            psi_score=round(psi_normalized, 1),
            log_likelihood_bot=round(ll_bot, 2),
            log_likelihood_human=round(ll_human, 2),
            hawkes_score=round(circadian, 2),
            markov_entropy=round(entropy_normalized, 2),
            action_diversity=round(diversity, 2),
            interpretation=interpretation,
            confidence=round(confidence, 2),
        )

    def _interpret(
        self,
        psi: float,
        circadian: float,
        entropy: float,
        diversity: float,
    ) -> str:
        """
        Generate human-readable interpretation of Ψ score.
        """
        if psi > 50:
            base = "Strong bot indicators"
        elif psi > 20:
            base = "Bot-like behavior"
        elif psi > -20:
            base = "Ambiguous (mixed signals)"
        elif psi > -50:
            base = "Human-like behavior"
        else:
            base = "Strong human indicators"

        details = []
        if circadian > 0.7:
            details.append("clear circadian rhythm")
        elif circadian < 0.3:
            details.append("24/7 activity (bot-like)")

        if entropy > 0.7:
            details.append("high action diversity")
        elif entropy < 0.3:
            details.append("repetitive actions")

        if diversity > 0.6:
            details.append("many action types")
        elif diversity < 0.3:
            details.append("focused/single action")

        detail_str = " + ".join(details) if details else "neutral indicators"

        return f"{base}: {detail_str}"
