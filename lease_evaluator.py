"""
lease_evaluator.py — Truck-as-a-trading-position risk engine.

WHAT THIS IS FOR
----------------
A lease-purchase contract is an asymmetric position. The payment is FIXED and
falls due every week regardless of whether the truck turns a wheel. The revenue
is STOCHASTIC and collapses to zero during breakdowns, home time, and soft
freight weeks.

Cost-per-mile arithmetic hides this completely. It reports an average and says
nothing about the distribution. An owner-operator does not go bankrupt on the
mean — he goes bankrupt in the left tail, when a $9k engine event lands in the
same month as a rate trough and the payment is still due.

WHAT THIS IS NOT FOR
--------------------
This tool does NOT tell you whether to sign. It cannot. The verdict it prints is
manufactured entirely by the numbers you feed it, and those numbers swing the
answer by six figures. Run --tornado and you will see that ~70% of the outcome
variance lives in variables you do not control.

The tool's real job is to tell you WHICH FIVE NUMBERS DECIDE YOUR LIFE, so you
can go get the real ones instead of trusting a recruiter's arithmetic.

Use --worksheet to print exactly what to go collect.

THE THREE THINGS MOST MODELS GET WRONG, WHICH THIS ONE DOES NOT
---------------------------------------------------------------
1. PARAMETER UNCERTAINTY. You do not know the mean rate. You are guessing at it.
   A model that treats your guess as ground truth understates ruin risk badly.
   `rate_mean_uncertainty` draws the mean itself from a distribution, once per
   path. This is the difference between risk (known odds) and uncertainty
   (unknown odds). Lease-purchase failures live in the second category.

2. IMPLIED APR. A lease is financing wearing a costume. Discounting the actual
   cash flows against the truck's fair market value reveals the true interest
   rate. This is the number the contract is designed not to state.

3. THE OPPORTUNITY COST. The lease does not have to be profitable. It has to
   beat the W2 seat you already have, on a RISK-ADJUSTED basis, while you carry
   100% of the downside. Most do not.

Run:
    python lease_evaluator.py --all                  # everything, illustrative
    python lease_evaluator.py --worksheet            # what to go collect
    python lease_evaluator.py --dump-template        # blank scenario JSON
    python lease_evaluator.py --scenario deal.json --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

WEEKS_PER_YEAR = 52


# ==========================================================================
# BOUNDARY SCHEMAS
# Same doctrine as the SDE gateway: a malformed contract is a hostile payload.
# ==========================================================================


class LeaseTerms(BaseModel):
    """The fixed leg. This is due whether you roll or not. That is the trap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    weekly_payment: float = Field(gt=0)
    term_weeks: int = Field(gt=0, le=520)
    down_payment: float = Field(ge=0)
    balloon_payment: float = Field(ge=0, description="Final buyout to take title")
    truck_fair_market_value: float = Field(
        gt=0, description="What the truck is ACTUALLY worth. Required for APR."
    )
    maintenance_escrow_weekly: float = Field(ge=0, default=0.0)
    escrow_refundable: bool = Field(
        default=False, description="If False, escrow is a sunk cost, not savings."
    )
    early_termination_penalty: float = Field(ge=0, default=0.0)


class OperatingCosts(BaseModel):
    """The variable leg. Scales with miles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fuel_price_per_gal: float = Field(gt=0)
    mpg: float = Field(gt=0, le=12)
    maintenance_reserve_per_mile: float = Field(
        ge=0, description="Real reserve on a used truck is $0.12-0.20/mi"
    )
    insurance_weekly: float = Field(ge=0)
    eld_and_software_weekly: float = Field(ge=0, default=0.0)
    tolls_parking_weekly: float = Field(ge=0, default=0.0)
    plates_permits_annual: float = Field(ge=0, default=0.0)
    factoring_pct: float = Field(ge=0, le=0.10, default=0.0)
    dispatch_fee_pct: float = Field(ge=0, le=0.15, default=0.0)


class RevenueModel(BaseModel):
    """The stochastic leg. The recruiter will present this as a constant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    avg_rate_per_mile: float = Field(gt=0, description="GROSS linehaul $/loaded mile")
    rate_volatility: float = Field(
        ge=0, description="Week-to-week std dev of realized rate"
    )
    rate_mean_uncertainty: float = Field(
        ge=0,
        default=0.0,
        description=(
            "Std dev of your BELIEF about the mean rate. You do not know the true "
            "mean — you are estimating it. Set this to how wrong you could be. "
            "0.15-0.25 is honest for someone who has never run their own authority."
        ),
    )
    loaded_miles_per_week: float = Field(gt=0)
    miles_volatility: float = Field(ge=0, default=0.0)
    deadhead_pct: float = Field(ge=0, lt=0.5)
    home_time_weeks_per_year: float = Field(ge=0, lt=52, default=2.0)


