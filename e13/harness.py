"""评估器 + 四个搜索臂。

一次评估 = 对某个策略版本施加一个攻击，在 [t0-15, t0+60] 交易日窗口回放，用判定器检查；
只把"无攻击时同窗口不出现"的违规算作攻击引起的发现（归因）。预算按评估次数计，四臂相同。
"""
from __future__ import annotations

import copy
import json
import math
import time
from dataclasses import dataclass

import numpy as np

from futures_replay.data import Panel
from futures_replay.sim import Config, simulate
from grammar import (ALL_KINDS, REAL_KINDS, ROBUST_KINDS, SECTORS, Attack, Primitive, apply, clip_to_envelope,
                     plausible, random_primitive, targets_of)
from oracles import ORACLE_CLASS, check, lookahead_probe
from defects.sealed import VARIANTS

PRE, POST = 15, 60


class Evaluator:
    def __init__(self, panel: Panel, env: dict, cfg: Config, dev=("20200102", "20231229")):
        self.panel, self.env, self.cfg = panel, env, cfg
        self.lo = panel.idx(dev[0]) + PRE + 70
        self.hi = panel.idx(dev[1]) - POST
        self._base = {}
        self.n_eval = 0
        self.i_idx = panel.products.index("I") if "I" in panel.products else None

    def strat(self, vid: str):
        s = VARIANTS[vid](self.cfg)
        s._i_idx = self.i_idx
        return s

    def _sim(self, vid, P, w0, hooks=None):
        hooks = hooks or {}
        i0, i1 = max(0, w0 - PRE), min(self.panel.T - 1, w0 + POST)
        return simulate(P, self.strat(vid), self.cfg, start=self.panel.dates[i0], end=self.panel.dates[i1],
                        margin_mult=hooks.get("margin_mult"), exec_delay=hooks.get("exec_delay", 0),
                        fill_ratio=hooks.get("fill_ratio"), reject=hooks.get("reject")), i1

    def base(self, vid, w0):
        k = (vid, w0)
        if k not in self._base:
            tr, i1 = self._sim(vid, self.panel, w0)
            self._base[k] = {(v["oracle"], v["product"]) for v in check(self.panel, tr, self.cfg, w0, i1)}
        return self._base[k]

    def normalize(self, atk: Attack) -> tuple[Attack, list]:
        prims, notes = [], []
        for p in atk.prims:
            p2, n = clip_to_envelope(p, self.env, self.panel)
            p2.t0 = int(min(max(p2.t0, self.lo), self.hi))
            prims.append(p2)
            notes += n
        return Attack(prims, atk.arm, atk.note), notes

    def evaluate(self, vid: str, atk: Attack, count=True) -> dict:
        if count:
            self.n_eval += 1
        atk, notes = self.normalize(atk)
        ok, why = plausible(atk, self.panel, self.env)
        w0 = atk.t0
        P, hooks = apply(atk, self.panel)
        tr, i1 = self._sim(vid, P, w0, hooks)
        viol = check(P, tr, self.cfg, w0, i1, margin_mult=hooks["margin_mult"])
        fut = [p for p in atk.prims if p.kind == "future_perturb" and targets_of(p, self.panel)]
        if fut:
            # 对照面板 = 其余攻击照旧、只去掉"未来扰动"，这样差异只能来自未来数据
            rest = Attack([p for p in atk.prims if p.kind != "future_perturb"], atk.arm)
            P0 = apply(rest, self.panel)[0] if rest.prims else self.panel
            t_cut = min(p.t0 for p in fut) - 1
            fn = lambda pp: self._sim(vid, pp, w0, {k: v for k, v in hooks.items() if k != "future_from"})[0]
            viol += lookahead_probe(fn, P, P0, t_cut, max(0, w0 - PRE))
        b = self.base(vid, w0)
        attributed = [v for v in viol if (v["oracle"], v["product"]) not in b]
        sev = sum(min(5.0, abs(v["severity"])) + 1.0 for v in attributed)
        return {"vid": vid, "attack": atk.to_json(), "cls": atk.cls, "plausible": ok, "plaus_note": why,
                "clipped": notes, "violations": viol, "attributed": attributed, "severity": sev,
                "oracles": sorted({v["oracle"] for v in attributed})}


