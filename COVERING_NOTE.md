Subject: ENAM - IIT screening - 2027

Hi team,

Here is my FINN submission.

- Live (open on a phone): https://finn-q8c8.onrender.com   (free tier: the first load after idle takes about a minute)
- Code: https://github.com/gsiddhi04/EnamHoldings
- AI build history: attached (Claude Code transcripts)

**What I built.** A mobile web app with two modes. *Push:* a brief that ranks every filing across an 18-stock portfolio and folds the
routine ones under a visible crease, results cards (Revenue / EBITDA / PBT / PAT with QoQ and YoY read from the filing's PDF),
management-change cards with who the people are, credit-rating changes ranked by direction, and alerts on thresholds each user
sets, with real push notifications. *Pull:* research on any NSE ticker from primary sources only: a business snapshot from the annual
report, the numbers and cash quality, bull and bear, and my favourite part, **promised vs delivered**: what management said on the
last five earnings calls, checked against the numbers they later reported.

**Decisions and trade-offs.**
- *Rules before models.* A regex ladder with a priority and a "why" classifies ~92% of filings for free; a cheap model sees only
  the rest. A stronger model is used in just three places: judging promises, bull/bear, and re-reading a results table whose
  self-check failed. The whole demo universe (71 model calls) cost about 156k input and 18k output tokens.
- *The model transcribes, Python reasons.* For results the model only copies a table. EBITDA, growth and margins are computed in
  code and cross-checked (PBT − tax ≈ PAT); a failure escalates, then is flagged rather than guessed. This caught a real error on a
  scanned filing where "533-402" was read as 533.402.
- *Every AI claim is checkable.* Promise quotes must appear verbatim in the transcript; bull/bear points can only cite computed
  numbers; segment figures must appear in the report text; Ask FINN answers from the supplied filing only and says what is missing.
- *Judgment over completeness in the feed.* The product's point of view is filtering: one event is one card, and the routine pile is
  collapsed but one tap away.

**Deliberately left out.** LinkedIn scraping (bios come from the filing, else a verified Wikipedia page, else nothing), OCR for scanned
PDFs, a full account system (settings are per browser), and a database beyond SQLite.

**Known weak spots.** Promise scoring is generous when a quote lacks context (it can say "no contradiction found", not "proved");
some companies publish no transcripts on screener.in (ITC, Trent), and the app says so; push delivery to a physical device is untested
(the subscription flow and the sender logic are tested). 37 automated tests run offline in about a second.

**Where I'd take it next.** Give the promise judge the surrounding paragraph and a per-company metric glossary; read the notes to the
accounts for contingent liabilities and related-party deals (the "narrative vs numbers" idea); add a daily 8am digest push; move to
Postgres and a shared rate limiter.

Thanks for the interesting problem.
