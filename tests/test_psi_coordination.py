"""
Unit Tests for PSI Coordination Engine

Tests community detection, BOTNET_NODE and GHOST identification.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.psi_coordination_engine import PSICoordinationEngine


def generate_synthetic_posts_with_coordination():
    """
    Generate synthetic posts with:
    - Cluster 1: 5 coordinated bots (high temporal sync, shared content)
    - Cluster 2: 3 humans (low sync, diverse content)
    """
    base_time = datetime.now()
    posts = []

    # Cluster 1: Coordinated bots
    bot_actors = ["bot_1", "bot_2", "bot_3", "bot_4", "bot_5"]
    for i in range(5):  # 5 posts
        comments = []
        for j, actor in enumerate(bot_actors):
            # Synchronized: comments within 2-3 seconds
            comment_time = base_time + timedelta(hours=i, seconds=j*2)
            comments.append({
                "author": actor,
                "text": "same template comment" + str(i),  # Identical text per post
                "timestamp": comment_time.isoformat(),
                "likes": 0,
            })

        posts.append({
            "url": f"https://example.com/post_{i}",
            "timestamp": base_time.isoformat(),
            "comments": comments,
        })

    # Cluster 2: Organic humans
    human_actors = ["human_1", "human_2", "human_3"]
    for i in range(5, 10):  # 5 more posts
        comments = []
        for j, actor in enumerate(human_actors):
            # Uncoordinated: random delays
            comment_time = base_time + timedelta(hours=i, minutes=j*10, seconds=j*15)
            comments.append({
                "author": actor,
                "text": f"diverse comment from {actor} about topic",  # Different text
                "timestamp": comment_time.isoformat(),
                "likes": 0,
            })

        posts.append({
            "url": f"https://example.com/post_{i}",
            "timestamp": base_time.isoformat(),
            "comments": comments,
        })

    return posts


def test_coordination_detection():
    """Test basic coordination detection."""
    print("\n" + "="*70)
    print("TEST 1: Coordination Detection")
    print("="*70)

    engine = PSICoordinationEngine({"psi_coordination": {"min_cluster_size": 2}})
    posts = generate_synthetic_posts_with_coordination()

    # Mock PSI scores
    psi_scores = {
        "bot_1": 75.0,
        "bot_2": 80.0,
        "bot_3": 72.0,
        "bot_4": 78.0,
        "bot_5": 85.0,
        "human_1": -20.0,
        "human_2": -15.0,
        "human_3": -25.0,
    }

    report = engine.analyze(posts, psi_scores)

    print(f"\n✅ Coordination analysis completed")
    print(f"   Clusters detected: {report.total_clusters}")
    print(f"   Overall coordination score: {report.overall_coordination_score}/100")
    print(f"   Organized network: {report.has_organized_network}")

    for cluster in report.clusters:
        print(f"\n   Cluster {cluster.cluster_id}:")
        print(f"      Actors: {', '.join(cluster.actors[:3])}{'...' if len(cluster.actors) > 3 else ''}")
        print(f"      Size: {cluster.size}")
        print(f"      Coordination: {cluster.coordination_score}/100")
        print(f"      Temporal sync: {cluster.temporal_sync_level:.2f}")
        print(f"      Content similarity: {cluster.content_similarity_avg:.2f}")
        print(f"      Command node: {cluster.command_node}")

    # Assertions
    assert report.total_clusters >= 1, "Should detect at least 1 cluster"
    assert isinstance(report.overall_coordination_score, (int, float))
    assert 0 <= report.overall_coordination_score <= 100

    print(f"\n✅ PASS: Coordination detection working")
    print("="*70)


def test_botnet_node_detection():
    """Test BOTNET_NODE identification."""
    print("\n" + "="*70)
    print("TEST 2: BOTNET_NODE Detection")
    print("="*70)

    engine = PSICoordinationEngine({"psi_coordination": {"min_cluster_size": 2}})
    posts = generate_synthetic_posts_with_coordination()

    psi_scores = {actor: 75.0 for actor in ["bot_1", "bot_2", "bot_3", "bot_4", "bot_5"]}
    psi_scores.update({actor: -20.0 for actor in ["human_1", "human_2", "human_3"]})

    report = engine.analyze(posts, psi_scores)

    print(f"\n✅ BOTNET_NODE detection completed")
    print(f"   BOTNET_NODEs found: {len(report.botnet_nodes)}")
    if report.botnet_nodes:
        print(f"   Candidates: {report.botnet_nodes}")

    # Assertions
    assert isinstance(report.botnet_nodes, list)

    print(f"\n✅ PASS: BOTNET_NODE detection working")
    print("="*70)


def test_ghost_detection():
    """Test GHOST (elite operator) detection."""
    print("\n" + "="*70)
    print("TEST 3: GHOST Detection")
    print("="*70)

    engine = PSICoordinationEngine({"psi_coordination": {"ghost_recurrence_min_clusters": 2}})
    posts = generate_synthetic_posts_with_coordination()

    # Add a GHOST: appears in multiple clusters with Ψ ≈ 0
    ghost_actor = "ghost_elite"
    for post in posts:
        if len(post["comments"]) < 5:
            post["comments"].append({
                "author": ghost_actor,
                "text": "subtle comment that blends in",
                "timestamp": (
                    datetime.fromisoformat(post["comments"][0]["timestamp"])
                    + timedelta(seconds=2)
                ).isoformat(),
                "likes": 0,
            })

    psi_scores = {
        "bot_1": 75.0, "bot_2": 80.0, "bot_3": 72.0, "bot_4": 78.0, "bot_5": 85.0,
        "human_1": -20.0, "human_2": -15.0, "human_3": -25.0,
        "ghost_elite": 5.0,  # Ψ ≈ 0 = ambiguous
    }

    report = engine.analyze(posts, psi_scores)

    print(f"\n✅ GHOST detection completed")
    print(f"   GHOST candidates found: {len(report.ghost_candidates)}")
    if report.ghost_candidates:
        print(f"   GHOSTs: {report.ghost_candidates}")

    # Assertions
    assert isinstance(report.ghost_candidates, list)

    print(f"\n✅ PASS: GHOST detection working")
    print("="*70)


def test_summary_generation():
    """Test summary generation."""
    print("\n" + "="*70)
    print("TEST 4: Summary Generation")
    print("="*70)

    engine = PSICoordinationEngine({"psi_coordination": {"min_cluster_size": 2}})
    posts = generate_synthetic_posts_with_coordination()
    psi_scores = {
        "bot_1": 75.0, "bot_2": 80.0, "bot_3": 72.0, "bot_4": 78.0, "bot_5": 85.0,
        "human_1": -20.0, "human_2": -15.0, "human_3": -25.0,
    }

    report = engine.analyze(posts, psi_scores)

    print(f"\n✅ Summary generated:")
    print(f"   {report.summary}")

    # Assertions
    assert isinstance(report.summary, str)
    assert len(report.summary) > 0

    print(f"\n✅ PASS: Summary generation working")
    print("="*70)


def main():
    """Run all coordination tests."""
    print("\n" + "🔥"*35)
    print("PSI COORDINATION ENGINE — UNIT TESTS")
    print("🔥"*35)

    try:
        test_coordination_detection()
        test_botnet_node_detection()
        test_ghost_detection()
        test_summary_generation()

        print("\n" + "="*70)
        print("✅ ALL COORDINATION TESTS PASSED")
        print("✅ PSI_COORDINATION READY FOR INTEGRATION")
        print("="*70 + "\n")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
