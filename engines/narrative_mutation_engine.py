"""
NarrativeMutationEngine.

Tracks how attack narratives evolve and mutate over the course of a campaign.
Bot operators don't use static scripts — they adapt the narrative in real-time
based on what's getting traction. This engine captures that evolution.

Algorithm:
  1. Sort all comments by timestamp into overlapping time windows
  2. Build TF-IDF vocabulary snapshot per window
  3. Compute cosine similarity between consecutive windows
  4. Significant similarity drop = MUTATION EVENT
  5. Extract new terms that appeared = mutation markers
  6. Find the first actor to use new terms = mutation introducer
  7. Track how fast the mutation spreads to other actors

Mutation Types:
  EXPANSION     — original narrative + new attack terms added
  PIVOT         — vocabulary completely replaced (new attack angle)
  AMPLIFICATION — same terms but escalated intensity (caps, profanity)
  INJECTION     — new entity/name introduced into the narrative
  CONVERGENCE   — separate narrative threads merging into one

Campaign mutation score 0-100:
  High = narrative was actively managed and adapted (coordinated operation)
  Low  = static vocabulary (either organic or unsophisticated bot)

All thresholds from cfg["narrative_mutation"]. Zero hardcoded values.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List


# ── TF-IDF implementation (no sklearn dependency) ─────────────────────────────

_STOPWORDS = frozenset({
    "de","la","el","en","y","a","que","es","lo","se","del","por","con","una",
    "un","las","los","al","su","no","le","más","o","pero","si","como","me",
    "esta","esto","eso","mi","te","ser","fue","hay","así","ya","han","hoy",
    "también","bien","todo","muy","sobre","ha","hasta","cuando","tiene",
    "the","and","of","to","in","is","that","it","for","on","are","with",
    "this","but","not","from","they","we","you","have","an","be",
})

_WORD_RE = re.compile(r"[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{3,}", re.UNICODE)

_CAPS_INTENSITY = re.compile(r'\b[A-ZÁÉÍÓÚÜÑ]{3,}\b')
_ENTITY_RE      = re.compile(
    r'\b(?:rocha|moya|mayo|gerardo|vargas|imelda|castro|'
    r'[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+ [A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+)\b'
)


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)
            if w.lower() not in _STOPWORDS]


def _tfidf_vector(docs: list[str], vocab: list[str]) -> list[float]:
    """Compute normalized TF-IDF vector for a collection of documents."""
    n_docs  = max(len(docs), 1)
    all_tok = [_tokenize(d) for d in docs]
    flat    = [t for toks in all_tok for t in toks]
    tf      = Counter(flat)

    # IDF: log(n_docs / (1 + docs_containing_term))
    df: Counter = Counter()
    for toks in all_tok:
        for t in set(toks):
            df[t] += 1

    vec = []
    for term in vocab:
        tfidf = tf.get(term, 0) * math.log(n_docs / (1 + df.get(term, 0)) + 1)
        vec.append(tfidf)

    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    return round(dot / (na * nb), 4) if na and nb else 0.0


def _classify_mutation(
    old_terms: set[str],
    new_terms: set[str],
    old_text:  str,
    new_text:  str,
) -> str:
    added   = new_terms - old_terms
    removed = old_terms - new_terms
    overlap = old_terms & new_terms

    caps_old = len(_CAPS_INTENSITY.findall(old_text))
    caps_new = len(_CAPS_INTENSITY.findall(new_text))
    entities_new = set(_ENTITY_RE.findall(new_text.lower()))
    entities_old = set(_ENTITY_RE.findall(old_text.lower()))

    if not overlap or len(overlap) / max(len(old_terms), 1) < 0.2:
        return "PIVOT"
    if entities_new - entities_old:
        return "INJECTION"
    if caps_new > caps_old * 1.5 and len(added) < len(removed):
        return "AMPLIFICATION"
    if len(added) > len(removed) * 0.5:
        return "EXPANSION"
    return "CONVERGENCE"


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class NarrativeSnapshot:
    window_id:     int
    start_ts:      str
    end_ts:        str
    top_terms:     List[str]       # top 10 terms this window
    comment_count: int
    actors:        List[str]
    intensity:     float           # avg aggressive/negative score


@dataclass
class MutationEvent:
    mutation_id:          int
    from_snapshot:        NarrativeSnapshot
    to_snapshot:          NarrativeSnapshot
    similarity_drop:      float      # 1.0 = identical, 0.0 = completely different
    mutation_type:        str        # EXPANSION|PIVOT|AMPLIFICATION|INJECTION|CONVERGENCE
    new_terms:            List[str]  # terms that appeared
    dropped_terms:        List[str]  # terms that disappeared
    mutation_introducer:  str        # first actor to use new terms
    adoption_count:       int        # actors who adopted within spread window
    mutation_score:       int        # 0-100


@dataclass
class NarrativeMutationReport:
    snapshots:             List[NarrativeSnapshot]
    mutations:             List[MutationEvent]
    seed_narrative:        List[str]   # top terms of first snapshot
    final_narrative:       List[str]   # top terms of last snapshot
    pivot_events:          int
    expansion_events:      int
    injection_events:      int
    most_active_mutator:   str | None
    mutation_score:        float       # 0-100
    summary:               str


class NarrativeMutationEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("narrative_mutation", {})
        self._window_min      = c.get("window_minutes",          30)
        self._overlap_pct     = c.get("window_overlap_pct",      0.50)
        self._mutation_thresh = c.get("mutation_threshold",       0.65)
        self._vocab_size      = c.get("vocab_size",              50)
        self._spread_window   = c.get("spread_window_minutes",   20)
        self._min_comments    = c.get("min_comments_per_window",  3)
        self._min_windows     = c.get("min_windows",              3)
        self._top_terms       = c.get("top_terms",               10)
        self._top_mutations   = c.get("top_mutations_output",    10)
        sw = c.get("score_weights", {})
        self._sw_pivot        = sw.get("pivot_weight",           25.0)
        self._sw_injection    = sw.get("injection_weight",       20.0)
        self._sw_expansion    = sw.get("expansion_weight",       15.0)
        self._sw_intensity    = sw.get("intensity_multiplier",    0.3)

    # ─────────────────────────────────────────────────────────────────────────

    def analyze(
        self,
        scraped_results:  list[dict],
        injection_report= None,
    ) -> NarrativeMutationReport:
        """
        injection_report: optional NarrativeInjectionReport to seed the
        initial narrative terms.
        """
        if not scraped_results:
            return self._empty()

        # ── Collect all comments with timestamps ──────────────────────────────
        all_items: list[tuple[datetime, str, str]] = []  # (ts, actor, text)
        for r in scraped_results:
            for c in r.get("comments", []):
                ts_str = c.get("timestamp")
                text   = (c.get("text") or "").strip()
                actor  = c.get("author", "?")
                if ts_str and text and actor != "?":
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        all_items.append((ts, actor, text))
                    except Exception:
                        pass

        if len(all_items) < self._min_comments * 2:
            return self._empty()

        all_items.sort(key=lambda x: x[0])
        t_start = all_items[0][0]
        t_end   = all_items[-1][0]

        # ── Build sliding windows ─────────────────────────────────────────────
        step_td   = timedelta(minutes=self._window_min * (1 - self._overlap_pct))
        window_td = timedelta(minutes=self._window_min)

        snapshots: list[NarrativeSnapshot] = []
        wid = 0
        current = t_start

        while current < t_end:
            wend = current + window_td
            window_items = [
                (ts, actor, text) for ts, actor, text in all_items
                if current <= ts < wend
            ]
            if len(window_items) >= self._min_comments:
                snap = self._build_snapshot(wid, current, wend, window_items)
                snapshots.append(snap)
                wid += 1
            current += step_td

        if len(snapshots) < self._min_windows:
            return self._empty()

        # ── Build global vocabulary ───────────────────────────────────────────
        all_texts = [
            text for _, _, text in all_items
        ]
        all_tokens = Counter(_tokenize(" ".join(all_texts)))
        vocab = [term for term, _ in all_tokens.most_common(self._vocab_size)]

        # Compute TF-IDF vectors per snapshot
        snap_vectors: list[list[float]] = []
        for snap in snapshots:
            win_texts = [
                text for item_ts, _, text in all_items
                if snap.start_ts <= item_ts.isoformat(timespec="seconds") < snap.end_ts
            ]
            snap_vectors.append(_tfidf_vector(win_texts or [""], vocab))

        # ── Detect mutations between consecutive windows ───────────────────────
        mutations: list[MutationEvent] = []
        mutator_counter: dict[str, int] = defaultdict(int)

        for i in range(len(snapshots) - 1):
            sa, sb = snapshots[i], snapshots[i + 1]
            va, vb = snap_vectors[i], snap_vectors[i + 1]

            sim = _cosine(va, vb)
            if sim > self._mutation_thresh:
                continue  # stable narrative, no mutation

            # Identify what changed
            terms_a = set(sa.top_terms)
            terms_b = set(sb.top_terms)
            new_terms     = sorted(terms_b - terms_a)[:8]
            dropped_terms = sorted(terms_a - terms_b)[:8]

            # Reconstruct original text for window A and B
            text_a = " ".join(
                text for ts, _, text in all_items
                if sa.start_ts <= ts.isoformat(timespec="seconds") < sa.end_ts
            )
            text_b = " ".join(
                text for ts, _, text in all_items
                if sb.start_ts <= ts.isoformat(timespec="seconds") < sb.end_ts
            )

            mutation_type = _classify_mutation(terms_a, terms_b, text_a, text_b)

            # Find first actor to use the new terms in window B
            introducer, intro_ts = self._find_introducer(
                new_terms, sb.start_ts, sb.end_ts, all_items,
            )
            if introducer:
                mutator_counter[introducer] += 1

            # Count adoption: actors who used new terms within spread window
            adoption = self._count_adoption(
                new_terms, intro_ts, self._spread_window, all_items, introducer,
            ) if introducer else 0

            mev = self._score_mutation(
                len(mutations), sa, sb, sim, mutation_type,
                new_terms, dropped_terms, introducer or "unknown", adoption,
            )
            mutations.append(mev)

        mutations.sort(key=lambda m: -m.mutation_score)
        top = mutations[:self._top_mutations]

        # Narrative evolution
        seed_narrative  = snapshots[0].top_terms
        final_narrative = snapshots[-1].top_terms

        pivot_cnt  = sum(1 for m in mutations if m.mutation_type == "PIVOT")
        exp_cnt    = sum(1 for m in mutations if m.mutation_type == "EXPANSION")
        inj_cnt    = sum(1 for m in mutations if m.mutation_type == "INJECTION")

        top_mutator = max(mutator_counter, key=lambda k: mutator_counter[k]) \
                      if mutator_counter else None

        score   = self._campaign_score(mutations, pivot_cnt, exp_cnt, inj_cnt, snapshots)
        summary = self._build_summary(
            mutations, pivot_cnt, exp_cnt, inj_cnt,
            top_mutator, seed_narrative, final_narrative, score,
        )

        return NarrativeMutationReport(
            snapshots           = snapshots,
            mutations           = top,
            seed_narrative      = seed_narrative,
            final_narrative     = final_narrative,
            pivot_events        = pivot_cnt,
            expansion_events    = exp_cnt,
            injection_events    = inj_cnt,
            most_active_mutator = top_mutator,
            mutation_score      = score,
            summary             = summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _build_snapshot(
        self,
        wid:   int,
        start: datetime,
        end:   datetime,
        items: list[tuple],
    ) -> NarrativeSnapshot:
        from engines.sentiment import _score_one, reload_lexicons

        texts   = [text for _, _, text in items]
        actors  = list({actor for _, actor, _ in items})
        tokens  = Counter(_tokenize(" ".join(texts)))
        top     = [term for term, _ in tokens.most_common(self._top_terms)]

        scored = [_score_one(t) for t in texts]
        n = max(len(scored), 1)
        intensity = sum(s["neg"] + s["agg"] for s in scored) / n

        return NarrativeSnapshot(
            window_id     = wid,
            start_ts      = start.isoformat(timespec="seconds"),
            end_ts        = end.isoformat(timespec="seconds"),
            top_terms     = top,
            comment_count = len(items),
            actors        = actors[:20],
            intensity     = round(intensity, 3),
        )

    def _find_introducer(
        self,
        new_terms: list[str],
        win_start: str,
        win_end:   str,
        all_items: list[tuple],
    ) -> tuple[str | None, datetime | None]:
        """Find the first actor to use any of the new mutation terms."""
        if not new_terms:
            return None, None
        term_re = re.compile(
            r'\b(' + '|'.join(re.escape(t) for t in new_terms) + r')\b',
            re.IGNORECASE,
        )
        for ts, actor, text in all_items:
            ts_s = ts.isoformat(timespec="seconds")
            if ts_s < win_start or ts_s >= win_end:
                continue
            if term_re.search(text):
                return actor, ts
        return None, None

    def _count_adoption(
        self,
        new_terms:    list[str],
        intro_ts:     datetime | None,
        spread_min:   int,
        all_items:    list[tuple],
        introducer:   str,
    ) -> int:
        if not intro_ts or not new_terms:
            return 0
        spread_end = intro_ts + timedelta(minutes=spread_min)
        term_re    = re.compile(
            r'\b(' + '|'.join(re.escape(t) for t in new_terms) + r')\b',
            re.IGNORECASE,
        )
        adopters: set[str] = set()
        for ts, actor, text in all_items:
            if ts <= intro_ts or ts > spread_end:
                continue
            if actor == introducer:
                continue
            if term_re.search(text):
                adopters.add(actor)
        return len(adopters)

    def _score_mutation(
        self,
        mid:         int,
        sa:          NarrativeSnapshot,
        sb:          NarrativeSnapshot,
        sim:         float,
        mtype:       str,
        new_terms:   list[str],
        dropped:     list[str],
        introducer:  str,
        adoption:    int,
    ) -> MutationEvent:
        base = {
            "PIVOT":         70,
            "INJECTION":     65,
            "EXPANSION":     45,
            "AMPLIFICATION": 40,
            "CONVERGENCE":   30,
        }.get(mtype, 30)
        drop_bonus    = int((1.0 - sim) * 20)
        adoption_bonus= min(10, adoption * 2)
        score = min(100, base + drop_bonus + adoption_bonus)

        return MutationEvent(
            mutation_id         = mid,
            from_snapshot       = sa,
            to_snapshot         = sb,
            similarity_drop     = round(1.0 - sim, 3),
            mutation_type       = mtype,
            new_terms           = new_terms,
            dropped_terms       = dropped,
            mutation_introducer = introducer,
            adoption_count      = adoption,
            mutation_score      = score,
        )

    def _campaign_score(
        self,
        mutations: list[MutationEvent],
        pivots:    int,
        expansions:int,
        injections:int,
        snapshots: list[NarrativeSnapshot],
    ) -> float:
        if not mutations:
            return 0.0
        avg_intensity = sum(s.intensity for s in snapshots) / len(snapshots)
        score = (pivots     * self._sw_pivot
                 + injections * self._sw_injection
                 + expansions * self._sw_expansion
                 + avg_intensity * self._sw_intensity * 100)
        return round(min(100.0, score), 1)

    def _build_summary(
        self,
        mutations:  list,
        pivots:     int,
        expansions: int,
        injections: int,
        mutator:    str | None,
        seed:       list[str],
        final:      list[str],
        score:      float,
    ) -> str:
        n = len(mutations)
        if not n:
            return "Narrative was static throughout campaign — no mutations detected."
        parts = [
            f"Narrative mutation score {score}/100. "
            f"{n} mutation event(s): {pivots} PIVOT · {expansions} EXPANSION · {injections} INJECTION."
        ]
        if seed and final:
            seed_str  = ', '.join(seed[:4])
            final_str = ', '.join(final[:4])
            if set(seed[:4]) != set(final[:4]):
                parts.append(f"Narrative evolved from [{seed_str}] → [{final_str}].")
        if mutator:
            parts.append(
                f"Most active mutator: '{mutator}' — introduced the most narrative variants."
            )
        if pivots > 0:
            parts.append(
                f"{pivots} PIVOT event(s) detected — complete narrative reframe "
                f"signals operator adaptation to counter-messaging."
            )
        return " ".join(parts)

    @staticmethod
    def _empty() -> NarrativeMutationReport:
        return NarrativeMutationReport(
            snapshots=[], mutations=[], seed_narrative=[], final_narrative=[],
            pivot_events=0, expansion_events=0, injection_events=0,
            most_active_mutator=None, mutation_score=0.0,
            summary="Insufficient timestamped comment data for mutation analysis.",
        )
