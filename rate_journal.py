"""
rate_journal.py — Turn observed loads into the parameters the lease model needs.

WHY THIS EXISTS
---------------
`lease_evaluator.py` needs four numbers it cannot invent for you:

    avg_rate_per_mile        what your lanes actually pay
    rate_volatility          how much that swings week to week
    rate_mean_uncertainty    HOW WRONG YOUR ESTIMATE OF THE AVERAGE MIGHT BE
    loaded_miles_per_week    what you actually turn

Guess at these and the model produces confident nonsense. This tool computes them
from real observations, and — more importantly — tells you **when you have logged
enough loads to trust the answer.**

THE POINT MOST PEOPLE MISS
--------------------------
Everyone eyeballs an average. Almost nobody asks how *wrong* that average could be.

With n weeks of observations, the standard error of the mean is:

    SEM = sigma / sqrt(n)

After 3 weeks your estimate of the average rate might be off by 20 cents a mile.
Twenty cents is the difference between a deal that beats your job and a deal that
destroys you. **You do not have an opinion yet. You have a small sample.**

This tool reports the 95% confidence interval on your average rate and tells you
how many more weeks you need to shrink it to a width you can actually bet on.

WHAT THIS TOOL WILL NOT DO
--------------------------
It will not scrape DAT or Truckstop. Those are paid, authenticated services whose
terms prohibit it, there is no free public load-board API, and getting your account
banned is a bad way to start. See HOW TO GET THE DATA below.

Run:
    python rate_journal.py log --origin "Dallas TX" --dest "Atlanta GA" \\
        --loaded-miles 780 --deadhead-miles 65 --rate 1850 --date 2026-07-08

    python rate_journal.py import-csv dat_export.csv
    python rate_journal.py stats
    python rate_journal.py emit --deal deal.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_JOURNAL = Path("rate_journal.jsonl")

# Rough two-sided 95% t-multipliers by degrees of freedom (n-1). With a handful of
# weeks the normal approximation (1.96) is badly optimistic, and being optimistic is
# the entire failure mode this tool exists to prevent.
_T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31,
        9: 2.26, 10: 2.23, 11: 2.20, 12: 2.18, 13: 2.16, 14: 2.14, 15: 2.13,
        16: 2.12, 17: 2.11, 18: 2.10, 19: 2.09, 20: 2.09, 25: 2.06, 30: 2.04,
        40: 2.02, 60: 2.00}


def t95(df: int) -> float:
    if df <= 0:
        return float("inf")
    if df in _T95:
        return _T95[df]
    keys = sorted(_T95)
    for k in keys:
        if df < k:
            return _T95[k]
    return 1.96


class LoadObservation(BaseModel):
    """One real load you saw, with a real rate on it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    date: date
    origin: str = Field(min_length=2, max_length=64)
    dest: str = Field(min_length=2, max_length=64)
    loaded_miles: float = Field(gt=0)
    deadhead_miles: float = Field(ge=0, default=0.0)
    rate_total: float = Field(gt=0, description="GROSS linehaul dollars for the load")
    equipment: str = Field(default="dry_van", max_length=32)
    source: str = Field(default="manual", max_length=32)
    note: str = Field(default="", max_length=256)

    @field_validator("date", mode="before")
    @classmethod
    def _parse_date(cls, v):
        if isinstance(v, str):
            return datetime.strptime(v.strip(), "%Y-%m-%d").date()
        return v

    @property
    def rate_per_mile(self) -> float:
        """$/loaded mile. This is the number the industry quotes."""
        return self.rate_total / self.loaded_miles

    @property
    def all_in_rate_per_mile(self) -> float:
        """$/total mile including deadhead. This is what you actually earn.

        The gap between these two is where owner-operators quietly lose money."""
        return self.rate_total / (self.loaded_miles + self.deadhead_miles)

    def iso_week(self) -> str:
        y, w, _ = self.date.isocalendar()
        return f"{y}-W{w:02d}"