class RiskModel(BaseModel):
    """The tail. This leg decides the outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    breakdown_prob_per_week: float = Field(ge=0, le=1)
    avg_breakdown_cost: float = Field(ge=0)
    breakdown_cost_volatility: float = Field(ge=0, default=0.0)
    avg_downtime_weeks: float = Field(
        ge=0, description="Payment still fires during this. That is the whole trap."
    )
    starting_cash_reserve: float = Field(ge=0, description="Ruin = this hits zero.")


class Alternative(BaseModel):
    """Opportunity cost. The lease must beat THIS, risk-adjusted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    w2_weekly_takehome: float = Field(ge=0, description="After-tax, driving for someone else")
    w2_weekly_volatility: float = Field(ge=0, default=0.0)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="Unnamed Deal", max_length=128)
    lease: LeaseTerms
    costs: OperatingCosts
    revenue: RevenueModel
    risk: RiskModel
    alternative: Alternative

    @model_validator(mode="after")
    def _sanity(self) -> "Scenario":
        if self.lease.down_payment > self.risk.starting_cash_reserve:
            raise ValueError(
                "down_payment exceeds starting_cash_reserve — you cannot fund this deal."
            )
        return self


# ==========================================================================
# RESULT TYPES
# ==========================================================================


class CostBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fuel: float
    maintenance_reserve: float
    fixed_amortized: float
    factoring_and_dispatch: float
    total: float
    weekly_fixed: float
    total_miles_per_week: float


class SimResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    weeks: int
    paths: int
    p_ruin: float
    p_beat_w2: float
    p_negative: float
    net_median: float
    net_mean: float
    net_p5: float
    net_p95: float
    w2_median: float
    median_edge: float
    sharpe_vs_w2: float
    worst_drawdown_median: float


# ==========================================================================
# THE ENGINE
# ==========================================================================


