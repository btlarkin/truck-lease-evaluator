# Truck Lease Evaluator

**A lease-purchase is a bet. This tool prices the bet.**

A recruiter will show you this:

> "Break-even is $1.43 a mile and loads are running $2.10. You're clearing sixty-seven cents a mile. Sign here."

That is true. It is also the wrong math, and it is how drivers lose everything.

I'm a CDL driver. I have never signed a lease-purchase — I ran the numbers on the offers I've
seen and decided against it. This is the tool I ran them with. It's free, it's yours, and it
doesn't want anything from you.

---

## The problem

The lease payment is **fixed**. It hits every Friday whether the truck moved or not.
Your revenue is **not**. It goes to zero during breakdowns, home time, and slow weeks.

Cost-per-mile math gives you an *average week*. It says nothing about your bad weeks.

**Nobody goes broke on an average week.** They go broke when a $9,000 engine repair lands in the
same month as soft rates — and the payment is still due Friday.

This tool prices the bad weeks.

## The two numbers that matter

| | Rate | What it means |
|---|---|---|
| Break-even | **$1.43/mi** | You stop **losing** money |
| Match your W2 | **$2.24/mi** | You stop **working for free** |
| The gap | **$0.81/mi** | What your labor is already worth |

The recruiter quotes the first one. The second is the one that decides your life, and the tool
solves for it:

```
  THE DETERMINISTIC FLOOR (what the recruiter shows you)
    Break-even gross rate              $    1.43 /loaded mi
    Your assumed rate                  $    2.10 /loaded mi
    Fixed cost due EVERY week          $    1202   <- even at zero miles

  WHAT YOU ACTUALLY NEED (solved, not guessed)
    Rate to merely MATCH the W2 seat   $    2.24 /loaded mi
    Miles/wk to match at assumed rate      2,445 loaded mi
```

At $2.10/mi you'd take on the payment, the repairs, the downtime, the escrow, and all of the
risk — **to earn less than the company job you already have.**

## What it will NOT do

**It will not tell you whether to sign.** Anything that claims it can is lying to you.

Feed it two sets of numbers that both look reasonable and it returns **−$7,798** on one and
**+$97,401** on the other. A $105,000 swing, from nothing but what you typed in.

Its real job is to show you **which numbers decide the outcome**, so you go get the true ones:

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

You'd be borrowing serious money against one truck you can't sell quickly, and 61% of how it turns
out is decided by things that don't care how hard you work. That's not a guess about this year.
It's how the deal is built, in any market.

## The payment is not the lever

Run the required rate against every payment a recruiter might offer:

| Lease payment | Break-even | Rate to match your W2 | Gap |
|---|---|---|---|
| $450/wk | $1.34 | $2.13 | $0.79 |
| $650/wk | $1.43 | **$2.24** | $0.81 |
| $850/wk | $1.53 | $2.34 | $0.81 |

**The gap stays near $0.80/mi no matter what the payment is.** Talking $650 down to $450 — a 30%
cut, real money, hard to win — moves the rate you need by **ten cents.**

The deal lives or dies on whether loads in *your* lanes really pay about $2.20/mile.

## Start here — nothing to install

The first step needs no setup at all. `worksheet.py` has **zero dependencies**: if you have
Python, it runs.

```bash
git clone https://github.com/btlarkin/truck-lease-evaluator
cd truck-lease-evaluator

python worksheet.py     # the list of numbers to go collect. START HERE.
```

That prints the whole worksheet — every figure to get in writing before you sign, and who to
get it from. Print it, take it to the recruiter, and go ask. You can stop there and still be
far ahead of where you started. It's also on the web page, if you'd rather not touch a
terminal at all.

## Then, to run the model

```bash
pip install -r requirements.txt          # Python 3.10+, two dependencies

python lease_evaluator.py --dump-template > deal.json
#   ... edit deal.json with your REAL numbers ...
python lease_evaluator.py --scenario deal.json --all
```

No cloud, no account, no tracking. Your contract terms never leave your machine.

Also: `--tornado` (which inputs decide it), `--sweep-rate` (rate table), `--all` on its own for a
full report on example numbers.

## Three things a spreadsheet won't do

