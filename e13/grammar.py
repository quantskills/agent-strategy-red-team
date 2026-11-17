"""攻击语法：每个攻击是带参数的小程序，参数上界来自开发期（2020–2023）各品种的历史包络或交易所规则。

两类攻击严格分开：
- real：真实可能发生的市场或执行情景，计入主结论；
- robust：仅用于软件健壮性的异常输入（缺数、陈旧、坏价、未来扰动探针），单独统计。
"""
from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field, asdict

import numpy as np

from futures_replay.data import Panel
from futures_replay.sim import chain_returns

SECTORS = {"black": ["RB", "I"], "metal": ["CU", "AL"], "agri": ["M", "P", "AP", "JD"], "chem": ["MA", "TA", "SA"]}
REAL_KINDS = ["gap", "limit_lock", "vol_burst", "whipsaw", "liquidity_dry", "margin_hike", "sector_shock",
              "exec_delay", "partial_fill", "reject"]
ROBUST_KINDS = ["missing_bars", "stale_bars", "bad_price", "future_perturb"]
ALL_KINDS = REAL_KINDS + ROBUST_KINDS


@dataclass
class Primitive:
    kind: str
    target: str              # 品种代码或 sector:<name> 或 all
    t0: int                  # 面板行号
    params: dict = field(default_factory=dict)

    def text(self) -> str:
        p = ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in self.params.items())
        return f"{self.kind}({self.target} @{self.t0}: {p})"


@dataclass
class Attack:
    prims: list
    arm: str = ""
    note: str = ""

    @property
    def cls(self) -> str:
        return "robust" if any(p.kind in ROBUST_KINDS for p in self.prims) else "real"

    @property
    def t0(self) -> int:
        return min(p.t0 for p in self.prims)

    def text(self) -> str:
        return " + ".join(p.text() for p in self.prims)

    def to_json(self) -> dict:
        return {"prims": [asdict(p) for p in self.prims], "arm": self.arm, "cls": self.cls, "text": self.text()}

    @staticmethod
    def from_json(d: dict) -> "Attack":
        return Attack([Primitive(**p) for p in d["prims"]], d.get("arm", ""), d.get("note", ""))


# ------------------------------------------------------------------ 包络
def envelope(panel: Panel, start: str = "20200102", end: str = "20231229") -> dict:
    i0, i1 = panel.idx(start), panel.idx(end)
    r = chain_returns(panel)[i0:i1]
    env = {"window": [start, end], "products": {}}
    for j, p in enumerate(panel.products):
        rj = r[:, j][np.isfinite(r[:, j])]
        o, ps = panel.f["open"][i0:i1, j], panel.f["pre_settlement"][i0:i1, j]
        gap = np.abs(o / ps - 1.0)
        gap = gap[np.isfinite(gap)]
        c, lu, ld = panel.f["close"][i0:i1, j], panel.f["limit_up"][i0:i1, j], panel.f["limit_down"][i0:i1, j]
        hi, lo = panel.f["high"][i0:i1, j], panel.f["low"][i0:i1, j]
        locked = ((np.abs(hi - lo) < 1e-9) & ((np.abs(c - lu) < 1e-9) | (np.abs(c - ld) < 1e-9)))
        run, mx = 0, 0
        for x in locked:
            run = run + 1 if x else 0
            mx = max(mx, run)
        rv = np.array([np.nanstd(r[max(0, k - 19):k + 1, j]) for k in range(len(r))])
        base = np.nanmedian(rv)
        v = panel.f["volume"][i0:i1, j]
        vmed = np.array([np.nanmedian(v[max(0, k - 20):k]) if k > 5 else np.nan for k in range(len(v))])
        vr = v / vmed
        vr = vr[np.isfinite(vr) & (vr > 0)]
        cum5 = np.array([np.nanprod(1 + rj[k:k + 5]) - 1 for k in range(max(0, len(rj) - 4))]) if len(rj) > 5 else np.array([0.1])
        env["products"][p] = {
            "limit_pct": float(panel.limit_pct[p]),
            "gap_max": float(min(panel.limit_pct[p], np.nanmax(gap))) if len(gap) else float(panel.limit_pct[p]),
            "ret_p99": float(np.nanquantile(np.abs(rj), 0.99)) if len(rj) else 0.03,
            "lock_run_max_obs": int(mx),
            "vol_ratio_max": float(np.nanmax(rv) / base) if base > 0 else 2.0,
            "volume_ratio_min": float(np.nanmin(vr)) if len(vr) else 0.3,
            "cum5_abs_max": float(np.nanmax(np.abs(cum5))) if len(cum5) else 0.1,
        }
    allmx = max(v["lock_run_max_obs"] for v in env["products"].values())
    for p, v in env["products"].items():
        sec = next((s for s, ps in SECTORS.items() if p in ps), None)
        sec_mx = max(env["products"][q]["lock_run_max_obs"] for q in SECTORS.get(sec, [p]) if q in env["products"])
        v["lock_days_max"] = int(max(1, sec_mx, min(2, allmx)))
    env["rule_bounds"] = {"margin_hike_pp_max": 0.05, "exec_delay_max": 2, "partial_fill_min": 0.3,
                          "reject_days_max": 3, "len_max": 20, "source_margin": "交易所在连续涨跌停或节假日前上调保证金的常见幅度（规则上限，非历史拟合）"}
    return env


