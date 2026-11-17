# Portable loader / 便携加载提示

Load and follow the canonical root `AGENTS.md`. This Hermes / OpenClaw adapter adds no policy.

```text
You have access to a local agent named agent-strategy-red-team at:
<AGENT_STRATEGY_RED_TEAM_ROOT>

Use it before a futures strategy is released, when the user wants plausible counterexamples
(wrong trades or runaway risk) beyond a fixed stress checklist.

1. Read <ROOT>/AGENTS.md first; it is the canonical declaration.
2. Read <ROOT>/references/design.md for the frozen protocol, oracles and metrics.
3. From <ROOT>/e13: python run_e13.py search --arms A0_fixed,A1_random,A2_evolve
   then python run_e13.py adjudicate; python summarize.py out; python regress.py --runs out --fix v2; python report_e13.py out
4. Report sealed-defect detection by arm, false-alarm rate, confirmed counterexamples (minimal form) and the regression verdict.
5. Never edit files listed in e13/out/freeze.json after freezing; log any change in ATTEMPTS.md.
6. Model keys and data credentials come only from environment variables; never upload them to a cloud workspace.
7. Research and education only: no trade instructions, no return promises, no official-endorsement claims.
```
