"""判定器：什么才算"做错单"或"风险失控"。全部在跑之前定死，攻击方看不到被测代码。

三类：
- 硬不变量（无论行情如何都不该发生）；
- 风险预算（风险卡里声明的上限，超了且由攻击引起才算）；
- 蜕变关系（不知道正确答案时，用"改了输入，输出应该怎么变"查错）。
"""
from __future__ import annotations

import numpy as np

from futures_replay.data import Panel
from futures_replay.sim import Config, chain_returns

RISK_CARD = {"margin_cap_tol": 0.02, "margin_breach_days": 2, "dd_budget": 0.22, "day_loss_budget": 0.06,
             "ruin": 0.5, "stop_overrun": 0.04, "stop_overrun_days": 3, "spurious_stop_tol": 0.02,
             "stale_contract_days": 2, "target_lag_days": 6, "overfill_tol_lots": 1}
ORACLE_CLASS = {"margin_breach": "risk", "dd_runaway": "risk", "day_loss": "risk", "ruin": "risk", "stop_missed": "risk",
                "spurious_stop": "wrong_trade", "overfill": "wrong_trade", "wrong_side": "wrong_trade",
                "fill_on_locked": "wrong_trade", "stale_contract": "wrong_trade", "target_unreached": "wrong_trade",
                "stale_open": "robust", "lookahead": "metamorphic", "scale_break": "metamorphic"}


def _locked(panel, i, j, side):
    hi, lo, lu, ld = (panel.f[c][i, j] for c in ("high", "low", "limit_up", "limit_down"))
    if not (np.isfinite(hi) and np.isfinite(lo)) or hi - lo > 1e-9:
        return False
    return (side < 0 and np.isfinite(ld) and abs(lo - ld) < 1e-6) or (side > 0 and np.isfinite(lu) and abs(hi - lu) < 1e-6)


def true_margin(panel: Panel, tr, cfg: Config, margin_mult=None) -> np.ndarray:
    """判定器自己按真实乘数和真实（含提保）保证金率重算占用，不信被测策略的自报值。"""
    bm = np.array([panel.base_margin[p] for p in panel.products])
    mm = margin_mult if margin_mult is not None else np.ones((panel.T, panel.N))
    S = np.where(np.isfinite(panel.f["settlement"]), panel.f["settlement"], 0.0)
    occ = np.nansum(np.abs(tr.q) * S * panel.mult * (bm * mm + cfg.margin_addon), axis=1)
    return occ


