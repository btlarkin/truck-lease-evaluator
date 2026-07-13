# Truck Lease Evaluator

**Price a lease-purchase like the trading position it actually is.**

A recruiter will show you this:

> "Break-even is $1.43 a mile and loads are running $2.10. You're clearing sixty-seven cents a mile. Sign here."

That is true. It is also irrelevant, and it is how drivers lose everything.

---

## The problem

A lease-purchase is an **asymmetric position**:

- The payment is **fixed**. It fires every week whether the truck moves or not.
- The revenue is **stochastic**. It goes to zero during breakdowns, home time, and soft weeks.

Cost-per-mile arithmetic — the only math most owner-operators are ever shown — reports an
average and says nothing about the distribution.

**Nobody goes bankrupt on the mean.** They go bankrupt in the left tail, when a $9,000 engine
event lands in the same month as a rate trough and the payment is still due on Friday.

This tool prices the tail.

## The two numbers that matter

```
  THE DETERMINISTIC FLOOR (what the recruiter shows you)
  ----------------------------------------------------------------------
    Break-even gross rate              $    1.43 /loaded mi
    Your assumed rate                  $    2.10 /loaded mi
    Apparent margin                    $    0.67 /loaded mi
    Fixed cost due EVERY week          $    1202   <- even at zero miles

  WHAT YOU ACTUALLY NEED (solved, not guessed)
  ----------------------------------------------------------------------
    Rate to merely MATCH the W2 seat   $    2.21 /loaded mi
    Miles/wk to match at assumed rate      2,398 loaded mi

    Below these lines you are paying for the privilege of taking risk.
```

| | Rate | What it means |
|---|---|---|
| Break-even | **$1.43/mi** | You stop **losing** money |
| Match your W2 | **$2.21/mi** | You stop **working for free** |
| The gap | **$0.78/mi** | What your labor is already worth |

At $2.10/mi you'd take on the payment, the maintenance, the downtime, the escrow, and 100% of
the risk — **to earn less than the company job you already have.**

## What this tool will NOT do

**It will not tell you whether to sign.** It cannot, and anything that claims to is lying to you.

The same model, on two equally plausible input sets, returns a **−$7,798** and a **+$97,401**
median edge. A $105,000 swing, from nothing but the numbers you typed in.

**Its actual job is to tell you which numbers decide your life**, so you can go get the real
ones instead of trusting someone else's arithmetic:

```
  WHICH NUMBERS ACTUALLY DECIDE THIS
  --------------------------------------------------------------------
  [YOU] you can influence it.    [MKT] the market decides, not you.

  Rate $/mi           $   55,784  ###################### [MKT]
  Loaded miles/wk     $   39,566  ################       [YOU]
  W2 take-home $/wk   $   23,400  #########              [MKT]
  Fuel $/gal          $   21,984  #########              [MKT]
  MPG                 $   15,405  ######                 [YOU]
  Deadhead %          $   14,523  ######                 [YOU]
  Maintenance $/mi    $   14,331  ######                 [MKT]
  Lease payment $/wk  $   13,000  #####                  [YOU]
  Breakdown prob/wk   $   12,407  #####                  [MKT]

  >>> 61% of the outcome sits in variables you DO NOT CONTROL.
```

**Read that last line again.** You would be taking a leveraged, illiquid, undiversified position
whose returns are 61% determined by forces indifferent to how hard you work.

That is not a forecast. It is a property of the deal's structure, and it is true in any market.

## The finding that surprised me

Sweeping the required rate across every plausible lease payment:

| Lease payment | Break-even | Rate to match your W2 |
|---|---|---|
| $450/wk | $1.34 | $2.10 |
| $650/wk | $1.43 | **$2.21** |
| $850/wk | $1.53 | $2.31 |

**The gap stays at ~$0.78/mi no matter what the payment is.**

Negotiating $650 down to $450 — a 30% cut, real money, hard to win — moves your required rate
by **eleven cents.**

**Haggling over the payment is not the lever.** The deal lives or dies on whether loads in your
lanes actually clear ~$2.20/mile. And you don't control that.

## The companion tool: `rate_journal.py`

The evaluator needs four numbers it cannot invent for you — what your lanes pay, how much
that swings, **how wrong your estimate might be**, and how many miles you actually turn.

`rate_journal.py` computes them from real observations, and tells you **when you have enough
data to trust the answer.**

```bash
python rate_journal.py how          # how to legitimately get rate data. START HERE.

python rate_journal.py log --date 2026-07-08 --origin "Dallas TX" --dest "Atlanta GA" \
    --loaded-miles 780 --deadhead-miles 65 --rate 1850

python rate_journal.py import-csv dat_export.csv    # or import a load-board export
python rate_journal.py stats
python rate_journal.py emit --deal deal.json        # writes straight into the lease model
```

### The thing nobody does: ask how wrong the average is

Everyone eyeballs an average. Almost nobody asks how *wrong* it could be.

