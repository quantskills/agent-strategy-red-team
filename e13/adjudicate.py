"""自动裁决：复跑、扰动复跑、合理性、回退测试（缺陷归因）、反例缩减。全部不计入搜索预算，单独记成本。"""
from __future__ import annotations

import copy
from collections import defaultdict

import numpy as np

from grammar import Attack

MAG = {"size": 0.0, "amp": 0.0, "pp": 0.0, "mult": None, "days": 1, "length": 1, "cycles": 1, "ratio": 1.0, "factor": 1.0, "scale": 0.0}


def group_key(rec) -> tuple:
    kinds = tuple(sorted({p["kind"] for p in rec["attack"]["prims"]}))
    return (rec["cls"], tuple(rec["oracles"]), kinds)


def jitter(atk: Attack, rng) -> Attack:
    a = Attack.from_json(atk.to_json())
    for p in a.prims:
        p.t0 = int(p.t0 + rng.integers(-3, 4))
        for k, v in list(p.params.items()):
            if k in ("direction", "seed"):
                continue
            if isinstance(v, float):
                p.params[k] = v * float(rng.uniform(0.9, 1.1))
    return a


def confirm(ev, vid, rec, rng, tries=3) -> dict:
    atk = Attack.from_json(rec["attack"])
    r1 = ev.evaluate(vid, atk, count=False)
    deterministic = set(r1["oracles"]) == set(rec["oracles"])
    hits = 0
    for _ in range(tries):
        r = ev.evaluate(vid, jitter(atk, rng), count=False)
        hits += int(any(o in r["oracles"] for o in rec["oracles"]))
    return {"deterministic": deterministic, "jitter_hits": hits, "robust": hits >= 2,
            "plausible": bool(rec["plausible"]) or rec["cls"] == "robust"}


def revert(ev, vid, rec) -> list[str]:
    """回退测试：把缺陷改回去（换成原策略），同一攻击下不再出现的判定器 = 缺陷引起。"""
    if vid == "CLEAN":
        return []
    rc = ev.evaluate("CLEAN", Attack.from_json(rec["attack"]), count=False)
    return sorted(set(rec["oracles"]) - set(rc["oracles"]))


def adjudicate_run(ev, vid, results: list[dict], seed=0, max_groups=40) -> dict:
    rng = np.random.default_rng(seed + 991)
    groups = defaultdict(list)
    first_idx = {}
    for idx, r in enumerate(results):
        if r.get("invalid") or not r["oracles"]:
            continue
        k = group_key(r)
        groups[k].append(r)
        first_idx.setdefault(k, idx)
    out = []
    for k, rs in sorted(groups.items(), key=lambda kv: -max(x["severity"] for x in kv[1]))[:max_groups]:
        rep = max(rs, key=lambda x: x["severity"])
        c = confirm(ev, vid, rep, rng)
        defect_or = revert(ev, vid, rep) if c["deterministic"] and c["robust"] else []
        valid = c["deterministic"] and c["robust"] and c["plausible"]
        out.append({"vid": vid, "cls": k[0], "oracles": list(k[1]), "kinds": list(k[2]), "n_members": len(rs),
                    "first_eval_idx": first_idx[k], "rep_attack": rep["attack"], "rep_severity": rep["severity"],
                    **c, "valid": valid, "defect_oracles": defect_or})
    n_reported = len(out)
    n_fa = sum(1 for g in out if not g["valid"])
    detect_idx = [g["first_eval_idx"] for g in out if g["valid"] and g["defect_oracles"]]
    return {"groups": out, "n_groups": n_reported, "n_false_alarm": n_fa,
            "detected": bool(detect_idx), "evals_to_detect": (min(detect_idx) + 1) if detect_idx else None}


def shrink(ev, vid, rep_attack: dict, oracle: str, steps=6) -> tuple[dict, int]:
    """把反例缩到最短：逐个参数向中性值二分，判定器仍触发就接受；再尝试删掉多余原语。"""
    a = Attack.from_json(rep_attack)
    n = 0

    def hits(x):
        nonlocal n
        n += 1
        return oracle in ev.evaluate(vid, x, count=False)["oracles"]
    if len(a.prims) > 1:
        for i in range(len(a.prims) - 1, -1, -1):
            b = Attack.from_json(a.to_json())
            b.prims.pop(i)
            if b.prims and hits(b):
                a = b
    for p_i, p in enumerate(a.prims):
        for k, v in list(p.params.items()):
            if k not in MAG or k in ("direction", "seed"):
                continue
            neutral = MAG[k]
            if neutral is None:
                neutral = 1.0
            lo, hi = neutral, v
            for _ in range(steps):
                mid = (lo + hi) / 2 if isinstance(v, float) else int(round((lo + hi) / 2))
                if mid == hi:
                    break
                b = Attack.from_json(a.to_json())
                b.prims[p_i].params[k] = type(v)(mid)
                if hits(b):
                    hi = mid
                    a = b
                else:
                    lo = mid
    return a.to_json(), n
