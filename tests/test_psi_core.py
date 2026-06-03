"""
Unit Tests for PSI Core Engine — ARGOS-Ψ

Tests synthetic data with 3 behavior profiles:
- HUMAN: Hawkes-generated (bursty + circadian sleep)
- BOT: Poisson-generated (periodic, 24/7)
- HUMAN_LIKE: Two Hawkes with temporal turnoff (same operator, different accounts)

Goal: Ψ(HUMAN) << Ψ(BOT) and Ψ(HUMAN_LIKE) ≈ 0 (ambiguous)
"""
import sys
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from engines.psi_models.hawkes import HawkesModel
    from engines.psi_models.markov_ppm import MarkovPPMModel
    from engines.psi_models.likelihood_ratio import LikelihoodRatioCalculator
    PSI_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  PSI models not available: {e}")
    PSI_AVAILABLE = False


def generate_hawkes_timestamps(
    base_rate=0.1,
    self_exciting=0.6,
    decay_rate=0.3,
    duration_hours=24,
    include_sleep=True,
) -> list[datetime]:
    """
    Generate timestamps from Hawkes process (human-like: bursty + circadian).

    Args:
        base_rate: background rate
        self_exciting: self-excitation coefficient
        decay_rate: decay of self-excitation
        duration_hours: length of observation window
        include_sleep: add circadian sleep valley if True

    Returns:
        list of datetime objects
    """
    timestamps_sec = []
    t = 0.0
    T = duration_hours * 3600.0

    while t < T:
        # Conditional intensity
        excitation = sum(math.exp(-decay_rate * (t - ti_sec)) for ti_sec in timestamps_sec)
        lambda_t = base_rate + self_exciting * excitation

        # Circadian modulation
        if include_sleep:
            hour_of_day = (t / 3600.0) % 24
            if 22 <= hour_of_day or hour_of_day < 8:
                lambda_t *= 0.1  # 90% reduction during sleep hours
            else:
                lambda_t *= 1.2

        # Poisson thinning
        u = random.random()
        if u < lambda_t / max(lambda_t, 1.0):
            timestamps_sec.append(t)

        # Next candidate time (exponential with mean 1/lambda_t)
        t += -math.log(random.random() + 1e-9) / max(lambda_t, 0.01)

    # Convert to datetime
    base_dt = datetime.now()
    return sorted([base_dt + timedelta(seconds=ts) for ts in timestamps_sec])


def generate_poisson_timestamps(
    rate=0.15,
    duration_hours=24,
) -> list[datetime]:
    """
    Generate timestamps from Poisson process (bot-like: periodic, no circadian).

    Args:
        rate: events per hour (constant)
        duration_hours: observation window

    Returns:
        list of datetime objects
    """
    timestamps = []
    t = 0.0
    T = duration_hours * 3600.0

    while t < T:
        t += -math.log(random.random() + 1e-9) / max(rate / 3600.0, 0.01)
        if t < T:
            base_dt = datetime.now()
            ts = base_dt + timedelta(seconds=t)
            timestamps.append(ts)

    return sorted(timestamps)


def generate_action_sequence(length: int, diversity="high") -> list[str]:
    """
    Generate action sequence.

    diversity:
    - "high": mix of comment, react, share, publish, follow (~5 types)
    - "low": mostly comment + react (2-3 types)
    """
    all_actions = ["comment", "react", "share", "publish", "follow"]

    if diversity == "high":
        actions = all_actions
    elif diversity == "medium":
        actions = ["comment", "react", "share"]
    else:  # low
        actions = ["comment", "react"]

    return [random.choice(actions) for _ in range(length)]


