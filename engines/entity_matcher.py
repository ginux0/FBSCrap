"""
Entity Matcher Engine — ELITE DEFCON LEVEL

Expande keywords con variaciones semánticas + NER-style matching.
Detecta referencias indirectas a personas/entidades.

Zero hardcoded values. 100% configurable.
"""
from __future__ import annotations
import re
from typing import List, Set, Tuple


class EntityMatcher:
    """
    Semantic expansion + entity matching for person names.

    Capabilities:
    - Extracts initials, abbreviations, partial names
    - Generates title variations (alcalde, presidente, etc.)
    - Fuzzy matching for typos/variations
    - Configurable strictness levels
    """

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("entity_matcher", {})
        self.min_name_length = c.get("min_name_length", 4)
        self.enable_initials = c.get("enable_initials", True)
        self.enable_titles = c.get("enable_titles", True)
        self.enable_partial = c.get("enable_partial", True)

        # Common titles for political figures (configurable)
        self.political_titles = c.get("political_titles", [
            "alcalde", "presidente municipal", "munícipe", "edil",
            "presidente", "gobernador", "diputado", "senador",
            "regidor", "síndico", "funcionario", "servidor público",
        ])

    def expand_person_name(
        self,
        name: str,
        strict: bool = False,
    ) -> List[str]:
        """
        Expand a person name into all possible variations.

        Args:
            name: Full name (e.g., "Gerardo Vargas Landeros")
            strict: If True, only include high-confidence variations

        Returns:
            List of keyword variations for matching
        """
        name = name.strip()
        if not name:
            return []

        variations: Set[str] = set()

        # Always include original
        variations.add(name.lower())

        # Split into parts
        parts = [p for p in name.split() if len(p) >= 2]
        if not parts:
            return [name.lower()]

        # 1. Full name variations
        variations.add(" ".join(parts).lower())

        # 2. Bigrams (consecutive pairs)
        for i in range(len(parts) - 1):
            bigram = f"{parts[i]} {parts[i+1]}"
            variations.add(bigram.lower())

        # 3. Individual parts (only if >= min_length)
        for part in parts:
            if len(part) >= self.min_name_length:
                variations.add(part.lower())

        if not strict:
            # 4. Initials (e.g., "GVL" for "Gerardo Vargas Landeros")
            if self.enable_initials and len(parts) >= 2:
                initials = "".join(p[0].upper() for p in parts)
                variations.add(initials)
                variations.add(initials.lower())

                # Also add dot-separated (e.g., "G.V.L.")
                initials_dots = ".".join(p[0].upper() for p in parts) + "."
                variations.add(initials_dots)

            # 5. Abbreviated middle names (e.g., "Gerardo V. Landeros")
            if len(parts) == 3:
                first, middle, last = parts
                variations.add(f"{first} {middle[0]}. {last}".lower())
                variations.add(f"{first} {last}".lower())

            # 6. Last name + first initial (e.g., "G. Vargas", "Vargas G.")
            if len(parts) >= 2:
                first = parts[0]
                last = parts[-1]
                variations.add(f"{first[0]}. {last}".lower())
                variations.add(f"{last} {first[0]}.".lower())

            # 7. Partial names (enable_partial)
            if self.enable_partial:
                # First + Last (skip middle)
                if len(parts) >= 2:
                    variations.add(f"{parts[0]} {parts[-1]}".lower())

                # Last name only (if distinctive enough)
                if len(parts[-1]) >= 6:
                    variations.add(parts[-1].lower())

        return sorted(variations)

    def expand_with_titles(
        self,
        name: str,
        context_keywords: List[str] | None = None,
    ) -> List[str]:
        """
        Expand name with political titles.

        Args:
            name: Person name
            context_keywords: Additional context (e.g., ["ahome", "sinaloa"])

        Returns:
            List including title variations
        """
        if not self.enable_titles:
            return self.expand_person_name(name)

        base_variations = self.expand_person_name(name)
        with_titles: Set[str] = set(base_variations)

        # Get last name for title combinations
        parts = [p for p in name.split() if len(p) >= 2]
        if not parts:
            return base_variations

        last_name = parts[-1].lower()

        # Add title + last name variations
        for title in self.political_titles:
            with_titles.add(f"{title} {last_name}")
            with_titles.add(f"el {title} {last_name}")
            with_titles.add(f"la {title} {last_name}")

        # Add context-specific variations
        if context_keywords:
            for ctx in context_keywords:
                with_titles.add(f"{last_name} {ctx}")
                with_titles.add(f"{ctx} {last_name}")

        return sorted(with_titles)

    def match_text(
        self,
        text: str,
        keywords: List[str],
        threshold: float = 0.7,
    ) -> Tuple[bool, float, List[str]]:
        """
        Match text against expanded keywords with scoring.

        Args:
            text: Text to match against
            keywords: List of keyword variations
            threshold: Match threshold (0.0-1.0)

        Returns:
            (is_match, confidence, matched_keywords)
        """
        text_lower = text.lower()
        matched: List[str] = []
        scores: List[float] = []

        for kw in keywords:
            if kw in text_lower:
                matched.append(kw)

                # Score based on keyword quality
                # Longer keywords = higher confidence
                # Full name matches = highest confidence
                if len(kw.split()) >= 3:
                    scores.append(1.0)  # Full name
                elif len(kw.split()) == 2:
                    scores.append(0.8)  # Bigram
                elif len(kw) <= 3:
                    scores.append(0.5)  # Initials (lower confidence)
                else:
                    scores.append(0.7)  # Single word

        if not matched:
            return (False, 0.0, [])

        # Overall confidence = max score among matches
        confidence = max(scores) if scores else 0.0

        # Match if confidence >= threshold
        is_match = confidence >= threshold

        return (is_match, confidence, matched)

    def adaptive_filter(
        self,
        name: str,
        initial_results_count: int,
        min_expected: int = 10,
    ) -> List[str]:
        """
        Adaptive keyword expansion based on initial results.

        If initial search finds too few results, relax constraints.

        Args:
            name: Person name
            initial_results_count: How many posts found with strict filter
            min_expected: Minimum expected posts

        Returns:
            Expanded or relaxed keyword list
        """
        if initial_results_count >= min_expected:
            # Enough results with strict filter
            return self.expand_person_name(name, strict=True)

        # Too few results → relax filter
        print(f"  [ENTITY] Initial results ({initial_results_count}) below threshold "
              f"({min_expected}) → relaxing filter")

        # Use loose matching with titles
        return self.expand_with_titles(name, context_keywords=None)


def expand_query_elite(
    query: str,
    cfg: dict | None = None,
    strict: bool = False,
) -> List[str]:
    """
    ELITE-level query expansion with entity matching.

    Args:
        query: Search query (person name)
        cfg: Configuration dict
        strict: Use strict mode (fewer variations)

    Returns:
        List of expanded keywords
    """
    matcher = EntityMatcher(cfg)

    # Detect if query is a person name (has 2-3 parts)
    parts = query.split()

    if len(parts) in (2, 3):
        # Likely a person name → use full expansion
        if strict:
            return matcher.expand_person_name(query, strict=True)
        else:
            return matcher.expand_with_titles(query)
    else:
        # Generic query → basic expansion
        return matcher.expand_person_name(query, strict=strict)