class LeaseEvaluator:
    def __init__(self, scenario: Scenario, seed: int = 1337):
        self.s = scenario
        self.seed = seed

    # ---- deterministic layer --------------------------------------------

    def total_miles_per_week(self) -> float:
        r = self.s.revenue
        return r.loaded_miles_per_week / (1.0 - r.deadhead_pct)

    def cost_per_mile(self) -> CostBreakdown:
        s = self.s
        total_mi = self.total_miles_per_week()

        fuel = s.costs.fuel_price_per_gal / s.costs.mpg
        maint = s.costs.maintenance_reserve_per_mile

        weekly_fixed = (
            s.lease.weekly_payment
            + s.lease.maintenance_escrow_weekly
            + s.costs.insurance_weekly
            + s.costs.eld_and_software_weekly
            + s.costs.tolls_parking_weekly
            + s.costs.plates_permits_annual / WEEKS_PER_YEAR
        )

        gross = s.revenue.avg_rate_per_mile * s.revenue.loaded_miles_per_week
        pct_weekly = gross * (s.costs.factoring_pct + s.costs.dispatch_fee_pct)

        fixed_cpm = weekly_fixed / total_mi
        pct_cpm = pct_weekly / total_mi

        return CostBreakdown(
            fuel=fuel,
            maintenance_reserve=maint,
            fixed_amortized=fixed_cpm,
            factoring_and_dispatch=pct_cpm,
            total=fuel + maint + fixed_cpm + pct_cpm,
            weekly_fixed=weekly_fixed,
            total_miles_per_week=total_mi,
        )

    def breakeven_rate_per_mile(self) -> float:
        """Gross loaded rate required just to not lose money. The floor."""
        s = self.s
        cb = self.cost_per_mile()
        variable_weekly = (cb.fuel + cb.maintenance_reserve) * cb.total_miles_per_week
        pct_take = s.costs.factoring_pct + s.costs.dispatch_fee_pct
        return (cb.weekly_fixed + variable_weekly) / (
            s.revenue.loaded_miles_per_week * (1.0 - pct_take)
        )

    def deterministic_weekly_net(self, rate: Optional[float] = None) -> float:
        """Expected weekly net at a given rate, ignoring all risk. The lie."""
        s = self.s
        rate = s.revenue.avg_rate_per_mile if rate is None else rate
        cb = self.cost_per_mile()
        pct_take = s.costs.factoring_pct + s.costs.dispatch_fee_pct
        gross = rate * s.revenue.loaded_miles_per_week * (1.0 - pct_take)
        variable = (cb.fuel + cb.maintenance_reserve) * cb.total_miles_per_week
        return gross - variable - cb.weekly_fixed

    # ---- implied APR ----------------------------------------------------

    def implied_apr(self, include_escrow: bool = False) -> Optional[float]:
        """The interest rate the contract does not state.

        A lease-purchase is a loan of (FMV - down_payment), repaid via weekly
        payments plus a balloon. Solving for the discount rate that equates
        those cash flows to the loan principal gives the true cost of the money.

        Returns annualized APR, or None if the deal has no positive principal
        (i.e. you are paying more down than the truck is worth — a red flag in
        itself, surfaced separately).
        """
        s = self.s
        principal = s.lease.truck_fair_market_value - s.lease.down_payment
        if principal <= 0:
            return None

        pmt = s.lease.weekly_payment + (
            s.lease.maintenance_escrow_weekly
            if (include_escrow and not s.lease.escrow_refundable)
            else 0.0
        )
        n = s.lease.term_weeks
        balloon = s.lease.balloon_payment

        def npv(weekly_rate: float) -> float:
            if weekly_rate <= -0.999999:
                return float("inf")
            if abs(weekly_rate) < 1e-12:
                pv = pmt * n + balloon
            else:
                annuity = (1.0 - (1.0 + weekly_rate) ** -n) / weekly_rate
                pv = pmt * annuity + balloon * (1.0 + weekly_rate) ** -n
            return pv - principal

        lo, hi = -0.5 / WEEKS_PER_YEAR, 5.0 / WEEKS_PER_YEAR
        if npv(lo) < 0:
            return None  # payments never repay principal even at ~0% — degenerate
        if npv(hi) > 0:
            return float("inf")  # APR beyond 500%; the contract is predatory

        for _ in range(200):
            mid = (lo + hi) / 2.0
            if npv(mid) > 0:
                lo = mid
            else:
                hi = mid
        weekly = (lo + hi) / 2.0
        return (1.0 + weekly) ** WEEKS_PER_YEAR - 1.0

    def equity_at_term(self) -> dict:
        s = self.s
        payments = s.lease.weekly_payment * s.lease.term_weeks
        escrow = s.lease.maintenance_escrow_weekly * s.lease.term_weeks
        sunk_escrow = 0.0 if s.lease.escrow_refundable else escrow
        all_in = s.lease.down_payment + payments + sunk_escrow + s.lease.balloon_payment
        return {
            "down_payment": s.lease.down_payment,
            "total_payments": payments,
            "escrow_at_risk": sunk_escrow,
            "balloon": s.lease.balloon_payment,
            "all_in_cost": all_in,
            "fair_market_value": s.lease.truck_fair_market_value,
            "premium_over_fmv": all_in - s.lease.truck_fair_market_value,
            "premium_pct": (all_in / s.lease.truck_fair_market_value - 1.0),
        }

    # ---- stochastic layer -----------------------------------------------

    def simulate(self, n_paths: int = 20_000, weeks: Optional[int] = None) -> SimResult:
        """Monte Carlo over the position.

        Critical mechanics:
          * The mean rate is DRAWN PER PATH, not assumed known. This is the
            single most important line in the file. You do not know the market.
          * During breakdown/home-time, revenue is zero but fixed costs fire.
          * Ruin is an ABSORBING state — once cash goes negative you are done,
            you do not get to recover on paper.
        """
        import numpy as np  # deferred: --worksheet must run without it
        s = self.s
        weeks = weeks or min(WEEKS_PER_YEAR, s.lease.term_weeks)
        rng = np.random.default_rng(self.seed)

        cb = self.cost_per_mile()
        var_cpm = cb.fuel + cb.maintenance_reserve
        pct_take = s.costs.factoring_pct + s.costs.dispatch_fee_pct
        deadhead_mult = 1.0 / (1.0 - s.revenue.deadhead_pct)

        # PARAMETER UNCERTAINTY: draw the true mean rate once per path.
        path_mean_rate = rng.normal(
            s.revenue.avg_rate_per_mile, s.revenue.rate_mean_uncertainty, n_paths
        )

        cash = np.full(n_paths, s.risk.starting_cash_reserve - s.lease.down_payment)
        peak = cash.copy()
        max_dd = np.zeros(n_paths)
        ruined = np.zeros(n_paths, dtype=bool)

        # Down payment is real money out the door — it belongs in the P&L.
        cumulative_net = np.full(n_paths, -s.lease.down_payment)
        weekly_nets = np.zeros((n_paths, weeks))
        downtime_left = np.zeros(n_paths)
        p_home = s.revenue.home_time_weeks_per_year / WEEKS_PER_YEAR

        for w in range(weeks):
            broke = rng.random(n_paths) < s.risk.breakdown_prob_per_week
            repair = np.where(
                broke,
                np.maximum(
                    0.0,
                    rng.normal(
                        s.risk.avg_breakdown_cost,
                        s.risk.breakdown_cost_volatility,
                        n_paths,
                    ),
                ),
                0.0,
            )
            downtime_left = np.where(
                broke, np.maximum(downtime_left, s.risk.avg_downtime_weeks), downtime_left
            )

            # fractional downtime handled properly: lose a FRACTION of the week
            lost = np.minimum(1.0, downtime_left)
            at_home = rng.random(n_paths) < p_home
            productivity = np.where(at_home, 0.0, 1.0 - lost)

            rate = np.maximum(
                0.0, rng.normal(path_mean_rate, s.revenue.rate_volatility, n_paths)
            )
            miles = np.maximum(
                0.0,
                rng.normal(
                    s.revenue.loaded_miles_per_week, s.revenue.miles_volatility, n_paths
                ),
            ) * productivity

            net_rev = rate * miles * (1.0 - pct_take)
            variable = miles * deadhead_mult * var_cpm
            net = net_rev - variable - cb.weekly_fixed - repair  # fixed ALWAYS fires

            cash += net
            cumulative_net += net
            weekly_nets[:, w] = net

            peak = np.maximum(peak, cash)
            max_dd = np.maximum(max_dd, peak - cash)
            ruined |= cash < 0

            downtime_left = np.maximum(0.0, downtime_left - 1.0)

        w2_weekly = rng.normal(
            s.alternative.w2_weekly_takehome,
            s.alternative.w2_weekly_volatility,
            (n_paths, weeks),
        )
        w2_total = w2_weekly.sum(axis=1)

        excess = weekly_nets - w2_weekly
        mu, sigma = float(excess.mean()), float(excess.std())
        if sigma > 1e-9:
            sharpe = mu / sigma * np.sqrt(WEEKS_PER_YEAR)
        else:
            # Degenerate case: zero variance. A riskless positive excess return is
            # an INFINITE Sharpe, not a zero one. Returning 0.0 here would cause the
            # verdict logic to punish a free lunch as "poor risk-adjusted return."
            sharpe = 0.0 if abs(mu) < 1e-9 else float(np.sign(mu)) * float("inf")

        return SimResult(
            weeks=weeks,
            paths=n_paths,
            p_ruin=float(ruined.mean()),
            p_beat_w2=float((cumulative_net > w2_total).mean()),
            p_negative=float((cumulative_net < 0).mean()),
            net_median=float(np.median(cumulative_net)),
            net_mean=float(cumulative_net.mean()),
            net_p5=float(np.percentile(cumulative_net, 5)),
            net_p95=float(np.percentile(cumulative_net, 95)),
            w2_median=float(np.median(w2_total)),
            median_edge=float(np.median(cumulative_net) - np.median(w2_total)),
            sharpe_vs_w2=float(sharpe),
            worst_drawdown_median=float(np.median(max_dd)),
        )

    # ---- solvers ---------------------------------------------------------

    def solve_indifference_rate(self, n_paths: int = 6_000, tol: float = 0.005) -> float:
        """The rate at which you are INDIFFERENT between the lease and the W2 seat.

        Below this number, you are paying for the privilege of taking on risk.
        This is the single most actionable output in the file: it converts a
        vague 'is this a good deal' into 'do loads in my lane clear $X.XX.'
        """
        lo, hi = 0.50, 6.00
        for _ in range(40):
            if hi - lo < tol:
                break
            mid = (lo + hi) / 2.0
            s2 = self.s.model_copy(
                update={"revenue": self.s.revenue.model_copy(update={"avg_rate_per_mile": mid})},
                deep=True,
            )
            if LeaseEvaluator(s2, self.seed).simulate(n_paths=n_paths).median_edge < 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    def solve_indifference_miles(self, n_paths: int = 6_000, tol: float = 10.0) -> float:
        """Loaded miles/week required to match the W2 seat at the assumed rate."""
        lo, hi = 200.0, 5_000.0
        for _ in range(40):
            if hi - lo < tol:
                break
            mid = (lo + hi) / 2.0
            s2 = self.s.model_copy(
                update={
                    "revenue": self.s.revenue.model_copy(update={"loaded_miles_per_week": mid})
                },
                deep=True,
            )
            if LeaseEvaluator(s2, self.seed).simulate(n_paths=n_paths).median_edge < 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    # ---- contract scanner -------------------------------------------------

    def contract_red_flags(self) -> list[str]:
        """Structural defects in the CONTRACT, independent of market outcomes.

        These do not depend on any assumption about rates. They are properties
        of the paper itself, and they are the part you can actually verify today.
        """
        s, eq, flags = self.s, self.equity_at_term(), []

        apr = self.implied_apr(include_escrow=True)
        if apr is None:
            flags.append(
                "DEGENERATE FINANCING — down payment meets or exceeds the truck's "
                "market value, or payments never retire the principal. Read again."
            )
        elif apr == float("inf"):
            flags.append("IMPLIED APR EXCEEDS 500%. This is not financing. It is a rental.")
        elif apr > 0.30:
            flags.append(f"PREDATORY APR — implied {apr:.1%} effective. Credit cards are cheaper.")
        elif apr > 0.18:
            flags.append(f"HIGH APR — implied {apr:.1%} effective. Shop conventional financing.")

        if eq["premium_pct"] > 0.75:
            flags.append(
                f"YOU PAY {eq['premium_pct']:.0%} OVER MARKET — ${eq['all_in_cost']:,.0f} "
                f"all-in for a ${eq['fair_market_value']:,.0f} truck."
            )

        if not s.lease.escrow_refundable and s.lease.maintenance_escrow_weekly > 0:
            flags.append(
                f"NON-REFUNDABLE ESCROW — ${eq['escrow_at_risk']:,.0f} over the term is a "
                "sunk cost dressed up as savings."
            )

        if s.lease.balloon_payment > 0.25 * s.lease.truck_fair_market_value:
            flags.append(
                f"LARGE BALLOON ${s.lease.balloon_payment:,.0f} — you own nothing until it clears."
            )

        if s.lease.early_termination_penalty > 5_000:
            flags.append(
                f"EXIT PENALTY ${s.lease.early_termination_penalty:,.0f} — you are locked in. "
                "A deal you cannot leave is a deal you should not enter."
            )

        weeks_of_reserve = s.risk.starting_cash_reserve - s.lease.down_payment
        weekly_fixed = self.cost_per_mile().weekly_fixed
        if weekly_fixed > 0 and weeks_of_reserve / weekly_fixed < 6:
            flags.append(
                f"THIN RESERVE — after the down payment you hold "
                f"{weeks_of_reserve / weekly_fixed:.1f} weeks of fixed costs. "
                "One engine event ends this."
            )

        return flags

    # ---- verdict ----------------------------------------------------------

    def verdict(self, sim: SimResult) -> tuple[str, list[str]]:
        s = self.s
        flags = list(self.contract_red_flags())
        be = self.breakeven_rate_per_mile()
        margin = s.revenue.avg_rate_per_mile - be

        if sim.p_ruin > 0.20:
            flags.append(f"RUIN RISK {sim.p_ruin:.0%} — better than 1-in-5 you run out of cash.")
        if margin < 0:
            flags.append(
                f"UNDERWATER AT THE MEAN — break-even ${be:.2f}/mi vs assumed "
                f"${s.revenue.avg_rate_per_mile:.2f}/mi."
            )
        elif margin < 0.15:
            flags.append(f"RAZOR MARGIN — ${margin:.2f}/mi over break-even. A fuel spike erases it.")
        if sim.p_beat_w2 < 0.50:
            flags.append(
                f"LOSES TO W2 — {sim.p_beat_w2:.0%} chance you beat the job you already "
                "have, while carrying 100% of the risk."
            )
        if sim.sharpe_vs_w2 < 0.5:
            flags.append(
                f"POOR RISK-ADJUSTED RETURN — Sharpe {sim.sharpe_vs_w2:.2f} vs W2. "
                "You are not being paid for the volatility you absorb."
            )

        if sim.p_ruin > 0.25 or margin < 0 or sim.p_beat_w2 < 0.40:
            return "DO NOT SIGN — on these inputs", flags
        if sim.p_ruin > 0.10 or sim.sharpe_vs_w2 < 0.5:
            return "RENEGOTIATE OR WALK — on these inputs", flags
        if sim.p_beat_w2 > 0.65 and sim.sharpe_vs_w2 > 0.8:
            return "DEFENSIBLE — if and only if the inputs are real", flags
        return "MARGINAL — the edge does not justify the risk", flags