# ------------------------------------------------------------------ 合法性与合理性
BOUNDS = {  # 参数 -> (下界, 上界) 的取法
    "gap": ["size"], "limit_lock": ["days", "direction"], "vol_burst": ["mult", "length"],
    "whipsaw": ["amp", "cycles", "period"], "liquidity_dry": ["mult", "length"], "margin_hike": ["pp", "length"],
    "sector_shock": ["size"], "exec_delay": ["days", "length"], "partial_fill": ["ratio", "length"],
    "reject": ["length"], "missing_bars": ["length"], "stale_bars": ["length"], "bad_price": ["factor"],
    "future_perturb": ["scale"],
}


def targets_of(prim: Primitive, panel: Panel) -> list[int]:
    if prim.target == "all":
        return list(range(panel.N))
    if prim.target.startswith("sector:"):
        names = SECTORS.get(prim.target.split(":", 1)[1], [])
        return [panel.products.index(p) for p in names if p in panel.products]
    return [panel.products.index(prim.target)] if prim.target in panel.products else []


def clip_to_envelope(prim: Primitive, env: dict, panel: Panel) -> tuple[Primitive, list[str]]:
    """把参数夹进包络；返回被夹过的参数说明。真实类攻击必须在包络内。"""
    p = copy.deepcopy(prim)
    notes = []
    tg = targets_of(p, panel)
    if not tg:
        return p, ["bad_target"]
    pe = [env["products"][panel.products[j]] for j in tg]
    rb = env["rule_bounds"]

    def cl(name, lo, hi):
        v = p.params.get(name)
        if v is None:
            p.params[name] = lo
            notes.append(f"{name}:missing")
            return
        nv = min(max(v, lo), hi)
        if nv != v:
            notes.append(f"{name}:{v:.4g}->{nv:.4g}")
        p.params[name] = type(v)(nv) if isinstance(v, int) else float(nv)
    k = p.kind
    if k == "gap":
        g = min(e["gap_max"] for e in pe)
        cl("size", -g, g)
    elif k == "limit_lock":
        cl("days", 1, min(e["lock_days_max"] for e in pe))
        p.params["direction"] = 1 if p.params.get("direction", -1) > 0 else -1
    elif k == "vol_burst":
        cl("mult", 1.0, min(e["vol_ratio_max"] for e in pe))
        cl("length", 3, rb["len_max"])
    elif k == "whipsaw":
        cl("amp", 0.0, min(e["ret_p99"] for e in pe))
        cl("cycles", 1, 4)
        cl("period", 1, 3)
    elif k == "liquidity_dry":
        cl("mult", max(e["volume_ratio_min"] for e in pe), 1.0)
        cl("length", 1, 10)
    elif k == "margin_hike":
        cl("pp", 0.0, rb["margin_hike_pp_max"])
        cl("length", 1, rb["len_max"])
    elif k == "sector_shock":
        g = min(min(e["limit_pct"], e["gap_max"]) for e in pe)
        cl("size", -g, g)
    elif k == "exec_delay":
        cl("days", 1, rb["exec_delay_max"])
        cl("length", 1, 10)
    elif k == "partial_fill":
        cl("ratio", rb["partial_fill_min"], 1.0)
        cl("length", 1, 5)
    elif k == "reject":
        cl("length", 1, rb["reject_days_max"])
    elif k in ("missing_bars", "stale_bars"):
        cl("length", 1, 5)
    elif k == "bad_price":
        cl("factor", 0.1, 10.0)
    elif k == "future_perturb":
        cl("scale", 0.01, 0.2)
    p.t0 = int(max(1, min(p.t0, panel.T - 2)))
    for kk in list(p.params):
        if isinstance(p.params[kk], (int, np.integer)) and kk in ("days", "length", "cycles", "period"):
            p.params[kk] = int(p.params[kk])
    return p, notes


