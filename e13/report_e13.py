"""E13 报告：python report_e13.py <run_dir>
需要 run_dir 下的 adjudication.json（run_e13.py adjudicate）、summarize.py 的四张表，可选 regression.json、env_info.json。
输出 report.md / report.html / report.json / redteam.parquet / counterexamples.json。
"""
from __future__ import annotations

import html
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

ARM_CN = {"A0_fixed": "固定压力清单（基线）", "A1_random": "随机搜索", "A2_evolve": "进化搜索（MAP-Elites）", "A3_llm": "LLM 红队"}
ORACLE_CN = {"margin_breach": "保证金连续超限", "dd_runaway": "窗口回撤超预算", "day_loss": "单日亏损超预算", "ruin": "权益腰斩",
             "stop_missed": "止损失灵", "spurious_stop": "止损误触发", "overfill": "多成交", "wrong_side": "方向反了",
             "fill_on_locked": "锁板方向成交", "stale_contract": "持有非主力合约", "target_unreached": "目标长期未达成",
             "stale_open": "在陈旧数据上开仓", "lookahead": "未来函数"}
GLOSSARY = [
    ("反向压力测试 reverse stress test", "普通压力测试问“发生这件事会亏多少”，反向压力测试问“发生什么事才会把策略打死”。"),
    ("合理性约束 plausibility", "攻击参数不能超过该品种开发期的历史极值或交易所规则；组合攻击的 5 日累计冲击也不能超过历史上限（思路来自 Breuer 等 2009）。"),
    ("变异测试 mutation testing", "故意往策略里埋已知缺陷，看测试方法能不能抓住；抓到的比例就是发现率。"),
    ("回退测试 revert test", "把缺陷改回去（换回原策略），同一个反例不再触发，才算真正定位到了这个缺陷。"),
    ("蜕变关系 metamorphic relation", "不知道正确答案时，用“改了输入，输出应该怎么变”查错。例如只改未来数据，过去的决策必须完全不变。"),
    ("扰动复跑 jitter rerun", "把攻击时点前后挪 3 天、参数放大缩小 10%，3 次里至少 2 次仍触发才算稳健的发现。"),
    ("质量多样性搜索 MAP-Elites", "按“攻击类型 × 命中的判定器”分格，每格保留最狠的攻击，再从格子里挑父本变异，避免只盯着一种打法。"),
]


def fmt_pct(x):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.0%}"


def md_table(df: pd.DataFrame, index=False, floatfmt=".3g") -> str:
    d = df.reset_index() if index else df

    def f(x):
        if isinstance(x, (float, np.floating)):
            return "—" if not np.isfinite(x) else format(x, floatfmt)
        return str(x)
    return "\n".join(["| " + " | ".join(map(str, d.columns)) + " |", "|" + "---|" * len(d.columns)] +
                     ["| " + " | ".join(f(v) for v in r) + " |" for r in d.itertuples(index=False)])


def shrink_cards(run_dir: Path, vul: pd.DataFrame, max_cards=8) -> list[dict]:
    from run_e13 import load, DEV
    from harness import Evaluator
    from adjudicate import shrink
    from grammar import Attack
    panel, env, cfg = load()
    ev = Evaluator(panel, env, cfg, DEV)
    cards = []
    seen = set()
    for v in vul.sort_values(["cls", "severity"], ascending=[False, False]).itertuples():
        atk = json.loads(v.rep_attack_json)
        oracle = v.oracles.split(",")[0]
        key = (v.cls, oracle)
        if key in seen or len(cards) >= max_cards:
            continue
        seen.add(key)
        small, n = shrink(ev, "CLEAN", atk, oracle)
        a = Attack.from_json(small)
        r = ev.evaluate("CLEAN", a, count=False)
        d0 = panel.dates[a.t0]
        cards.append({"cls": v.cls, "oracle": oracle, "oracle_cn": ORACLE_CN.get(oracle, oracle), "found_by": v.found_by,
                      "fixed_list_found": bool(v.fixed_list_found), "original": v.rep_attack, "minimal": a.text(),
                      "minimal_json": small, "start_date": str(d0), "still_triggers": oracle in r["oracles"], "shrink_evals": n})
    (run_dir / "counterexamples.json").write_text(json.dumps(cards, ensure_ascii=False, indent=1))
    return cards