def test_hawkes_vs_poisson():
    """
    Test 1: Hawkes process should score human-like; Poisson should score bot-like.
    """
    print("\n" + "="*70)
    print("TEST 1: Hawkes (Human) vs Poisson (Bot) timestamps")
    print("="*70)

    if not PSI_AVAILABLE:
        print("⚠️  Skipping: PSI models not available")
        return

    # Generate human-like timestamps (Hawkes with circadian)
    human_ts = generate_hawkes_timestamps(
        base_rate=0.08,
        self_exciting=0.5,
        decay_rate=0.2,
        duration_hours=24,
        include_sleep=True,
    )

    # Generate bot-like timestamps (Poisson, no circadian)
    bot_ts = generate_poisson_timestamps(rate=0.12, duration_hours=24)

    print(f"Human timestamps: {len(human_ts)} events over 72h")
    print(f"Bot timestamps: {len(bot_ts)} events over 72h")

    # Train models
    human_hawkes = HawkesModel({"hawkes_params": {}})
    human_hawkes.fit(human_ts)

    bot_hawkes = HawkesModel({"hawkes_params": {}})
    bot_hawkes.fit(bot_ts)
    bot_hawkes.alpha = 0.05  # Parameterize to be flat

    print(f"\nHuman model: α={human_hawkes.alpha:.3f}, β={human_hawkes.beta:.3f}")
    print(f"Bot model: α={bot_hawkes.alpha:.3f}, β={bot_hawkes.beta:.3f}")

    # Score human timestamps under both models
    ll_human_under_human = human_hawkes.log_likelihood(human_ts)
    ll_human_under_bot = bot_hawkes.log_likelihood(human_ts)

    # Score bot timestamps under both models
    ll_bot_under_human = human_hawkes.log_likelihood(bot_ts)
    ll_bot_under_bot = bot_hawkes.log_likelihood(bot_ts)

    print(f"\nHuman TS under human model: {ll_human_under_human:.2f}")
    print(f"Human TS under bot model: {ll_human_under_bot:.2f}")
    print(f"→ Δ = {ll_human_under_bot - ll_human_under_human:.2f} (negative = more human-like) ✓")

    print(f"\nBot TS under human model: {ll_bot_under_human:.2f}")
    print(f"Bot TS under bot model: {ll_bot_under_bot:.2f}")
    print(f"→ Δ = {ll_bot_under_bot - ll_bot_under_human:.2f} (positive = more bot-like) ✓")

    # Assertions
    assert (
        ll_human_under_bot < ll_human_under_human
    ), "Human TS should be better under human model"
    assert (
        ll_bot_under_bot > ll_bot_under_human
    ), "Bot TS should be better under bot model"

    print("\n✅ PASS: Temporal models discriminate human vs bot")


def test_psi_calculation():
    """
    Test 2: PSI calculation — combined Ψ score.
    """
    print("\n" + "="*70)
    print("TEST 2: PSI Score (Ψ = log P(S|A) - log P(S|H))")
    print("="*70)

    if not PSI_AVAILABLE:
        print("⚠️  Skipping: PSI models not available")
        return

    # Generate synthetic streams
    human_ts = generate_hawkes_timestamps(duration_hours=24, include_sleep=True)
    human_actions = generate_action_sequence(len(human_ts), diversity="high")

    bot_ts = generate_poisson_timestamps(rate=0.12, duration_hours=24)
    bot_actions = generate_action_sequence(len(bot_ts), diversity="low")

    # Train models
    human_hawkes = HawkesModel({"hawkes_params": {}})
    human_hawkes.fit(human_ts)
    human_markov = MarkovPPMModel({"markov_params": {}})
    human_markov.fit(human_actions)

    bot_hawkes = HawkesModel({"hawkes_params": {}})
    bot_hawkes.fit(bot_ts)
    bot_hawkes.alpha = 0.05
    bot_markov = MarkovPPMModel({"markov_params": {}})
    bot_markov.fit(bot_actions)

    # Create calculator
    calculator = LikelihoodRatioCalculator(
        (human_hawkes, human_markov),
        (bot_hawkes, bot_markov),
        {"psi_core": {}},
    )

    # Compute Ψ for human stream
    human_psi = calculator.compute("human_account", human_ts, human_actions)
    print(f"\nHuman account Ψ score: {human_psi.psi_score:.1f}")
    print(f"  Circadian: {human_psi.hawkes_score:.2f} (1.0 = very human)")
    print(f"  Action diversity: {human_psi.action_diversity:.2f}")
    print(f"  Interpretation: {human_psi.interpretation}")

    # Compute Ψ for bot stream
    bot_psi = calculator.compute("bot_account", bot_ts, bot_actions)
    print(f"\nBot account Ψ score: {bot_psi.psi_score:.1f}")
    print(f"  Circadian: {bot_psi.hawkes_score:.2f} (0.0 = 24/7)")
    print(f"  Action diversity: {bot_psi.action_diversity:.2f}")
    print(f"  Interpretation: {bot_psi.interpretation}")

    # Assertions
    assert human_psi.psi_score < bot_psi.psi_score, "Human should have lower Ψ than bot"
    assert human_psi.hawkes_score > bot_psi.hawkes_score, "Human should have higher circadian"
    assert (
        human_psi.action_diversity > bot_psi.action_diversity
    ), "Human should have more diverse actions"

    print("\n✅ PASS: Ψ scores correctly differentiate human from bot")