def plausible(attack: Attack, panel: Panel, env: dict) -> tuple[bool, str]:
    """组合合理性：注入到任一品种的 5 日累计收益不超过该品种开发期 5 日最大绝对累计收益。"""
    if attack.cls == "robust":
        return True, "robust-class"
    inj = np.zeros((panel.T, panel.N))
    for pr in attack.prims:
        d = injected_returns(pr, panel)
        if d is not None:
            inj += d
    for j, p in enumerate(panel.products):
        x = inj[:, j]
        if not np.any(x):
            continue
        nz = np.where(x != 0)[0]
        lo, hi = nz.min(), nz.max()
        seg = x[lo:hi + 1]
        c5 = [abs(np.prod(1 + seg[k:k + 5]) - 1) for k in range(max(1, len(seg) - 4))]
        if max(c5) > env["products"][p]["cum5_abs_max"] + 1e-9:
            return False, f"{p}: 5日累计注入 {max(c5):.3f} > 历史上界 {env['products'][p]['cum5_abs_max']:.3f}"
    return True, "ok"


def injected_returns(prim: Primitive, panel: Panel):
    d = np.zeros((panel.T, panel.N))
    tg = targets_of(prim, panel)
    t0, k, pp = prim.t0, prim.kind, prim.params
    if k in ("gap", "sector_shock"):
        for j in tg:
            d[t0, j] = pp["size"]
    elif k == "limit_lock":
        for j in tg:
            lim = panel.limit_pct[panel.products[j]]
            for s in range(int(pp["days"])):
                if t0 + s < panel.T:
                    d[t0 + s, j] = pp["direction"] * lim
    elif k == "whipsaw":
        t = t0
        for _ in range(int(pp["cycles"])):
            for sgn in (1, -1):
                for _ in range(int(pp["period"])):
                    if t < panel.T:
                        for j in tg:
                            d[t, j] = sgn * pp["amp"]
                    t += 1
    else:
        return None
    return d


# ------------------------------------------------------------------ 施加
PRICE = ["open", "high", "low", "close", "settlement"]


def _scale_from(panel: Panel, j: int, t: int, factor: float):
    """t 日起所有价格乘 factor（含换月日旧合约价格）；t+1 日起昨结算同步。"""
    for c in PRICE:
        panel.f[c][t:, j] *= factor
    panel.f["pre_settlement"][t + 1:, j] *= factor
    for c in ["open", "high", "low", "close", "settlement", "limit_up", "limit_down"]:
        panel.pf[c][t:, j] *= factor
    panel.pf["pre_settlement"][t + 1:, j] *= factor


def _relimit(panel: Panel, j: int, t0: int):
    """按昨结算重算涨跌停并把价格夹进去；换月日旧合约（pf）用同样规则，避免新旧两腿价差被人为扭曲。"""
    lim = panel.limit_pct[panel.products[j]]
    for src in (panel.f, panel.pf):
        ps = src["pre_settlement"][t0:, j]
        src["limit_up"][t0:, j] = ps * (1 + lim)
        src["limit_down"][t0:, j] = ps * (1 - lim)
        for c in PRICE:
            if c in src:
                src[c][t0:, j] = np.minimum(np.maximum(src[c][t0:, j], src["limit_down"][t0:, j]), src["limit_up"][t0:, j])