# ------------------------------------------------------------------ 臂
def fixed_list(ev: Evaluator, budget: int) -> list[Attack]:
    """A0 固定压力清单：20 项标准情景，按固定日期轮换铺满预算。事前冻结，不随结果调整。"""
    e = ev.env["products"]
    p99 = float(np.median([v["ret_p99"] for v in e.values()]))
    items = [
        ("sector_shock", "sector:black", {"size": -0.99}), ("sector_shock", "sector:metal", {"size": -0.99}),
        ("sector_shock", "sector:agri", {"size": 0.99}), ("sector_shock", "sector:chem", {"size": -0.99}),
        ("gap", "all", {"size": -0.04}), ("gap", "all", {"size": 0.04}),
        ("limit_lock", "RB", {"days": 2, "direction": -1}), ("limit_lock", "I", {"days": 2, "direction": 1}),
        ("limit_lock", "sector:agri", {"days": 1, "direction": -1}),
        ("vol_burst", "all", {"mult": 2.0, "length": 20}), ("vol_burst", "all", {"mult": 3.0, "length": 10}),
        ("liquidity_dry", "all", {"mult": 0.3, "length": 5}), ("margin_hike", "all", {"pp": 0.05, "length": 10}),
        ("exec_delay", "all", {"days": 1, "length": 10}), ("partial_fill", "all", {"ratio": 0.5, "length": 5}),
        ("reject", "all", {"length": 2}), ("whipsaw", "all", {"amp": p99, "cycles": 2, "period": 2}),
        ("missing_bars", "all", {"length": 2}), ("stale_bars", "all", {"length": 2}), ("bad_price", "RB", {"factor": 10.0}),
    ]
    n_dates = max(1, math.ceil(budget / len(items)))
    dates = np.linspace(ev.lo, ev.hi, n_dates).astype(int)
    out = []
    for d in dates:
        for k, t, pp in items:
            out.append(Attack([Primitive(k, t, int(d), dict(pp))], "A0_fixed"))
            if len(out) >= budget:
                return out
    return out


def run_fixed(ev, vid, budget, seed=0):
    return [ev.evaluate(vid, a) for a in fixed_list(ev, budget)]


def run_random(ev, vid, budget, seed):
    rng = np.random.default_rng(seed)
    res = []
    for _ in range(budget):
        prims = [random_primitive(rng, ev.panel, ev.lo, ev.hi)]
        if rng.random() < 0.3:
            p2 = random_primitive(rng, ev.panel, ev.lo, ev.hi)
            p2.t0 = prims[0].t0 + int(rng.integers(-3, 4))
            prims.append(p2)
        res.append(ev.evaluate(vid, Attack(prims, "A1_random")))
    return res


def _mutate(rng, atk: Attack, ev: Evaluator) -> Attack:
    a = Attack.from_json(atk.to_json())
    a.arm = "A2_evolve"
    r = rng.random()
    p = a.prims[int(rng.integers(len(a.prims)))]
    if r < 0.45:
        for k, v in p.params.items():
            if k in ("direction", "seed"):
                continue
            if isinstance(v, int):
                p.params[k] = int(max(1, v + rng.integers(-1, 2)))
            else:
                p.params[k] = float(v * rng.uniform(0.7, 1.4))
    elif r < 0.65:
        p.t0 = int(p.t0 + rng.integers(-10, 11))
    elif r < 0.8:
        pool = ev.panel.products + [f"sector:{s}" for s in SECTORS] + ["all"]
        if p.kind not in ("exec_delay",):
            p.target = str(rng.choice(pool)) if p.kind != "sector_shock" else f"sector:{rng.choice(list(SECTORS))}"
    elif r < 0.93 and len(a.prims) < 3:
        q = random_primitive(rng, ev.panel, ev.lo, ev.hi)
        q.t0 = p.t0 + int(rng.integers(-3, 4))
        a.prims.append(q)
    elif len(a.prims) > 1:
        a.prims.pop(int(rng.integers(len(a.prims))))
    return a


def run_evolve(ev, vid, budget, seed):
    """A2 质量多样性搜索：按（首个原语类型 × 命中判定器）分格保留最狠的攻击，再从格子里挑父本变异。"""
    rng = np.random.default_rng(seed)
    res, archive = [], {}
    n0 = min(40, budget // 4)
    for _ in range(n0):
        a = Attack([random_primitive(rng, ev.panel, ev.lo, ev.hi)], "A2_evolve")
        r = ev.evaluate(vid, a)
        res.append(r)
        _arch(archive, r)
    while len(res) < budget:
        if archive and rng.random() < 0.85:
            keys = list(archive)
            k = keys[int(rng.integers(len(keys)))]   # MAP-Elites：各格子等概率挑父本
            child = _mutate(rng, Attack.from_json(archive[k]["attack"]), ev)
        else:
            child = Attack([random_primitive(rng, ev.panel, ev.lo, ev.hi)], "A2_evolve")
        r = ev.evaluate(vid, child)
        res.append(r)
        _arch(archive, r)
    return res


def _arch(archive, r):
    kind = r["attack"]["prims"][0]["kind"]
    keys = [(kind, o) for o in r["oracles"]] or [(kind, "none")]
    for k in keys:
        if k not in archive or r["severity"] > archive[k]["severity"]:
            archive[k] = r