# ==========================================================================
# ANALYSIS
# ==========================================================================

TORNADO_INPUTS = [
    # label,               group,         field,                          low,   high,  you_control_it
    ("Rate $/mi",          "revenue",     "avg_rate_per_mile",            1.90,  2.45,  False),
    ("Loaded miles/wk",    "revenue",     "loaded_miles_per_week",        1900,  2600,  True),
    ("W2 take-home $/wk",  "alternative", "w2_weekly_takehome",           1000,  1450,  False),
    ("Fuel $/gal",         "costs",       "fuel_price_per_gal",           3.30,  4.50,  False),
    ("MPG",                "costs",       "mpg",                          5.80,  7.20,  True),
    ("Deadhead %",         "revenue",     "deadhead_pct",                 0.06,  0.20,  True),
    ("Maintenance $/mi",   "costs",       "maintenance_reserve_per_mile", 0.10,  0.22,  False),
    ("Lease payment $/wk", "lease",       "weekly_payment",                525,   775,  True),
    ("Breakdown prob/wk",  "risk",        "breakdown_prob_per_week",      0.01,  0.05,  False),
    ("Rate uncertainty",   "revenue",     "rate_mean_uncertainty",        0.00,  0.25,  False),
]


def tornado(ev: LeaseEvaluator, n_paths: int = 10_000) -> str:
    """Which inputs decide the outcome — and do you control them?

    This is the most important function in the file. The verdict is manufactured
    by whatever you typed in. THIS tells you which numbers are load-bearing.
    """
    import numpy as np  # deferred: --worksheet must run without it

    base = ev.s

    def edge(sc: Scenario) -> float:
        return LeaseEvaluator(sc, ev.seed).simulate(n_paths=n_paths).median_edge

    rows = []
    for label, grp, field, lo, hi, ctrl in TORNADO_INPUTS:
        vals = []
        for v in (lo, hi):
            try:
                sub = getattr(base, grp).model_copy(update={field: v})
                vals.append(edge(base.model_copy(update={grp: sub}, deep=True)))
            except Exception:
                vals.append(float("nan"))
        if any(np.isnan(vals)):
            continue
        rows.append((label, lo, hi, vals[0], vals[1], abs(vals[1] - vals[0]), ctrl))

    rows.sort(key=lambda r: -r[5])
    span = max((r[5] for r in rows), default=1.0) or 1.0

    L = ["", "  WHICH NUMBERS ACTUALLY DECIDE THIS", "  " + "-" * 68]
    L.append("  Swing in median edge vs. W2 across a plausible range for each input.")
    L.append("  [YOU] you can influence it.    [MKT] the market decides, not you.")
    L.append("")
    for label, lo, hi, el, eh, sw, ctrl in rows:
        bar = "#" * max(1, int(round(sw / span * 22)))
        L.append(f"  {label:<20}${sw:>9,.0f}  {bar:<23}{'[YOU]' if ctrl else '[MKT]'}")

    total = sum(r[5] for r in rows)
    uncontrolled = sum(r[5] for r in rows if not r[6])
    pct = uncontrolled / total if total else 0.0
    L.append("")
    L.append(f"  >>> {pct:.0%} of the outcome sits in variables you DO NOT CONTROL.")
    L.append("")
    L.append("  Get the REAL values for the top three before forming any opinion.")
    return "\n".join(L) + "\n"