def check(panel: Panel, tr, cfg: Config, w0: int, w1: int, margin_mult=None) -> list[dict]:
    """在 [w0, w1) 窗口内检查一次回放。返回违规列表。"""
    rc = RISK_CARD
    out = []
    eq = tr.equity
    cap0 = eq[tr.i0] if np.isfinite(eq[tr.i0]) else cfg.capital
    occ = true_margin(panel, tr, cfg, margin_mult)
    # 保证金越线连续多日
    run = 0
    for i in range(w0, w1):
        if not np.isfinite(eq[i]) or eq[i] <= 0:
            continue
        ex = occ[i] / eq[i] - (cfg.margin_cap + rc["margin_cap_tol"])
        run = run + 1 if ex > 0 else 0
        if run >= rc["margin_breach_days"]:
            out.append({"oracle": "margin_breach", "product": None, "day": i, "severity": float(ex)})
            break
    seg = eq[w0:w1]
    seg = seg[np.isfinite(seg)]
    if len(seg) > 1:
        pk = np.maximum.accumulate(np.concatenate([[eq[max(tr.i0, w0 - 1)]], seg]))
        dd = (np.concatenate([[eq[max(tr.i0, w0 - 1)]], seg]) / pk - 1).min()
        if dd < -rc["dd_budget"]:
            out.append({"oracle": "dd_runaway", "product": None, "day": w0, "severity": float(-dd - rc["dd_budget"])})
        dl = np.diff(np.concatenate([[eq[max(tr.i0, w0 - 1)]], seg])) / np.concatenate([[eq[max(tr.i0, w0 - 1)]], seg])[:-1]
        if dl.min() < -rc["day_loss_budget"]:
            out.append({"oracle": "day_loss", "product": None, "day": w0 + int(dl.argmin()), "severity": float(-dl.min() - rc["day_loss_budget"])})
        if seg.min() < rc["ruin"] * cap0:
            out.append({"oracle": "ruin", "product": None, "day": w0, "severity": float(1 - seg.min() / cap0)})
    S = panel.f["settlement"]
    stop_days = {(e[0], e[1]) for e in tr.events if e[2] == "stop"}
    ret = chain_returns(panel)
    for j in range(panel.N):
        run = 0
        for i in range(w0, w1):
            q = tr.q[i, j]
            ent = tr.entry[i, j] if tr.entry is not None else np.nan
            if q != 0 and np.isfinite(ent) and np.isfinite(S[i, j]) and ent > 0:
                adv = -np.sign(q) * (S[i, j] / ent - 1.0)
                locked = _locked(panel, i, j, -np.sign(q))
                run = run + 1 if (adv > cfg.stop_pct + rc["stop_overrun"] and not locked) else 0
                if run >= rc["stop_overrun_days"]:
                    out.append({"oracle": "stop_missed", "product": panel.products[j], "day": i, "severity": float(adv - cfg.stop_pct)})
                    break
            else:
                run = 0
        # 止损误触发：判定器按成交记录独立重建"应有的"止损参考价（开仓/加仓加权平均，换月按两腿成交价平移），
        # 策略触发止损时，若按该参考价计的不利幅度明显小于止损线，即为误触发。
        stops_j = sorted(i for (i, jj) in stop_days if jj == j and w0 <= i < w1)
        if stops_j:
            ref = np.full(panel.T, np.nan)
            pos, ent, p_old = 0.0, np.nan, np.nan
            fills_j = [f for f in tr.fills if f[1] == j]
            fi = 0
            for d in range(tr.i0, w1):
                while fi < len(fills_j) and fills_j[fi][0] == d:
                    _, _, _, lots, px, kind = fills_j[fi]
                    if kind == "roll_out":
                        p_old = px
                    elif kind == "roll_in":
                        if np.isfinite(ent) and np.isfinite(p_old) and p_old > 0:
                            ent *= px / p_old
                    else:
                        new_pos = pos + lots
                        if new_pos == 0:
                            ent = np.nan
                        elif pos == 0 or np.sign(new_pos) != np.sign(pos):
                            ent = px
                        elif abs(new_pos) > abs(pos):
                            ent = (ent * abs(pos) + px * abs(lots)) / abs(new_pos)
                        pos = new_pos
                    fi += 1
                ref[d] = ent
            for i in stops_j:
                q, si, e = tr.q[i, j], S[i, j], ref[i]
                if q == 0 or not (np.isfinite(si) and np.isfinite(e)) or e <= 0:
                    continue
                adv = -np.sign(q) * (si / e - 1.0)
                if adv < cfg.stop_pct - rc["spurious_stop_tol"]:
                    out.append({"oracle": "spurious_stop", "product": panel.products[j], "day": i, "severity": float(cfg.stop_pct - adv)})
                    break
    # 成交层面：每张目标单从下一交易日收盘起检查，直到下一次目标
    blk_any = {(e[0], e[1]) for e in tr.events if e[2] in ("locked", "no_liquidity", "cap_zero", "rejected", "stop", "margin_scale")}
    blk_all = {e[0] for e in tr.events if e[2] in ("dd_stop", "margin_scale")}
    orders = sorted(tr.orders)
    for n_o, (i, j, dq, tgt, w, due) in enumerate(orders):
        if not (w0 - 1 <= i < w1) or tgt == 0:
            continue
        nxt = next((o[0] for o in orders[n_o + 1:] if o[1] == j), w1)
        for d in range(due, min(nxt + 1, w1)):
            if (d, j) in blk_any or d in blk_all or (d - 1, j) in blk_any or (d - 1) in blk_all:
                break
            q = tr.q[d, j]
            # 多成交：按下单方向越过目标（买单成交后高于目标，卖单成交后低于目标）；只成交一部分不算
            if (dq > 0 and q > tgt + rc["overfill_tol_lots"]) or (dq < 0 and q < tgt - rc["overfill_tol_lots"]):
                out.append({"oracle": "overfill", "product": panel.products[j], "day": d, "severity": float(abs(q) / abs(tgt) - 1)})
                break
            if q * tgt < 0:
                out.append({"oracle": "wrong_side", "product": panel.products[j], "day": d, "severity": 1.0})
                break
    for (i, j, c, lots, px, kind) in tr.fills:
        if not (w0 <= i < w1):
            continue
        if kind == "trade" and _locked(panel, i, j, np.sign(lots)):
            out.append({"oracle": "fill_on_locked", "product": panel.products[j], "day": i, "severity": 1.0})
        if kind == "trade" and lots != 0:
            c0, v0 = panel.f["close"][i, j], panel.f["volume"][i, j]
            stale = (not np.isfinite(c0)) or (not np.isfinite(v0)) or v0 <= 0
            if i > 0 and not stale:
                same = all(panel.f[x][i, j] == panel.f[x][i - 1, j] for x in ("open", "high", "low", "close", "volume"))
                stale = stale or same
            if stale and (tr.q[i - 1, j] == 0 or np.sign(lots) == np.sign(tr.q[i - 1, j])):
                out.append({"oracle": "stale_open", "product": panel.products[j], "day": i, "severity": 1.0})
    for j in range(panel.N):
        run = 0
        for i in range(w0, w1):
            held, cur = tr.held[i, j], panel.contract[i, j]
            can_roll = (panel.pf_contract[i, j] == held and np.isfinite(panel.pf["open"][i, j]) and np.isfinite(panel.f["open"][i, j])
                        and panel.f["volume"][i, j] > 0)
            run = run + 1 if (tr.q[i, j] != 0 and held is not None and cur is not None and held != cur and can_roll) else 0
            if run >= rc["stale_contract_days"]:
                out.append({"oracle": "stale_contract", "product": panel.products[j], "day": i, "severity": float(run)})
                break
    # 目标长期未达成且没有锁板/无量/拒单记录
    blockers = {(e[0], e[1]) for e in tr.events if e[2] in ("locked", "no_liquidity", "cap_zero", "partial", "rejected", "stop")}
    blockers |= {(e[0], jj) for e in tr.events if e[2] in ("dd_stop", "margin_scale") for jj in range(panel.N)}
    for (i, j, dq, tgt, w, due) in tr.orders:
        if not (w0 <= i < w1):
            continue
        k = due + rc["target_lag_days"] - 1
        if k < w1 and tr.q[k, j] != tgt and np.all(~np.isfinite(tr.target[i + 1:k + 1, j])):
            if not any((d, j) in blockers for d in range(i + 1, k + 1)):
                out.append({"oracle": "target_unreached", "product": panel.products[j], "day": i, "severity": float(abs(tr.q[k, j] - tgt))})
    return out


def lookahead_probe(sim_fn, panel_attacked, panel_orig, t_cut: int, w0: int) -> list[dict]:
    """蜕变关系：只改 t_cut 之后的数据，t_cut 及之前的目标仓位必须完全相同。"""
    a = sim_fn(panel_orig)
    b = sim_fn(panel_attacked)
    ta, tb = a.target[w0:t_cut + 1], b.target[w0:t_cut + 1]
    same = np.array_equal(np.nan_to_num(ta, nan=-9e9), np.nan_to_num(tb, nan=-9e9))
    if same:
        return []
    diff = np.where(np.nan_to_num(ta, nan=-9e9) != np.nan_to_num(tb, nan=-9e9))
    return [{"oracle": "lookahead", "product": panel_orig.products[int(diff[1][0])], "day": int(w0 + diff[0][0]), "severity": float(len(diff[0]))}]
