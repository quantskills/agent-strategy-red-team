"""修复与回归：S1 是否消除了 S0 上确认的漏洞，又是否引入了新问题。

python regress.py --runs out/<run_dir>        # 读该次运行的 clean_vulnerabilities.csv
四项检查（容差事前写定）：
  R1 原反例：S0 上确认的每条反例在 S1 上不再触发同一判定器；
  R2 固定清单：S1 在固定压力清单上的命中不多于 S0；
  R3 正常表现：保留期（2024-01-02 至 2026-11-13）无攻击回放，S1 相对 S0 年化收益下降 ≤ 0.5 个百分点、夏普下降 ≤ 0.10；
  R4 再搜索：同预算（随机 + 进化，各 5 个种子 × 300 次）在 S1 上确认的发现中，S0 同一攻击下不出现的判定器 = 修复引入的新问题。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from run_e13 import load, DEV  # noqa: E402
from harness import Evaluator, run_fixed, run_random, run_evolve  # noqa: E402
from adjudicate import adjudicate_run  # noqa: E402
from grammar import Attack  # noqa: E402
from fixes import S1, S1v2, sanitize_panel, sanitize_panel_v2  # noqa: E402
FIX = {"v1": (S1, sanitize_panel), "v2": (S1v2, sanitize_panel_v2)}
FIX_VER = "v2"
from defects.sealed import VARIANTS  # noqa: E402
from futures_replay.sim import simulate, summary  # noqa: E402

TOL = {"ret_drop": 0.005, "sharpe_drop": 0.10}
HOLD = ("20240102", "20261113")


class RegEvaluator(Evaluator):
    def strat(self, vid):
        if vid == "S1":
            s = FIX[FIX_VER][0](self.cfg)
            s._products = list(self.panel.products)
            s._i_idx = self.i_idx
            return s
        return super().strat(vid)

    def _sim(self, vid, P, w0, hooks=None):
        if vid == "S1":
            P, _ = FIX[FIX_VER][1](P)
        return super()._sim(vid, P, w0, hooks)


def main(run_dir: Path, budget=300, seeds=(1, 2, 3, 4, 5)):
    panel, env, cfg = load()
    ev = RegEvaluator(panel, env, cfg, DEV)
    out = {"tolerances": TOL}
    # R1
    vul = pd.read_csv(run_dir / "clean_vulnerabilities.csv")
    r1 = []
    for v in vul.itertuples():
        atk = Attack.from_json(json.loads(v.rep_attack_json))
        a = ev.evaluate("CLEAN", atk, count=False)
        b = ev.evaluate("S1", atk, count=False)
        ors = set(v.oracles.split(","))
        r1.append({"cls": v.cls, "oracles": v.oracles, "attack": atk.text(), "S0_hits": sorted(ors & set(a["oracles"])),
                   "S1_hits": sorted(ors & set(b["oracles"])), "fixed": not (ors & set(b["oracles"]))})
    out["R1_counterexamples"] = r1
    # R2
    f0 = run_fixed(ev, "CLEAN", budget)
    f1 = run_fixed(ev, "S1", budget)
    out["R2_fixed_list"] = {"S0_hits": sum(1 for r in f0 if r["oracles"]), "S1_hits": sum(1 for r in f1 if r["oracles"]),
                            "S0_real_hits": sum(1 for r in f0 if r["oracles"] and r["cls"] == "real"),
                            "S1_real_hits": sum(1 for r in f1 if r["oracles"] and r["cls"] == "real")}
    # R3
    perf = {}
    for name, strat, P in [("S0", VARIANTS["CLEAN"](cfg), panel), ("S1", ev.strat("S1"), FIX[FIX_VER][1](panel)[0])]:
        for wname, w in [("dev", DEV), ("holdout", HOLD)]:
            s = summary(simulate(P, strat, cfg, start=w[0], end=w[1]))
            perf[f"{name}_{wname}"] = {k: s[k] for k in ("ann_ret", "sharpe", "max_dd", "n_fills")}
    d_ret = perf["S0_holdout"]["ann_ret"] - perf["S1_holdout"]["ann_ret"]
    d_sh = perf["S0_holdout"]["sharpe"] - perf["S1_holdout"]["sharpe"]
    out["R3_performance"] = {**perf, "holdout_ret_drop": d_ret, "holdout_sharpe_drop": d_sh,
                             "within_tolerance": bool(d_ret <= TOL["ret_drop"] and d_sh <= TOL["sharpe_drop"])}
    # R4
    introduced, remaining = [], []
    for arm, fn in [("A1_random", run_random), ("A2_evolve", run_evolve)]:
        for s in seeds:
            res = fn(ev, "S1", budget, s)
            adj = adjudicate_run(ev, "S1", res, s)
            for g in adj["groups"]:
                if not g["valid"]:
                    continue
                rec = {"arm": arm, "seed": s, "cls": g["cls"], "oracles": ",".join(g["oracles"]), "kinds": ",".join(g["kinds"]),
                       "attack": g["rep_attack"]["text"], "introduced_oracles": ",".join(g["defect_oracles"])}
                (introduced if g["defect_oracles"] else remaining).append(rec)
    out["R4_new_search"] = {"introduced_by_fix": introduced, "remaining_n": len(remaining),
                            "remaining_kinds": sorted({(r["cls"], r["oracles"], r["kinds"]) for r in remaining})}
    out["verdict"] = {"R1_all_fixed": all(x["fixed"] for x in r1) if r1 else None,
                      "R2_not_worse": out["R2_fixed_list"]["S1_hits"] <= out["R2_fixed_list"]["S0_hits"],
                      "R3_within_tolerance": out["R3_performance"]["within_tolerance"],
                      "R4_no_new_issue": len(introduced) == 0}
    out["fix_version"] = FIX_VER
    (run_dir / f"regression_{FIX_VER}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    (run_dir / "regression.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(out["verdict"], ensure_ascii=False), json.dumps(out["R3_performance"], ensure_ascii=False, default=str)[:600])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--fix", default="v2", choices=["v1", "v2"])
    a = ap.parse_args()
    FIX_VER = a.fix
    main(Path(a.runs))
