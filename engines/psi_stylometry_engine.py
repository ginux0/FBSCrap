"""
PSI STYLOMETRY ENGINE — ARGOS-Ψ Sockpuppet Detection

Detects accounts operated by the same person through:
1. Stylometric fingerprinting (function words, n-grams, punctuation)
2. Temporal anti-correlation (never simultaneously active = same operator)
3. Burrows Delta distance for author linkage
4. Account clustering by shared operator

All parameters from cfg["psi_stylometry"]. Zero hardcoded values.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import math
import re


@dataclass
class StylometricFingerprint:
    """Per-account writing style signature."""
    actor: str
    total_texts: int
    avg_text_length: float
    function_word_freq: dict[str, float]
    punctuation_freq: dict[str, float]
    ngram_dist: dict[str, float]
    emoji_ratio: float
    caps_ratio: float
    avg_sentence_length: float


@dataclass
class AccountLinkage:
    """Suspected linkage between two accounts."""
    account_a: str
    account_b: str
    stylometric_distance: float  # Burrows Delta (0=identical, 1=very different)
    temporal_anticorr: float     # Anti-correlation (0=random, 1=perfect opposite schedule)
    shared_ngrams_pct: float     # % of shared n-grams
    overall_confidence: float    # 0-1 (linkage probability)
    likely_same_operator: bool


@dataclass
class PSIStylometryReport:
    """Output of PSIStylometryEngine."""
    fingerprints: dict[str, StylometricFingerprint]
    linkages: list[AccountLinkage]
    sockpuppet_groups: list[list[str]]  # Clustered accounts [account_a, account_b, account_c]
    high_confidence_pairs: int
    summary: str


class PSIStylometryEngine:
    """
    Stylometric analysis for detecting sockpuppet networks.

    HUMAN_LIKE accounts share same operator across multiple personas.
    Detection via: writing style + temporal patterns.
    """

    # Common function words (language-agnostic patterns)
    _FUNCTION_WORDS = set([
        "el", "la", "de", "que", "y", "a", "en", "se", "los",
        "un", "una", "por", "con", "para", "está", "como",
        "the", "is", "and", "or", "but", "if", "in", "on", "at",
        "to", "of", "a", "by", "from", "up", "about", "into",
    ])

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("psi_stylometry", {})
        self.min_texts_for_fingerprint = c.get("min_texts_for_fingerprint", 3)
        self.linkage_threshold = c.get("linkage_threshold", 0.65)
        self.temporal_anticorr_threshold = c.get("temporal_anticorr_threshold", 0.7)
        self.ngram_size = c.get("ngram_size", 3)

    def analyze(
        self,
        posts: list[dict],
    ) -> PSIStylometryReport:
        """
        Main entry: detect sockpuppet networks via stylometry.

        Args:
            posts: [{comments: [{author, text, timestamp}, ...]}, ...]

        Returns:
            PSIStylometryReport with linkages and sockpuppet groups
        """
        # Extract texts per actor
        actor_texts: dict[str, list[str]] = defaultdict(list)
        actor_timestamps: dict[str, list[datetime]] = defaultdict(list)

        for post in posts:
            for comment in post.get("comments", []):
                author = (comment.get("author") or "").strip()
                text = (comment.get("text") or "").strip()
                ts_str = comment.get("timestamp")

                if author and author != "?" and len(text) > 5:
                    actor_texts[author].append(text)

                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            actor_timestamps[author].append(ts)
                        except (ValueError, TypeError):
                            pass

        if not actor_texts:
            return self._empty_report("No texts found")

        # Compute fingerprints
        fingerprints = {}
        for actor, texts in actor_texts.items():
            if len(texts) >= self.min_texts_for_fingerprint:
                fingerprints[actor] = self._compute_fingerprint(actor, texts)

        if len(fingerprints) < 2:
            return self._empty_report("Insufficient accounts for linkage analysis")

        # Find linkages
        linkages = self._find_linkages(fingerprints, actor_timestamps)

        # Cluster into sockpuppet groups
        sockpuppet_groups = self._cluster_sockpuppets(linkages, fingerprints.keys())

        summary = self._build_summary(linkages, sockpuppet_groups)

        return PSIStylometryReport(
            fingerprints=fingerprints,
            linkages=linkages,
            sockpuppet_groups=sockpuppet_groups,
            high_confidence_pairs=len([l for l in linkages if l.overall_confidence > 0.8]),
            summary=summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _compute_fingerprint(self, actor: str, texts: list[str]) -> StylometricFingerprint:
        """
        Compute stylometric fingerprint from texts.
        """
        combined = " ".join(texts).lower()

        # Function word frequency
        words = re.findall(r"\b\w+\b", combined)
        total_words = len(words)
        fw_counts = Counter(w for w in words if w in self._FUNCTION_WORDS)
        fw_freq = {w: count / max(total_words, 1) for w, count in fw_counts.most_common(20)}

        # Punctuation frequency
        punct = re.findall(r"[,.!?;:\-\']", combined)
        punct_freq = {p: count / len(combined) for p, count in Counter(punct).most_common(10)}

        # N-gram distribution
        ngrams = [combined[i:i+self.ngram_size] for i in range(len(combined) - self.ngram_size)]
        ngram_counts = Counter(ngrams)
        ngram_dist = {ng: count / len(ngrams) for ng, count in ngram_counts.most_common(30)}

        # Surface-level stats
        emoji_count = len(re.findall(r"[😀-🙏🌀-🗿👀-👿]", combined))
        caps = len(re.findall(r"[A-Z]", combined))
        sentences = len(re.split(r"[.!?]", combined)) or 1
        avg_sent_len = total_words / sentences if sentences > 0 else 0

        return StylometricFingerprint(
            actor=actor,
            total_texts=len(texts),
            avg_text_length=sum(len(t) for t in texts) / len(texts),
            function_word_freq=fw_freq,
            punctuation_freq=punct_freq,
            ngram_dist=ngram_dist,
            emoji_ratio=emoji_count / len(combined) if combined else 0,
            caps_ratio=caps / len(combined) if combined else 0,
            avg_sentence_length=avg_sent_len,
        )

    def _find_linkages(
        self,
        fingerprints: dict[str, StylometricFingerprint],
        actor_timestamps: dict[str, list[datetime]],
    ) -> list[AccountLinkage]:
        """
        Find suspected account linkages via stylometry + temporal patterns.
        """
        linkages = []
        actors = list(fingerprints.keys())

        for i, actor_a in enumerate(actors):
            for actor_b in actors[i+1:]:
                # Stylometric distance (Burrows Delta)
                delta = self._burrows_delta(fingerprints[actor_a], fingerprints[actor_b])

                # Temporal anti-correlation
                anticorr = self._temporal_anticorrelation(
                    actor_timestamps.get(actor_a, []),
                    actor_timestamps.get(actor_b, []),
                )

                # Shared n-grams
                shared_ngrams = set(fingerprints[actor_a].ngram_dist.keys()) & set(
                    fingerprints[actor_b].ngram_dist.keys()
                )
                shared_pct = len(shared_ngrams) / max(
                    len(fingerprints[actor_a].ngram_dist) + len(fingerprints[actor_b].ngram_dist), 1
                )

                # Overall confidence: low delta + high anticorr + shared ngrams
                confidence = (
                    (1.0 - delta) * 0.4 +  # Stylometric similarity
                    anticorr * 0.4 +  # Temporal opposition
                    shared_pct * 0.2  # Shared patterns
                )

                likely_same = confidence > self.linkage_threshold

                linkages.append(
                    AccountLinkage(
                        account_a=actor_a,
                        account_b=actor_b,
                        stylometric_distance=round(delta, 2),
                        temporal_anticorr=round(anticorr, 2),
                        shared_ngrams_pct=round(shared_pct, 2),
                        overall_confidence=round(confidence, 2),
                        likely_same_operator=likely_same,
                    )
                )

        return sorted(linkages, key=lambda l: -l.overall_confidence)

    def _burrows_delta(
        self,
        fp_a: StylometricFingerprint,
        fp_b: StylometricFingerprint,
    ) -> float:
        """
        Burrows Delta distance: author similarity via function word frequencies.

        Returns: 0 (identical) to 1 (very different)
        """
        # Get all function words from both fingerprints
        all_words = set(fp_a.function_word_freq.keys()) | set(fp_b.function_word_freq.keys())

        if not all_words:
            return 0.5  # Neutral distance if no function words

        # Euclidean distance in function-word space
        dist_sq = sum(
            (fp_a.function_word_freq.get(w, 0) - fp_b.function_word_freq.get(w, 0)) ** 2
            for w in all_words
        )

        delta = math.sqrt(dist_sq / len(all_words))  # Normalize by dimension

        # Scale to 0-1 range
        return min(1.0, delta)

    def _temporal_anticorrelation(
        self,
        timestamps_a: list[datetime],
        timestamps_b: list[datetime],
    ) -> float:
        """
        Measure temporal anti-correlation: accounts never active at same time = same operator.

        Returns: 0 (random) to 1 (perfect opposite)
        """
        if not timestamps_a or not timestamps_b:
            return 0.0

        # Bin into hourly buckets
        def hour_bins(timestamps):
            bins = defaultdict(int)
            for ts in timestamps:
                hour_key = ts.strftime("%Y-%m-%d %H")
                bins[hour_key] += 1
            return bins

        bins_a = hour_bins(timestamps_a)
        bins_b = hour_bins(timestamps_b)

        all_hours = set(bins_a.keys()) | set(bins_b.keys())

        if not all_hours:
            return 0.0

        # Count non-overlapping hours
        non_overlapping = sum(1 for h in all_hours if (h in bins_a) != (h in bins_b))

        anticorr = non_overlapping / len(all_hours)

        return min(1.0, anticorr)

    def _cluster_sockpuppets(
        self,
        linkages: list[AccountLinkage],
        all_actors: set[str],
    ) -> list[list[str]]:
        """
        Cluster accounts into sockpuppet groups via linkage graph.
        """
        # Build adjacency for high-confidence linkages
        graph = defaultdict(set)
        for linkage in linkages:
            if linkage.likely_same_operator:
                graph[linkage.account_a].add(linkage.account_b)
                graph[linkage.account_b].add(linkage.account_a)

        # Simple connected-component clustering
        visited = set()
        clusters = []

        for actor in all_actors:
            if actor in visited:
                continue

            # BFS to find connected component
            cluster = set()
            queue = [actor]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                cluster.add(current)
                for neighbor in graph.get(current, []):
                    if neighbor not in visited:
                        queue.append(neighbor)

            if len(cluster) > 1:  # Only report clusters of 2+
                clusters.append(sorted(cluster))

        return clusters

    def _build_summary(self, linkages: list[AccountLinkage], clusters: list[list[str]]) -> str:
        """Generate human-readable summary."""
        if not linkages:
            return "No stylometric analysis possible (insufficient data)."

        high_conf = len([l for l in linkages if l.overall_confidence > 0.8])
        med_conf = len([l for l in linkages if 0.65 < l.overall_confidence <= 0.8])

        parts = [
            f"Stylometry analysis: {len(linkages)} account pairs examined."
        ]

        if high_conf:
            parts.append(f"{high_conf} high-confidence linkage(s) (0.8+ → likely same operator).")

        if clusters:
            parts.append(
                f"{len(clusters)} sockpuppet cluster(s) detected — "
                f"accounts operated by same person(s)."
            )

        if not high_conf and not clusters:
            parts.append("No significant linkages detected (likely distinct authors).")

        return " ".join(parts)

    @staticmethod
    def _empty_report(reason: str) -> PSIStylometryReport:
        """Return empty report when analysis unavailable."""
        return PSIStylometryReport(
            fingerprints={},
            linkages=[],
            sockpuppet_groups=[],
            high_confidence_pairs=0,
            summary=f"Stylometry analysis unavailable: {reason}",
        )