def apply(attack: Attack, panel: Panel) -> tuple[Panel, dict]:
    """返回被攻击的面板副本与回放钩子。"""
    P = panel.copy()
    T, N = P.T, P.N
    hooks = {"margin_mult": np.ones((T, N)), "exec_delay": np.zeros(T, dtype=int), "fill_ratio": np.ones((T, N)),
             "reject": np.zeros((T, N), dtype=bool), "future_from": None}
    for pr in attack.prims:
        tg, t0, k, pp = targets_of(pr, P), pr.t0, pr.kind, pr.params
        if k in ("gap", "sector_shock", "whipsaw", "limit_lock"):
            d = injected_returns(pr, P)
            for j in tg:
                touched = []
                for t in np.where(d[:, j] != 0)[0]:
                    _scale_from(P, j, int(t), 1.0 + d[t, j])
                    touched.append(int(t))
                if touched:
                    _relimit(P, j, min(touched))
                if k == "limit_lock":
                    for t in touched:
                        lim_px = P.f["limit_up"][t, j] if pp["direction"] > 0 else P.f["limit_down"][t, j]
                        for c in PRICE:
                            P.f[c][t, j] = lim_px
                        P.f["volume"][t, j] = 0.0
                        if t + 1 < T:
                            P.f["pre_settlement"][t + 1, j] = lim_px
                    _relimit(P, j, min(touched))
        elif k == "vol_burst":
            r = chain_returns(P)
            for j in tg:
                for t in range(t0, min(T, t0 + int(pp["length"]))):
                    if np.isfinite(r[t, j]):
                        _scale_from(P, j, t, (1 + pp["mult"] * r[t, j]) / (1 + r[t, j]))
                _relimit(P, j, t0)
        elif k == "liquidity_dry":
            for j in tg:
                P.f["volume"][t0:t0 + int(pp["length"]), j] *= pp["mult"]
        elif k == "margin_hike":
            for j in tg:
                bm = P.base_margin[P.products[j]]
                hooks["margin_mult"][t0:t0 + int(pp["length"]), j] = (bm + pp["pp"]) / bm
        elif k == "exec_delay":
            hooks["exec_delay"][t0:t0 + int(pp["length"])] = int(pp["days"])
        elif k == "partial_fill":
            for j in tg:
                hooks["fill_ratio"][t0:t0 + int(pp["length"]), j] = pp["ratio"]
        elif k == "reject":
            for j in tg:
                hooks["reject"][t0:t0 + int(pp["length"]), j] = True
        elif k == "missing_bars":
            for j in tg:
                for c in list(P.f):
                    if P.f[c].dtype.kind == "f":
                        P.f[c][t0:t0 + int(pp["length"]), j] = np.nan
        elif k == "stale_bars":
            for j in tg:
                for t in range(t0, min(T, t0 + int(pp["length"]))):
                    for c in PRICE + ["volume", "open_interest"]:
                        P.f[c][t, j] = P.f[c][t0 - 1, j]
        elif k == "bad_price":
            for j in tg:
                for c in ["close", "settlement"]:
                    P.f[c][t0, j] *= pp["factor"]
        elif k == "future_perturb":
            rng = np.random.default_rng(int(pp.get("seed", 1)))
            for j in tg:
                f = np.exp(np.cumsum(rng.normal(0, pp["scale"] / math.sqrt(20), T - t0)))
                fprev = np.concatenate([[1.0], f[:-1]])
                for c in PRICE + ["limit_up", "limit_down"]:
                    P.f[c][t0:, j] *= f
                    P.pf[c][t0:, j] *= f
                P.f["pre_settlement"][t0:, j] *= fprev
                P.pf["pre_settlement"][t0:, j] *= fprev
            hooks["future_from"] = t0
    return P, hooks


def random_primitive(rng: np.random.Generator, panel: Panel, lo: int, hi: int, kinds=None) -> Primitive:
    kinds = kinds or ALL_KINDS
    k = str(rng.choice(kinds))
    tgt_pool = panel.products + [f"sector:{s}" for s in SECTORS] + (["all"] if k in ("exec_delay", "margin_hike", "liquidity_dry") else [])
    tgt = "all" if k == "exec_delay" else str(rng.choice(tgt_pool))
    u = rng.uniform
    params = {
        "gap": {"size": u(-0.12, 0.12)}, "limit_lock": {"days": int(rng.integers(1, 4)), "direction": int(rng.choice([-1, 1]))},
        "vol_burst": {"mult": u(1.0, 4.0), "length": int(rng.integers(3, 21))},
        "whipsaw": {"amp": u(0.0, 0.06), "cycles": int(rng.integers(1, 5)), "period": int(rng.integers(1, 4))},
        "liquidity_dry": {"mult": u(0.02, 1.0), "length": int(rng.integers(1, 11))},
        "margin_hike": {"pp": u(0.0, 0.06), "length": int(rng.integers(1, 21))},
        "sector_shock": {"size": u(-0.1, 0.1)}, "exec_delay": {"days": int(rng.integers(1, 3)), "length": int(rng.integers(1, 11))},
        "partial_fill": {"ratio": u(0.2, 1.0), "length": int(rng.integers(1, 6))}, "reject": {"length": int(rng.integers(1, 4))},
        "missing_bars": {"length": int(rng.integers(1, 6))}, "stale_bars": {"length": int(rng.integers(1, 6))},
        "bad_price": {"factor": float(rng.choice([0.1, 0.5, 2.0, 10.0]))}, "future_perturb": {"scale": u(0.01, 0.2), "seed": int(rng.integers(1, 1000))},
    }[k]
    if k == "sector_shock" and not tgt.startswith("sector:"):
        tgt = f"sector:{rng.choice(list(SECTORS))}"
    return Primitive(k, tgt, int(rng.integers(lo, hi)), params)
