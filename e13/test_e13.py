"""离线自测：python e13/test_e13.py（不需要网络与密钥）。

需要真实面板的测试（e13/data/panel/ 不存在时）会明确标为 SKIPPED，不算通过。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from futures_replay import test_engine  # noqa: E402

RESULTS = []


def case(fn):
    try:
        msg = fn()
        RESULTS.append((fn.__name__, "PASS", msg))
    except SkipTest as e:
        RESULTS.append((fn.__name__, "SKIPPED", str(e)))
    return fn


class SkipTest(Exception):
    pass


def _panel():
    p = HERE / "data" / "panel" / "panel_meta.json"
    if not p.exists():
        raise SkipTest("e13/data/panel/ 不存在：运行 fetch_data.py 后 python e13/run_e13.py freeze 会生成，或使用 make_bundle.sh 打出的包里的面板")
    from run_e13 import load, DEV
    from harness import Evaluator
    panel, env, cfg = load()
    return panel, env, cfg, Evaluator(panel, env, cfg, DEV)


@case
def test_engine_hand_checks():
    return "; ".join(t() for t in (test_engine.test_pnl_fees_mult, test_engine.test_locked_no_fill, test_engine.test_roll,
                                   test_engine.test_double_sided_fix, test_engine.test_chain_returns))


@case
def test_freeze_intact():
    from run_e13 import check_frozen
    fz = check_frozen()
    return f"{len(fz['files'])} 个冻结文件哈希一致（冻结于 {fz['frozen_at']}）"


@case
def test_clip_to_envelope():
    panel, env, cfg, ev = _panel()
    from grammar import Primitive, clip_to_envelope
    p, notes = clip_to_envelope(Primitive("gap", "RB", ev.lo + 10, {"size": -0.5}), env, panel)
    assert abs(p.params["size"]) <= env["products"]["RB"]["gap_max"] + 1e-12 and notes, (p.params, notes)
    q, _ = clip_to_envelope(Primitive("margin_hike", "all", ev.lo + 10, {"pp": 0.5, "length": 99}), env, panel)
    assert q.params["pp"] <= 0.05 and q.params["length"] <= 20
    return f"越界参数被夹回包络：{notes}"


@case
def test_plausibility_rejects_stacked_shocks():
    panel, env, cfg, ev = _panel()
    from grammar import Attack, Primitive, plausible
    t = ev.lo + 50
    stacked = Attack([Primitive("gap", "RB", t, {"size": -0.06}), Primitive("limit_lock", "RB", t + 1, {"days": 1, "direction": -1}),
                      Primitive("gap", "RB", t + 2, {"size": -0.06})])
    stacked, _ = ev.normalize(stacked)
    ok, why = plausible(stacked, panel, env)
    assert not ok, why
    return f"叠加冲击超过历史 5 日上界被判不合理：{why}"


@case
def test_determinism():
    panel, env, cfg, ev = _panel()
    from grammar import Attack, Primitive
    a = Attack([Primitive("sector_shock", "sector:agri", ev.lo + 200, {"size": -0.05})])
    r1, r2 = ev.evaluate("CLEAN", a), ev.evaluate("CLEAN", a)
    assert r1["oracles"] == r2["oracles"] and r1["severity"] == r2["severity"]
    return f"同一攻击两次回放结果一致：{r1['oracles']}"


@case
def test_revert_locates_defect():
    panel, env, cfg, ev = _panel()
    from harness import run_random
    from adjudicate import adjudicate_run
    res = run_random(ev, "V03", 120, 1)
    adj = adjudicate_run(ev, "V03", res, 1)
    found = [g for g in adj["groups"] if g["valid"] and "stop_missed" in g["defect_oracles"]]
    assert found, "V03（空头不止损）应被 stop_missed 通过回退测试定位"
    return f"V03 在 {adj['evals_to_detect']} 次回放内被定位，回退测试只在缺陷版本上触发 stop_missed"


if __name__ == "__main__":
    for name, status, msg in RESULTS:
        print(f"[{status}] {name}: {msg}")
    failed = [r for r in RESULTS if r[1] not in ("PASS", "SKIPPED")]
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"{n_pass} PASS, {sum(1 for r in RESULTS if r[1] == 'SKIPPED')} SKIPPED")
    sys.exit(1 if failed else 0)