```
  HOW WRONG COULD YOU BE?
  ----------------------------------------------------------------------
    Std error of the mean              $     0.07 /mi
    95% confidence interval             $2.01 .. $2.42
    Interval WIDTH                     $     0.42 /mi

    [!] Your average could be off by $0.21/mi in either
        direction. On 2,200 loaded miles a week that is
        $23,915 a year of pure uncertainty.
        YOU DO NOT HAVE AN ANSWER YET.

    Weeks needed to pin the mean within +/- $0.10/mi:    10
    Weeks needed to pin the mean within +/- $0.05/mi:    29
```

**Four weeks of data is not a sample. It is an anecdote.** After a month your estimate of your
own average rate can still be off by twenty cents a mile — and twenty cents is the difference
between a deal that beats your job and a deal that ends you.

The standard error of the mean is `sigma / sqrt(n)`. It shrinks slowly. **That is not a flaw in
the tool; it is a fact about small samples, and it is why so many drivers sign on a hunch.**

### It will not scrape load boards

DAT and Truckstop are paid, authenticated services whose terms prohibit it, and there is no free
public load-board API. `python rate_journal.py how` lays out the legitimate paths — including
the one that costs nothing and matters most:

> **"Show me the last 12 weeks of settlement statements from three drivers currently in this
> lease program."**
>
> A legitimate program will show you. A predatory one will deflect.
> **The deflection is the answer.**

## Install

```bash
git clone https://github.com/btlarkin/truck-lease-evaluator
cd truck-lease-evaluator
pip install -r requirements.txt
```

Python 3.10+. Two dependencies. No cloud, no account, no telemetry, nothing phones home.
Your contract terms never leave your machine.

## Use

```bash
python lease_evaluator.py --worksheet     # what to go collect. START HERE.

python lease_evaluator.py --dump-template > deal.json
#   ... edit deal.json with your REAL numbers ...
python lease_evaluator.py --scenario deal.json --all
```

Other flags:

```bash
python lease_evaluator.py --all           # full report on illustrative numbers
python lease_evaluator.py --tornado       # which inputs decide the outcome
python lease_evaluator.py --sweep-rate    # rate sensitivity table
```

## Three things it does that a spreadsheet won't

### 1. It knows you don't know the rate

Most models assume you *know* your average rate per mile. You don't — you're estimating it, and
you might be wrong. A model that treats your guess as ground truth badly understates your odds
of going broke.

`rate_mean_uncertainty` draws the mean itself from a distribution, once per simulated path. This
is the difference between **risk** (known odds) and **uncertainty** (unknown odds).

Lease-purchase failures live in the second category.

### 2. It unmasks the interest rate

A lease is financing wearing a costume. Discounting the actual cash flows against the truck's
real market value reveals the APR the contract is designed not to state.

On a not-unusual set of terms, this tool prints:

```
    IMPLIED APR (incl. sunk escrow)        92.1%
    Truck fair market value            $    65,000
    All-in cost to own it              $   189,400
    Premium over market                $   124,400  (+191%)
```

Those flags depend on the **paper**, not on any guess about the freight market. They are the
only part of this analysis that is fact rather than forecast.

### 3. It uses the right benchmark

The lease does not need to be *profitable*. It needs to beat **the company job you already have**,
risk-adjusted, while you carry 100% of the downside.

Most don't. The Sharpe ratio here is computed against your W2 take-home, not against zero.

## Red flags it will catch

- Predatory implied APR
- All-in cost far above the truck's market value
- **Non-refundable escrow** — a sunk cost dressed up as savings
- Oversized balloon payment
- Exit penalties that lock you in
- A cash reserve too thin to survive one engine event

## Tests

```bash
python test_lease_evaluator.py    # 39 tests, ~4s, no network
```

Every number this model prints is verified against a hand-computed or analytically-known result:

- With all randomness switched off, the Monte Carlo **must** collapse onto the closed-form answer
- A truck that never moves must still bleed **exactly** the fixed cost — the trap, encoded
- The APR solver must recover a known annuity's rate to 4 decimal places
- The indifference solvers must round-trip to ~zero edge
- Parameter uncertainty must widen both tails

A model used to make a six-figure, hard-to-reverse decision without tests is malpractice.

## The one question this replaces

You do not have to agonize. You have to answer one question:

> **"Do loads in my lanes clear $2.20+ a mile, consistently, after deadhead?"**

If yes, the truck is worth a serious look. If no, you already have the better job.

**Go pull thirty days of real load-board data for the lanes you'd actually run.** Not the
national average. Not the recruiter's number. Yours.

Everything in this repo is a machine waiting for that number.

---

## Disclaimer

This is a modeling tool, not financial, legal, or tax advice. Its output is only as good as the
numbers you feed it, and it is explicitly designed to make that limitation impossible to ignore.
Nothing here is a recommendation to enter or avoid any contract. Consult professionals who owe
you a duty of care. Read your contract. Twice.

## License

MIT. Use it, fork it, sell your own version. If it stops one driver from signing something that
would have wrecked him, it paid for itself.