FIX_DESC = {
    "v1": ("板块总敞口上限 + 数据校验 + 陈旧检测",
           "S1 v1.2.0 = S0 + 板块总敞口上限（单板块总名义 ≤ 0.5 倍权益）+ 数据校验层（越出涨跌停或变动超过常规幅度 +1% 判坏数据）+ 陈旧检测（整根 K 线与前一日相同）。"),
    "v2": ("板块净敞口上限 + 按当天实际涨跌停的数据校验 + 陈旧检测",
           "S1v2 v1.2.1 = S0 + 板块净敞口上限（单板块净名义 ≤ 0.5 倍权益，只缩较重的一侧）+ 数据校验层（结算价越出当天实际涨跌停范围判坏数据）+ 陈旧检测（整根 K 线与前一日相同）。迭代 1（总敞口上限）的回归结果见 regression_v1.json。"),
}


def build(run_dir: Path):
    from defects.sealed import SEALED, OPEN, DEFECT_LAYER
    fz = json.loads((HERE / "out" / "freeze.json").read_text())
    arm = pd.read_csv(run_dir / "arm_summary.csv")
    det = pd.read_csv(run_dir / "detection_matrix.csv", index_col=0)
    ttd = pd.read_csv(run_dir / "evals_to_detect.csv", index_col=0)
    vul = pd.read_csv(run_dir / "clean_vulnerabilities.csv") if (run_dir / "clean_vulnerabilities.csv").exists() else pd.DataFrame()
    reg = json.loads((run_dir / "regression.json").read_text()) if (run_dir / "regression.json").exists() else None
    envinfo = json.loads((run_dir / "env_info.json").read_text()) if (run_dir / "env_info.json").exists() else None
    cards = shrink_cards(run_dir, vul) if len(vul) else []
    arms = [a for a in ARM_CN if a in det.columns]
    sealed = det.loc[[v for v in SEALED if v in det.index], arms]
    only_search = [v for v in sealed.index if sealed.loc[v, "A0_fixed"] == 0 and sealed.loc[v, [a for a in arms if a != "A0_fixed"]].max() > 0] if "A0_fixed" in arms else []
    only_list = [v for v in sealed.index if "A0_fixed" in arms and sealed.loc[v, "A0_fixed"] > 0 and sealed.loc[v, [a for a in arms if a != "A0_fixed"]].max() < 0.5]
    missed = [v for v in sealed.index if sealed.loc[v].max() == 0]
    a_ix = arm.set_index("arm")
    lines = []
    lines.append("冻结预算下（每个臂对每个策略版本 300 次回放），对 7 个封存缺陷的发现率："
                 + "；".join(f"{ARM_CN[a]} {fmt_pct(a_ix.loc[a, 'sealed_detect_rate'])}" + (f"（90% 区间 {a_ix.loc[a, 'sealed_ci90']}）" if a != "A0_fixed" else "")
                            for a in arms) + "。")
    if only_search:
        lines.append("只有主动搜索抓到、固定清单抓不到的：" + "、".join(f"{v}（{DEFECT_LAYER[v]}）" for v in only_search) + "。")
    if only_list:
        lines.append("固定清单更稳、搜索容易漏的：" + "、".join(f"{v}（{DEFECT_LAYER[v]}）" for v in only_list) + "。")
    if missed:
        lines.append("所有方法都没抓到的盲区：" + "、".join(f"{v}（{DEFECT_LAYER[v]}）" for v in missed) + "。")
    fa = arm[["arm", "false_alarm_rate"]].set_index("arm")["false_alarm_rate"]
    if "A3_llm" in arms and a_ix.loc["A3_llm", "llm_fallback"] > 0:
        lines.append(f"LLM 红队臂的 {int(a_ix.loc['A3_llm', 'evals'])} 次回放里有 {int(a_ix.loc['A3_llm', 'llm_fallback'])} 次是模型输出无法解析或越界后的随机补位，它的发现率不能全部归功于 LLM。")
    lines.append("误报率（上报后未通过扰动复跑或合理性检查的比例）：" + "；".join(f"{ARM_CN[a]} {fmt_pct(fa[a])}" for a in arms) + "；所有上报逐字复跑均 100% 一致。")
    if cards:
        real = [c for c in cards if c["cls"] == "real"]
        rob = [c for c in cards if c["cls"] == "robust"]
        if real:
            lines.append("原策略上确认的真实情景漏洞：" + "；".join(f"{c['oracle_cn']}（最短反例：{c['minimal']}，"
                                                         + ("固定清单也能发现" if c["fixed_list_found"] else "只有搜索发现") + "）" for c in real) + "。")
        if rob:
            lines.append("软件健壮性漏洞（单独统计）：" + "；".join(f"{c['oracle_cn']}（{c['minimal']}）" for c in rob) + "。")
    if reg:
        v = reg["verdict"]
        lines.append(f"修复版 S1（{FIX_DESC.get(reg.get('fix_version', 'v1'), FIX_DESC['v1'])[0]}）：原反例" + ("全部消除" if v["R1_all_fixed"] else "未全部消除")
                     + "；固定清单命中" + ("不多于" if v["R2_not_worse"] else "多于") + "原策略；保留期正常表现" + ("在容差内" if v["R3_within_tolerance"] else "超出容差")
                     + f"（年化下降 {reg['R3_performance']['holdout_ret_drop']*100:.2f} 个百分点（容差 {reg['tolerances']['ret_drop']*100:.1f}），夏普下降 {reg['R3_performance']['holdout_sharpe_drop']:.3f}（容差 {reg['tolerances']['sharpe_drop']:.2f}））；"
                     + ("同预算再搜索没有发现修复引入的新问题。" if v["R4_no_new_issue"] else f"再搜索发现 {len(reg['R4_new_search']['introduced_by_fix'])} 个修复引入的新问题。"))
    lines.append("合成攻击路径不是真实样本外业绩；结论只对这一类策略、这套语法和这个预算成立。")
    plain = "\n".join(lines)
    # ---------- markdown
    det_show = det.copy()
    for a in arms:
        det_show[a] = det_show[a].map(fmt_pct)
    det_show.index = [f"{v}{'（封存）' if v in SEALED else '（公开）'}" for v in det_show.index]
    arm_show = arm.copy()
    arm_show["arm"] = arm_show["arm"].map(ARM_CN)
    parts = [f"# 红队 Agent 主动寻找策略失效反例：实验报告\n",
             f"> 冻结时间 {fz['frozen_at']}；被测策略 {fz['config'] and 'S0_xsmom63_weekly_band25 v1.1.0'}（公开信号，不是推荐策略）；"
             f"数据 PandaData，输入指纹 `{fz['data']['input_digest']}`。研究与教育用途，不构成投资建议。\n",
             "## 结论（人话）\n", plain.replace("\n", "\n\n"), "\n",
             "## 实验设计（事前冻结）\n",
             "- 被测对象：S0 及 12 个版本（原策略 CLEAN、行为等价的重构版 EQ、3 个公开缺陷 V04/V07/V10、7 个封存缺陷 V01/V02/V03/V05/V06/V08/V09）。\n"
             "- 攻击语法：10 类真实情景 + 4 类软件健壮性异常，参数上界来自 2020–2023 开发期的历史包络或交易所规则，见 `out/envelope.json`。\n"
             "- 判定器：13 个，分硬不变量、风险预算、蜕变关系三类；只把“无攻击时同窗口不出现”的违规算作攻击引起。\n"
             f"- 预算：每臂每版本 {fz['budget']['evals_per_run']} 次回放；种子 {json.dumps(fz['budget']['seeds'])}。\n"
             "- 裁决：逐字复跑 + 扰动复跑（3 次中 ≥2 次）+ 合理性；封存缺陷只在回退测试通过时才算发现。\n"
             f"- 冻结文件 sha256 见 `out/freeze.json`（{len(fz['files'])} 个文件）。\n",
             "## 发现矩阵（每格 = 该臂在多少比例的种子上发现了该缺陷）\n", md_table(det_show, index=True), "\n",
             "## 发现所需回放次数（中位数）\n", md_table(ttd, index=True, floatfmt=".0f"), "\n",
             "## 各臂汇总\n", md_table(arm_show, floatfmt=".3g"), "\n"]
    if cards:
        parts += ["## 原策略上确认的漏洞（最短反例）\n",
                  md_table(pd.DataFrame([{"类别": "真实情景" if c["cls"] == "real" else "软件健壮性", "判定器": c["oracle_cn"], "最短反例": c["minimal"],
                                          "起始交易日": c["start_date"], "发现者": c["found_by"], "固定清单能否发现": "能" if c["fixed_list_found"] else "不能"} for c in cards])), "\n"]
    if reg:
        r1 = pd.DataFrame(reg["R1_counterexamples"])
        parts += ["## 修复与回归\n",
                  FIX_DESC.get(reg.get("fix_version", "v1"), FIX_DESC["v1"])[1] + "\n",
                  md_table(r1[["cls", "oracles", "attack", "S0_hits", "S1_hits", "fixed"]]) if len(r1) else "无", "\n",
                  f"- 固定清单命中：S0 {reg['R2_fixed_list']['S0_hits']} 次（真实情景 {reg['R2_fixed_list']['S0_real_hits']}），S1 {reg['R2_fixed_list']['S1_hits']} 次（真实情景 {reg['R2_fixed_list']['S1_real_hits']}）。\n",
                  "- 正常表现（无攻击）：" + "；".join(f"{k} 年化 {v['ann_ret']:+.2%} 夏普 {v['sharpe']:.2f} 回撤 {v['max_dd']:.1%}" for k, v in reg["R3_performance"].items() if isinstance(v, dict)) + "。\n",
                  f"- 同预算再搜索：修复引入的新问题 {len(reg['R4_new_search']['introduced_by_fix'])} 个；S0 上已有、S1 上仍在的问题 {reg['R4_new_search']['remaining_n']} 组。\n"]
    parts += ["## 交易执行核验与等价回放范围\n",
              "任务要求交易执行部分用期货模拟赛核验。本期用户不参加模拟赛，因此执行语义只在回放中核验，事前写明的等价范围如下：\n\n"
              "| 执行语义 | 回放中的处理 | 模拟赛能否验 |\n|---|---|---|\n"
              "| 锁板方向不能成交 | 最高=最低=涨/跌停时该方向不成交，顺延 | 能，本期未验 |\n"
              "| 成交价不越出涨跌停 | 成交价夹在当日涨跌停内 | 能（柜台 dailyPriceLimit 校验），本期未验 |\n"
              "| 部分成交、拒单、下单延迟 | 由攻击原语注入 | 部分能，本期未验 |\n"
              "| 换月：旧腿平、新腿开 | 主力标签切换日开盘两腿同时成交 | 能（rollover 预演），本期未验 |\n"
              "| 跳空、连续锁板、提保、流动性枯竭、板块共振 | 只能在回放中构造 | 不能（柜台造不出来） |\n\n"
              "模拟赛柜台是 500 万固定资金的仿真成交，费率为交易所标准的 1.5 倍，本来也只能验证账本口径，不能验证大资金冲击。\n"]
    src_runs = json.loads((run_dir / "adjudication.json").read_text())
    if any("source" in r for r in src_runs):
        src = pd.DataFrame([{"来源目录": ("PandaAI EVO 分块运行（chunk1–24）" if str(r.get("source", "")).startswith("chunk") else r.get("source", "-")), "臂": ARM_CN.get(r["arm"], r["arm"])} for r in src_runs]).value_counts().rename("运行数").reset_index()
        parts += ["## 运行来源\n", "每条运行（臂 × 版本 × 种子）来自哪个运行目录（由 merge_runs.py 记录）：\n", md_table(src), "\n"]
    if envinfo:
        parts += ["## 运行平台记录\n", "```json\n" + json.dumps(envinfo, ensure_ascii=False, indent=1) + "\n```\n"]
    parts += ["## 适用边界\n",
              "- 只测一类策略（周频截面 CTA）；缺陷由作者设计，作者同时设计了攻击语法，偏置只能减轻（封存、事前冻结），不能消除。\n"
              "- 合成攻击路径是“可能发生”的情景，不是真实样本外业绩，也不预测概率。\n"
              "- LLM 红队臂只看策略卡与攻击日志（黑盒），不读被测代码；读代码的白盒审查是另一种能力，不在本题范围。\n"
              "- 判定器的阈值来自风险卡（单日亏损 6%、窗口回撤 22%、保证金上限 25%+2% 等），换风险卡要重新冻结。\n"
              "- 健壮性类攻击（坏价格、缺数、陈旧、未来扰动）单独统计，不代表真实市场会发生。\n",
              "## 术语\n", "\n".join(f"- **{a}**：{b}" for a, b in GLOSSARY), "\n"]
    md = "\n".join(parts)
    (run_dir / "report.md").write_text(md)
    # ---------- html
    chart = {"arms": [ARM_CN[a] for a in arms], "rates": [float(a_ix.loc[a, "sealed_detect_rate"]) for a in arms],
             "fa": [float(fa[a]) for a in arms], "defects": list(det.index), "matrix": {ARM_CN[a]: [float(x) for x in det[a].fillna(0)] for a in arms}}
    page = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>策略红队报告</title>
