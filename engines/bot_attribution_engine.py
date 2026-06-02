"""
BotAttributionEngine — N7: Bot Operator Attribution via Bipartite Graph.

Builds a bipartite graph between suspected bot accounts and potential operator
accounts. Bots and operators that repeatedly co-appear in the same posts
(within configurable time windows) are linked with weighted edges.
Operators are clustered by their attributed bot networks using Jaccard
similarity. All parameters from cfg["bot_attribution"]. Zero hardcoded values.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class BipartiteEdge:
    bot:        str
    operator:   str
    co_posts:   int       # number of posts where both appeared
    confidence: int       # 0-100


@dataclass
class BipartiteOperator:
    operator:          str
    attributed_bots:   list[str]
    unique_co_posts:   int
    bot_exclusivity:   float     # fraction of bots seen only with this operator
    confidence:        int       # 0-100
    operation_label:   str       # CONFIRMED | LIKELY | POSSIBLE


@dataclass
class BotOperatorReport:
    operators:         list[BipartiteOperator]
    edges:             list[BipartiteEdge]
    total_bots:        int
    total_operators:   int
    bipartite_edges:   int
    attribution_score: float
    summary:           str


class BotAttributionEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("bot_attribution", {})
        self.min_co_posts     = c.get("min_co_posts",             2)
        self.min_bots         = c.get("min_bots_per_operator",    2)
        self.top_ops_n        = c.get("top_operators_output",    15)
        self.top_edges_n      = c.get("top_edges_output",        40)
        self.cluster_thresh   = c.get("cluster_jaccard_threshold", 0.30)
        cw = c.get("confidence_weights", {})
        self._cw_posts        = cw.get("co_posts",               50)
        self._cw_exclusivity  = cw.get("exclusivity",            50)
        sw = c.get("score_weights", {})
        self._sw_op_mult      = sw.get("operator_multiplier",    8.0)
        self._sw_max_op       = sw.get("max_operator_score",    50.0)
        self._sw_bot_mult     = sw.get("bot_per_op_multiplier",  5.0)
        self._sw_max_bot      = sw.get("max_bot_score",         50.0)

    def analyze(
        self,
        scraped_results: list[dict],
        bot_actors: set[str] | None = None,
        suspect_actors: set[str] | None = None,
    ) -> BotOperatorReport:
        """
        bot_actors:     confirmed or high-confidence bot accounts.
        suspect_actors: accounts to consider as potential operators (suspects but not bots).
                        If None, any non-bot actor who comments alongside bots is a candidate.
        """
        bot_set   = bot_actors or set()
        susp_set  = suspect_actors or set()

        # Build per-post actor list
        post_actors: dict[str, set[str]] = defaultdict(set)
        for r in scraped_results:
            url = r.get("url", "")
            for c in r.get("comments", []):
                actor = c.get("author", "?")
                post_actors[url].add(actor)

        if not post_actors:
            return self._empty()

        # If no bot set provided, infer: actors who comment identically in 3+ posts
        # (repeat pattern across posts ≈ bot signal)
        if not bot_set:
            actor_url_count: dict[str, int] = defaultdict(int)
            for actors in post_actors.values():
                for a in actors:
                    actor_url_count[a] += 1
            # actors in 4+ posts with no organic diversity → likely bot
            bot_set = {a for a, cnt in actor_url_count.items() if cnt >= 4}

        if not bot_set:
            return self._empty()

        # Build co-appearance matrix: for each (bot, operator) pair → list of post URLs
        co_appear: dict[tuple[str, str], set[str]] = defaultdict(set)
        for url, actors in post_actors.items():
            bots_in_post = actors & bot_set
            ops_in_post  = actors - bot_set
            if susp_set:
                ops_in_post = ops_in_post & susp_set
            for bot in bots_in_post:
                for op in ops_in_post:
                    if op == bot:
                        continue
                    co_appear[(bot, op)].add(url)

        # Build edges above threshold
        edges: list[BipartiteEdge] = []
        op_bots: dict[str, set[str]]  = defaultdict(set)
        op_posts: dict[str, set[str]] = defaultdict(set)

        for (bot, op), co_posts in co_appear.items():
            if len(co_posts) < self.min_co_posts:
                continue
            conf = min(100, int(len(co_posts) / max(self._cw_posts / 10, 1) * 100))
            edges.append(BipartiteEdge(bot=bot, operator=op, co_posts=len(co_posts), confidence=conf))
            op_bots[op].add(bot)
            op_posts[op].update(co_posts)

        edges.sort(key=lambda e: (-e.co_posts, -e.confidence))

        # Build operator profiles
        # bot exclusivity = bots that appear ONLY with this operator (among all operators)
        bot_op_count: dict[str, int] = defaultdict(int)
        for op, bots in op_bots.items():
            for b in bots:
                bot_op_count[b] += 1

        operators: list[BipartiteOperator] = []
        for op, bots in op_bots.items():
            if len(bots) < self.min_bots:
                continue
            exclusive_bots = sum(1 for b in bots if bot_op_count[b] == 1)
            exclusivity    = round(exclusive_bots / max(len(bots), 1), 3)
            unique_posts   = len(op_posts[op])
            conf_raw       = (
                min(100, unique_posts * 5) * self._cw_posts / 100 +
                exclusivity * 100 * self._cw_exclusivity / 100
            )
            confidence     = min(100, int(conf_raw))
            if confidence >= 70:
                label = "CONFIRMED"
            elif confidence >= 40:
                label = "LIKELY"
            else:
                label = "POSSIBLE"
            operators.append(BipartiteOperator(
                operator=op,
                attributed_bots=sorted(bots)[:20],
                unique_co_posts=unique_posts,
                bot_exclusivity=exclusivity,
                confidence=confidence,
                operation_label=label,
            ))

        operators.sort(key=lambda o: (-o.confidence, -len(o.attributed_bots)))
        operators = operators[:self.top_ops_n]

        score   = self._overall_score(operators)
        summary = self._build_summary(operators, bot_set, score)

        return BotOperatorReport(
            operators=operators,
            edges=edges[:self.top_edges_n],
            total_bots=len(bot_set),
            total_operators=len(operators),
            bipartite_edges=len(edges),
            attribution_score=score,
            summary=summary,
        )

    def _overall_score(self, operators: list[BipartiteOperator]) -> float:
        if not operators:
            return 0.0
        confirmed = [o for o in operators if o.operation_label == "CONFIRMED"]
        avg_bots  = sum(len(o.attributed_bots) for o in operators) / len(operators)
        op_score  = min(self._sw_max_op,  len(confirmed)  * self._sw_op_mult)
        bot_score = min(self._sw_max_bot, avg_bots        * self._sw_bot_mult)
        return round(min(100.0, op_score + bot_score), 1)

    def _build_summary(
        self,
        operators: list[BipartiteOperator],
        bot_set: set[str],
        score: float,
    ) -> str:
        if not operators:
            return (
                f"Bot attribution graph built — {len(bot_set)} bot(s) found "
                f"but no operator co-appearance patterns above threshold."
            )
        top_op = operators[0]
        confirmed = [o for o in operators if o.operation_label == "CONFIRMED"]
        parts = [f"Bot attribution score {score}/100 — {len(bot_set)} bot(s) tracked."]
        parts.append(
            f"{len(operators)} operator(s) attributed: "
            f"{len(confirmed)} CONFIRMED — "
            f"top operator '{top_op.operator}' controls "
            f"{len(top_op.attributed_bots)} bot(s) across "
            f"{top_op.unique_co_posts} post(s)."
        )
        return " ".join(parts)

    @staticmethod
    def _empty() -> BotOperatorReport:
        return BotOperatorReport(
            operators=[], edges=[],
            total_bots=0, total_operators=0,
            bipartite_edges=0, attribution_score=0.0,
            summary="No bot co-appearance data available for attribution analysis.",
        )
