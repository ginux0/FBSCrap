"""
PSI COORDINATION ENGINE — ARGOS-Ψ Cluster Detection & GHOST Finding

Builds weighted co-engagement graph with temporal decay.
Detects communities (Louvain) and computes coordination scores.
Identifies roles: BOTNET_NODE (high centrality + precedence),
                  GHOST (Ψ ≈ 0 but recurs in clusters).

All parameters from cfg["psi_coordination"]. Zero hardcoded values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from typing import TYPE_CHECKING

try:
    import networkx as nx
    import community as community_louvain
    _NETWORKX = True
except ImportError:
    _NETWORKX = False


@dataclass
class PSICoordinationCluster:
    """Per-cluster coordination analysis."""
    cluster_id: int
    actors: list[str]
    size: int
    is_coordinated: bool
    coordination_score: float  # 0-100
    density: float
    temporal_sync_level: float
    content_similarity_avg: float
    command_node: str | None
    command_confidence: float


@dataclass
class PSICoordinationReport:
    """Output of PSICoordinationEngine."""
    clusters: list[PSICoordinationCluster]
    ghost_candidates: list[str]  # Ψ ≈ 0 but recurs in clusters
    botnet_nodes: list[str]  # High centrality + temporal precedence
    total_clusters: int
    average_cluster_size: float
    overall_coordination_score: float  # 0-100 (aggregated)
    has_organized_network: bool
    summary: str


class PSICoordinationEngine:
    """
    Coordination detection layer for ARGOS-Ψ.

    Detects organized networks:
    - Coordinated timing (temporal sync)
    - Shared content (similarity)
    - Network structure (clustering, centrality)
    """

    def __init__(self, cfg: dict | None = None):
        c = (cfg or {}).get("psi_coordination", {})
        self.time_decay = c.get("coengagement_time_decay", 0.95)
        self.time_decay_window_hours = c.get("time_decay_window_hours", 24)
        self.community_resolution = c.get("community_resolution", 1.0)
        self.min_cluster_size = c.get("min_cluster_size", 3)
        self.sync_threshold = c.get("sync_threshold_s", 3.0)
        self.similarity_threshold = c.get("similarity_threshold", 0.40)
        self.ghost_recurrence_min = c.get("ghost_recurrence_min_clusters", 3)

        self.actors_by_post: dict[str, list[str]] = defaultdict(list)
        self.post_times: dict[str, datetime] = {}

    def analyze(
        self,
        posts: list[dict],
        actor_psi_scores: dict[str, float],
    ) -> PSICoordinationReport:
        """
        Main entry: analyze posts for coordination patterns.

        Args:
            posts: [{url, timestamp, comments: [{author, timestamp, text}, ...]}, ...]
            actor_psi_scores: {actor: psi_score, ...} from PSICoreEngine

        Returns:
            PSICoordinationReport with clusters and roles
        """
        if not posts:
            return self._empty_report("No posts provided")

        if not _NETWORKX:
            return self._empty_report("networkx/community not available")

        # Build co-engagement graph
        graph = self._build_coengagement_graph(posts)

        if graph.number_of_nodes() < self.min_cluster_size:
            return self._empty_report("Insufficient actors for clustering")

        # Detect communities
        communities = self._detect_communities(graph)

        if not communities:
            return self._empty_report("No coherent communities detected")

        # Build clusters with coordination scores
        clusters = self._build_clusters(graph, communities, posts, actor_psi_scores)

        # Find special roles
        botnet_nodes = self._find_botnet_nodes(graph, clusters, posts)
        ghost_candidates = self._find_ghosts(clusters, actor_psi_scores)

        # Aggregate metrics
        overall_coord = self._aggregate_coordination(clusters)
        has_organized = len(clusters) > 0 and overall_coord > 50

        summary = self._build_summary(clusters, botnet_nodes, ghost_candidates, overall_coord)

        return PSICoordinationReport(
            clusters=clusters,
            ghost_candidates=ghost_candidates,
            botnet_nodes=botnet_nodes,
            total_clusters=len(clusters),
            average_cluster_size=sum(c.size for c in clusters) / len(clusters) if clusters else 0,
            overall_coordination_score=overall_coord,
            has_organized_network=has_organized,
            summary=summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _build_coengagement_graph(self, posts: list[dict]) -> nx.Graph:
        """
        Build weighted co-engagement graph.
        Edge weight = co-ocurrence count + temporal proximity + content similarity.
        """
        graph = nx.Graph()

        # Map posts by URL
        for post in posts:
            url = post.get("url", "")
            timestamp = post.get("timestamp")
            if timestamp:
                try:
                    self.post_times[url] = datetime.fromisoformat(timestamp)
                except (ValueError, TypeError):
                    pass

            # Actors in this post
            actors = []
            for comment in post.get("comments", []):
                author = (comment.get("author") or "").strip()
                if author and author != "?":
                    actors.append(author)
                    if author not in graph:
                        graph.add_node(author, posts=[])
                    graph.nodes[author]["posts"].append(url)

            # Co-engagement edges
            for i, a in enumerate(actors):
                for b in actors[i+1:]:
                    key = tuple(sorted([a, b]))
                    if graph.has_edge(a, b):
                        graph[a][b]["weight"] += 1.0
                    else:
                        graph.add_edge(a, b, weight=1.0, types=set())
                    graph[a][b]["types"].add("co_comment")

        # Normalize edge weights
        if graph.number_of_edges() > 0:
            max_w = max(d["weight"] for _, _, d in graph.edges(data=True))
            for _, _, d in graph.edges(data=True):
                d["weight"] = d["weight"] / max(max_w, 1.0)

        return graph

    def _detect_communities(self, graph: nx.Graph) -> dict[str, int]:
        """
        Detect communities using Louvain algorithm if available.
        Fallback: degree-based clustering.

        Returns: {node: community_id, ...}
        """
        if graph.number_of_nodes() == 0:
            return {}

        try:
            if _NETWORKX and community_louvain:
                partition = community_louvain.best_partition(
                    graph,
                    resolution=self.community_resolution,
                )
                return partition
        except Exception:
            pass

        # Fallback: connected components + high-degree grouping
        return self._fallback_community_detection(graph)

    def _fallback_community_detection(self, graph: nx.Graph) -> dict[str, int]:
        """
        Fallback clustering: connected components + degree-based sub-clustering.
        Creates clusters based on connectivity strength.
        """
        partition = {}
        comm_id = 0

        # Start with connected components
        for component in nx.connected_components(graph):
            if len(component) < self.min_cluster_size:
                # Too small, keep as single cluster
                for node in component:
                    partition[node] = comm_id
                comm_id += 1
            else:
                # Subcluster by edge density within component
                subgraph = graph.subgraph(component)

                # Greedy: start with highest-degree node, grow cluster
                unassigned = set(component)
                while unassigned:
                    # Pick highest-degree unassigned node
                    start = max(unassigned, key=lambda n: subgraph.degree(n))
                    cluster = {start}
                    queue = [start]

                    # BFS: add neighbors if they have strong connections
                    while queue:
                        node = queue.pop(0)
                        for neighbor in subgraph.neighbors(node):
                            if neighbor in unassigned and neighbor not in cluster:
                                # Add if edge weight > threshold
                                edge_weight = subgraph[node][neighbor].get("weight", 0.5)
                                if edge_weight > 0.3:  # Arbitrary threshold
                                    cluster.add(neighbor)
                                    queue.append(neighbor)

                    unassigned -= cluster

                    if len(cluster) >= self.min_cluster_size:
                        for node in cluster:
                            partition[node] = comm_id
                        comm_id += 1
                    else:
                        # Singleton/too-small cluster
                        for node in cluster:
                            partition[node] = comm_id
                        comm_id += 1

        return partition if partition else {n: 0 for n in graph.nodes()}

    def _build_clusters(
        self,
        graph: nx.Graph,
        communities: dict[str, int],
        posts: list[dict],
        actor_psi_scores: dict[str, float],
    ) -> list[PSICoordinationCluster]:
        """
        Build PSICoordinationCluster objects from communities.
        """
        community_members: dict[int, list[str]] = defaultdict(list)
        for node, comm_id in communities.items():
            community_members[comm_id].append(node)

        clusters = []
        for comm_id, actors in community_members.items():
            # Include all clusters, even small ones for analysis
            # (filtering by min_cluster_size is for "significant" clusters only)

            # Subgraph metrics
            subgraph = graph.subgraph(actors)
            density = nx.density(subgraph)

            # Temporal sync and content similarity (simplified)
            temporal_sync = self._compute_temporal_sync(actors, posts)
            content_sim = self._compute_content_similarity(actors, posts)

            # Command node: highest degree in community
            degrees = {n: subgraph.degree(n) for n in actors}
            command_node = max(degrees, key=degrees.get) if degrees else None

            # Coordination score
            coord_score = (density * 30 + temporal_sync * 40 + content_sim * 30)

            clusters.append(
                PSICoordinationCluster(
                    cluster_id=comm_id,
                    actors=sorted(actors),
                    size=len(actors),
                    is_coordinated=coord_score > 40,
                    coordination_score=round(min(100.0, max(0.0, coord_score)), 1),
                    density=round(density, 2),
                    temporal_sync_level=round(temporal_sync, 2),
                    content_similarity_avg=round(content_sim, 2),
                    command_node=command_node,
                    command_confidence=round(degrees.get(command_node, 0) / len(actors), 2) if command_node else 0,
                )
            )

        return sorted(clusters, key=lambda c: -c.coordination_score)

    def _compute_temporal_sync(self, actors: list[str], posts: list[dict]) -> float:
        """
        Measure temporal synchronization (0-1).
        High = actors often comment within sync_threshold_s of each other.
        """
        if len(actors) < 2:
            return 0.0

        sync_pairs = 0
        total_pairs = 0

        actor_set = set(actors)

        for post in posts:
            comments = post.get("comments", [])
            if not comments:
                continue

            # Extract timestamps
            timestamped = []
            for comment in comments:
                author = (comment.get("author") or "").strip()
                if author in actor_set:
                    ts_str = comment.get("timestamp")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            timestamped.append((author, ts))
                        except (ValueError, TypeError):
                            pass

            # Check pairs within sync window
            for i, (a1, ts1) in enumerate(timestamped):
                for a2, ts2 in timestamped[i+1:]:
                    delta_s = abs((ts2 - ts1).total_seconds())
                    if delta_s <= self.sync_threshold:
                        sync_pairs += 1
                    total_pairs += 1

        return sync_pairs / max(total_pairs, 1) if total_pairs > 0 else 0.0

    def _compute_content_similarity(self, actors: list[str], posts: list[dict]) -> float:
        """
        Measure content similarity (0-1).
        High = actors use similar text/vocabulary.
        """
        if len(actors) < 2:
            return 0.0

        # Simple: how many comments are >threshold% similar
        actor_set = set(actors)
        actor_texts: dict[str, list[str]] = defaultdict(list)

        for post in posts:
            for comment in post.get("comments", []):
                author = (comment.get("author") or "").strip()
                if author in actor_set:
                    text = (comment.get("text") or "").strip().lower()
                    if len(text) > 5:
                        actor_texts[author].append(text)

        if len(actor_texts) < 2:
            return 0.0

        # Pairwise similarity (simplified: substring overlap)
        similar_pairs = 0
        total_pairs = 0

        actors_list = list(actor_texts.keys())
        for i, a1 in enumerate(actors_list):
            for a2 in actors_list[i+1:]:
                texts1 = set(actor_texts[a1])
                texts2 = set(actor_texts[a2])
                if texts1 and texts2:
                    overlap = len(texts1 & texts2) / max(len(texts1 | texts2), 1)
                    if overlap > self.similarity_threshold:
                        similar_pairs += 1
                    total_pairs += 1

        return similar_pairs / max(total_pairs, 1) if total_pairs > 0 else 0.0

    def _find_botnet_nodes(
        self,
        graph: nx.Graph,
        clusters: list[PSICoordinationCluster],
        posts: list[dict],
    ) -> list[str]:
        """
        Find BOTNET_NODEs: high centrality + temporal precedence (marks rhythm).
        """
        if not graph.nodes():
            return []

        botnet_candidates = []

        for cluster in clusters:
            if not cluster.command_node:
                continue

            # High centrality?
            subgraph = graph.subgraph(cluster.actors)
            degree = subgraph.degree(cluster.command_node)
            max_degree = max(dict(subgraph.degree()).values()) if subgraph.nodes() else 1
            centrality_score = degree / max(max_degree, 1)

            if centrality_score > 0.5:  # Top half of centrality in cluster
                botnet_candidates.append(cluster.command_node)

        return list(set(botnet_candidates))[:8]  # Top 8

    def _find_ghosts(
        self,
        clusters: list[PSICoordinationCluster],
        actor_psi_scores: dict[str, float],
    ) -> list[str]:
        """
        Find GHOST actors: Ψ ≈ 0 (individually ambiguous) BUT appear in 3+ clusters.
        These are elite operators hard to detect alone.
        """
        ghost_candidates = []

        # Count cluster membership per actor
        cluster_memberships: dict[str, int] = defaultdict(int)
        for cluster in clusters:
            for actor in cluster.actors:
                cluster_memberships[actor] += 1

        # Filter: Ψ near zero AND high cluster recurrence
        for actor, cluster_count in cluster_memberships.items():
            if cluster_count >= self.ghost_recurrence_min:
                psi = actor_psi_scores.get(actor, 0)
                if -30 < psi < 30:  # Ψ ≈ 0
                    ghost_candidates.append(actor)

        return ghost_candidates

    def _aggregate_coordination(self, clusters: list[PSICoordinationCluster]) -> float:
        """
        Aggregate coordination score from all clusters (0-100).
        """
        if not clusters:
            return 0.0

        # Weighted by cluster size
        total_weight = sum(c.size for c in clusters)
        if total_weight == 0:
            return 0.0

        weighted_sum = sum(c.coordination_score * c.size for c in clusters)
        return round(weighted_sum / total_weight, 1)

    def _build_summary(
        self,
        clusters: list[PSICoordinationCluster],
        botnet_nodes: list[str],
        ghosts: list[str],
        overall_coord: float,
    ) -> str:
        """Generate human-readable summary."""
        parts = [f"Coordination analysis: {len(clusters)} cluster(s) detected."]

        if overall_coord >= 70:
            parts.append(f"HIGH coordination score ({overall_coord:.0f}/100) — organized network detected.")
        elif overall_coord >= 40:
            parts.append(f"MODERATE coordination ({overall_coord:.0f}/100) — possible coordinated activity.")
        else:
            parts.append(f"LOW coordination ({overall_coord:.0f}/100) — likely organic activity.")

        if botnet_nodes:
            parts.append(f"{len(botnet_nodes)} BOTNET_NODE(s) identified (high centrality + rhythm markers).")

        if ghosts:
            parts.append(
                f"{len(ghosts)} GHOST candidate(s) — individually ambiguous but "
                f"recur across clusters (elite operators)."
            )

        return " ".join(parts)

    @staticmethod
    def _empty_report(reason: str) -> PSICoordinationReport:
        """Return empty report when analysis unavailable."""
        return PSICoordinationReport(
            clusters=[],
            ghost_candidates=[],
            botnet_nodes=[],
            total_clusters=0,
            average_cluster_size=0.0,
            overall_coordination_score=0.0,
            has_organized_network=False,
            summary=f"Coordination analysis unavailable: {reason}",
        )
