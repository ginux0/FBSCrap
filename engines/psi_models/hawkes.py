"""
Hawkes Process Model — self-exciting temporal dynamics.

Human behavior: bursts (self-exciting) + circadian valleys.
Bot behavior: periodic/flat (no self-excitation).

All parameters from cfg["psi_core"]["hawkes_params"].
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional


class HawkesModel:
    """
    Hawkes process: λ(t) = μ + α * Σ exp(-β(t - tᵢ)) for t > tᵢ

    μ = base rate
    α = self-exciting coefficient (how much each event triggers future events)
    β = decay rate (how quickly self-excitation fades)

    For humans: α > 0 (ráfagas seguidas de calma)
    For bots: α ≈ 0 (Poisson — no self-excitation)
    """

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("hawkes_params", {})
        self.mu = c.get("base_rate", 0.1)
        self.alpha = c.get("self_exciting_coef", 0.5)
        self.beta = c.get("decay_rate", 0.3)
        self.circadian_weight = c.get("circadian_weight", 0.2)
        self.sleep_hours = c.get("sleep_hours", (22, 8))  # 10pm-8am

    def fit(self, timestamps: list[datetime]) -> HawkesModel:
        """
        Fit Hawkes parameters from observed timestamps.
        Simple MLE-like estimation (not full MLE, but fast).
        """
        if len(timestamps) < 2:
            return self

        sorted_ts = sorted(timestamps)
        inter_event_times = []
        for i in range(1, len(sorted_ts)):
            delta_s = (sorted_ts[i] - sorted_ts[i-1]).total_seconds()
            if delta_s > 0:
                inter_event_times.append(delta_s)

        if not inter_event_times:
            return self

        # Estimate α from burstiness signature
        mean_iet = sum(inter_event_times) / len(inter_event_times)
        var_iet = sum((t - mean_iet)**2 for t in inter_event_times) / len(inter_event_times)

        # High variance in inter-event times → high α (self-exciting)
        if mean_iet > 0:
            burstiness = (var_iet - mean_iet) / (var_iet + mean_iet + 1e-9)
            self.alpha = max(0.0, min(0.9, (burstiness + 1) / 2))

        self.mu = len(timestamps) / max(
            (sorted_ts[-1] - sorted_ts[0]).total_seconds(), 1.0
        )

        return self

    def log_likelihood(self, timestamps: list[datetime], T: float | None = None) -> float:
        """
        Log-likelihood of observing these timestamps under Hawkes model.
        L = Σ log(λ(tᵢ)) - ∫₀ᵀ λ(t) dt

        Args:
            timestamps: sorted list of event times
            T: observation window (seconds). If None, use last timestamp.

        Returns:
            log-likelihood (higher = more likely under this model)
        """
        if not timestamps or len(timestamps) < 1:
            return 0.0

        sorted_ts = sorted(timestamps)

        if T is None:
            T = (sorted_ts[-1] - sorted_ts[0]).total_seconds() or 1.0

        # Log-intensity at each event
        log_intensity = 0.0
        for i, t_i in enumerate(sorted_ts):
            # λ(tᵢ) = μ + α * Σⱼ<ᵢ exp(-β(tᵢ - tⱼ))
            excitation = 0.0
            for j in range(i):
                delta_s = (t_i - sorted_ts[j]).total_seconds()
                if delta_s >= 0:
                    excitation += math.exp(-self.beta * delta_s)

            intensity = self.mu + self.alpha * excitation
            if intensity > 1e-10:
                log_intensity += math.log(intensity)
            else:
                log_intensity -= 1e3  # penalize zero intensity

        # Integral of intensity (approximation via trapezoid on grid)
        integral = self._integrate_intensity(sorted_ts, T)

        return log_intensity - integral

    def _integrate_intensity(self, timestamps: list[datetime], T: float) -> float:
        """
        Approximate ∫₀ᵀ λ(t) dt via numerical integration.
        """
        if not timestamps:
            return self.mu * T

        sorted_ts = sorted(timestamps)
        base_integral = self.mu * T

        # Excitation integral: ∫ α Σ exp(-β(t - tⱼ)) dt
        # = α Σⱼ ∫ₜⱼᵀ exp(-β(t - tⱼ)) dt
        # = α Σⱼ (1/β) * (1 - exp(-β(T - tⱼ)))

        excitation_integral = 0.0
        for t_j in sorted_ts:
            delta = T - (t_j - sorted_ts[0]).total_seconds()
            if delta > 0 and self.beta > 0:
                excitation_integral += (1.0 / self.beta) * (1.0 - math.exp(-self.beta * delta))

        return base_integral + self.alpha * excitation_integral

    def circadian_score(self, timestamps: list[datetime]) -> float:
        """
        Score how "human" the circadian pattern is.
        Humans sleep (low activity 10pm-8am); bots don't.

        Returns: 0.0-1.0 (higher = more human-like rhythm)
        """
        if not timestamps:
            return 0.5

        sleep_start, sleep_end = self.sleep_hours

        sleep_count = 0
        for ts in timestamps:
            hour = ts.hour
            if sleep_start <= hour or hour < sleep_end:
                sleep_count += 1

        sleep_ratio = sleep_count / len(timestamps) if timestamps else 0.0

        # Human-like: ~15-20% activity during sleep hours
        # Bot-like: ~4% (proportional to 24h)
        ideal_sleep_ratio = 8 / 24  # 33% = true sleep, but some activity expected

        deviation = abs(sleep_ratio - ideal_sleep_ratio)
        score = max(0.0, 1.0 - deviation * 2)

        return score