def sweep_rate(ev: LeaseEvaluator, n_paths: int = 8_000) -> str:
    base = ev.s.revenue.avg_rate_per_mile
    L = ["", "  RATE SENSITIVITY — the market sets this, not you", "  " + "-" * 68]
    L.append(f"    {'$/mi':>6}{'P(ruin)':>11}{'P(beat W2)':>13}{'Median edge':>15}")
    for delta in (-0.40, -0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30):
        rate = round(base + delta, 2)
        if rate <= 0:
            continue
        s2 = ev.s.model_copy(
            update={"revenue": ev.s.revenue.model_copy(update={"avg_rate_per_mile": rate})},
            deep=True,
        )
        sim = LeaseEvaluator(s2, ev.seed).simulate(n_paths=n_paths)
        mark = "  <-- assumed" if abs(delta) < 1e-9 else ""
        L.append(
            f"    ${rate:>5.2f}{sim.p_ruin:>10.1%}{sim.p_beat_w2:>12.1%}"
            f"{sim.median_edge:>14,.0f}{mark}"
        )
    return "\n".join(L) + "\n"


# ==========================================================================
# REPORT
# ==========================================================================


def render(ev: LeaseEvaluator, sim: SimResult) -> str:
    import numpy as np  # deferred: --worksheet must run without it

    s = ev.s
    cb = ev.cost_per_mile()
    be = ev.breakeven_rate_per_mile()
    eq = ev.equity_at_term()
    apr = ev.implied_apr(include_escrow=True)
    v, flags = ev.verdict(sim)
    W = 74
    L: list[str] = ["=" * W, f"  LEASE POSITION ANALYSIS — {s.label}".upper()[: W - 2], "=" * W]

    L.append("\n  COST PER MILE (all miles, incl. deadhead)")
    L.append("  " + "-" * (W - 4))
    for k, lbl in (
        ("fuel", "Fuel"),
        ("maintenance_reserve", "Maintenance reserve"),
        ("fixed_amortized", "Fixed, amortized"),
        ("factoring_and_dispatch", "Factoring + dispatch"),
    ):
        L.append(f"    {lbl:<34} ${getattr(cb, k):>8.3f}")
    L.append(f"    {'TOTAL COST PER MILE':<34} ${cb.total:>8.3f}")

    L.append("\n  THE DETERMINISTIC FLOOR (what the recruiter shows you)")
    L.append("  " + "-" * (W - 4))
    L.append(f"    {'Break-even gross rate':<34} ${be:>8.2f} /loaded mi")
    L.append(f"    {'Your assumed rate':<34} ${s.revenue.avg_rate_per_mile:>8.2f} /loaded mi")
    L.append(f"    {'Apparent margin':<34} ${s.revenue.avg_rate_per_mile - be:>8.2f} /loaded mi")
    L.append(f"    {'Fixed cost due EVERY week':<34} ${cb.weekly_fixed:>8.0f}   <- even at zero miles")

    L.append("\n  THE CONTRACT (independent of any market assumption)")
    L.append("  " + "-" * (W - 4))
    if apr is None:
        L.append(f"    {'Implied APR':<34} {'DEGENERATE':>9}")
    elif apr == float("inf"):
        L.append(f"    {'Implied APR':<34} {'>500%':>9}")
    else:
        L.append(f"    {'IMPLIED APR (incl. sunk escrow)':<34} {apr:>9.1%}")
    L.append(f"    {'Truck fair market value':<34} ${eq['fair_market_value']:>10,.0f}")
    L.append(f"    {'All-in cost to own it':<34} ${eq['all_in_cost']:>10,.0f}")
    L.append(f"    {'Premium over market':<34} ${eq['premium_over_fmv']:>10,.0f}  ({eq['premium_pct']:+.0%})")

    L.append(f"\n  THE DISTRIBUTION ({sim.paths:,} paths x {sim.weeks} weeks)")
    L.append("  " + "-" * (W - 4))
    L.append(f"    {'PROBABILITY OF RUIN':<34} {sim.p_ruin:>9.1%}   <- cash hits zero")
    L.append(f"    {'Probability you beat W2':<34} {sim.p_beat_w2:>9.1%}")
    L.append(f"    {'Probability of a losing year':<34} {sim.p_negative:>9.1%}")
    sharpe_txt = (
        f"{sim.sharpe_vs_w2:>9.2f}"
        if np.isfinite(sim.sharpe_vs_w2)
        else f"{'riskless' if sim.sharpe_vs_w2 > 0 else 'hopeless':>9}"
    )
    L.append(f"    {'Sharpe ratio vs. W2':<34} {sharpe_txt}")
    L.append(f"    {'Median worst drawdown':<34} ${sim.worst_drawdown_median:>10,.0f}")
    L.append("")
    L.append(f"    {'Median net (lease)':<34} ${sim.net_median:>10,.0f}")
    L.append(f"    {'Median net (stay W2)':<34} ${sim.w2_median:>10,.0f}")
    L.append(f"    {'MEDIAN EDGE':<34} ${sim.median_edge:>10,.0f}")
    L.append("")
    L.append(f"    {'Bad year (5th pctile)':<34} ${sim.net_p5:>10,.0f}")
    L.append(f"    {'Good year (95th pctile)':<34} ${sim.net_p95:>10,.0f}")

    L.append("\n  WHAT YOU ACTUALLY NEED (solved, not guessed)")
    L.append("  " + "-" * (W - 4))
    r_star = ev.solve_indifference_rate()
    m_star = ev.solve_indifference_miles()
    L.append(f"    {'Rate to merely MATCH the W2 seat':<34} ${r_star:>8.2f} /loaded mi")
    L.append(f"    {'Miles/wk to match at assumed rate':<34} {m_star:>9,.0f} loaded mi")
    L.append("")
    L.append("    Below these lines you are paying for the privilege of taking risk.")

    if flags:
        L.append("\n  RED FLAGS")
        L.append("  " + "-" * (W - 4))
        for f in flags:
            L.append(f"    [!] {f}")

    L.append("\n" + "=" * W)
    L.append(f"  VERDICT: {v}")
    L.append("=" * W)
    L.append(
        "\n  This verdict is manufactured by the numbers you typed in. It is not\n"
        "  evidence. Run --tornado to see which inputs actually decide it, then go\n"
        "  get those numbers from the CONTRACT and from REAL settlement statements.\n"
    )
    return "\n".join(L)


