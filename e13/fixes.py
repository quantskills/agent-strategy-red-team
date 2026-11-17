"""修复版 S1：针对红队在原策略 S0 上确认的漏洞做的三处修复。搜索阶段冻结的文件一律不改，修复独立成文件。

F1 板块敞口上限：单板块总名义 ≤ 0.5 倍权益。依据风险卡的单日亏损预算 6%：
   商品单日涨跌停幅度最高约 9%（铁矿石 10% 档除外按 9% 计），0.5 × 9% ≈ 4.5% < 6%，留出余量；不是调参得到的。
F2 数据校验层：结算价越出当日涨跌停（容差 1 跳）或相对昨结算变动超过涨跌停幅度 + 1%，判为坏数据，
   整根 K 线按前一日值处理（不用于盯市，不据此交易）。
F3 陈旧检测：整根 K 线（开高低收量）与前一日完全相同，也判为陈旧，不新开仓。
"""
from __future__ import annotations

import numpy as np

from futures_replay.data import Panel
from futures_replay.sim import StrategyS0
from grammar import SECTORS

SECTOR_GROSS_CAP = 0.5


class S1(StrategyS0):
    vid = "S1"
    name = "S1_xsmom63_band25_fixed"
    version = "1.2.0"
    _products: list | None = None

    def weights(self, sig, vol, eligible):
        w = super().weights(sig, vol, eligible)
        if not self._products:
            return w
        for sec, names in SECTORS.items():
            idx = [self._products.index(p) for p in names if p in self._products]
            g = float(np.abs(w[idx]).sum())
            if g > SECTOR_GROSS_CAP:
                w[idx] = w[idx] * SECTOR_GROSS_CAP / g
        return w

    def is_stale(self, panel, i, j):
        if super().is_stale(panel, i, j):
            return True
        if i > 0:
            same = all(panel.f[c][i, j] == panel.f[c][i - 1, j] for c in ("open", "high", "low", "close", "volume"))
            if same:
                return True
        return False


def sanitize_panel(panel: Panel) -> tuple[Panel, int]:
    """F2：坏价格整根按前一日处理。返回清洗后的面板副本与被替换的格子数。"""
    P = panel.copy()
    n = 0
    tick = np.array([P.tick[p] for p in P.products])
    lim = np.array([P.limit_pct[p] for p in P.products])
    S, ps = P.f["settlement"], P.f["pre_settlement"]
    lu, ld = P.f["limit_up"], P.f["limit_down"]
    for t in range(1, P.T):
        for j in range(P.N):
            s = S[t, j]
            if not np.isfinite(s):
                continue
            bad = False
            if np.isfinite(lu[t, j]) and np.isfinite(ld[t, j]):
                bad = s > lu[t, j] + tick[j] or s < ld[t, j] - tick[j]
            if not bad and np.isfinite(ps[t, j]) and ps[t, j] > 0:
                bad = abs(s / ps[t, j] - 1.0) > lim[j] + 0.01
            if bad:
                n += 1
                for c in ("open", "high", "low", "close", "settlement", "volume"):
                    P.f[c][t, j] = P.f[c][t - 1, j]
    return P, n


# ---------------------------------------------------------------- 修复迭代 2（迭代 1 回归未通过后的改法）
# 迭代 1 的两处问题（见 ATTEMPTS.md）：
#   a) 板块“总”敞口上限把板块内对冲着的多空腿也砍掉，保留期年化从 -1.2% 掉到 -5.1%；
#      锁板对多头和空头方向相反，单日损失取决于板块“净”敞口，因此改为净敞口上限。
#   b) 校验规则“变动超过常规涨跌停幅度 + 1%”把交易所扩板日的真实行情误判为坏数据（干净数据上 9 格，
#      如 2020-02-03、2021-10-28），改为只认当天数据里的实际涨跌停范围。
SECTOR_NET_CAP = 0.5


class S1v2(S1):
    vid = "S1v2"
    name = "S1v2_xsmom63_band25_netcap_sanitize"
    version = "1.2.1"

    def weights(self, sig, vol, eligible):
        w = StrategyS0.weights(self, sig, vol, eligible)
        if not self._products:
            return w
        for sec, names in SECTORS.items():
            idx = [self._products.index(p) for p in names if p in self._products]
            net = float(w[idx].sum())
            if abs(net) > SECTOR_NET_CAP and np.abs(w[idx]).sum() > 0:
                # 只缩净敞口所在一侧，保留板块内对冲
                side = np.sign(net)
                heavy = [k for k in idx if np.sign(w[k]) == side]
                hs = float(np.abs(w[heavy]).sum())
                excess = abs(net) - SECTOR_NET_CAP
                if hs > 0:
                    w[heavy] = w[heavy] * max(0.0, (hs - excess) / hs)
        return w


def sanitize_panel_v2(panel: Panel) -> tuple[Panel, int]:
    """只认当天实际涨跌停范围（容差 1 跳）；范围外的结算价判坏，整根按前一日处理。"""
    P = panel.copy()
    n = 0
    tick = np.array([P.tick[p] for p in P.products])
    S, lu, ld = P.f["settlement"], P.f["limit_up"], P.f["limit_down"]
    for t in range(1, P.T):
        for j in range(P.N):
            s = S[t, j]
            if not (np.isfinite(s) and np.isfinite(lu[t, j]) and np.isfinite(ld[t, j])):
                continue
            if s > lu[t, j] + tick[j] or s < ld[t, j] - tick[j]:
                n += 1
                for c in ("open", "high", "low", "close", "settlement", "volume"):
                    P.f[c][t, j] = P.f[c][t - 1, j]
    return P, n