class Journal:
    """Append-only JSONL. No database, no schema migration, greppable with your eyes."""

    def __init__(self, path: Path = DEFAULT_JOURNAL):
        self.path = path

    def load(self) -> list[LoadObservation]:
        if not self.path.exists():
            return []
        out = []
        for i, line in enumerate(self.path.read_text().splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(LoadObservation.model_validate_json(line))
            except Exception as e:
                print(f"  [!] skipping malformed line {i}: {e}", file=sys.stderr)
        return sorted(out, key=lambda o: o.date)

    def append(self, obs: LoadObservation) -> None:
        with self.path.open("a") as f:
            f.write(obs.model_dump_json() + "\n")

    def append_many(self, obs: list[LoadObservation]) -> int:
        with self.path.open("a") as f:
            for o in obs:
                f.write(o.model_dump_json() + "\n")
        return len(obs)


class Estimates(BaseModel):
    """Exactly the parameters lease_evaluator.py asks for — plus how much to
    trust them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_loads: int
    n_weeks: int
    span_days: int

    avg_rate_per_mile: float
    rate_volatility: float
    rate_mean_uncertainty: float  # SEM: sigma / sqrt(n)
    ci95_low: float
    ci95_high: float
    ci95_width: float

    loaded_miles_per_week: float
    miles_volatility: float
    deadhead_pct: float

    revenue_weighted_rpm: float
    all_in_rpm: float

    weeks_needed_for_10c: int
    weeks_needed_for_5c: int


def estimate(obs: list[LoadObservation]) -> Optional[Estimates]:
    """Aggregate loads into WEEKS, then estimate. The lease model runs weekly, so
    the parameters must be weekly, not per-load. Averaging per-load rates would
    understate volatility badly — a slow week is not one bad load, it is five."""
    if len(obs) < 2:
        return None

    weeks: dict[str, list[LoadObservation]] = {}
    for o in obs:
        weeks.setdefault(o.iso_week(), []).append(o)

    week_rpm, week_miles = [], []
    for _, loads in sorted(weeks.items()):
        loaded = sum(x.loaded_miles for x in loads)
        revenue = sum(x.rate_total for x in loads)
        week_rpm.append(revenue / loaded)  # revenue-weighted within the week
        week_miles.append(loaded)

    n = len(week_rpm)
    mean_rpm = statistics.fmean(week_rpm)
    sd_rpm = statistics.stdev(week_rpm) if n >= 2 else 0.0
    sem = sd_rpm / math.sqrt(n) if n >= 2 else float("inf")
    half = t95(n - 1) * sem if n >= 2 else float("inf")

    tot_loaded = sum(o.loaded_miles for o in obs)
    tot_dead = sum(o.deadhead_miles for o in obs)
    tot_rev = sum(o.rate_total for o in obs)

    def weeks_for(target_half_width: float) -> int:
        """n such that t*sigma/sqrt(n) <= target. Iterate, since t depends on n."""
        if sd_rpm == 0:
            return n
        for k in range(2, 5_000):
            if t95(k - 1) * sd_rpm / math.sqrt(k) <= target_half_width:
                return k
        return 5_000

    return Estimates(
        n_loads=len(obs),
        n_weeks=n,
        span_days=(obs[-1].date - obs[0].date).days,
        avg_rate_per_mile=round(mean_rpm, 4),
        rate_volatility=round(sd_rpm, 4),
        rate_mean_uncertainty=round(sem, 4) if math.isfinite(sem) else 0.0,
        ci95_low=round(mean_rpm - half, 4) if math.isfinite(half) else 0.0,
        ci95_high=round(mean_rpm + half, 4) if math.isfinite(half) else 0.0,
        ci95_width=round(2 * half, 4) if math.isfinite(half) else 0.0,
        loaded_miles_per_week=round(statistics.fmean(week_miles), 1),
        miles_volatility=round(statistics.stdev(week_miles) if n >= 2 else 0.0, 1),
        deadhead_pct=round(tot_dead / (tot_loaded + tot_dead), 4) if tot_loaded else 0.0,
        revenue_weighted_rpm=round(tot_rev / tot_loaded, 4),
        all_in_rpm=round(tot_rev / (tot_loaded + tot_dead), 4),
        weeks_needed_for_10c=weeks_for(0.10),
        weeks_needed_for_5c=weeks_for(0.05),
    )


def render_stats(e: Estimates) -> str:
    W = 74
    L = ["=" * W, "  LANE RATE ESTIMATES — from your own observations", "=" * W]

    L.append(f"\n  SAMPLE")
    L.append("  " + "-" * (W - 4))
    L.append(f"    {'Loads logged':<34} {e.n_loads:>10}")
    L.append(f"    {'Weeks covered':<34} {e.n_weeks:>10}")
    L.append(f"    {'Calendar span':<34} {e.span_days:>10} days")

    L.append(f"\n  WHAT YOUR LANES PAY")
    L.append("  " + "-" * (W - 4))
    L.append(f"    {'Average rate (weekly mean)':<34} ${e.avg_rate_per_mile:>9.2f} /loaded mi")
    L.append(f"    {'Revenue-weighted':<34} ${e.revenue_weighted_rpm:>9.2f} /loaded mi")
    L.append(f"    {'ALL-IN (incl. deadhead)':<34} ${e.all_in_rpm:>9.2f} /total mi   <- what you EARN")
    L.append(f"    {'Week-to-week volatility':<34} ${e.rate_volatility:>9.2f}")
    L.append(f"    {'Deadhead':<34} {e.deadhead_pct:>10.1%}")
    L.append(f"    {'Loaded miles/week':<34} {e.loaded_miles_per_week:>10,.0f}")

    L.append(f"\n  HOW WRONG COULD YOU BE?")
    L.append("  " + "-" * (W - 4))
    L.append(f"    {'Std error of the mean':<34} ${e.rate_mean_uncertainty:>9.2f} /mi")
    L.append(f"    {'95% confidence interval':<34}  ${e.ci95_low:.2f} .. ${e.ci95_high:.2f}")
    L.append(f"    {'Interval WIDTH':<34} ${e.ci95_width:>9.2f} /mi")
    L.append("")

    if e.n_weeks < 4:
        L.append(f"    [!] {e.n_weeks} weeks is not a sample. It is an anecdote.")
    if e.ci95_width > 0.20:
        L.append(f"    [!] Your average could be off by ${e.ci95_width/2:.2f}/mi in either")
        L.append(f"        direction. On 2,200 loaded miles a week that is")
        L.append(f"        ${e.ci95_width/2 * 2200 * 52:,.0f} a year of pure uncertainty.")
        L.append(f"        YOU DO NOT HAVE AN ANSWER YET.")
    else:
        L.append(f"    [ok] Interval is tight enough to reason with.")

    L.append("")
    L.append(f"    Weeks needed to pin the mean within +/- $0.10/mi:  {e.weeks_needed_for_10c:>4}")
    L.append(f"    Weeks needed to pin the mean within +/- $0.05/mi:  {e.weeks_needed_for_5c:>4}")

    L.append(f"\n  FEED THESE TO THE LEASE MODEL")
    L.append("  " + "-" * (W - 4))
    L.append(f'    "avg_rate_per_mile":     {e.avg_rate_per_mile},')
    L.append(f'    "rate_volatility":       {e.rate_volatility},')
    L.append(f'    "rate_mean_uncertainty": {e.rate_mean_uncertainty},')
    L.append(f'    "loaded_miles_per_week": {e.loaded_miles_per_week},')
    L.append(f'    "miles_volatility":      {e.miles_volatility},')
    L.append(f'    "deadhead_pct":          {e.deadhead_pct}')
    L.append("")
    L.append("    Or run:  python rate_journal.py emit --deal deal.json")
    L.append("=" * W)
    return "\n".join(L)


# --------------------------------------------------------------------------
# CSV IMPORT — flexible, because every load board exports differently
# --------------------------------------------------------------------------

COLUMN_ALIASES = {
    "date": ["date", "pickup_date", "ship_date", "pu_date", "posted"],
    "origin": ["origin", "from", "pickup", "origin_city"],
    "dest": ["dest", "destination", "to", "delivery", "dest_city"],
    "loaded_miles": ["loaded_miles", "miles", "trip_miles", "distance", "loaded"],
    "deadhead_miles": ["deadhead_miles", "deadhead", "dh", "dh_miles", "empty_miles"],
    "rate_total": ["rate_total", "rate", "amount", "linehaul", "total_rate", "pay"],
    "equipment": ["equipment", "equip", "trailer", "trailer_type"],
}


def _match(header: list[str], field: str) -> Optional[str]:
    lower = {h.lower().strip().replace(" ", "_"): h for h in header}
    for alias in COLUMN_ALIASES[field]:
        if alias in lower:
            return lower[alias]
    return None


def import_csv(path: Path) -> tuple[list[LoadObservation], list[str]]:
    """Import a load-board or settlement CSV export. Tolerant of column naming;
    intolerant of bad data — a row that will not validate is reported, not
    silently coerced."""
    rows, errors = [], []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        mapping = {k: _match(header, k) for k in COLUMN_ALIASES}

        required = ["date", "origin", "dest", "loaded_miles", "rate_total"]
        missing = [k for k in required if not mapping[k]]
        if missing:
            raise ValueError(
                f"CSV is missing required columns: {missing}\n"
                f"  Found: {header}\n"
                f"  Accepted aliases: "
                + "; ".join(f"{k}={COLUMN_ALIASES[k]}" for k in missing)
            )

        for i, row in enumerate(reader, 2):
            try:
                def num(field, default=None):
                    col = mapping[field]
                    if not col or not row.get(col, "").strip():
                        return default
                    return float(str(row[col]).replace("$", "").replace(",", "").strip())

                rows.append(
                    LoadObservation(
                        date=row[mapping["date"]].strip()[:10],
                        origin=row[mapping["origin"]].strip(),
                        dest=row[mapping["dest"]].strip(),
                        loaded_miles=num("loaded_miles"),
                        deadhead_miles=num("deadhead_miles", 0.0) or 0.0,
                        rate_total=num("rate_total"),
                        equipment=(row.get(mapping["equipment"] or "", "") or "dry_van").strip()
                        or "dry_van",
                        source="csv",
                    )
                )
            except Exception as e:
                errors.append(f"row {i}: {e}")
    return rows, errors


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

HOW_TO_GET_DATA = """
================================================================================
  HOW TO GET REAL RATE DATA (you cannot scrape it, so do this instead)
================================================================================

  THE PROBLEM
  ----------------------------------------------------------------------------
  As a COMPANY DRIVER you never see the linehaul rate. You see your cents-per-
  mile. What the broker actually paid is invisible to you. So "just check the
  rates in your lanes" is not something you can do from the seat you are in.

  Load boards (DAT, Truckstop) are paid and authenticated. There is no free
  public API. Scraping them violates their terms and gets your account killed.

  WHAT TO DO INSTEAD, in order of leverage
  ----------------------------------------------------------------------------

  1. ASK THE RECRUITER FOR REAL SETTLEMENTS.  Cost: $0.  Do this first.

     "Show me the last 12 weeks of settlement statements from three drivers
      currently in this lease program. Names redacted is fine."

     A legitimate program will show you. A predatory one will deflect, offer
     averages instead, or tell you it is confidential.

     >>> THE DEFLECTION IS THE ANSWER. If they will not show you what current
         drivers actually cleared, you already know what you need to know.

  2. BUY ONE MONTH OF A LOAD BOARD.  Cost: ~$45-150.

     You are contemplating a ~$189,000 commitment. Spending $150 to see what
     your lanes actually pay is not an expense, it is the cheapest insurance
     you will ever buy. Export to CSV, then:

         python rate_journal.py import-csv export.csv

  3. TALK TO THREE OWNER-OPERATORS RUNNING YOUR LANES.  Cost: $0.

     Truck stops, forums, r/Truckers. Ask what they cleared per mile last
     month, all-in, after deadhead. Log each answer.

  4. PUBLIC MARKET INDICES.  Cost: $0.

     DAT and others publish free national and regional spot-rate averages.
     These are a BASELINE, not your lanes -- national averages hide the spread
     that decides your outcome. Use them to sanity-check, never to decide.

  Log whatever you get:

      python rate_journal.py log --origin "Dallas TX" --dest "Atlanta GA" \\
          --loaded-miles 780 --deadhead-miles 65 --rate 1850 --date 2026-07-08

  Then:  python rate_journal.py stats

================================================================================
"""


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Turn observed loads into lease-model parameters.")
    p.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    sub = p.add_subparsers(dest="cmd")

    lg = sub.add_parser("log", help="Log one observed load")
    lg.add_argument("--date", required=True, help="YYYY-MM-DD")
    lg.add_argument("--origin", required=True)
    lg.add_argument("--dest", required=True)
    lg.add_argument("--loaded-miles", type=float, required=True)
    lg.add_argument("--deadhead-miles", type=float, default=0.0)
    lg.add_argument("--rate", type=float, required=True, help="GROSS linehaul $ for the load")
    lg.add_argument("--equipment", default="dry_van")
    lg.add_argument("--note", default="")

    ic = sub.add_parser("import-csv", help="Import a load-board / settlement CSV export")
    ic.add_argument("csv_path", type=Path)

    sub.add_parser("stats", help="Estimate the parameters, and how much to trust them")
    sub.add_parser("list", help="Show every logged load")
    sub.add_parser("how", help="How to legitimately get rate data")

    em = sub.add_parser("emit", help="Write estimates into a lease deal.json")
    em.add_argument("--deal", type=Path, required=True)

    a = p.parse_args(argv)
    jr = Journal(a.journal)

    if a.cmd == "how" or a.cmd is None:
        print(HOW_TO_GET_DATA)
        return 0

    if a.cmd == "log":
        obs = LoadObservation(
            date=a.date, origin=a.origin, dest=a.dest,
            loaded_miles=a.loaded_miles, deadhead_miles=a.deadhead_miles,
            rate_total=a.rate, equipment=a.equipment, note=a.note, source="manual",
        )
        jr.append(obs)
        print(f"  logged: {obs.origin} -> {obs.dest}  "
              f"${obs.rate_per_mile:.2f}/loaded mi  "
              f"(${obs.all_in_rate_per_mile:.2f} all-in)")
        n = len(jr.load())
        print(f"  journal now holds {n} load{'s' if n != 1 else ''}.")
        return 0

    if a.cmd == "import-csv":
        rows, errors = import_csv(a.csv_path)
        n = jr.append_many(rows)
        print(f"  imported {n} loads from {a.csv_path}")
        if errors:
            print(f"  [!] {len(errors)} rows rejected (not silently coerced):")
            for e in errors[:10]:
                print(f"      {e}")
        return 0

    obs = jr.load()

    if a.cmd == "list":
        if not obs:
            print("  journal is empty.")
            return 0
        print(f"  {'DATE':<12}{'LANE':<30}{'$/LOADED':>10}{'$/ALL-IN':>10}")
        print("  " + "-" * 62)
        for o in obs:
            lane = f"{o.origin} -> {o.dest}"[:29]
            print(f"  {o.date.isoformat():<12}{lane:<30}"
                  f"{o.rate_per_mile:>10.2f}{o.all_in_rate_per_mile:>10.2f}")
        return 0

    est = estimate(obs)
    if est is None:
        print(f"\n  Not enough data. You have {len(obs)} load(s); you need at least 2,")
        print("  and realistically 4+ weeks before the number means anything.\n")
        print("  Run:  python rate_journal.py how\n")
        return 1

    if a.cmd == "stats":
        print(render_stats(est))
        return 0

    if a.cmd == "emit":
        if not a.deal.exists():
            print(f"  [!] {a.deal} does not exist. Create it first:")
            print("      python lease_evaluator.py --dump-template > deal.json")
            return 1
        deal = json.loads(a.deal.read_text())
        deal["revenue"].update(
            avg_rate_per_mile=est.avg_rate_per_mile,
            rate_volatility=est.rate_volatility,
            rate_mean_uncertainty=est.rate_mean_uncertainty,
            loaded_miles_per_week=est.loaded_miles_per_week,
            miles_volatility=est.miles_volatility,
            deadhead_pct=est.deadhead_pct,
        )
        a.deal.write_text(json.dumps(deal, indent=2) + "\n")
        print(f"  wrote {est.n_loads} loads / {est.n_weeks} weeks of real data into {a.deal}")
        if est.ci95_width > 0.20:
            print(f"  [!] but your 95% CI is still ${est.ci95_width:.2f}/mi wide.")
            print(f"      The model will run. It will not yet be trustworthy.")
        print(f"\n  Now:  python lease_evaluator.py --scenario {a.deal} --all")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
