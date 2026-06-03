"""
Markov / Prediction by Partial Matching (PPM) — action sequence model.

Humans: diverse action transitions (comment, react, share, publish, follow, etc.)
Bots: repetitive (usually just react + comment, low diversity)

Models P(aᵢ | aᵢ₋₁, aᵢ₋₂) for order-2 Markov.
Falls back to order-1 (bigram) or order-0 (unigram) if data sparse.
"""
from __future__ import annotations

import math
from collections import defaultdict, Counter
from typing import Optional


class MarkovPPMModel:
    """
    Order-2 Markov model for action sequences.

    state = (aᵢ₋₂, aᵢ₋₁)
    transition = aᵢ

    Learns P(aᵢ | state) from training data.
    """

    def __init__(self, cfg: dict | None = None, order: int = 2):
        c = (cfg or {}).get("markov_params", {})
        self.order = min(order, c.get("max_order", 2))
        self.smoothing = c.get("laplace_smoothing", 0.1)
        self.min_freq = c.get("min_transition_freq", 1)

        # Transition counts: state → {action → count}
        self.transitions: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.vocab: set[str] = set()
        self.total_transitions = 0

    def fit(self, action_sequence: list[str]) -> MarkovPPMModel:
        """
        Fit Markov model from observed action sequence.

        Args:
            action_sequence: list of actions ['comment', 'react', 'share', ...]
        """
        if len(action_sequence) < self.order:
            return self

        self.vocab = set(action_sequence)

        for i in range(self.order, len(action_sequence)):
            state = tuple(action_sequence[i-self.order:i])
            action = action_sequence[i]

            self.transitions[state][action] += 1
            self.total_transitions += 1

        return self

    def log_likelihood(self, action_sequence: list[str]) -> float:
        """
        Log-likelihood of sequence under Markov model.
        L = Σᵢ log P(aᵢ | state_{i-1})
        """
        if len(action_sequence) < self.order:
            return 0.0

        log_ll = 0.0
        for i in range(self.order, len(action_sequence)):
            state = tuple(action_sequence[i-self.order:i])
            action = action_sequence[i]

            prob = self._transition_prob(state, action)
            if prob > 1e-10:
                log_ll += math.log(prob)
            else:
                log_ll -= 10  # penalize unseen transitions

        return log_ll

    def _transition_prob(self, state: tuple, action: str) -> float:
        """
        P(action | state) with Laplace smoothing.
        """
        vocab_size = len(self.vocab) or 1

        if state not in self.transitions:
            return self.smoothing / (vocab_size + self.smoothing * vocab_size)

        state_counts = self.transitions[state]
        total = sum(state_counts.values())

        if total == 0:
            return self.smoothing / (vocab_size + self.smoothing * vocab_size)

        count = state_counts.get(action, 0)
        numerator = count + self.smoothing
        denominator = total + self.smoothing * vocab_size

        return numerator / denominator if denominator > 0 else 1e-10

    def entropy(self, action_sequence: list[str]) -> float:
        """
        Shannon entropy of sequence under model: -Σ log P(aᵢ|state)

        High entropy = diverse/unpredictable (human-like)
        Low entropy = predictable/repetitive (bot-like)

        Returns: entropy value (0+ bits)
        """
        if len(action_sequence) < self.order:
            return 0.0

        entropy = 0.0
        count = 0

        for i in range(self.order, len(action_sequence)):
            state = tuple(action_sequence[i-self.order:i])
            action = action_sequence[i]

            prob = self._transition_prob(state, action)
            if prob > 1e-10:
                entropy -= math.log2(prob)
                count += 1

        return entropy / count if count > 0 else 0.0

    def diversity(self, action_sequence: list[str]) -> float:
        """
        Action diversity score: unique actions / total actions.

        Returns: 0.0-1.0
        """
        if not action_sequence:
            return 0.0

        unique = len(set(action_sequence))
        total = len(action_sequence)

        return unique / total