from worksheet import WORKSHEET  # zero-dep module; see worksheet.py


# ==========================================================================
# ILLUSTRATIVE DEFAULT — THESE ARE INVENTED NUMBERS, NOT A REAL CONTRACT
# ==========================================================================

ILLUSTRATIVE = Scenario(
    label="Used Cascadia lease-purchase (ILLUSTRATIVE — numbers are invented)",
    lease=LeaseTerms(
        weekly_payment=650.0,
        term_weeks=208,
        down_payment=5_000.0,
        balloon_payment=18_000.0,
        truck_fair_market_value=65_000.0,
        maintenance_escrow_weekly=150.0,
        escrow_refundable=False,
        early_termination_penalty=0.0,
    ),
    costs=OperatingCosts(
        fuel_price_per_gal=3.85,
        mpg=6.5,
        maintenance_reserve_per_mile=0.15,
        insurance_weekly=250.0,
        eld_and_software_weekly=35.0,
        tolls_parking_weekly=75.0,
        plates_permits_annual=2_200.0,
        factoring_pct=0.03,
    ),
    revenue=RevenueModel(
        avg_rate_per_mile=2.10,
        rate_volatility=0.35,
        rate_mean_uncertainty=0.18,
        loaded_miles_per_week=2_200.0,
        miles_volatility=450.0,
        deadhead_pct=0.12,
        home_time_weeks_per_year=3.0,
    ),
    risk=RiskModel(
        breakdown_prob_per_week=0.03,
        avg_breakdown_cost=3_500.0,
        breakdown_cost_volatility=2_500.0,
        avg_downtime_weeks=1.0,
        starting_cash_reserve=10_000.0,
    ),
    alternative=Alternative(w2_weekly_takehome=1_250.0, w2_weekly_volatility=150.0),
)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Price a lease-purchase like the trading position it is.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--scenario", type=Path, help="JSON file with your REAL contract terms")
    p.add_argument("--paths", type=int, default=20_000)
    p.add_argument("--tornado", action="store_true", help="Which inputs decide the outcome")
    p.add_argument("--sweep-rate", action="store_true", help="Rate sensitivity table")
    p.add_argument("--all", action="store_true", help="Full report + tornado + sweep")
    p.add_argument("--worksheet", action="store_true", help="What to go collect")
    p.add_argument("--dump-template", action="store_true", help="Emit a scenario JSON template")
    a = p.parse_args(argv)

    if a.worksheet:
        print(WORKSHEET)
        return 0
    if a.dump_template:
        print(json.dumps(ILLUSTRATIVE.model_dump(), indent=2))
        return 0

    if a.scenario:
        scenario = Scenario.model_validate_json(a.scenario.read_text())
    else:
        scenario = ILLUSTRATIVE
        print("\n  [!] No --scenario supplied. Using INVENTED numbers.")
        print("      These are not anyone's real terms. Run --worksheet.\n")

    ev = LeaseEvaluator(scenario)
    sim = ev.simulate(n_paths=a.paths)
    print(render(ev, sim))
    if a.tornado or a.all:
        print(tornado(ev))
    if a.sweep_rate or a.all:
        print(sweep_rate(ev))
    return 0


if __name__ == "__main__":
    sys.exit(main())