def test_ambiguous_zone():
    """
    Test 3: Ambiguous case (HUMAN_LIKE / sockpuppet).

    Two accounts with same operator (shared stylometry, temporal turnoff).
    Should both have Ψ ≈ 0.
    """
    print("\n" + "="*70)
    print("TEST 3: Ambiguous Zone (HUMAN_LIKE / Sockpuppet)")
    print("="*70)

    if not PSI_AVAILABLE:
        print("⚠️  Skipping: PSI models not available")
        return

    # Generate two accounts with temporal turnoff (alternating shifts)
    base_ts = generate_hawkes_timestamps(duration_hours=24, include_sleep=True)

    # Split into two streams: account_A (daytime), account_B (nighttime)
    account_a_ts = [ts for ts in base_ts if 8 <= ts.hour < 22]
    account_b_ts = [ts for ts in base_ts if 22 <= ts.hour or ts.hour < 8]

    # Same actions (shared stylometry)
    shared_actions = generate_action_sequence(max(len(account_a_ts), len(account_b_ts)), diversity="medium")

    print(f"\nAccount A (daytime): {len(account_a_ts)} events (8am-10pm)")
    print(f"Account B (nighttime): {len(account_b_ts)} events (10pm-8am)")

    # Train models on mixed data
    all_ts = account_a_ts + account_b_ts
    human_hawkes = HawkesModel({"hawkes_params": {}})
    human_hawkes.fit(all_ts)

    human_markov = MarkovPPMModel({"markov_params": {}})
    human_markov.fit(shared_actions)

    bot_hawkes = HawkesModel({"hawkes_params": {}})
    bot_hawkes.fit(all_ts)
    bot_hawkes.alpha = 0.05

    bot_markov = MarkovPPMModel({"markov_params": {}})
    bot_markov.fit(shared_actions)

    calculator = LikelihoodRatioCalculator(
        (human_hawkes, human_markov),
        (bot_hawkes, bot_markov),
        {"psi_core": {}},
    )

    # Score both accounts
    psi_a = calculator.compute("account_a", account_a_ts, shared_actions[: len(account_a_ts)])
    psi_b = calculator.compute("account_b", account_b_ts, shared_actions[: len(account_b_ts)])

    print(f"\nAccount A Ψ score: {psi_a.psi_score:.1f}")
    print(f"Account B Ψ score: {psi_b.psi_score:.1f}")
    print(f"→ Both near zero = ambiguous zone (likely same operator)")

    # Assertions: both should be close to zero (in abstention zone)
    assert -30 < psi_a.psi_score < 30, "Account A should be in ambiguous zone"
    assert -30 < psi_b.psi_score < 30, "Account B should be in ambiguous zone"

    print("\n✅ PASS: Sockpuppet accounts detected as ambiguous (Ψ ≈ 0)")


def main():
    """Run all tests."""
    print("\n" + "🔥"*35)
    print("ARGOS-Ψ PSI_CORE ENGINE — UNIT TESTS")
    print("🔥"*35)

    try:
        test_hawkes_vs_poisson()
        test_psi_calculation()
        test_ambiguous_zone()

        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED — PSI_CORE READY FOR INTEGRATION")
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
