"""A3 LLM 红队臂：模型只看到策略卡（黑盒描述）、攻击语法与上界、预算、历史攻击结果，输出攻击程序 JSON。

不读被测代码，不冒充平台原生多智能体；循环是显式脚本。所有请求与回复原样记录，便于复跑和计费核对。
Key 只从环境变量 LLMX_API_KEY 读取；未设置时本臂跳过并在报告里写明。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request

import numpy as np

from grammar import ALL_KINDS, REAL_KINDS, ROBUST_KINDS, SECTORS, Attack, Primitive

BASE_URL = os.getenv("LLMX_BASE_URL", "https://llmx.pandaaiquant.com")
MODEL = os.getenv("REDTEAM_MODEL", "DeepSeek-V4-flash")

STRATEGY_CARD = """被测策略（黑盒）：国内商品期货 11 个品种（RB,I,CU,AL,M,P,MA,TA,SA,AP,JD）的周频截面动量策略。
周五收盘按过去 63 日收益排序，做多涨得最多的三分之一、做空跌得最多的三分之一，逆波动率加权，总杠杆约 1.5 倍名义，目标变化不足 25% 不调仓。
下一交易日开盘成交；主力标签切换日开盘换月；风险卡：单品种不利 8% 止损、组合回撤 15% 全部平仓并冷却 5 天、
保证金占用上限 25% 权益、数据缺失或无成交量时不新开仓。成交受涨跌停锁板和当日成交量 10% 的限制。"""

GRAMMAR = """攻击由 1-3 个原语组成，每个原语 {"kind","target","t0","params"}：
- target: 品种代码 / "sector:black|metal|agri|chem" / "all"；t0: 整数交易日序号（会被夹进开发期窗口 [LO,HI]）。
真实情景（计入主结论）：
  gap{size}（单日跳空，|size|≤品种历史最大跳空且≤涨跌停）；limit_lock{days,direction(+1/-1)}（连续锁板，days≤同板块历史最长）；
  vol_burst{mult,length}（收益放大，mult≤历史波动比上界）；whipsaw{amp,cycles,period}（来回洗盘，amp≤历史99分位日收益）；
  liquidity_dry{mult,length}（成交量乘数，mult≥历史最低比例）；margin_hike{pp,length}（提保，pp≤0.05）；
  sector_shock{size}（板块同日冲击）；exec_delay{days,length}（下单延迟1-2天）；partial_fill{ratio,length}；reject{length}。
软件健壮性（单独统计）：missing_bars{length}；stale_bars{length}（行情冻结重复）；bad_price{factor}；future_perturb{scale,seed}（只改未来数据，检验未来函数）。
超出上界的参数会被夹回上界；组合攻击若任一品种 5 日累计注入收益超过历史 5 日最大值，判为不合理。"""

ORACLES = """判定器（攻击方需要触发其中之一，且无攻击时同窗口不出现）：margin_breach 保证金连续2日超上限；dd_runaway 窗口回撤>22%；
day_loss 单日亏损>6%；ruin 权益<50%；stop_missed 不利超过止损线+4%持续3日且未锁板；spurious_stop 止损误触发；overfill 超目标持仓；
wrong_side 持仓方向与目标相反；fill_on_locked 锁板方向上成交；stale_contract 持有非主力合约≥2日；target_unreached 目标6日未达成且无阻断；
stale_open 在陈旧/缺失数据上开仓；lookahead 只改未来数据却改变了过去的目标仓位。"""


def _post(payload: dict, key: str, timeout=120) -> dict:
    req = urllib.request.Request(f"{BASE_URL}/v1/messages", data=json.dumps(payload).encode(),
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _parse(text: str) -> list[dict]:
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
        return arr if isinstance(arr, list) else []
    except json.JSONDecodeError:
        return []


def run_llm(ev, vid, budget, seed, log_path, batch=30) -> list[dict]:
    key = os.getenv("LLMX_API_KEY")
    if not key:
        return []
    rng = np.random.default_rng(seed)
    res, calls = [], []
    while len(res) < budget:
        n = min(batch, budget - len(res))
        top = sorted(res, key=lambda r: -r["severity"])[:12]
        recent_fail = [r for r in res[-40:] if not r["oracles"]][:8]
        hist = [{"attack": r["attack"]["text"], "oracles": r["oracles"], "severity": round(r["severity"], 2)} for r in top]
        hist_f = [r["attack"]["text"] for r in recent_fail]
        prompt = (f"你是策略红队。目标：在合理范围内找出让下列策略做错单或风险失控的条件。\n{STRATEGY_CARD}\n\n{GRAMMAR}\n\n{ORACLES}\n\n"
                  f"开发期窗口 t0 取值 [{ev.lo},{ev.hi}]。剩余预算 {budget - len(res)} 次评估，本轮给出恰好 {n} 个攻击。\n"
                  f"已命中的攻击（按严重度）：{json.dumps(hist, ensure_ascii=False)}\n最近未命中的：{json.dumps(hist_f, ensure_ascii=False)}\n"
                  f"尽量覆盖不同的判定器和不同的攻击类型，避免重复已命中的同一种打法。随机种子提示 {int(rng.integers(1e6))}。\n"
                  "只输出一个 JSON 数组，每个元素 {\"prims\":[{\"kind\":..,\"target\":..,\"t0\":..,\"params\":{..}}],\"why\":\"一句话理由\"}。")
        payload = {"model": MODEL, "max_tokens": int(os.getenv("REDTEAM_MAX_TOKENS", "8000")),
                   "messages": [{"role": "user", "content": prompt}]}
        if os.getenv("REDTEAM_THINKING", "off") == "off":
            # A3 第一次运行中，带思考的模型把 4000 token 全部用在思考上，正文 JSON 被截断（0/3600 可解析），故默认关闭
            payload["thinking"] = {"type": "disabled"}
        t = time.time()
        err, text, usage = None, "", {}
        try:
            resp = _post(payload, key)
            text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
            usage = resp.get("usage", {})
        except Exception as e:  # noqa: BLE001
            err = str(e)[:300]
        items = _parse(text)
        calls.append({"vid": vid, "seed": seed, "t": round(time.time() - t, 1), "n_req": n, "n_parsed": len(items),
                      "usage": usage, "error": err, "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:12],
                      "prompt": prompt, "response": text})
        if not items:
            # 解析失败也计预算，防止无限重试；用随机攻击补位并标记
            from grammar import random_primitive
            items = [{"prims": [vars(random_primitive(rng, ev.panel, ev.lo, ev.hi))], "why": "fallback-random"} for _ in range(n)]
        for it in items[:n]:
            try:
                prims = [Primitive(str(p["kind"]), str(p.get("target", "all")), int(p.get("t0", ev.lo)), dict(p.get("params", {})))
                         for p in it.get("prims", [])][:3]
                prims = [p for p in prims if p.kind in ALL_KINDS]
                if not prims:
                    raise ValueError("no valid prims")
                a = Attack(prims, "A3_llm", note=str(it.get("why", ""))[:200])
                r = ev.evaluate(vid, a)
                r["llm_why"] = a.note
                r["llm_fallback"] = it.get("why") == "fallback-random"
            except Exception as e:  # noqa: BLE001
                ev.n_eval += 1
                r = {"vid": vid, "attack": {"text": f"invalid: {str(e)[:80]}", "prims": [], "arm": "A3_llm", "cls": "invalid"},
                     "cls": "invalid", "plausible": False, "violations": [], "attributed": [], "severity": 0.0, "oracles": [], "invalid": True}
            res.append(r)
            if len(res) >= budget:
                break
    with open(log_path, "a") as f:
        for c in calls:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return res
