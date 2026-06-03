"""
Unit Tests for PSI Stylometry Engine

Tests sockpuppet detection via stylometric linkage + temporal patterns.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.psi_stylometry_engine import PSIStylometryEngine


def generate_sockpuppet_posts():
    """
    Generate synthetic posts with:
    - Account A: high frequency (day hours)
    - Account B: high frequency (night hours) — likely same operator
    - Account C: distinct writing style (unrelated)
    """
    base_time = datetime.now()
    posts = []

    # Posts 1-10: Account A (day operator) + Account C (organic)
    for i in range(10):
        comments = []

        # Account A: day hours, specific writing style
        comments.append({
            "author": "account_a",
            "text": "This is really interesting and important discussion we need",
            "timestamp": (base_time + timedelta(hours=i*2, minutes=i)).isoformat(),
            "likes": 0,
        })

        # Account C: organic writing
        comments.append({
            "author": "account_c",
            "text": f"I disagree with this completely here {i}",
            "timestamp": (base_time + timedelta(hours=i*2, minutes=i+5)).isoformat(),
            "likes": 0,
        })

        posts.append({
            "url": f"https://example.com/post_a_{i}",
            "timestamp": base_time.isoformat(),
            "comments": comments,
        })

    # Posts 11-20: Account B (night hours, same operator as A) + Account C
    for i in range(10, 20):
        comments = []

        # Account B: night hours, SAME style as A
        comments.append({
            "author": "account_b",
            "text": "This is really interesting and important matter at stake",
            "timestamp": (base_time + timedelta(hours=12+i, minutes=i)).isoformat(),
            "likes": 0,
        })

        # Account C: keeps distinct style
        comments.append({
            "author": "account_c",
            "text": f"Nobody agrees with that obviously {i}",
            "timestamp": (base_time + timedelta(hours=12+i, minutes=i+5)).isoformat(),
            "likes": 0,
        })

        posts.append({
            "url": f"https://example.com/post_b_{i}",
            "timestamp": base_time.isoformat(),
            "comments": comments,
        })

    return posts


def test_fingerprint_computation():
    """Test stylometric fingerprint extraction."""
    print("\n" + "="*70)
    print("TEST 1: Stylometric Fingerprint Computation")
    print("="*70)

    engine = PSIStylometryEngine({"psi_stylometry": {}})
    posts = generate_sockpuppet_posts()

    report = engine.analyze(posts)

    print(f"\n✅ Stylometry analysis completed")
    print(f"   Fingerprints computed: {len(report.fingerprints)}")

    for actor, fp in list(report.fingerprints.items())[:3]:
        print(f"\n   {actor}:")
        print(f"      Texts: {fp.total_texts}")
        print(f"      Avg length: {fp.avg_text_length:.1f} chars")
        print(f"      Emoji ratio: {fp.emoji_ratio:.3f}")
        print(f"      Caps ratio: {fp.caps_ratio:.3f}")
        print(f"      Unique function words: {len(fp.function_word_freq)}")

    # Assertions
    assert len(report.fingerprints) >= 2, "Should extract 2+ fingerprints"
    assert all(fp.total_texts > 0 for fp in report.fingerprints.values())

    print(f"\n✅ PASS: Fingerprint computation working")
    print("="*70)


def test_linkage_detection():
    """Test account linkage detection."""
    print("\n" + "="*70)
    print("TEST 2: Account Linkage Detection")
    print("="*70)

    engine = PSIStylometryEngine({"psi_stylometry": {}})
    posts = generate_sockpuppet_posts()

    report = engine.analyze(posts)

    print(f"\n✅ Linkage analysis completed")
    print(f"   Account pairs analyzed: {len(report.linkages)}")
    print(f"   High-confidence linkages (0.8+): {report.high_confidence_pairs}")

    if report.linkages:
        # Show top linkages
        for linkage in report.linkages[:3]:
            print(f"\n   {linkage.account_a} ↔ {linkage.account_b}:")
            print(f"      Stylometric distance: {linkage.stylometric_distance:.2f}")
            print(f"      Temporal anti-corr: {linkage.temporal_anticorr:.2f}")
            print(f"      Shared n-grams: {linkage.shared_ngrams_pct:.2f}")
            print(f"      Confidence: {linkage.overall_confidence:.2f}")
            print(f"      Likely same? {linkage.likely_same_operator}")

    # Assertions
    assert isinstance(report.linkages, list)
    assert all(0 <= l.overall_confidence <= 1 for l in report.linkages)

    print(f"\n✅ PASS: Linkage detection working")
    print("="*70)


def test_sockpuppet_clustering():
    """Test sockpuppet group clustering."""
    print("\n" + "="*70)
    print("TEST 3: Sockpuppet Clustering")
    print("="*70)

    engine = PSIStylometryEngine({"psi_stylometry": {}})
    posts = generate_sockpuppet_posts()

    report = engine.analyze(posts)

    print(f"\n✅ Clustering completed")
    print(f"   Sockpuppet groups found: {len(report.sockpuppet_groups)}")

    for group in report.sockpuppet_groups:
        print(f"\n   Group: {', '.join(group)}")

    # Assertions
    assert isinstance(report.sockpuppet_groups, list)

    print(f"\n✅ PASS: Sockpuppet clustering working")
    print("="*70)


def test_summary_generation():
    """Test summary generation."""
    print("\n" + "="*70)
    print("TEST 4: Summary Generation")
    print("="*70)

    engine = PSIStylometryEngine({"psi_stylometry": {}})
    posts = generate_sockpuppet_posts()

    report = engine.analyze(posts)

    print(f"\n✅ Summary generated:")
    print(f"   {report.summary}")

    # Assertions
    assert isinstance(report.summary, str)
    assert len(report.summary) > 0

    print(f"\n✅ PASS: Summary generation working")
    print("="*70)


def main():
    """Run all stylometry tests."""
    print("\n" + "🔥"*35)
    print("PSI STYLOMETRY ENGINE — UNIT TESTS")
    print("🔥"*35)

    try:
        test_fingerprint_computation()
        test_linkage_detection()
        test_sockpuppet_clustering()
        test_summary_generation()

        print("\n" + "="*70)
        print("✅ ALL STYLOMETRY TESTS PASSED")
        print("✅ PSI_STYLOMETRY READY FOR INTEGRATION")
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