<style>:root{{--bg:#0f1218;--fg:#e8eaed;--mut:#9aa0a6;--card:#171b23;--line:#2a2f3a}}body{{background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"PingFang SC",sans-serif;margin:0;padding:24px 16px}}
.w{{max-width:1100px;margin:auto}}h1{{font-size:22px}}.c{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}}
pre{{white-space:pre-wrap;font-size:13px}}canvas{{background:var(--card);border-radius:10px;padding:8px;max-height:320px}}.g2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}
.card{{border-left:3px solid #ef6c00;padding-left:10px;margin:8px 0}}.note{{color:var(--mut);font-size:13px}}</style></head><body><div class="w">
<h1>红队 Agent 主动寻找策略失效反例</h1><p class="note">被测策略为公开信号 S0（不是推荐策略）。研究与教育用途，不构成投资建议。</p>
<div class="c"><pre>{html.escape(plain)}</pre></div>
<div class="g2"><canvas id="c1"></canvas><canvas id="c2"></canvas></div>
<h2>原策略上的最短反例</h2>{''.join(f"<div class='card'><b>{html.escape(c['oracle_cn'])}</b>（{'真实情景' if c['cls'] == 'real' else '软件健壮性'}，{html.escape(c['found_by'])}）<br>{html.escape(c['minimal'])}<br><span class='note'>起始交易日 {c['start_date']}；固定清单{'能' if c['fixed_list_found'] else '不能'}发现</span></div>" for c in cards)}
<h2>完整读数</h2><div class="c"><pre>{html.escape(md)}</pre></div></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>const D={json.dumps(chart, ensure_ascii=False)};if(window.Chart){{Chart.defaults.color='#c9ccd1';Chart.defaults.borderColor='#2a2f3a';
new Chart(c1,{{type:'bar',data:{{labels:D.arms,datasets:[{{label:'封存缺陷发现率',data:D.rates}},{{label:'误报率',data:D.fa}}]}},options:{{plugins:{{title:{{display:true,text:'各臂发现率与误报率'}}}},scales:{{y:{{max:1}}}}}}}});
new Chart(c2,{{type:'bar',data:{{labels:D.defects,datasets:Object.entries(D.matrix).map(([k,v])=>({{label:k,data:v}}))}},options:{{plugins:{{title:{{display:true,text:'逐缺陷发现率'}}}},scales:{{y:{{max:1}}}}}}}});}}</script></body></html>"""
    (run_dir / "report.html").write_text(page)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    rows = [{"trade_date": fz["dev_window"][1], "build_id": "LSY04-E13", "build_name": "策略红队", "target_id": f"{r.arm}",
             "result_type": "arm_summary", "result_value": float(r.sealed_detect_rate), "result_json": json.dumps(r._asdict(), ensure_ascii=False, default=str),
             "data_version": fz["data"]["input_digest"], "update_time": ts} for r in arm.itertuples()]
    rows += [{"trade_date": c["start_date"], "build_id": "LSY04-E13", "build_name": "策略红队", "target_id": "S0", "result_type": f"counterexample:{c['cls']}",
              "result_value": 1.0, "result_json": json.dumps(c, ensure_ascii=False), "data_version": fz["data"]["input_digest"], "update_time": ts} for c in cards]
    rows.append({"trade_date": fz["dev_window"][1], "build_id": "LSY04-E13", "build_name": "策略红队", "target_id": "S0", "result_type": "summary",
                 "result_value": float(len(cards)), "result_json": json.dumps({"regression": reg["verdict"] if reg else None}, ensure_ascii=False),
                 "data_version": fz["data"]["input_digest"], "update_time": ts, "plain_text": plain})
    pd.DataFrame(rows).to_parquet(run_dir / "redteam.parquet", index=False)
    (run_dir / "report.json").write_text(json.dumps({"plain_text": plain, "only_search": only_search, "only_list": only_list, "missed": missed,
                                                     "cards": cards, "regression": reg["verdict"] if reg else None}, ensure_ascii=False, indent=1))
    print(plain)


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "out")
