"""The data-collection worksheet — what to go get before you sign.

Deliberately ZERO dependencies. Stock Python, nothing to install:

    python worksheet.py

The rest of the tool needs numpy and pydantic. This part does not, because the
worksheet is the one piece a driver needs BEFORE deciding whether to bother
with the rest of it, and "pip install" should not stand between him and a list
of questions to ask his recruiter.
"""

WORKSHEET = """
================================================================================
  DATA COLLECTION WORKSHEET
  Take this to the dealer, the recruiter, and your own settlement statements.
================================================================================

  The model is worthless without these. Do not estimate them. Get them.

  FROM THE CONTRACT (they must give you these in writing)
  ----------------------------------------------------------------------------
  [ ] Weekly payment                            $________
  [ ] Term, in weeks                             ________
  [ ] Down payment / first-and-last              $________
  [ ] Balloon / purchase option at end           $________
  [ ] Weekly maintenance escrow                  $________
  [ ] Is escrow REFUNDABLE if you walk?          Y / N      <- ask twice, get it in writing
  [ ] Early termination penalty                  $________
  [ ] Is the payment reduced during downtime?    Y / N      <- almost always N. That is the trap.
  [ ] Who pays for a major engine event?         ________
  [ ] Forced dispatch, or can you refuse loads?  ________
  [ ] What happens if you miss ONE payment?      ________

  THE NUMBER THEY WILL NOT VOLUNTEER
  ----------------------------------------------------------------------------
  [ ] Truck's actual fair market value           $________
      Get this from a THIRD PARTY. Look up the year/make/model/mileage on
      TruckPaper or a dealer that is not selling you this truck. If all-in cost
      is 75%+ over FMV, the financing is the product, not the truck.

  FROM THE MARKET (not from the recruiter)
  ----------------------------------------------------------------------------
  [ ] Actual avg $/loaded mile in YOUR lanes     $________
      Pull 30 days of real postings on a load board. Do not use their number.
  [ ] Week-to-week spread on that rate           $________
  [ ] Honest uncertainty about the MEAN          $________   <- how wrong could you be?
  [ ] Realistic loaded miles/week                 ________
  [ ] Realistic deadhead %                        _______%

  FROM YOUR OWN LIFE (you already know these)
  ----------------------------------------------------------------------------
  [ ] Current W2 weekly take-home, after tax     $________   <- THE BENCHMARK
  [ ] Cash reserve you can actually risk         $________
  [ ] Home time weeks per year                    ________

  FROM REALITY (be honest or the model lies to you)
  ----------------------------------------------------------------------------
  [ ] Truck mileage at signing                    ________
  [ ] Realistic maintenance reserve $/mi         $________   <- $0.12-0.20 on a used truck
  [ ] Odds of a breakdown in any given week       _______%
  [ ] Typical repair bill                        $________
  [ ] Weeks of downtime when it happens           ________

  You can stop here. This list on paper, filled in, is worth more than any
  model run on numbers you guessed at.

  To run the model once you have them:

         pip install -r requirements.txt        <- needed for this part only
         python lease_evaluator.py --dump-template > deal.json
         (edit deal.json with the real numbers)
         python lease_evaluator.py --scenario deal.json --all

================================================================================
"""


if __name__ == "__main__":
    print(WORKSHEET)
