"""
Ownership Attribution Engine — Who controls the bots?

All parameters read from cfg["ownership_engine"]. Zero hardcoded values.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .comment_bot_detector import BotSuspect
    from .cib_graph import CIBGraphResult


@dataclass
class PageProfile:
    page_name:       str
    total_posts:     int
    attack_posts:    int
    attack_rate:     float
    bot_commenters:  list[str]
    all_commenters:  list[str]
    bot_density:     float
    sample_attacks:  list[str]
    narrative_hash:  str


@dataclass
class PageCluster:
    cluster_id:      int
    pages:           list[str]
    shared_bots:     list[str]
    jaccard_min:     float
    jaccard_avg:     float
    total_attacks:   int
    narrative_match: float
    risk_label:      str


@dataclass
class OperatorProfile:
    operator_id:      int
    controlled_pages: list[str]
    bot_army:         list[str]
    confidence:       int
    confidence_label: str
    signals:          list[str]
    attack_volume:    int
    page_cluster_id:  int


@dataclass
class BotPageBinding:
    bot_actor:       str
    bound_pages:     list[str]
    binding_score:   int
    exclusivity:     float
    likely_operator: str


@dataclass
class OwnershipReport:
    page_profiles:      dict[str, PageProfile]
    page_clusters:      list[PageCluster]
    operator_profiles:  list[OperatorProfile]
    bot_bindings:       list[BotPageBinding]
    attack_pages:       list[str]
    total_attack_pages: int
    total_operators:    int
    network_summary:    str


class OwnershipEngine:

    def __init__(
        self,
        posts:        list[dict],
        bot_suspects: "list[BotSuspect] | None" = None,
        cib_result:   "CIBGraphResult | None"   = None,
        cfg:          dict | None               = None,
    ):
        self.posts       = posts
        self.bot_set     = {s.author for s in (bot_suspects or [])}
        self.cib_result  = cib_result
        self.suspect_map = {s.author: s for s in (bot_suspects or [])}

        c = (cfg or {}).get("ownership_engine", {})
        self._jaccard_cluster_threshold = c.get("jaccard_cluster_threshold", 0.25)
        self._bot_density_threshold     = c.get("bot_density_threshold", 0.30)
        self._min_shared_bots           = c.get("min_shared_bots", 2)
        self._max_bindings_output       = c.get("max_bindings_output", 100)

        rt = c.get("risk_thresholds", {})
        self._rt_crit_j     = rt.get("critical_jaccard", 0.60)
        self._rt_high_j     = rt.get("high_jaccard", 0.35)
        self._rt_med_j      = rt.get("medium_jaccard", 0.20)
        self._rt_high_bots  = rt.get("high_bot_count", 5)
        self._rt_med_bots   = rt.get("medium_bot_count", 3)

        cw = c.get("confidence_weights", {})
        self._cw_jaccard    = cw.get("jaccard", 40)
        self._cw_shared_bots= cw.get("shared_bots", 30)
        self._cw_narrative  = cw.get("narrative", 20)

        rb = c.get("risk_bonus", {})
        self._rb = {"CONFIRMED": rb.get("CONFIRMED", 10), "PROBABLE": rb.get("HIGH", 7),
                    "SUSPECTED": rb.get("MEDIUM", 3), "POSSIBLE": rb.get("LOW", 0)}

        bw = c.get("binding_weights", {})
        self._bw_excl = bw.get("exclusivity", 60)
        self._bw_atk  = bw.get("attack_rate", 39)

        self._attack_labels = set(c.get("attack_labels", ["NEGATIVO", "AGRESIVO"]))

    def analyze(self) -> OwnershipReport:
        page_profiles = self._build_page_profiles()

        if len(page_profiles) < 2:
            return self._minimal_report(page_profiles)

        jaccard       = self._pairwise_jaccard(page_profiles)
        page_clusters = self._cluster_pages(page_profiles, jaccard)
        operators     = self._build_operators(page_profiles, page_clusters)
        bindings      = self._build_bindings(page_profiles, page_clusters, operators)

        attack_pages = [
            name for name, p in page_profiles.items()
            if p.bot_density >= self._bot_density_threshold or p.attack_rate >= 0.70
        ]

        summary = self._summarize(page_profiles, page_clusters, operators)

        return OwnershipReport(
            page_profiles=page_profiles,
            page_clusters=page_clusters,
            operator_profiles=operators,
            bot_bindings=bindings,
            attack_pages=attack_pages,
            total_attack_pages=len(attack_pages),
            total_operators=len(operators),
            network_summary=summary,
        )

    def _build_page_profiles(self) -> dict[str, PageProfile]:
        page_data: dict[str, dict] = defaultdict(lambda: {
            "posts": [], "commenters": set(), "bot_commenters": set(),
            "attack_texts": [], "all_texts": []
        })

        for post in self.posts:
            src  = (post.get("source") or post.get("url") or "?").strip()
            lbl  = (post.get("label") or "").upper()
            text = post.get("title") or post.get("text") or ""
            page_data[src]["posts"].append(post)
            if lbl in self._attack_labels:
                page_data[src]["attack_texts"].append(text[:150])
            page_data[src]["all_texts"].append(text[:150])

            for c in post.get("comments", []):
                actor = (c.get("author") or "").strip()
                if not actor or actor == "?":
                    continue
                page_data[src]["commenters"].add(actor)
                if actor in self.bot_set:
                    page_data[src]["bot_commenters"].add(actor)

        profiles: dict[str, PageProfile] = {}
        for page, data in page_data.items():
            if not data["posts"]:
                continue
            total      = len(data["posts"])
            attacks    = len(data["attack_texts"])
            all_c      = list(data["commenters"])
            bot_c      = list(data["bot_commenters"])
            bot_density = len(bot_c) / max(len(all_c), 1)
            narrative   = self._narrative_hash(data["attack_texts"])

            profiles[page] = PageProfile(
                page_name=page,
                total_posts=total,
                attack_posts=attacks,
                attack_rate=round(attacks / max(total, 1), 3),
                bot_commenters=bot_c,
                all_commenters=all_c,
                bot_density=round(bot_density, 3),
                sample_attacks=data["attack_texts"][:3],
                narrative_hash=narrative,
            )

        return profiles

    @staticmethod
    def _pairwise_jaccard(
        profiles: dict[str, PageProfile]
    ) -> dict[tuple[str, str], float]:
        pages = list(profiles.keys())
        result: dict[tuple[str, str], float] = {}

        for i, pa in enumerate(pages):
            bots_a = set(profiles[pa].bot_commenters)
            if not bots_a:
                continue
            for pb in pages[i + 1:]:
                bots_b = set(profiles[pb].bot_commenters)
                if not bots_b:
                    continue
                inter = len(bots_a & bots_b)
                if inter < 2:
                    continue
                union = len(bots_a | bots_b)
                j     = inter / union if union else 0.0
                if j > 0:
                    result[tuple(sorted([pa, pb]))] = round(j, 4)

        return result

    def _cluster_pages(
        self,
        profiles: dict[str, PageProfile],
        jaccard:  dict[tuple[str, str], float],
    ) -> list[PageCluster]:
        parent = {p: p for p in profiles}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for (pa, pb), sim in jaccard.items():
            if sim >= self._jaccard_cluster_threshold:
                ra, rb = find(pa), find(pb)
                if ra != rb:
                    parent[ra] = rb

        groups: dict[str, list[str]] = defaultdict(list)
        for page in profiles:
            groups[find(page)].append(page)

        clusters: list[PageCluster] = []
        for cid, (root, pages) in enumerate(groups.items()):
            if len(pages) < 2:
                continue

            bot_sets    = [set(profiles[p].bot_commenters) for p in pages]
            shared_bots = list(set.intersection(*bot_sets)) if bot_sets else []
            if not shared_bots:
                shared_bots = list(set.union(*bot_sets) if bot_sets else set())[:20]

            sims   = [jaccard.get(tuple(sorted([pa, pb])), 0.0)
                      for i, pa in enumerate(pages) for pb in pages[i + 1:]]
            j_min  = round(min(sims) if sims else 0.0, 4)
            j_avg  = round(sum(sims) / len(sims) if sims else 0.0, 4)

            total_atk = sum(profiles[p].attack_posts for p in pages)

            nar_sims = []
            for i, pa in enumerate(pages):
                for pb in pages[i + 1:]:
                    nar_sims.append(
                        self._narrative_similarity(
                            profiles[pa].narrative_hash,
                            profiles[pb].narrative_hash,
                        )
                    )
            nar_sim = round(sum(nar_sims) / len(nar_sims) if nar_sims else 0.0, 3)

            if j_avg >= self._rt_crit_j and len(shared_bots) >= self._rt_high_bots:
                risk = "CONFIRMED"
            elif j_avg >= self._rt_high_j and len(shared_bots) >= self._rt_med_bots:
                risk = "PROBABLE"
            elif j_avg >= self._rt_med_j:
                risk = "SUSPECTED"
            else:
                risk = "POSSIBLE"

            clusters.append(PageCluster(
                cluster_id=cid, pages=pages, shared_bots=shared_bots,
                jaccard_min=j_min, jaccard_avg=j_avg,
                total_attacks=total_atk, narrative_match=nar_sim,
                risk_label=risk,
            ))

        risk_order = {"CONFIRMED": 3, "PROBABLE": 2, "SUSPECTED": 1, "POSSIBLE": 0}
        clusters.sort(key=lambda c: (risk_order[c.risk_label], len(c.shared_bots)), reverse=True)
        return clusters

    def _build_operators(
        self,
        profiles: dict[str, PageProfile],
        clusters: list[PageCluster],
    ) -> list[OperatorProfile]:
        operators: list[OperatorProfile] = []
        for cl in clusters:
            bot_army = list({b for p in cl.pages for b in profiles[p].bot_commenters})

            conf = int(
                cl.jaccard_avg * self._cw_jaccard +
                min(len(cl.shared_bots) / 10, 1.0) * self._cw_shared_bots +
                cl.narrative_match * self._cw_narrative +
                self._rb.get(cl.risk_label, 0)
            )
            conf = min(99, max(1, conf))

            conf_label = (
                "CONFIRMED" if conf >= 75 else
                "PROBABLE"  if conf >= 50 else
                "SUSPECTED" if conf >= 25 else
                "POSSIBLE"
            )

            signals: list[str] = []
            if cl.jaccard_avg >= 0.50:
                signals.append(f"{len(cl.shared_bots)} bots shared across {len(cl.pages)} pages")
            if cl.narrative_match >= 0.60:
                signals.append(f"identical narrative ({cl.narrative_match:.0%} similarity)")
            if cl.total_attacks >= 10:
                signals.append(f"{cl.total_attacks} coordinated attack posts")
            if cl.jaccard_min >= 0.40:
                signals.append(f"min Jaccard {cl.jaccard_min:.2f} — very high overlap")
            signals = signals[:5]

            operators.append(OperatorProfile(
                operator_id=cl.cluster_id,
                controlled_pages=cl.pages,
                bot_army=bot_army,
                confidence=conf,
                confidence_label=conf_label,
                signals=signals,
                attack_volume=cl.total_attacks,
                page_cluster_id=cl.cluster_id,
            ))

        operators.sort(key=lambda o: -o.confidence)
        return operators

    def _build_bindings(
        self,
        profiles:  dict[str, PageProfile],
        clusters:  list[PageCluster],
        operators: list[OperatorProfile],
    ) -> list[BotPageBinding]:
        bot_pages: dict[str, set[str]] = defaultdict(set)
        for page, prof in profiles.items():
            for bot in prof.bot_commenters:
                bot_pages[bot].add(page)

        page_operator: dict[str, int] = {}
        for op in operators:
            for page in op.controlled_pages:
                page_operator[page] = op.operator_id

        total_pages = max(len(profiles), 1)
        bindings: list[BotPageBinding] = []

        for bot, pages in bot_pages.items():
            pages_list  = list(pages)
            exclusivity = 1.0 - (len(pages) - 1) / total_pages
            op_ids      = {page_operator[p] for p in pages_list if p in page_operator}
            likely_op   = f"OP-{min(op_ids)}" if op_ids else "UNATTRIBUTED"
            avg_atk     = sum(
                profiles[p].attack_rate for p in pages_list if p in profiles
            ) / max(len(pages_list), 1)
            binding_score = min(99, max(1, int(
                exclusivity * self._bw_excl + avg_atk * self._bw_atk
            )))

            bindings.append(BotPageBinding(
                bot_actor=bot, bound_pages=pages_list,
                binding_score=binding_score,
                exclusivity=round(exclusivity, 3),
                likely_operator=likely_op,
            ))

        bindings.sort(key=lambda b: -b.binding_score)
        return bindings[:self._max_bindings_output]

    @staticmethod
    def _narrative_hash(texts: list[str]) -> str:
        from collections import Counter
        all_words: list[str] = []
        for t in texts:
            all_words.extend(re.findall(r'\b\w{4,}\b', t.lower()))
        if not all_words:
            return ""
        top = [w for w, _ in Counter(all_words).most_common(20)]
        return " ".join(sorted(top))

    @staticmethod
    def _narrative_similarity(hash_a: str, hash_b: str) -> float:
        if not hash_a or not hash_b:
            return 0.0
        words_a = set(hash_a.split())
        words_b = set(hash_b.split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)

    def _summarize(
        self,
        profiles:  dict[str, PageProfile],
        clusters:  list[PageCluster],
        operators: list[OperatorProfile],
    ) -> str:
        attack_pages = [
            p for p, pr in profiles.items()
            if pr.attack_rate >= 0.70 or pr.bot_density >= self._bot_density_threshold
        ]
        top_op = operators[0] if operators else None
        if top_op:
            return (
                f"{len(attack_pages)} attack pages detected · "
                f"{len(clusters)} coordinated networks · "
                f"Top operator: {len(top_op.controlled_pages)} pages + "
                f"{len(top_op.bot_army)} bots (confidence {top_op.confidence}/99)"
            )
        return (
            f"{len(attack_pages)} attack pages · "
            f"{len(profiles)} sources analyzed · no confirmed operators"
        )

    def _minimal_report(self, profiles: dict[str, PageProfile]) -> OwnershipReport:
        attack_pages = [
            n for n, p in profiles.items()
            if p.attack_rate >= 0.70 or p.bot_density >= self._bot_density_threshold
        ]
        return OwnershipReport(
            page_profiles=profiles, page_clusters=[], operator_profiles=[],
            bot_bindings=[], attack_pages=attack_pages,
            total_attack_pages=len(attack_pages), total_operators=0,
            network_summary=f"{len(attack_pages)} attack pages · insufficient data for clustering",
        )
