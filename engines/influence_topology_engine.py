"""
InfluenceTopologyEngine — P7: Influence Topology Score.

Computes ranked influence topology from an existing CIBGraphResult:
PageRank + betweenness centrality + degree → composite influence score per actor.
Gini concentration index reveals whether a few actors control the narrative network.
All parameters read from cfg["influence_topology"]. Zero hardcoded values.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cib_graph import CIBGraphResult


@dataclass
class TopologyActor:
    actor:           str
    rank:            int
    influence_score: float      # composite 0-100
    pagerank:        float
    betweenness:     float
    degree:          int
    role:            str        # COMMAND / AMPLIFIER / HUB / BOT_CLUSTER / PERIPHERAL
    community_id:    int
    is_suspect:      bool
    suspect_score:   int


@dataclass
class CommunityTopology:
    community_id:   int
    size:           int
    top_actor:      str
    avg_influence:  float
    suspect_ratio:  float


@dataclass
class InfluenceTopologyReport:
    actors:             list[TopologyActor]
    command_chain:      list[str]
    amplifiers:         list[str]
    hubs:               list[str]
    top_communities:    list[CommunityTopology]
    pagerank_gini:      float
    suspect_top_ratio:  float
    influence_score:    float
    coordination_score: int
    total_actors:       int
    summary:            str


class InfluenceTopologyEngine:

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("influence_topology", {})
        self.top_n         = c.get("top_actors_output",        25)
        self.top_comm_n    = c.get("top_communities_output",   10)
        self._pr_w         = c.get("pagerank_weight",          50.0)
        self._bt_w         = c.get("betweenness_weight",       30.0)
        self._dg_w         = c.get("degree_weight",            20.0)
        self._susp_bonus   = c.get("suspect_score_bonus",      20.0)
        sw = c.get("score_weights", {})
        self._sw_gini      = sw.get("gini_pct",                40.0)
        self._sw_suspect   = sw.get("suspect_top_pct",         35.0)
        self._sw_coord     = sw.get("coord_score_pct",         25.0)

    def analyze(self, cib: "CIBGraphResult") -> InfluenceTopologyReport:
        if not cib or not cib.nodes:
            return self._empty()

        nodes = cib.nodes
        max_pr = max((n.pagerank    for n in nodes.values()), default=1e-9) or 1e-9
        max_bt = max((n.betweenness for n in nodes.values()), default=1e-9) or 1e-9
        max_dg = max((n.degree      for n in nodes.values()), default=1)    or 1

        actors: list[TopologyActor] = []
        for actor, node in nodes.items():
            pr_n   = node.pagerank    / max_pr
            bt_n   = node.betweenness / max_bt
            dg_n   = node.degree      / max_dg
            base   = self._pr_w * pr_n + self._bt_w * bt_n + self._dg_w * dg_n
            bonus  = (node.suspect_score / 100.0) * self._susp_bonus if node.is_suspect else 0.0
            actors.append(TopologyActor(
                actor=actor, rank=0,
                influence_score=round(min(100.0, base + bonus), 2),
                pagerank=node.pagerank,
                betweenness=node.betweenness,
                degree=node.degree,
                role=node.role,
                community_id=node.community_id,
                is_suspect=node.is_suspect,
                suspect_score=node.suspect_score,
            ))

        actors.sort(key=lambda a: -a.influence_score)
        for i, a in enumerate(actors, 1):
            a.rank = i

        top = actors[:self.top_n]
        command_chain = [a.actor for a in actors if a.role == "COMMAND"]
        amplifiers    = [a.actor for a in actors if a.role == "AMPLIFIER"]
        hubs          = [a.actor for a in actors if a.role == "HUB"]

        gini = self._gini(sorted(n.pagerank for n in nodes.values()))
        suspect_top_ratio = sum(1 for a in top if a.is_suspect) / max(len(top), 1)
        communities   = self._build_communities(actors)
        score         = self._overall_score(gini, suspect_top_ratio, cib.coordination_score)
        summary       = self._build_summary(actors, command_chain, gini, score)

        return InfluenceTopologyReport(
            actors=top,
            command_chain=command_chain[:8],
            amplifiers=amplifiers[:8],
            hubs=hubs[:8],
            top_communities=communities[:self.top_comm_n],
            pagerank_gini=round(gini, 4),
            suspect_top_ratio=round(suspect_top_ratio, 4),
            influence_score=round(score, 1),
            coordination_score=cib.coordination_score,
            total_actors=len(actors),
            summary=summary,
        )

    @staticmethod
    def _gini(values: list[float]) -> float:
        n = len(values)
        if n == 0:
            return 0.0
        total = sum(values) or 1e-9
        idx_sum = sum((i + 1) * v for i, v in enumerate(values))
        return round((2 * idx_sum) / (n * total) - (n + 1) / n, 4)

    def _build_communities(self, actors: list[TopologyActor]) -> list[CommunityTopology]:
        comm: dict[int, list[TopologyActor]] = defaultdict(list)
        for a in actors:
            if a.community_id >= 0:
                comm[a.community_id].append(a)
        result = []
        for cid, members in comm.items():
            if len(members) < 2:
                continue
            top_a   = max(members, key=lambda a: a.influence_score)
            avg_inf = sum(a.influence_score for a in members) / len(members)
            susp_r  = sum(1 for a in members if a.is_suspect) / len(members)
            result.append(CommunityTopology(
                community_id=cid, size=len(members),
                top_actor=top_a.actor,
                avg_influence=round(avg_inf, 2),
                suspect_ratio=round(susp_r, 3),
            ))
        result.sort(key=lambda c: -(c.avg_influence * c.size))
        return result

    def _overall_score(self, gini: float, suspect_ratio: float, coord_score: int) -> float:
        s = (gini               * self._sw_gini   +
             suspect_ratio      * self._sw_suspect +
             (coord_score/99.0) * self._sw_coord)
        return min(100.0, s)

    def _build_summary(
        self, actors: list[TopologyActor],
        command_chain: list[str], gini: float, score: float,
    ) -> str:
        if not actors:
            return "No actors found in CIB graph for topology analysis."
        parts = [f"{len(actors)} actors analyzed — influence topology score {score:.1f}/100."]
        if command_chain:
            top3 = ", ".join(command_chain[:3])
            parts.append(
                f"{len(command_chain)} COMMAND node(s) dominate network topology "
                f"(high PageRank + betweenness): {top3}."
            )
        gini_lbl = ("highly concentrated" if gini >= 0.6 else
                    "moderately concentrated" if gini >= 0.35 else "distributed")
        parts.append(
            f"PageRank distribution is {gini_lbl} (Gini={gini:.3f}) — "
            f"{'few actors dominate narrative influence' if gini >= 0.5 else 'influence is spread across the network'}."
        )
        return " ".join(parts)

    @staticmethod
    def _empty() -> InfluenceTopologyReport:
        return InfluenceTopologyReport(
            actors=[], command_chain=[], amplifiers=[], hubs=[],
            top_communities=[], pagerank_gini=0.0,
            suspect_top_ratio=0.0, influence_score=0.0,
            coordination_score=0, total_actors=0,
            summary="No CIB graph data available for topology analysis.",
        )