### 1. It knows you're guessing at the rate

Most models assume you *know* your average rate per mile. You don't — you're estimating, and you
might be off. Treating your guess as gospel makes your odds of going broke look far better than
they are. This one re-rolls the rate on every simulated run, so "my number might be wrong" is part
of the answer.

### 2. It shows the interest rate the contract hides

A lease is a loan in a costume. Run the real payments against what the truck is actually worth and
out comes the rate the paperwork avoids printing:

```
    IMPLIED APR (incl. sunk escrow)        92.1%
    Truck fair market value            $    65,000
    All-in cost to own it              $   189,400
    Premium over market                $   124,400  (+191%)
```

That comes off the **paperwork**, not off any guess about freight. It's the only part of this
analysis that's fact instead of forecast.

### 3. It compares against the right thing

The lease doesn't need to make money. It needs to beat **the job you already have** — by enough to
be worth carrying all the risk yourself. Most don't.

## Red flags it will catch

- An interest rate that's predatory once you unmask it
- Total cost far above what the truck is worth
- **Escrow you never get back** — their money now, sold to you as your savings
- A balloon payment at the end that's too big to handle
- Exit penalties that trap you in
- Savings too thin to survive one engine failure

## Getting the rate data: `rate_journal.py`

The evaluator needs numbers it can't invent: what your lanes pay, how much that bounces, and how
wrong your estimate might be. Log real loads and `rate_journal.py` works them out — and tells you
when you have **enough** loads to trust the answer.

```bash
python rate_journal.py how          # how to legitimately get rate data. START HERE.

python rate_journal.py log --date 2026-07-08 --origin "Dallas TX" --dest "Atlanta GA" \
    --loaded-miles 780 --deadhead-miles 65 --rate 1850

python rate_journal.py import-csv dat_export.csv    # or a load-board export
python rate_journal.py stats
python rate_journal.py emit --deal deal.json        # writes into the lease model
```

Everybody eyeballs an average. Almost nobody asks how far off it could be:

```
  HOW WRONG COULD YOU BE?
    95% confidence interval             $2.01 .. $2.42

    [!] Your average could be off by $0.21/mi in either
        direction. On 2,200 loaded miles a week that is
        $23,915 a year of pure uncertainty.
        YOU DO NOT HAVE AN ANSWER YET.

    Weeks needed to pin the mean within +/- $0.10/mi:    10
```

**Four weeks of loads is not data. It's a story.** Twenty cents a mile is the difference between a
deal that beats your job and a deal that ends you — and averages tighten up slowly. To cut your
error in half you need four times the loads.

It won't scrape load boards. DAT and Truckstop cost money, need a login, and their terms say
don't. `rate_journal.py how` lays out the legal routes — including the free one that matters most:

> **"Show me the last 12 weeks of settlement statements from three drivers currently in this
> lease program."**
>
> An honest program will show you. A predatory one changes the subject.
> **The dodge is your answer.**

## Tests

```bash
python test_lease_evaluator.py    # 39 tests, ~4s, no network
```

Every number is checked against an answer worked out by hand. Turn the randomness off and the
simulation has to land exactly on the plain-math result. A truck that never moves has to bleed
*exactly* the fixed cost — the trap, in code. The interest-rate solver has to recover a known
loan's rate to four decimals.

A model you'd use to make a six-figure decision you can't undo, with no tests behind it, is
malpractice.

## The one question this replaces

You don't have to agonize. You have to answer one question:

> **"Do loads in my lanes clear $2.20+ a mile, consistently, after deadhead?"**

If yes, the truck is worth a serious look. If no, you already have the better job.

**Go pull thirty days of real load-board data for the lanes you'd actually run.** Not the national
average. Not the recruiter's number. Yours.

Everything in this repo is a machine waiting for that number.

---

## Disclaimer

This is a modeling tool, not financial, legal, or tax advice. Its output is only as good as the
numbers you feed it. Nothing here is a recommendation to sign or avoid any contract. Talk to
professionals who owe you a duty of care. Read your contract. Twice.

## License

MIT. Use it, fork it, sell your own version. If it stops one driver from signing something that
would have wrecked him, it paid for itself.
