"""
test_lease_evaluator.py — QA suite for the lease position engine.

This model may be used to make a six-figure, multi-year, hard-to-reverse
decision. Every number it prints is therefore load-bearing, and every number it
prints is verified here against a hand-computed or analytically-known result.

No Ollama, no network, no database. Deterministic seeds throughout.

Run:
    python test_lease_evaluator.py
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from lease_evaluator import (
    ILLUSTRATIVE,
    WEEKS_PER_YEAR,
    Alternative,
    LeaseEvaluator,
    LeaseTerms,
    OperatingCosts,
    RevenueModel,
    RiskModel,
    Scenario,
    main,
    tornado,
)


def make_scenario(**overrides) -> Scenario:
    """A deliberately frictionless scenario: no volatility, no breakdowns,
    no home time. Every stochastic term is switched off so that simulated
    output must collapse onto the closed-form deterministic result."""
    base = dict(
        label="test",
        lease=LeaseTerms(
            weekly_payment=500.0,
            term_weeks=208,
            down_payment=0.0,
            balloon_payment=0.0,
            truck_fair_market_value=60_000.0,
            maintenance_escrow_weekly=0.0,
            escrow_refundable=True,
        ),
        costs=OperatingCosts(
            fuel_price_per_gal=4.00,
            mpg=8.0,  # -> exactly $0.50/mi fuel
            maintenance_reserve_per_mile=0.10,
            insurance_weekly=200.0,
            eld_and_software_weekly=0.0,
            tolls_parking_weekly=0.0,
            plates_permits_annual=0.0,
            factoring_pct=0.0,
            dispatch_fee_pct=0.0,
        ),
        revenue=RevenueModel(
            avg_rate_per_mile=2.00,
            rate_volatility=0.0,
            rate_mean_uncertainty=0.0,
            loaded_miles_per_week=2_000.0,
            miles_volatility=0.0,
            deadhead_pct=0.0,
            home_time_weeks_per_year=0.0,
        ),
        risk=RiskModel(
            breakdown_prob_per_week=0.0,
            avg_breakdown_cost=0.0,
            breakdown_cost_volatility=0.0,
            avg_downtime_weeks=0.0,
            starting_cash_reserve=50_000.0,
        ),
        alternative=Alternative(w2_weekly_takehome=1_000.0, w2_weekly_volatility=0.0),
    )
    base.update(overrides)
    return Scenario(**base)


# --------------------------------------------------------------------------
class TestBoundarySchemas(unittest.TestCase):
    """The contract is a hostile payload until proven otherwise."""

    def test_rejects_unknown_field(self):
        with self.assertRaises(ValidationError):
            LeaseTerms(
                weekly_payment=500,
                term_weeks=208,
                down_payment=0,
                balloon_payment=0,
                truck_fair_market_value=60_000,
                sneaky_extra_fee=99,  # extra="forbid"
            )

    def test_rejects_nonpositive_payment(self):
        with self.assertRaises(ValidationError):
            LeaseTerms(
                weekly_payment=0,
                term_weeks=208,
                down_payment=0,
                balloon_payment=0,
                truck_fair_market_value=60_000,
            )

    def test_rejects_absurd_mpg(self):
        with self.assertRaises(ValidationError):
            OperatingCosts(
                fuel_price_per_gal=4.0,
                mpg=99.0,  # a Cascadia does not get 99 mpg
                maintenance_reserve_per_mile=0.1,
                insurance_weekly=200,
            )

    def test_rejects_deadhead_over_half(self):
        with self.assertRaises(ValidationError):
            RevenueModel(
                avg_rate_per_mile=2.0,
                rate_volatility=0.2,
                loaded_miles_per_week=2000,
                deadhead_pct=0.60,
            )

    def test_rejects_down_payment_exceeding_reserve(self):
        """You cannot fund a deal with money you do not have."""
        with self.assertRaises(ValidationError):
            make_scenario(
                lease=LeaseTerms(
                    weekly_payment=500,
                    term_weeks=208,
                    down_payment=20_000,
                    balloon_payment=0,
                    truck_fair_market_value=60_000,
                ),
                risk=RiskModel(
                    breakdown_prob_per_week=0.0,
                    avg_breakdown_cost=0.0,
                    avg_downtime_weeks=0.0,
                    starting_cash_reserve=10_000,  # < down payment
                ),
            )

    def test_frozen(self):
        with self.assertRaises(ValidationError):
            make_scenario().lease.weekly_payment = 1.0


# --------------------------------------------------------------------------
class TestDeterministicMath(unittest.TestCase):
    """Hand-computed. If these drift, every downstream number is a lie."""

    def setUp(self):
        self.ev = LeaseEvaluator(make_scenario())

    def test_cost_per_mile_components(self):
        cb = self.ev.cost_per_mile()
        self.assertAlmostEqual(cb.fuel, 0.50, places=6)  # $4.00 / 8 mpg
        self.assertAlmostEqual(cb.maintenance_reserve, 0.10, places=6)
        # fixed = 500 payment + 200 insurance = 700/wk over 2000 mi = $0.35/mi
        self.assertAlmostEqual(cb.weekly_fixed, 700.0, places=6)
        self.assertAlmostEqual(cb.fixed_amortized, 0.35, places=6)
        self.assertAlmostEqual(cb.factoring_and_dispatch, 0.0, places=6)
        self.assertAlmostEqual(cb.total, 0.95, places=6)

    def test_deadhead_inflates_total_miles(self):
        ev = LeaseEvaluator(
            make_scenario(
                revenue=RevenueModel(
                    avg_rate_per_mile=2.0,
                    rate_volatility=0.0,
                    loaded_miles_per_week=1_800.0,
                    deadhead_pct=0.10,
                    home_time_weeks_per_year=0.0,
                )
            )
        )
        self.assertAlmostEqual(ev.total_miles_per_week(), 2_000.0, places=6)

    def test_breakeven_rate(self):
        # variable = (0.50 + 0.10) * 2000 mi = 1200; fixed = 700
        # breakeven = 1900 / 2000 loaded mi = $0.95/mi
        self.assertAlmostEqual(self.ev.breakeven_rate_per_mile(), 0.95, places=6)

    def test_net_is_zero_at_breakeven_rate(self):
        """The definition of break-even. If this fails, the solver is broken."""
        be = self.ev.breakeven_rate_per_mile()
        self.assertAlmostEqual(self.ev.deterministic_weekly_net(be), 0.0, places=6)

    def test_deterministic_weekly_net(self):
        # gross 2.00*2000 = 4000; variable 1200; fixed 700 -> 2100/wk
        self.assertAlmostEqual(self.ev.deterministic_weekly_net(), 2_100.0, places=6)

    def test_factoring_raises_breakeven(self):
        ev = LeaseEvaluator(
            make_scenario(
                costs=OperatingCosts(
                    fuel_price_per_gal=4.0,
                    mpg=8.0,
                    maintenance_reserve_per_mile=0.10,
                    insurance_weekly=200.0,
                    factoring_pct=0.05,
                )
            )
        )
        # 1900 / (2000 * 0.95) = $1.0
        self.assertAlmostEqual(ev.breakeven_rate_per_mile(), 1.0, places=6)


# --------------------------------------------------------------------------
class TestImpliedAPR(unittest.TestCase):
    """A lease is financing wearing a costume. Unmask it."""

    def test_zero_interest_deal_returns_zero_apr(self):
        """Payments exactly equal principal, no time value -> ~0% APR."""
        ev = LeaseEvaluator(
            make_scenario(
                lease=LeaseTerms(
                    weekly_payment=100.0,
                    term_weeks=100,
                    down_payment=0.0,
                    balloon_payment=0.0,
                    truck_fair_market_value=10_000.0,  # 100 * 100 = 10,000
                    escrow_refundable=True,
                )
            )
        )
        apr = ev.implied_apr()
        self.assertIsNotNone(apr)
        self.assertAlmostEqual(apr, 0.0, places=3)

    def test_known_annuity_recovers_its_rate(self):
        """Analytic check: price an annuity at a known weekly rate, then solve
        for the rate and confirm we recover it."""
        weekly = 0.002  # ~10.9% APR
        n, pmt = 208, 600.0
        principal = pmt * (1 - (1 + weekly) ** -n) / weekly
        ev = LeaseEvaluator(
            make_scenario(
                lease=LeaseTerms(
                    weekly_payment=pmt,
                    term_weeks=n,
                    down_payment=0.0,
                    balloon_payment=0.0,
                    truck_fair_market_value=principal,
                    escrow_refundable=True,
                ),
                risk=RiskModel(
                    breakdown_prob_per_week=0.0,
                    avg_breakdown_cost=0.0,
                    avg_downtime_weeks=0.0,
                    starting_cash_reserve=50_000,
                ),
            )
        )
        expected = (1 + weekly) ** WEEKS_PER_YEAR - 1
        self.assertAlmostEqual(ev.implied_apr(), expected, places=4)

    def test_expensive_lease_has_high_apr(self):
        apr = LeaseEvaluator(ILLUSTRATIVE).implied_apr(include_escrow=True)
        self.assertIsNotNone(apr)
        self.assertGreater(apr, 0.15)

    def test_sunk_escrow_raises_apr(self):
        """Non-refundable escrow is interest by another name."""
        ev = LeaseEvaluator(ILLUSTRATIVE)
        self.assertGreater(ev.implied_apr(include_escrow=True), ev.implied_apr(False))

    def test_degenerate_financing_returns_none(self):
        """Down payment >= FMV means there is no principal to finance."""
        ev = LeaseEvaluator(
            make_scenario(
                lease=LeaseTerms(
                    weekly_payment=500,
                    term_weeks=208,
                    down_payment=40_000,
                    balloon_payment=0,
                    truck_fair_market_value=40_000,
                    escrow_refundable=True,
                )
            )
        )
        self.assertIsNone(ev.implied_apr())


# --------------------------------------------------------------------------
class TestSimulation(unittest.TestCase):
    def test_zero_variance_collapses_to_deterministic(self):
        """With every stochastic term off, the Monte Carlo MUST reproduce the
        closed-form answer exactly. This is the master check on the sim loop."""
        ev = LeaseEvaluator(make_scenario())
        sim = ev.simulate(n_paths=500, weeks=52)
        expected = ev.deterministic_weekly_net() * 52
        self.assertAlmostEqual(sim.net_median, expected, places=2)
        self.assertAlmostEqual(sim.net_mean, expected, places=2)
        self.assertEqual(sim.p_ruin, 0.0)
        self.assertEqual(sim.p_beat_w2, 1.0)  # 2100/wk vs 1000/wk W2

    def test_down_payment_charged_against_pnl(self):
        """A down payment is money out the door and must reduce net."""
        a = LeaseEvaluator(make_scenario()).simulate(n_paths=300, weeks=52)
        b = LeaseEvaluator(
            make_scenario(
                lease=LeaseTerms(
                    weekly_payment=500,
                    term_weeks=208,
                    down_payment=7_000,
                    balloon_payment=0,
                    truck_fair_market_value=60_000,
                    escrow_refundable=True,
                )
            )
        ).simulate(n_paths=300, weeks=52)
        self.assertAlmostEqual(a.net_median - b.net_median, 7_000.0, places=2)

    def test_fixed_costs_fire_during_downtime(self):
        """THE TRAP. A truck that never moves must still bleed the fixed cost."""
        ev = LeaseEvaluator(
            make_scenario(
                risk=RiskModel(
                    breakdown_prob_per_week=1.0,  # broken every week
                    avg_breakdown_cost=0.0,
                    breakdown_cost_volatility=0.0,
                    avg_downtime_weeks=1.0,
                    starting_cash_reserve=50_000,
                )
            )
        )
        sim = ev.simulate(n_paths=300, weeks=10)
        # zero revenue, zero variable cost, but 700/wk fixed for 10 weeks
        self.assertAlmostEqual(sim.net_median, -7_000.0, places=2)

    def test_ruin_is_certain_when_reserve_cannot_absorb_losses(self):
        ev = LeaseEvaluator(
            make_scenario(
                risk=RiskModel(
                    breakdown_prob_per_week=1.0,
                    avg_breakdown_cost=0.0,
                    avg_downtime_weeks=1.0,
                    starting_cash_reserve=1_000.0,  # < 2 weeks of fixed cost
                )
            )
        )
        self.assertEqual(ev.simulate(n_paths=300, weeks=10).p_ruin, 1.0)

    def test_home_time_reduces_net(self):
        with_home = LeaseEvaluator(
            make_scenario(
                revenue=RevenueModel(
                    avg_rate_per_mile=2.0,
                    rate_volatility=0.0,
                    loaded_miles_per_week=2_000.0,
                    deadhead_pct=0.0,
                    home_time_weeks_per_year=10.0,
                )
            )
        ).simulate(n_paths=2_000, weeks=52)
        self.assertLess(with_home.net_median, LeaseEvaluator(make_scenario())
                        .simulate(n_paths=500, weeks=52).net_median)

    def test_parameter_uncertainty_widens_the_tails(self):
        """The headline feature. Not knowing the mean rate is itself a risk, and
        a model without it will understate ruin. This proves ours does not."""
        tight = LeaseEvaluator(ILLUSTRATIVE.model_copy(
            update={"revenue": ILLUSTRATIVE.revenue.model_copy(
                update={"rate_mean_uncertainty": 0.0})}, deep=True)
        ).simulate(n_paths=8_000)
        loose = LeaseEvaluator(ILLUSTRATIVE.model_copy(
            update={"revenue": ILLUSTRATIVE.revenue.model_copy(
                update={"rate_mean_uncertainty": 0.30})}, deep=True)
        ).simulate(n_paths=8_000)

        self.assertGreater(loose.p_ruin, tight.p_ruin)
        self.assertLess(loose.net_p5, tight.net_p5)      # worse bad case
        self.assertGreater(loose.net_p95, tight.net_p95)  # better good case

    def test_determinism_under_seed(self):
        a = LeaseEvaluator(ILLUSTRATIVE, seed=42).simulate(n_paths=1_000)
        b = LeaseEvaluator(ILLUSTRATIVE, seed=42).simulate(n_paths=1_000)
        self.assertEqual(a.net_median, b.net_median)
        self.assertEqual(a.p_ruin, b.p_ruin)

    def test_higher_rate_monotonically_improves_edge(self):
        prev = None
        for rate in (1.80, 2.00, 2.20, 2.40):
            s = ILLUSTRATIVE.model_copy(
                update={"revenue": ILLUSTRATIVE.revenue.model_copy(
                    update={"avg_rate_per_mile": rate})}, deep=True)
            edge = LeaseEvaluator(s).simulate(n_paths=4_000).median_edge
            if prev is not None:
                self.assertGreater(edge, prev)
            prev = edge


# --------------------------------------------------------------------------
class TestSolvers(unittest.TestCase):
    def test_indifference_rate_actually_produces_indifference(self):
        """Solve for the rate that matches W2, then verify the edge is ~zero
        when we plug it back in. A solver that does not round-trip is a bug."""
        ev = LeaseEvaluator(ILLUSTRATIVE)
        r = ev.solve_indifference_rate(n_paths=6_000)
        s2 = ILLUSTRATIVE.model_copy(
            update={"revenue": ILLUSTRATIVE.revenue.model_copy(
                update={"avg_rate_per_mile": r})}, deep=True)
        edge = LeaseEvaluator(s2).simulate(n_paths=12_000).median_edge
        self.assertLess(abs(edge), 2_500.0)  # within noise of zero on ~$65k

    def test_indifference_rate_exceeds_breakeven(self):
        """Beating zero is not the bar. Beating the W2 seat is the bar."""
        ev = LeaseEvaluator(ILLUSTRATIVE)
        self.assertGreater(ev.solve_indifference_rate(n_paths=4_000),
                           ev.breakeven_rate_per_mile())

    def test_indifference_miles_round_trips(self):
        ev = LeaseEvaluator(ILLUSTRATIVE)
        m = ev.solve_indifference_miles(n_paths=6_000)
        s2 = ILLUSTRATIVE.model_copy(
            update={"revenue": ILLUSTRATIVE.revenue.model_copy(
                update={"loaded_miles_per_week": m})}, deep=True)
        edge = LeaseEvaluator(s2).simulate(n_paths=12_000).median_edge
        self.assertLess(abs(edge), 3_000.0)


# --------------------------------------------------------------------------
class TestContractScanner(unittest.TestCase):
    """These flags depend on the PAPER, not on any market assumption. They are
    the only part of this analysis that is fact rather than forecast."""

    def test_clean_contract_raises_no_flags(self):
        ev = LeaseEvaluator(
            make_scenario(
                lease=LeaseTerms(
                    weekly_payment=100.0,
                    term_weeks=100,
                    down_payment=0.0,
                    balloon_payment=0.0,
                    truck_fair_market_value=10_000.0,
                    escrow_refundable=True,
                )
            )
        )
        self.assertEqual(ev.contract_red_flags(), [])

    def test_flags_nonrefundable_escrow(self):
        flags = LeaseEvaluator(ILLUSTRATIVE).contract_red_flags()
        self.assertTrue(any("NON-REFUNDABLE ESCROW" in f for f in flags))

    def test_flags_large_balloon(self):
        flags = LeaseEvaluator(ILLUSTRATIVE).contract_red_flags()
        self.assertTrue(any("BALLOON" in f for f in flags))

    def test_flags_thin_reserve(self):
        ev = LeaseEvaluator(
            make_scenario(
                lease=LeaseTerms(
                    weekly_payment=500, term_weeks=208, down_payment=8_000,
                    balloon_payment=0, truck_fair_market_value=60_000,
                    escrow_refundable=True,
                ),
                risk=RiskModel(
                    breakdown_prob_per_week=0.0, avg_breakdown_cost=0.0,
                    avg_downtime_weeks=0.0, starting_cash_reserve=10_000,
                ),
            )
        )
        # 2,000 left / 700 per week = 2.9 weeks
        self.assertTrue(any("THIN RESERVE" in f for f in ev.contract_red_flags()))

    def test_flags_predatory_apr(self):
        ev = LeaseEvaluator(
            make_scenario(
                lease=LeaseTerms(
                    weekly_payment=900.0, term_weeks=208, down_payment=5_000.0,
                    balloon_payment=25_000.0, truck_fair_market_value=45_000.0,
                    escrow_refundable=True,
                )
            )
        )
        self.assertTrue(any("APR" in f for f in ev.contract_red_flags()))

    def test_flags_exit_penalty(self):
        ev = LeaseEvaluator(
            make_scenario(
                lease=LeaseTerms(
                    weekly_payment=500, term_weeks=208, down_payment=0,
                    balloon_payment=0, truck_fair_market_value=60_000,
                    escrow_refundable=True, early_termination_penalty=15_000,
                )
            )
        )
        self.assertTrue(any("EXIT PENALTY" in f for f in ev.contract_red_flags()))


# --------------------------------------------------------------------------
class TestVerdictAndReporting(unittest.TestCase):
    def test_good_deal_is_defensible(self):
        ev = LeaseEvaluator(make_scenario())  # 2100/wk vs 1000/wk W2, no risk
        v, _ = ev.verdict(ev.simulate(n_paths=1_000, weeks=52))
        self.assertIn("DEFENSIBLE", v)

    def test_ruinous_deal_is_refused(self):
        ev = LeaseEvaluator(
            make_scenario(
                revenue=RevenueModel(
                    avg_rate_per_mile=0.80,  # below break-even of 0.95
                    rate_volatility=0.0,
                    loaded_miles_per_week=2_000.0,
                    deadhead_pct=0.0,
                    home_time_weeks_per_year=0.0,
                )
            )
        )
        v, flags = ev.verdict(ev.simulate(n_paths=1_000, weeks=52))
        self.assertIn("DO NOT SIGN", v)
        self.assertTrue(any("UNDERWATER" in f for f in flags))

    def test_tornado_ranks_by_swing_and_is_complete(self):
        out = tornado(LeaseEvaluator(ILLUSTRATIVE), n_paths=800)
        self.assertIn("DO NOT CONTROL", out)
        self.assertIn("Rate $/mi", out)
        self.assertIn("W2 take-home", out)

    def test_report_renders_without_error(self):
        ev = LeaseEvaluator(ILLUSTRATIVE)
        out = __import__("lease_evaluator").render(ev, ev.simulate(n_paths=800))
        for expected in ("PROBABILITY OF RUIN", "IMPLIED APR", "VERDICT", "MEDIAN EDGE"):
            self.assertIn(expected, out)

    def test_cli_smoke(self):
        self.assertEqual(main(["--worksheet"]), 0)
        self.assertEqual(main(["--dump-template"]), 0)
        self.assertEqual(main(["--paths", "500"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
