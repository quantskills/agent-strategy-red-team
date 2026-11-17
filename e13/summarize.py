"""汇总裁决结果：发现率、误报率、新增漏洞、成本；缩减原策略上的反例。"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
OUT = HERE / "out"
ARMS = ["A0_fixed", "A1_random", "A2_evolve", "A3_llm"]


def boot_ci(x, n=2000, seed=0):
    x = np.asarray(x, float)
    if len(x) == 0:
        return (np.nan, np.nan)
    if len(x) == 1:
        return (x[0], x[0])
    rng = np.random.default_rng(seed)
    m = rng.choice(x, size=(n, len(x)), replace=True).mean(1)
    return (float(np.quantile(m, 0.05)), float(np.quantile(m, 0.95)))


def summarize(run_dir=OUT):
    """run_dir 下需有 adjudication.json；结果表写回 run_dir。"""
    from defects.sealed import OPEN, SEALED, DEFECT_LAYER
    run_dir = Path(run_dir)
    OUTD = run_dir
    runs = json.loads((run_dir / "adjudication.json").read_text())
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "groups"} for r in runs])
    arms = [a for a in ARMS if a in set(df.arm)]
    # 1 发现矩阵
    det = df[df.vid.isin(SEALED + OPEN)].pivot_table(index="vid", columns="arm", values="detected", aggfunc="mean").reindex(columns=arms)
    ttd = df[df.vid.isin(SEALED + OPEN)].pivot_table(index="vid", columns="arm", values="evals_to_detect", aggfunc="median").reindex(columns=arms)
    # 2 每臂汇总
    rows = []
    for a in arms:
        d = df[df.arm == a]
        sealed_by_seed = d[d.vid.isin(SEALED)].groupby("seed").detected.mean()
        lo, hi = boot_ci(sealed_by_seed.values)
        allg = [g for r in runs if r["arm"] == a for g in r["groups"]]
        fa = sum(1 for g in allg if not g["valid"])
        clean_valid = {(g["cls"], tuple(g["oracles"]), tuple(g["kinds"])) for r in runs if r["arm"] == a and r["vid"] == "CLEAN" for g in r["groups"] if g["valid"]}
        eq_false = sum(1 for r in runs if r["arm"] == a and r["vid"] == "EQ" for g in r["groups"] if g["valid"] and g["defect_oracles"])
        rows.append({"arm": a, "runs": len(d), "evals": int(d.n_evals.sum()), "sealed_detect_rate": float(sealed_by_seed.mean()) if len(sealed_by_seed) else np.nan,
                     "sealed_ci90": f"[{lo:.2f}, {hi:.2f}]", "open_detect_rate": float(d[d.vid.isin(OPEN)].detected.mean()),
                     "reported_groups": len(allg), "false_alarm_groups": fa, "false_alarm_rate": fa / max(1, len(allg)),
                     "clean_vulns_real": sum(1 for k in clean_valid if k[0] == "real"), "clean_vulns_robust": sum(1 for k in clean_valid if k[0] == "robust"),
                     "eq_false_differential": eq_false, "invalid_proposals": int(d.n_invalid.sum()), "llm_fallback": int(d.n_fallback.sum())})
    arm_tab = pd.DataFrame(rows)
    # 3 原策略新增漏洞（并集），谁找到的
    vul = defaultdict(lambda: {"arms": set(), "best": None})
    for r in runs:
        if r["vid"] != "CLEAN":
            continue
        for g in r["groups"]:
            if not g["valid"]:
                continue
            k = (g["cls"], tuple(g["oracles"]), tuple(g["kinds"]))
            vul[k]["arms"].add(r["arm"])
            if vul[k]["best"] is None or g["rep_severity"] > vul[k]["best"]["rep_severity"]:
                vul[k]["best"] = g
    vrows = []
    for k, v in vul.items():
        vrows.append({"cls": k[0], "oracles": ",".join(k[1]), "kinds": ",".join(k[2]), "found_by": ",".join(sorted(v["arms"])),
                      "fixed_list_found": "A0_fixed" in v["arms"], "rep_attack": v["best"]["rep_attack"]["text"], "severity": v["best"]["rep_severity"],
                      "rep_attack_json": json.dumps(v["best"]["rep_attack"], ensure_ascii=False)})
    vul_tab = pd.DataFrame(vrows).sort_values(["cls", "severity"], ascending=[True, False]) if vrows else pd.DataFrame()
    layer = pd.Series(DEFECT_LAYER, name="layer")
    det = det.join(layer)
    det.to_csv(OUTD / "detection_matrix.csv")
    ttd.to_csv(OUTD / "evals_to_detect.csv")
    arm_tab.to_csv(OUTD / "arm_summary.csv", index=False)
    if len(vul_tab):
        vul_tab.to_csv(OUTD / "clean_vulnerabilities.csv", index=False)
    return det, ttd, arm_tab, vul_tab


if __name__ == "__main__":
    d, t, a, v = summarize(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
    pd.set_option("display.width", 250)
    print(d.to_string()); print(t.to_string()); print(a.to_string(index=False))
    if len(v):
        print(v.drop(columns=["rep_attack_json"]).to_string(index=False))
