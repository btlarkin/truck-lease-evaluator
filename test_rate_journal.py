"""
test_rate_journal.py — QA suite for the rate journal / parameter estimator.

The estimator's whole purpose is to stop you betting six figures on a small
sample. If IT is wrong, it does the opposite. So every statistic is verified
against a hand-computed value.

Run:
    python test_rate_journal.py
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from rate_journal import (
    Journal,
    LoadObservation,
    estimate,
    import_csv,
    main,
    render_stats,
    t95,
)


def obs(d: str, loaded: float, rate: float, dead: float = 0.0) -> LoadObservation:
    return LoadObservation(
        date=d, origin="Dallas TX", dest="Atlanta GA",
        loaded_miles=loaded, deadhead_miles=dead, rate_total=rate,
    )


class TestLoadObservation(unittest.TestCase):
    def test_rate_per_mile(self):
        o = obs("2026-07-06", loaded=1_000, rate=2_000)
        self.assertAlmostEqual(o.rate_per_mile, 2.00)

    def test_all_in_rate_accounts_for_deadhead(self):
        """The number the industry quotes vs. the number you actually earn."""
        o = obs("2026-07-06", loaded=1_000, rate=2_000, dead=250)
        self.assertAlmostEqual(o.rate_per_mile, 2.00)        # quoted
        self.assertAlmostEqual(o.all_in_rate_per_mile, 1.60)  # earned
        # 40 cents a mile evaporates into deadhead. That is the gap.

    def test_iso_week(self):
        self.assertEqual(obs("2026-07-06", 100, 200).iso_week(), "2026-W28")

    def test_rejects_unknown_field(self):
        with self.assertRaises(ValidationError):
            LoadObservation(date="2026-07-06", origin="A TX", dest="B GA",
                            loaded_miles=100, rate_total=200, bogus=1)

    def test_rejects_zero_miles(self):
        with self.assertRaises(ValidationError):
            obs("2026-07-06", loaded=0, rate=500)

    def test_rejects_negative_rate(self):
        with self.assertRaises(ValidationError):
            obs("2026-07-06", loaded=100, rate=-1)

    def test_parses_string_date(self):
        self.assertEqual(obs("2026-07-06", 100, 200).date, date(2026, 7, 6))


class TestEstimator(unittest.TestCase):
    def test_needs_at_least_two(self):
        self.assertIsNone(estimate([]))
        self.assertIsNone(estimate([obs("2026-07-06", 1000, 2000)]))

    def test_hand_computed_two_weeks(self):
        """Week A: 1000 mi / $2000 -> $2.00. Week B: 1000 mi / $2400 -> $2.40.
        mean = 2.20, stdev (sample, n-1) = 0.2828, SEM = 0.2828/sqrt(2) = 0.2"""
        e = estimate([obs("2026-07-06", 1_000, 2_000),   # 2026-W28
                      obs("2026-07-13", 1_000, 2_400)])  # 2026-W29
        self.assertEqual(e.n_weeks, 2)
        self.assertAlmostEqual(e.avg_rate_per_mile, 2.20, places=3)
        self.assertAlmostEqual(e.rate_volatility, 0.2828, places=3)
        self.assertAlmostEqual(e.rate_mean_uncertainty, 0.2000, places=3)

    def test_loads_aggregate_into_weeks_not_averaged_individually(self):
        """Two loads in the SAME week are one observation, revenue-weighted.
        Averaging per-load would understate volatility — a slow week is not one
        bad load, it is five."""
        e = estimate([
            obs("2026-07-06", 1_000, 2_000),  # W28
            obs("2026-07-08", 1_000, 3_000),  # W28  -> week rpm = 5000/2000 = 2.50
            obs("2026-07-13", 1_000, 1_500),  # W29  -> week rpm = 1.50
        ])
        self.assertEqual(e.n_loads, 3)
        self.assertEqual(e.n_weeks, 2)
        self.assertAlmostEqual(e.avg_rate_per_mile, 2.00, places=3)  # (2.50+1.50)/2

    def test_revenue_weighting_within_week(self):
        """A long cheap load must not be averaged equally with a short rich one."""
        e = estimate([
            obs("2026-07-06", 2_000, 2_000),  # $1.00/mi, 2000 mi
            obs("2026-07-07", 500, 1_500),    # $3.00/mi, 500 mi
            obs("2026-07-13", 1_000, 2_000),
        ])
        # week 28: revenue 3500 / 2500 mi = $1.40  (NOT the naive (1+3)/2 = $2.00)
        self.assertAlmostEqual(e.avg_rate_per_mile, (1.40 + 2.00) / 2, places=3)

    def test_deadhead_pct(self):
        e = estimate([obs("2026-07-06", 900, 1_800, dead=100),
                      obs("2026-07-13", 900, 1_800, dead=100)])
        self.assertAlmostEqual(e.deadhead_pct, 200 / 2_000, places=4)  # 10%

    def test_all_in_rpm_is_lower_than_quoted(self):
        e = estimate([obs("2026-07-06", 1_000, 2_000, dead=200),
                      obs("2026-07-13", 1_000, 2_000, dead=200)])
        self.assertAlmostEqual(e.revenue_weighted_rpm, 2.00, places=3)
        self.assertAlmostEqual(e.all_in_rpm, 4_000 / 2_400, places=3)
        self.assertLess(e.all_in_rpm, e.revenue_weighted_rpm)

    def test_loaded_miles_per_week(self):
        e = estimate([obs("2026-07-06", 1_000, 2_000),
                      obs("2026-07-07", 1_200, 2_400),   # same week -> 2200
                      obs("2026-07-13", 1_800, 3_600)])  # next week -> 1800
        self.assertAlmostEqual(e.loaded_miles_per_week, 2_000.0, places=1)

    def test_uncertainty_shrinks_as_sample_grows(self):
        """THE HEADLINE PROPERTY. More weeks -> tighter estimate of the mean.
        This is the entire reason the tool exists."""
        small = estimate([obs(f"2026-0{m}-06", 1_000, 2_000 + 200 * m) for m in (1, 2, 3)])
        large = estimate([obs("2026-01-06", 1_000, 2_200), obs("2026-02-06", 1_000, 2_400),
                          obs("2026-03-06", 1_000, 2_600), obs("2026-04-06", 1_000, 2_200),
                          obs("2026-05-06", 1_000, 2_400), obs("2026-06-06", 1_000, 2_600),
                          obs("2026-07-06", 1_000, 2_200), obs("2026-08-06", 1_000, 2_400),
                          obs("2026-09-06", 1_000, 2_600), obs("2026-10-06", 1_000, 2_400)])
        self.assertGreater(small.n_weeks, 1)
        self.assertLess(large.rate_mean_uncertainty, small.rate_mean_uncertainty)
        self.assertLess(large.ci95_width, small.ci95_width)

    def test_ci_brackets_the_mean(self):
        e = estimate([obs("2026-07-06", 1_000, 2_000), obs("2026-07-13", 1_000, 2_400),
                      obs("2026-07-20", 1_000, 2_200)])
        self.assertLess(e.ci95_low, e.avg_rate_per_mile)
        self.assertGreater(e.ci95_high, e.avg_rate_per_mile)

    def test_zero_volatility_gives_zero_uncertainty(self):
        e = estimate([obs("2026-07-06", 1_000, 2_000), obs("2026-07-13", 1_000, 2_000),
                      obs("2026-07-20", 1_000, 2_000)])
        self.assertAlmostEqual(e.rate_volatility, 0.0, places=6)
        self.assertAlmostEqual(e.rate_mean_uncertainty, 0.0, places=6)
        self.assertAlmostEqual(e.ci95_width, 0.0, places=6)

    def test_weeks_needed_is_monotone_in_precision(self):
        """Pinning to +/- 5c must require at least as many weeks as +/- 10c."""
        e = estimate([obs("2026-01-06", 1_000, 2_000), obs("2026-02-06", 1_000, 2_600),
                      obs("2026-03-06", 1_000, 2_200)])
        self.assertGreaterEqual(e.weeks_needed_for_5c, e.weeks_needed_for_10c)

    def test_t_multiplier_is_conservative_for_small_n(self):
        """With 2 observations the normal approximation (1.96) is dangerously
        optimistic. We must use the t-distribution."""
        self.assertGreater(t95(1), 12.0)
        self.assertGreater(t95(2), 4.0)
        self.assertLess(t95(100), 2.0)


class TestJournalIO(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "j.jsonl"

    def test_roundtrip(self):
        j = Journal(self.tmp)
        j.append(obs("2026-07-06", 1_000, 2_000))
        j.append(obs("2026-07-13", 900, 2_100, dead=50))
        back = j.load()
        self.assertEqual(len(back), 2)
        self.assertAlmostEqual(back[0].rate_per_mile, 2.00)

    def test_empty_journal(self):
        self.assertEqual(Journal(self.tmp).load(), [])

    def test_returns_sorted_by_date(self):
        j = Journal(self.tmp)
        j.append(obs("2026-07-20", 1_000, 2_000))
        j.append(obs("2026-07-06", 1_000, 2_000))
        self.assertEqual([o.date.day for o in j.load()], [6, 20])

    def test_malformed_line_is_skipped_not_fatal(self):
        j = Journal(self.tmp)
        j.append(obs("2026-07-06", 1_000, 2_000))
        with self.tmp.open("a") as f:
            f.write("{not json at all\n")
        self.assertEqual(len(j.load()), 1)  # survives, does not crash


class TestCSVImport(unittest.TestCase):
    def _write(self, text: str) -> Path:
        p = Path(tempfile.mkdtemp()) / "x.csv"
        p.write_text(text)
        return p

    def test_standard_columns(self):
        rows, errs = import_csv(self._write(
            "date,origin,dest,loaded_miles,deadhead_miles,rate_total\n"
            "2026-07-06,Dallas TX,Atlanta GA,780,65,1850\n"
            "2026-07-09,Atlanta GA,Memphis TN,390,20,900\n"
        ))
        self.assertEqual(len(rows), 2)
        self.assertEqual(errs, [])
        self.assertAlmostEqual(rows[0].rate_per_mile, 1850 / 780, places=4)

    def test_alias_columns_and_currency_formatting(self):
        """Real exports have '$1,850.00' and columns named 'Miles' and 'Pay'."""
        rows, errs = import_csv(self._write(
            "Pickup Date,From,To,Miles,DH,Pay\n"
            '2026-07-06,Dallas TX,Atlanta GA,780,65,"$1,850.00"\n'
        ))
        self.assertEqual(errs, [])
        self.assertAlmostEqual(rows[0].rate_total, 1850.0)
        self.assertAlmostEqual(rows[0].deadhead_miles, 65.0)

    def test_missing_required_column_raises_with_guidance(self):
        with self.assertRaises(ValueError) as cm:
            import_csv(self._write("date,origin,dest\n2026-07-06,A TX,B GA\n"))
        self.assertIn("loaded_miles", str(cm.exception))

    def test_bad_row_reported_not_silently_coerced(self):
        rows, errs = import_csv(self._write(
            "date,origin,dest,loaded_miles,rate_total\n"
            "2026-07-06,Dallas TX,Atlanta GA,780,1850\n"
            "2026-07-09,Atlanta GA,Memphis TN,0,900\n"  # zero miles -> invalid
        ))
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("row 3", errs[0])

    def test_deadhead_defaults_to_zero_when_absent(self):
        rows, _ = import_csv(self._write(
            "date,origin,dest,loaded_miles,rate_total\n2026-07-06,A TX,B GA,780,1850\n"
        ))
        self.assertEqual(rows[0].deadhead_miles, 0.0)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.j = self.tmp / "j.jsonl"

    def test_log_then_stats(self):
        for d, rate in (("2026-07-06", 2000), ("2026-07-13", 2400), ("2026-07-20", 2200)):
            self.assertEqual(main([
                "--journal", str(self.j), "log", "--date", d,
                "--origin", "Dallas TX", "--dest", "Atlanta GA",
                "--loaded-miles", "1000", "--rate", str(rate),
            ]), 0)
        self.assertEqual(main(["--journal", str(self.j), "stats"]), 0)
        self.assertEqual(main(["--journal", str(self.j), "list"]), 0)

    def test_stats_refuses_on_thin_data(self):
        main(["--journal", str(self.j), "log", "--date", "2026-07-06",
              "--origin", "A TX", "--dest", "B GA", "--loaded-miles", "1000",
              "--rate", "2000"])
        self.assertEqual(main(["--journal", str(self.j), "stats"]), 1)  # nonzero = refuse

    def test_how_always_works(self):
        self.assertEqual(main(["how"]), 0)

    def test_emit_writes_into_deal_json(self):
        deal = self.tmp / "deal.json"
        deal.write_text(json.dumps({
            "label": "t",
            "revenue": {"avg_rate_per_mile": 9.99, "rate_volatility": 9.99,
                        "rate_mean_uncertainty": 9.99, "loaded_miles_per_week": 1.0,
                        "miles_volatility": 0.0, "deadhead_pct": 0.99},
        }))
        for d, rate in (("2026-07-06", 2000), ("2026-07-13", 2400)):
            main(["--journal", str(self.j), "log", "--date", d, "--origin", "A TX",
                  "--dest", "B GA", "--loaded-miles", "1000", "--rate", str(rate)])
        self.assertEqual(main(["--journal", str(self.j), "emit", "--deal", str(deal)]), 0)

        rev = json.loads(deal.read_text())["revenue"]
        self.assertAlmostEqual(rev["avg_rate_per_mile"], 2.20, places=2)
        self.assertAlmostEqual(rev["rate_mean_uncertainty"], 0.20, places=2)
        self.assertNotEqual(rev["deadhead_pct"], 0.99)  # overwritten with real data

    def test_emit_refuses_missing_deal(self):
        for d, rate in (("2026-07-06", 2000), ("2026-07-13", 2400)):
            main(["--journal", str(self.j), "log", "--date", d, "--origin", "A TX",
                  "--dest", "B GA", "--loaded-miles", "1000", "--rate", str(rate)])
        self.assertEqual(
            main(["--journal", str(self.j), "emit", "--deal", str(self.tmp / "nope.json")]), 1)


class TestRendering(unittest.TestCase):
    def test_thin_sample_is_called_an_anecdote(self):
        e = estimate([obs("2026-07-06", 1_000, 2_000), obs("2026-07-13", 1_000, 2_600)])
        out = render_stats(e)
        self.assertIn("anecdote", out)
        self.assertIn("YOU DO NOT HAVE AN ANSWER YET", out)

    def test_tight_sample_is_blessed(self):
        e = estimate([obs(f"2026-{m:02d}-06", 1_000, 2_200) for m in range(1, 11)])
        self.assertIn("[ok]", render_stats(e))

    def test_report_emits_pasteable_params(self):
        e = estimate([obs("2026-07-06", 1_000, 2_000), obs("2026-07-13", 1_000, 2_400)])
        out = render_stats(e)
        for key in ("avg_rate_per_mile", "rate_volatility", "rate_mean_uncertainty",
                    "loaded_miles_per_week", "deadhead_pct"):
            self.assertIn(key, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
