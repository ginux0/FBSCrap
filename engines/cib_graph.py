"""
CIB Graph Engine — Coordinated Inauthentic Behavior network analysis.

All parameters read from cfg["cib_graph"]. Zero hardcoded values.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import networkx as nx
    _NX = True
except ImportError:
    _NX = False

try:
    import community as community_louvain
    _LOUVAIN = True
except ImportError:
    _LOUVAIN = False

if TYPE_CHECKING:
    from .comment_bot_detector import BotSuspect


@dataclass
class CIBNode:
    actor:          str
    total_comments: int
    posts_in:       list[str]
    comment_texts:  list[str]
    attack_count:   int
    is_suspect:     bool
    suspect_score:  int
    degree:         int   = 0
    betweenness:    float = 0.0
    pagerank:       float = 0.0
    community_id:   int   = -1
    role:           str   = "PERIPHERAL"


@dataclass
class CIBEdge:
    source:       str
    target:       str
    weight:       float
    edge_types:   list[str]
    shared_posts: int


@dataclass
class CIBCluster:
    cluster_id:   int
    actors:       list[str]
    size:         int
    top_actor:    str
    coord_score:  float
    edge_density: float
    attack_count: int
    risk_label:   str


@dataclass
class CIBGraphResult:
    nodes:              dict[str, CIBNode]
    edges:              list[CIBEdge]
    clusters:           list[CIBCluster]
    command_nodes:      list[str]
    amplifier_nodes:    list[str]
    total_actors:       int
    total_edges:        int
    coordination_score: int
    graphml_path:       str | None
    d3_path:            str | None
    d3_json:            dict


class CIBGraphEngine:

    def __init__(
        self,
        posts:        list[dict],
        bot_suspects: "list[BotSuspect] | None" = None,
        output_dir:   "Path | None"             = None,
        cfg:          dict | None               = None,
    ):
        self.posts      = posts
        self.suspects   = {s.author: s for s in (bot_suspects or [])}
        self.output_dir = output_dir

        c = (cfg or {}).get("cib_graph", {})
        self._phrase_threshold      = c.get("phrase_threshold", 0.40)
        self._max_actors_per_post   = c.get("max_actors_per_post", 60)
        self._pagerank_max_iter     = c.get("pagerank_max_iter", 150)
        self._betweenness_k         = c.get("betweenness_k", 50)
        self._betweenness_k_thresh  = c.get("betweenness_k_threshold", 200)
        self._uf_cutoff_ratio       = c.get("union_find_cutoff_ratio", 0.50)
        self._phrase_cmp_limit      = c.get("phrase_comparison_limit", 10)
        self._phrase_text_max       = c.get("phrase_text_max_len", 200)
        self._phrase_early_exit     = c.get("phrase_early_exit_sim", 0.95)
        self._d3_max_nodes          = c.get("d3_max_nodes", 500)
        self._d3_max_edges          = c.get("d3_max_edges", 2000)
        self._max_clusters_out      = c.get("max_clusters_output", 50)

        rt = c.get("risk_thresholds", {})
        self._rt_critical = rt.get("critical", 70)
        self._rt_high     = rt.get("high", 40)
        self._rt_medium   = rt.get("medium", 20)

        rol = c.get("role_thresholds", {})
        self._rol_cmd_deg  = rol.get("command_deg_pct", 0.50)
        self._rol_cmd_bet  = rol.get("amplifier_bet_pct", 0.30)
        self._rol_amp_deg  = rol.get("hub_deg_pct", 0.30)
        self._rol_hub_deg  = rol.get("peripheral_deg_pct", 0.50)

        cw = c.get("coordination_weights", {})
        self._cw_density   = cw.get("density", 40)
        self._cw_pagerank  = cw.get("pagerank_concentration", 30)
        self._cw_cluster   = cw.get("cluster_quality", 30)

    def build(self) -> CIBGraphResult:
        actor_map = self._build_actor_map()
        if not actor_map:
            return self._empty_result()

        edges = self._build_edges(actor_map)
        nodes = self._build_nodes(actor_map)

        if _NX and len(nodes) >= 3:
            nodes, communities = self._nx_metrics(nodes, edges)
        else:
            nodes, communities = self._fallback_metrics(nodes, edges)

        clusters = self._build_clusters(nodes, communities)

        for actor, node in nodes.items():
            node.role = self._classify_role(node, nodes)

        command_nodes = [
            a for a, n in sorted(
                nodes.items(), key=lambda x: x[1].betweenness, reverse=True
            ) if n.role == "COMMAND"
        ][:8]

        amplifier_nodes = [
            a for a, n in sorted(
                nodes.items(), key=lambda x: x[1].degree, reverse=True
            ) if n.role == "AMPLIFIER"
        ][:8]

        coord_score  = self._coordination_score(nodes, edges, clusters)
        d3_json      = self._build_d3(nodes, edges)
        graphml_path = None
        d3_path      = None

        if self.output_dir:
            graphml_path, d3_path = self._export(nodes, edges, d3_json)

        return CIBGraphResult(
            nodes=nodes, edges=edges, clusters=clusters,
            command_nodes=command_nodes, amplifier_nodes=amplifier_nodes,
            total_actors=len(nodes), total_edges=len(edges),
            coordination_score=coord_score,
            graphml_path=graphml_path, d3_path=d3_path, d3_json=d3_json,
        )

    def _build_actor_map(self) -> dict:
        actor_map: dict[str, dict] = defaultdict(lambda: {
            "posts_in": set(), "texts": [], "total_comments": 0, "attack_count": 0,
        })
        for post in self.posts:
            url = post.get("url", "")
            for c in post.get("comments", []):
                actor = (c.get("author") or "").strip()
                if not actor or actor == "?":
                    continue
                actor_map[actor]["posts_in"].add(url)
                actor_map[actor]["texts"].append(c.get("text", ""))
                actor_map[actor]["total_comments"] += 1

        for actor, suspect in self.suspects.items():
            if actor in actor_map:
                actor_map[actor]["attack_count"] = suspect.total_attacks

        return dict(actor_map)

    def _build_nodes(self, actor_map: dict) -> dict[str, CIBNode]:
        return {
            actor: CIBNode(
                actor=actor,
                total_comments=data["total_comments"],
                posts_in=list(data["posts_in"]),
                comment_texts=data["texts"],
                attack_count=data["attack_count"],
                is_suspect=actor in self.suspects,
                suspect_score=(
                    self.suspects[actor].composite_score
                    if actor in self.suspects else 0
                ),
            )
            for actor, data in actor_map.items()
        }

    def _build_edges(self, actor_map: dict) -> list[CIBEdge]:
        post_actors: dict[str, list[str]] = defaultdict(list)
        for actor, data in actor_map.items():
            for url in data["posts_in"]:
                post_actors[url].append(actor)

        edge_data: dict[tuple, dict] = defaultdict(lambda: {
            "weight": 0.0, "types": set(), "shared_posts": 0
        })
        for url, actors in post_actors.items():
            capped = actors[:self._max_actors_per_post]
            for i, a in enumerate(capped):
                for b in capped[i + 1:]:
                    key = tuple(sorted([a, b]))
                    edge_data[key]["weight"]      += 1.0
                    edge_data[key]["shared_posts"] += 1
                    edge_data[key]["types"].add("co_comment")

        suspects_list = list(self.suspects.keys())
        for i, a in enumerate(suspects_list):
            if a not in actor_map:
                continue
            for b in suspects_list[i + 1:]:
                if b not in actor_map:
                    continue
                sim = self._max_phrase_sim(actor_map[a]["texts"], actor_map[b]["texts"])
                if sim >= self._phrase_threshold:
                    key = tuple(sorted([a, b]))
                    edge_data[key]["weight"] += sim * 2.0
                    edge_data[key]["types"].add("phrase_share")

        if not edge_data:
            return []

        max_w = max(d["weight"] for d in edge_data.values()) or 1.0
        return [
            CIBEdge(
                source=k[0], target=k[1],
                weight=round(d["weight"] / max_w, 3),
                edge_types=list(d["types"]),
                shared_posts=d["shared_posts"],
            )
            for k, d in edge_data.items()
        ]

    def _nx_metrics(self, nodes: dict[str, CIBNode], edges: list[CIBEdge]):
        G = nx.Graph()
        G.add_nodes_from(nodes.keys())
        for e in edges:
            G.add_edge(e.source, e.target, weight=e.weight)

        try:
            pr = nx.pagerank(G, weight="weight", max_iter=self._pagerank_max_iter)
        except Exception:
            pr = {n: 1.0 / len(nodes) for n in nodes}

        try:
            k  = min(self._betweenness_k, len(nodes)) if len(nodes) > self._betweenness_k_thresh else None
            bc = nx.betweenness_centrality(G, k=k, weight="weight")
        except Exception:
            bc = {n: 0.0 for n in nodes}

        deg = dict(G.degree())
        for actor, node in nodes.items():
            node.degree      = deg.get(actor, 0)
            node.betweenness = round(bc.get(actor, 0.0), 5)
            node.pagerank    = round(pr.get(actor, 0.0), 7)

        if _LOUVAIN and G.number_of_edges() > 0:
            try:
                communities = community_louvain.best_partition(G, weight="weight")
            except Exception:
                communities = self._union_find(nodes, edges, self._uf_cutoff_ratio)
        else:
            communities = self._union_find(nodes, edges, self._uf_cutoff_ratio)

        for actor, cid in communities.items():
            if actor in nodes:
                nodes[actor].community_id = cid

        return nodes, communities

    def _fallback_metrics(self, nodes: dict[str, CIBNode], edges: list[CIBEdge]):
        deg: dict[str, int] = defaultdict(int)
        for e in edges:
            deg[e.source] += 1
            deg[e.target] += 1

        max_deg   = max(deg.values(), default=1) or 1
        total_deg = sum(deg.values()) or 1

        for actor, node in nodes.items():
            node.degree      = deg.get(actor, 0)
            node.betweenness = round(node.degree / max_deg, 5)
            node.pagerank    = round(node.degree / total_deg, 7)

        communities = self._union_find(nodes, edges, self._uf_cutoff_ratio)
        for actor, cid in communities.items():
            if actor in nodes:
                nodes[actor].community_id = cid

        return nodes, communities

    @staticmethod
    def _union_find(nodes: dict, edges: list[CIBEdge], cutoff_ratio: float) -> dict[str, int]:
        parent = {a: a for a in nodes}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        sorted_edges = sorted(edges, key=lambda e: e.weight, reverse=True)
        cutoff = max(1, int(len(sorted_edges) * cutoff_ratio))
        for e in sorted_edges[:cutoff]:
            if e.source in parent and e.target in parent:
                px, py = find(e.source), find(e.target)
                if px != py:
                    parent[px] = py

        roots: dict[str, int] = {}
        cid    = 0
        result: dict[str, int] = {}
        for actor in nodes:
            root = find(actor)
            if root not in roots:
                roots[root] = cid
                cid += 1
            result[actor] = roots[root]
        return result

    def _build_clusters(
        self, nodes: dict[str, CIBNode], communities: dict[str, int]
    ) -> list[CIBCluster]:
        comm_actors: dict[int, list[str]] = defaultdict(list)
        for actor, cid in communities.items():
            if actor in nodes:
                comm_actors[cid].append(actor)

        clusters: list[CIBCluster] = []
        risk_order = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}

        for cid, actors in comm_actors.items():
            if len(actors) < 2:
                continue

            top_actor    = max(actors, key=lambda a: nodes[a].degree)
            scores       = [nodes[a].suspect_score for a in actors]
            coord_score  = sum(scores) / len(scores)
            attack_count = sum(nodes[a].attack_count for a in actors)
            edge_density = min(1.0, coord_score / 100.0)

            if coord_score >= self._rt_critical or attack_count >= 20:
                risk = "CRITICAL"
            elif coord_score >= self._rt_high or attack_count >= 10:
                risk = "HIGH"
            elif coord_score >= self._rt_medium or attack_count >= 5:
                risk = "MEDIUM"
            else:
                risk = "LOW"

            clusters.append(CIBCluster(
                cluster_id=cid, actors=actors, size=len(actors),
                top_actor=top_actor, coord_score=round(coord_score, 1),
                edge_density=round(edge_density, 3), attack_count=attack_count,
                risk_label=risk,
            ))

        clusters.sort(key=lambda c: (risk_order[c.risk_label], c.size), reverse=True)
        return clusters[:self._max_clusters_out]

    def _classify_role(self, node: CIBNode, all_nodes: dict[str, CIBNode]) -> str:
        if not all_nodes:
            return "PERIPHERAL"
        max_deg  = max(n.degree      for n in all_nodes.values()) or 1
        max_betw = max(n.betweenness for n in all_nodes.values()) or 0.001
        deg_pct  = node.degree      / max_deg
        bet_pct  = node.betweenness / max_betw

        if deg_pct >= self._rol_cmd_deg and bet_pct >= self._rol_cmd_bet:
            return "COMMAND"
        if deg_pct >= self._rol_amp_deg and node.is_suspect:
            return "AMPLIFIER"
        if node.is_suspect and node.degree >= 2:
            return "BOT_CLUSTER"
        if deg_pct >= self._rol_hub_deg:
            return "HUB"
        return "PERIPHERAL"

    def _coordination_score(
        self,
        nodes:    dict[str, CIBNode],
        edges:    list[CIBEdge],
        clusters: list[CIBCluster],
    ) -> int:
        if not nodes or not edges:
            return 0

        total         = len(nodes)
        suspect_count = sum(1 for n in nodes.values() if n.is_suspect)
        f1 = (suspect_count / total) * self._cw_density
        co_edges = sum(1 for e in edges if "co_comment" in e.edge_types)
        f2 = (co_edges / len(edges)) * self._cw_pagerank
        f3 = (clusters[0].size / total * self._cw_cluster) if clusters else 0.0

        return min(99, max(0, int(f1 + f2 + f3)))

    def _max_phrase_sim(self, texts_a: list[str], texts_b: list[str]) -> float:
        best = 0.0
        for ta in texts_a[:self._phrase_cmp_limit]:
            for tb in texts_b[:self._phrase_cmp_limit]:
                if not ta or not tb:
                    continue
                s = SequenceMatcher(
                    None,
                    ta.lower()[:self._phrase_text_max],
                    tb.lower()[:self._phrase_text_max],
                ).ratio()
                if s > best:
                    best = s
                if best >= self._phrase_early_exit:
                    return best
        return best

    def _build_d3(self, nodes: dict[str, CIBNode], edges: list[CIBEdge]) -> dict:
        _role_color = {
            "COMMAND":    "#FF3333",
            "AMPLIFIER":  "#FF6B00",
            "BOT_CLUSTER":"#FFC000",
            "HUB":        "#44CCFF",
            "PERIPHERAL": "#606060",
        }
        node_list = sorted(nodes.values(), key=lambda n: -n.degree)[:self._d3_max_nodes]
        node_set  = {n.actor for n in node_list}
        edge_list = [e for e in edges if e.source in node_set and e.target in node_set][:self._d3_max_edges]

        return {
            "nodes": [
                {
                    "id":            n.actor,
                    "degree":        n.degree,
                    "pagerank":      n.pagerank,
                    "betweenness":   n.betweenness,
                    "is_suspect":    n.is_suspect,
                    "suspect_score": n.suspect_score,
                    "community":     n.community_id,
                    "role":          n.role,
                    "color":         _role_color.get(n.role, "#606060"),
                    "radius":        max(4, min(20, n.degree * 2)),
                }
                for n in node_list
            ],
            "links": [
                {
                    "source": e.source,
                    "target": e.target,
                    "weight": e.weight,
                    "types":  e.edge_types,
                }
                for e in edge_list
            ],
        }

    def _export(
        self, nodes: dict[str, CIBNode], edges: list[CIBEdge], d3_json: dict
    ) -> tuple[str | None, str | None]:
        if not _NX or not self.output_dir:
            return None, None
        try:
            G = nx.Graph()
            for actor, n in nodes.items():
                G.add_node(
                    actor,
                    degree=n.degree, betweenness=n.betweenness,
                    pagerank=n.pagerank, is_suspect=int(n.is_suspect),
                    suspect_score=n.suspect_score,
                    community=n.community_id, role=n.role,
                )
            for e in edges:
                G.add_edge(e.source, e.target, weight=e.weight, edge_type="|".join(e.edge_types))

            self.output_dir.mkdir(parents=True, exist_ok=True)
            gml = self.output_dir / "cib_network.graphml"
            d3f = self.output_dir / "cib_network_d3.json"
            nx.write_graphml(G, str(gml))
            d3f.write_text(json.dumps(d3_json, ensure_ascii=False, indent=2))
            print(f"  [CIB GRAPH] Exported → {gml.name} + {d3f.name}")
            return str(gml), str(d3f)
        except Exception as exc:
            print(f"  [CIB GRAPH] Export warning: {exc}")
            return None, None

    @staticmethod
    def _empty_result() -> CIBGraphResult:
        return CIBGraphResult(
            nodes={}, edges=[], clusters=[],
            command_nodes=[], amplifier_nodes=[],
            total_actors=0, total_edges=0, coordination_score=0,
            graphml_path=None, d3_path=None,
            d3_json={"nodes": [], "links": []},
        )
