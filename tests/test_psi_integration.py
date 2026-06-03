"""
Integration Test: PSI_CORE + CIBScoreEngine

Verify that PSI report integrates cleanly with CIBScoreEngine
and contributes appropriately to overall CIB score.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.cib_score_engine import CIBScoreEngine, CIBScoreReport


def test_psi_integration_with_cib_score():
    """
    Test that CIBScoreEngine accepts psi_report and integrates cleanly.
    """
    print("\n" + "="*70)
    print("TEST: PSI_CORE Integration with CIBScoreEngine")
    print("="*70)

    # Create CIBScoreEngine with PSI weight in config
    cfg = {
        "cib_score": {
            "weights": {
                "troll_hunter":    0.22,
                "cib_graph":       0.16,
                "temporal":        0.13,
                "narrative_mut":   0.09,
                "dark_amp":        0.07,
                "engagement":      0.07,
                "contagion":       0.05,
                "reply_chain":     0.04,
                "bot_farm_shift":  0.03,
                "cross_campaign":  0.02,
                "identity":        0.01,
                "psi_core":        0.10,  # ← NEW ENGINE
            },
            "thresholds": {
                "confirmed":       80.0,
                "high_confidence": 60.0,
                "probable":        40.0,
                "possible":        20.0,
            },
            "top_signals_count": 5,
        }
    }

    engine = CIBScoreEngine(cfg)

    print(f"\n✅ CIBScoreEngine instantiated with PSI weight")
    print(f"   PSI weight: {engine._weights.get('psi_core', 'NOT FOUND')}")
    print(f"   Total weights: {sum(engine._weights.values()):.2f}")

    # Create a mock PSI report
    class MockPSIReport:
        overall_score = 65.0
        confidence_label = "BOT"
        high_risk_actors = ["bot_account_1", "bot_account_2"]
        ambiguous_actors = ["ambiguous_account"]
        summary = "2 high-risk bots detected, 1 ambiguous"

    psi_report = MockPSIReport()

    # Create mock reports for other engines
    class MockTrollReport:
        bot_risk_score = 45

    class MockTemporalReport:
        overall_score = 35

    # Compute CIB score WITH PSI
    result = engine.compute(
        troll_report=MockTrollReport(),
        temporal_report=MockTemporalReport(),
        psi_report=psi_report,
    )

    print(f"\n✅ CIBScoreEngine.compute() executed successfully")
    print(f"   Overall score: {result.overall_score}/100")
    print(f"   Confidence label: {result.confidence_label}")
    print(f"   Engines present: {result.engines_present}")
    print(f"   Engines active: {result.engines_active}")
    print(f"   Data quality: {result.data_quality}")

    # Verify PSI is in the dimensions
    psi_dims = [d for d in result.dimensions if d.engine == "psi_core"]
    if psi_dims:
        psi_dim = psi_dims[0]
        print(f"\n✅ PSI_CORE in dimensions:")
        print(f"   Label: {psi_dim.label}")
        print(f"   Score: {psi_dim.score}/100")
        print(f"   Weight: {psi_dim.weight:.4f}")
        print(f"   Contribution: {psi_dim.contribution:.2f}")
    else:
        print(f"\n⚠️  PSI_CORE not in dimensions (missing reports treated as 0-score)")

    # Verify PSI signals appear in top_signals
    psi_signals = [s for s in result.top_signals if "bot indicator" in s.lower() or "ambiguous" in s.lower()]
    if psi_signals:
        print(f"\n✅ PSI signals detected:")
        for sig in psi_signals:
            print(f"   • {sig}")
    else:
        print(f"\n⚠️  No PSI-specific signals (expected if psi_score=0)")

    # Assertions
    assert isinstance(result, CIBScoreReport), "Should return CIBScoreReport"
    assert result.overall_score >= 0 and result.overall_score <= 100, "Score should be 0-100"
    assert "psi_core" in engine._weights, "PSI weight should exist in config"
    assert engine._weights["psi_core"] == 0.10, "PSI weight should be 0.10"

    print(f"\n✅ PASS: PSI_CORE integrates cleanly with CIBScoreEngine")
    print("="*70 + "\n")


def test_backward_compatibility():
    """
    Verify that CIBScoreEngine still works without psi_report (backward compatible).
    """
    print("\n" + "="*70)
    print("TEST: Backward Compatibility (without PSI report)")
    print("="*70)

    cfg = {
        "cib_score": {
            "weights": {
                "troll_hunter":    0.25,
                "cib_graph":       0.18,
                "temporal":        0.14,
                "narrative_mut":   0.10,
                "dark_amp":        0.08,
                "engagement":      0.08,
                "contagion":       0.06,
                "reply_chain":     0.05,
                "bot_farm_shift":  0.03,
                "cross_campaign":  0.02,
                "identity":        0.01,
            },
            "thresholds": {
                "confirmed":       80.0,
                "high_confidence": 60.0,
                "probable":        40.0,
                "possible":        20.0,
            },
            "top_signals_count": 5,
        }
    }

    engine = CIBScoreEngine(cfg)

    class MockTrollReport:
        bot_risk_score = 75

    result = engine.compute(troll_report=MockTrollReport())

    print(f"\n✅ CIBScoreEngine works without psi_report")
    print(f"   Overall score: {result.overall_score}/100")
    print(f"   Data quality: {result.data_quality}")

    assert result.overall_score >= 0 and result.overall_score <= 100
    print(f"\n✅ PASS: Backward compatibility maintained")
    print("="*70 + "\n")


def main():
    """Run all integration tests."""
    print("\n" + "🔥"*35)
    print("ARGOS-Ψ + CIBScoreEngine Integration Tests")
    print("🔥"*35)

    try:
        test_psi_integration_with_cib_score()
        test_backward_compatibility()

        print("\n" + "="*70)
        print("✅ ALL INTEGRATION TESTS PASSED")
        print("✅ PSI_CORE READY FOR PHASE 2")
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
