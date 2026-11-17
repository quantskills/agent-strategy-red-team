# Red-team agent that searches for strategy failure counterexamples (agent-strategy-red-team)

> QuantSkills Community Project, not reviewed, certified or endorsed by the maintainers. For quantitative research and education only. **Not investment advice, no return promises, no automatic order placement.**

Before a futures strategy is released, this agent actively searches, within plausible bounds, for conditions that make it trade wrongly or lose control of risk, and answers: what a fixed stress checklist misses, what active search adds and at what false-alarm cost, and whether a fix makes things worse. Chinese version: [README.md](README.md).

In academic terms this is reverse stress testing plus search-based testing. Every counterexample must be explainable, re-runnable and fixable.

## Findings (strategy S0, development period 2020-01-02 to 2023-12-29, 11 commodity futures)

S0 is a public signal (63-day cross-sectional momentum, 25% no-trade band, weekly), used only as the object under test. Budget: 300 replays per arm per strategy version; 5 seeds for A1/A2, 2 for A3. A0/A1/A2 ran on PandaAI EVO, A3 locally; a local re-run of the same frozen code matches the EVO results exactly. Full report: [e13/out/final/report.md](e13/out/final/report.md).

| Question | Finding |
|---|---|
| Detection rate on 7 sealed defects (counted only when the revert test passes) | Fixed checklist A0 **43%**; random search A1 **57%** (90% CI 0.51–0.63); MAP-Elites A2 **46%** (0.34–0.57); LLM red team A3 **50%** (0.43–0.57) |
| Found only by search | V01 one-day look-ahead in the signal, V02 too-short volatility window (sizing); V05 static margin rate found by A1 on 1/5 seeds only |
| Checklist more reliable | V08 back-test fills at locked limits, V09 duplicate orders after partial fills: checklist always; A1 3/5, A2 2/5; A3 2/2 and 1/2 |
| Missed by every method | V06 drawdown-stop baseline reset (sealed), V07 stale-data check removed (open) |
| False alarms (fail jitter re-run or plausibility) | A0 27%, A1 23%, A2 21%, A3 37%; every report reproduces exactly on verbatim re-run |
| Real-scenario vulnerability of the clean strategy | A one-day limit-down lock across the agricultural sector (from 2022-01-19) causes a daily loss above 6% (no sector exposure cap); minimal counterexample has one primitive, **found only by the fixed checklist** |
| Software-robustness vulnerabilities (reported separately) | A one-day 14% bad close/settlement price in the agricultural sector breaches the daily-loss budget; opens new positions on 3-day stale bars; future-only perturbations can breach the drawdown budget |
| LLM arm caveat | 2,850 of 7,200 replays (40%) were random fallbacks after unparseable or out-of-bounds model output; its detection rate is not all attributable to the LLM |
| Fix (S1v2: sector net-exposure cap + same-day price-limit data check + stale check) | 33 of 38 counterexamples removed (the real one included; the remaining 5 are robustness cases); fixed-list hits 15 → 4; no new issue introduced by the fix under equal-budget re-search; but holdout annual return falls from -1.16% to -2.08% (0.92pp, above the pre-set 0.5pp tolerance; Sharpe drop 0.096 within 0.10) |

**Decision change:** releasing on the fixed checklist alone misses signal- and sizing-layer defects; releasing on search alone misses execution-layer defects and the only real-scenario vulnerability. Both are needed, and drawdown-stop and data-check defects need dedicated unit tests because no method sees them. The fix closes the sector-lock tail risk at a cost of about 1pp per year, which fails the pre-set tolerance and is left to the decision maker.

## Workflow (everything frozen before running)

Freeze strategy and risk card, attack grammar and plausibility bounds, oracles, fixed checklist, defect set and budget (sha256 in `e13/out/freeze.json`) → four arms with equal budget → automatic adjudication (verbatim re-run, jitter re-run ≥2/3, plausibility, revert test) → shrink to minimal counterexamples → fix → four regression checks (original counterexamples, fixed list, holdout performance, equal-budget re-search) → report. Details: [references/design.md](references/design.md), [AGENTS.md](AGENTS.md).

## Usage

```bash
pip install -r requirements.txt
python fetch_data.py                         # PandaData download (credentials via environment variables)
cd e13
python run_e13.py freeze
python run_e13.py search --arms A0_fixed,A1_random,A2_evolve
LLMX_BASE_URL=... REDTEAM_MODEL=... LLMX_API_KEY=... python run_e13.py search --arms A3_llm   # keys only via environment variables
python run_e13.py adjudicate
python summarize.py out && python regress.py --runs out --fix v2 && python report_e13.py out
python test_e13.py
```

On PandaAI EVO (120 s per run, no multiprocessing, runs isolated from each other) the experiment is split into 24 chunks via `e13/evo_chunk.py`; results are merged with `e13/merge_runs.py`. The EVO run log, approval screenshots, run IDs, raw result chunks and the EVO-vs-local comparison are in [platform_evidence/evo/](platform_evidence/evo/run_log.md).

## Data source, assumptions, parameters, limitations and risk

Data source: PandaData futures interfaces ([references/api_guide.md](references/api_guide.md)). Replay assumptions (open fill ±1 tick, ≤10% of daily volume, no fills on the locked side, margin rate +3pp, 1bp fees), parameters (development/holdout windows, replay window, budget and seeds, risk-card thresholds) and known limitations are in [references/source_boundary.md](references/source_boundary.md). Main limitations: one strategy family and ten defect classes; defects and grammar were designed by the same author (bias reduced by sealing and freezing, not removed); synthetic attack paths are plausible scenarios, not out-of-sample performance; execution semantics are verified only in replay because the futures contest was not used ([references/execution_scope.md](references/execution_scope.md)). All voided runs and failed attempts are recorded in [ATTEMPTS.md](ATTEMPTS.md).

**QuantSkills Community Project, for quantitative research and education only. Not investment advice, no return promises.**
