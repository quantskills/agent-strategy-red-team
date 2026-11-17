"""埋入缺陷的策略版本（变异体）。本文件在任何搜索开始前写定并记录 sha256；搜索方只看得到版本编号。

公开（只用于调通流程）：V04、V07、V10。封存（结果只在这些上报告）：V01、V02、V03、V05、V06、V08、V09。
EQ 为行为完全等价的重构版本（阴性对照），CLEAN 为原策略。
"""
from __future__ import annotations

import math

import numpy as np

from futures_replay.sim import StrategyS0


class Clean(StrategyS0):
    vid = "CLEAN"


class EQ(StrategyS0):
    """阴性对照：用另一种写法实现同样的权重分配（降序排序后取反），行为应逐位一致。"""
    vid = "EQ"

    def weights(self, sig, vol, eligible):
        n = int(eligible.sum())
        w = np.zeros_like(sig)
        if n < self.cfg.min_products:
            return w
        idx = np.where(eligible)[0]
        desc = idx[np.argsort(-sig[idx], kind="stable")]
        k = max(1, n // 3)
        asc = idx[np.argsort(sig[idx])]
        w[asc[-k:]] = 1.0 / vol[asc[-k:]]
        w[asc[:k]] = -1.0 / vol[asc[:k]]
        _ = desc
        for _i in range(3):
            g = np.abs(w).sum()
            if g == 0:
                break
            w = np.clip(w / g * self.cfg.gross_leverage, -self.cfg.max_weight, self.cfg.max_weight)
        return w


class V01(StrategyS0):
    """未来函数：信号窗口多看了一天。"""
    vid = "V01"

    def signal(self, ret, i):
        return super().signal(ret, min(i + 1, ret.shape[0] - 1))


class V02(StrategyS0):
    """波动率估计窗口过短且去掉下限：低波动时仓位失控。"""
    vid = "V02"

    def vol(self, ret, i):
        w = ret[max(0, i - 4):i + 1]
        v = np.nanstd(w, axis=0) * math.sqrt(252)
        return np.where(v > 1e-4, v, 1e-4)


class V03(StrategyS0):
    """方向错误：空头持仓永不触发止损。"""
    vid = "V03"

    def stop_hit(self, side, entry, px):
        if side < 0:
            return False
        return super().stop_hit(side, entry, px)


class V04(StrategyS0):
    """换月后止损参考价不随新合约平移，升贴水被当成亏损。"""
    vid = "V04"
    flags = {**StrategyS0.flags, "rebase_entry_on_roll": False}


class V05(StrategyS0):
    """保证金检查用静态保证金率，看不到交易所提保。"""
    vid = "V05"
    flags = {**StrategyS0.flags, "margin_uses_hike": False}


class V06(StrategyS0):
    """回撤停机的基准在每次调仓时被重置，慢速失血时停机失效。"""
    vid = "V06"
    flags = {**StrategyS0.flags, "dd_peak_reset_on_rebalance": True}


class V07(StrategyS0):
    """陈旧/缺失数据检查被删除。"""
    vid = "V07"

    def is_stale(self, panel, i, j):
        return False


class V08(StrategyS0):
    """回测假设锁板时也能成交。"""
    vid = "V08"
    flags = {**StrategyS0.flags, "block_locked_fill": False}


class V09(StrategyS0):
    """部分成交后把已成交部分重复报单。"""
    vid = "V09"
    flags = {**StrategyS0.flags, "resubmit_full_after_partial": True}


class V10(StrategyS0):
    """单位错误：铁矿石（I）合约乘数按 10 计算（实际 100），仓位放大 10 倍。"""
    vid = "V10"

    def lots(self, w, equity, settle, mult):
        m = mult.copy()
        if hasattr(self, "_i_idx") and self._i_idx is not None:
            m[self._i_idx] = m[self._i_idx] / 10.0
        return super().lots(w, equity, settle, m)


VARIANTS = {c.vid: c for c in [Clean, EQ, V01, V02, V03, V04, V05, V06, V07, V08, V09, V10]}
OPEN = ["V04", "V07", "V10"]
SEALED = ["V01", "V02", "V03", "V05", "V06", "V08", "V09"]
DEFECT_LAYER = {"V01": "信号", "V02": "仓位", "V03": "风控-止损", "V04": "风控-止损/换月", "V05": "风控-保证金",
                "V06": "风控-回撤停机", "V07": "数据校验", "V08": "执行假设", "V09": "执行-报单", "V10": "仓位-乘数"}
