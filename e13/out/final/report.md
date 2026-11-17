# 红队 Agent 主动寻找策略失效反例：实验报告

> 冻结时间 2026-11-17 02:52:51；被测策略 S0_xsmom63_weekly_band25 v1.1.0（公开信号，不是推荐策略）；数据 PandaData，输入指纹 `3a216d03b7f24ea8`。研究与教育用途，不构成投资建议。

## 结论（人话）

冻结预算下（每个臂对每个策略版本 300 次回放），对 7 个封存缺陷的发现率：固定压力清单（基线） 43%；随机搜索 57%（90% 区间 [0.51, 0.63]）；进化搜索（MAP-Elites） 46%（90% 区间 [0.34, 0.57]）；LLM 红队 50%（90% 区间 [0.43, 0.57]）。

只有主动搜索抓到、固定清单抓不到的：V01（信号）、V02（仓位）、V05（风控-保证金）。

所有方法都没抓到的盲区：V06（风控-回撤停机）。

LLM 红队臂的 7200 次回放里有 2850 次是模型输出无法解析或越界后的随机补位，它的发现率不能全部归功于 LLM。

误报率（上报后未通过扰动复跑或合理性检查的比例）：固定压力清单（基线） 27%；随机搜索 23%；进化搜索（MAP-Elites） 21%；LLM 红队 37%；所有上报逐字复跑均 100% 一致。

原策略上确认的真实情景漏洞：单日亏损超预算（最短反例：limit_lock(sector:agri @558: days=1, direction=-1)，固定清单也能发现）。

软件健壮性漏洞（单独统计）：单日亏损超预算（bad_price(sector:agri @428: factor=1.141)）；在陈旧数据上开仓（stale_bars(sector:agri @816: length=3)）；窗口回撤超预算（future_perturb(sector:agri @377: scale=0.07165, seed=185)）。

修复版 S1（板块净敞口上限 + 按当天实际涨跌停的数据校验 + 陈旧检测）：原反例未全部消除；固定清单命中不多于原策略；保留期正常表现超出容差（年化下降 0.92 个百分点（容差 0.5），夏普下降 0.096（容差 0.10））；同预算再搜索没有发现修复引入的新问题。

合成攻击路径不是真实样本外业绩；结论只对这一类策略、这套语法和这个预算成立。


## 实验设计（事前冻结）

- 被测对象：S0 及 12 个版本（原策略 CLEAN、行为等价的重构版 EQ、3 个公开缺陷 V04/V07/V10、7 个封存缺陷 V01/V02/V03/V05/V06/V08/V09）。
- 攻击语法：10 类真实情景 + 4 类软件健壮性异常，参数上界来自 2020–2023 开发期的历史包络或交易所规则，见 `out/envelope.json`。
- 判定器：13 个，分硬不变量、风险预算、蜕变关系三类；只把“无攻击时同窗口不出现”的违规算作攻击引起。
- 预算：每臂每版本 300 次回放；种子 {"A0_fixed": [0], "A1_random": [1, 2, 3, 4, 5], "A2_evolve": [1, 2, 3, 4, 5], "A3_llm": [1, 2]}。
- 裁决：逐字复跑 + 扰动复跑（3 次中 ≥2 次）+ 合理性；封存缺陷只在回退测试通过时才算发现。
- 冻结文件 sha256 见 `out/freeze.json`（8 个文件）。

## 发现矩阵（每格 = 该臂在多少比例的种子上发现了该缺陷）

| index | A0_fixed | A1_random | A2_evolve | A3_llm | layer |
|---|---|---|---|---|---|
| V01（封存） | 0% | 100% | 40% | 50% | 信号 |
| V02（封存） | 0% | 60% | 100% | 50% | 仓位 |
| V03（封存） | 100% | 100% | 100% | 100% | 风控-止损 |
| V04（公开） | 100% | 100% | 100% | 100% | 风控-止损/换月 |
| V05（封存） | 0% | 20% | 0% | 0% | 风控-保证金 |
| V06（封存） | 0% | 0% | 0% | 0% | 风控-回撤停机 |
| V07（公开） | 0% | 0% | 0% | 0% | 数据校验 |
| V08（封存） | 100% | 60% | 40% | 100% | 执行假设 |
| V09（封存） | 100% | 60% | 40% | 50% | 执行-报单 |
| V10（公开） | 100% | 100% | 100% | 100% | 仓位-乘数 |


## 发现所需回放次数（中位数）

| vid | A0_fixed | A1_random | A2_evolve | A3_llm |
|---|---|---|---|---|
| V01 | — | 112 | 123 | 130 |
| V02 | — | 123 | 167 | 147 |
| V03 | 10 | 14 | 13 | 3 |
| V04 | 25 | 14 | 16 | 26 |
| V05 | — | 206 | — | — |
| V08 | 150 | 187 | 86 | 70 |
| V09 | 15 | 87 | 118 | 22 |
| V10 | 1 | 25 | 25 | 22 |


## 各臂汇总

| arm | runs | evals | sealed_detect_rate | sealed_ci90 | open_detect_rate | reported_groups | false_alarm_groups | false_alarm_rate | clean_vulns_real | clean_vulns_robust | eq_false_differential | invalid_proposals | llm_fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 固定压力清单（基线） | 12 | 3600 | 0.429 | [0.43, 0.43] | 0.667 | 84 | 23 | 0.274 | 1 | 2 | 0 | 0 | 0 |
| 随机搜索 | 60 | 18000 | 0.571 | [0.51, 0.63] | 0.667 | 856 | 194 | 0.227 | 0 | 23 | 0 | 0 | 0 |
| 进化搜索（MAP-Elites） | 60 | 18000 | 0.457 | [0.34, 0.57] | 0.667 | 616 | 130 | 0.211 | 0 | 19 | 0 | 0 | 0 |
| LLM 红队 | 24 | 7200 | 0.5 | [0.43, 0.57] | 0.667 | 262 | 96 | 0.366 | 0 | 8 | 0 | 7 | 2850 |


## 原策略上确认的漏洞（最短反例）

| 类别 | 判定器 | 最短反例 | 起始交易日 | 发现者 | 固定清单能否发现 |
|---|---|---|---|---|---|
| 软件健壮性 | 单日亏损超预算 | bad_price(sector:agri @428: factor=1.141) | 20210709 | A0_fixed,A1_random,A2_evolve | 能 |
| 软件健壮性 | 在陈旧数据上开仓 | stale_bars(sector:agri @816: length=3) | 20230216 | A1_random,A2_evolve,A3_llm | 不能 |
| 软件健壮性 | 窗口回撤超预算 | future_perturb(sector:agri @377: scale=0.07165, seed=185) | 20210423 | A2_evolve | 不能 |
| 真实情景 | 单日亏损超预算 | limit_lock(sector:agri @558: days=1, direction=-1) | 20220119 | A0_fixed | 能 |


## 修复与回归

S1v2 v1.2.1 = S0 + 板块净敞口上限（单板块净名义 ≤ 0.5 倍权益，只缩较重的一侧）+ 数据校验层（结算价越出当天实际涨跌停范围判坏数据）+ 陈旧检测（整根 K 线与前一日相同）。迭代 1（总敞口上限）的回归结果见 regression_v1.json。

| cls | oracles | attack | S0_hits | S1_hits | fixed |
|---|---|---|---|---|---|
| real | day_loss | limit_lock(sector:agri @558: days=1, direction=-1) | ['day_loss'] | [] | True |
| robust | day_loss,dd_runaway,ruin | bad_price(sector:agri @428: factor=10) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | day_loss,dd_runaway,ruin | bad_price(sector:chem @552: factor=10) + missing_bars(JD @545: length=4) + future_perturb(sector:chem @551: scale=0.02686, seed=351) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | day_loss,dd_runaway,ruin | bad_price(sector:chem @552: factor=10) + missing_bars(sector:black @545: length=4) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | day_loss,dd_runaway,ruin | stale_bars(RB @923: length=4) + bad_price(sector:chem @925: factor=10) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | day_loss,dd_runaway,ruin | bad_price(M @516: factor=10) + gap(P @519: size=0.05865) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | day_loss,dd_runaway,ruin | bad_price(AL @546: factor=10) + liquidity_dry(AL @543: mult=0.5207, length=10) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | day_loss,dd_runaway,ruin | bad_price(all @257: factor=10) + whipsaw(JD @259: amp=0.02198, cycles=4, period=2) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | day_loss,dd_runaway,ruin | partial_fill(sector:metal @183: ratio=0.3, length=2) + bad_price(JD @180: factor=10) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | day_loss,dd_runaway,ruin | bad_price(MA @841: factor=10) + future_perturb(P @842: scale=0.04841, seed=647) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | day_loss,dd_runaway,ruin | bad_price(MA @843: factor=10) + exec_delay(all @845: days=2, length=5) | ['day_loss', 'dd_runaway', 'ruin'] | [] | True |
| robust | stale_open | stale_bars(sector:agri @816: length=5) | ['stale_open'] | [] | True |
| robust | stale_open | stale_bars(all @940: length=3) + missing_bars(all @940: length=1) | ['stale_open'] | ['stale_open'] | False |
| robust | day_loss,dd_runaway | bad_price(sector:agri @556: factor=10) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | bad_price(M @552: factor=10) + missing_bars(sector:black @545: length=4) + future_perturb(sector:chem @551: scale=0.02204, seed=351) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | bad_price(sector:metal @386: factor=10) + margin_hike(SA @388: pp=0.01403, length=5) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | liquidity_dry(JD @171: mult=0.2536, length=1) + bad_price(RB @169: factor=10) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | vol_burst(SA @175: mult=2.213, length=9) + bad_price(CU @177: factor=10) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | bad_price(AP @546: factor=10) + missing_bars(sector:black @545: length=4) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | limit_lock(CU @637: days=1, direction=1) + bad_price(sector:agri @635: factor=0.1) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | partial_fill(JD @529: ratio=0.4857, length=3) + bad_price(sector:agri @529: factor=2) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | bad_price(sector:agri @950: factor=2) + whipsaw(CU @952: amp=0.006257, cycles=3, period=3) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | stale_bars(all @890: length=2) + bad_price(all @892: factor=0.2) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | reject(I @259: length=2) + bad_price(TA @261: factor=0.1) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | day_loss,dd_runaway | future_perturb(all @500: scale=0.2, seed=144159) | ['day_loss', 'dd_runaway'] | ['day_loss', 'dd_runaway'] | False |
| robust | day_loss,dd_runaway | sector_shock(sector:black @660: size=-0.03575) + bad_price(AL @663: factor=0.1) | ['day_loss', 'dd_runaway'] | [] | True |
| robust | stale_open | stale_bars(P @378: length=5) + reject(M @378: length=2) | ['stale_open'] | ['stale_open'] | False |
| robust | stale_open | partial_fill(SA @429: ratio=0.4083, length=1) + stale_bars(AP @432: length=5) | ['stale_open'] | [] | True |
| robust | day_loss | bad_price(sector:black @735: factor=0.1) | ['day_loss'] | [] | True |
| robust | day_loss | margin_hike(RB @817: pp=0.04304, length=12) + bad_price(P @818: factor=2) | ['day_loss'] | [] | True |
| robust | day_loss | bad_price(SA @617: factor=0.1) + gap(RB @616: size=0.05986) | ['day_loss'] | [] | True |
| robust | day_loss | bad_price(P @861: factor=2) + vol_burst(sector:metal @863: mult=2.441, length=7) | ['day_loss'] | [] | True |
| robust | day_loss | future_perturb(sector:metal @840: scale=0.1203, seed=340) + bad_price(TA @841: factor=0.1) | ['day_loss'] | [] | True |
| robust | dd_runaway | future_perturb(sector:agri @377: scale=0.1638, seed=185) | ['dd_runaway'] | ['dd_runaway'] | False |
| robust | day_loss | exec_delay(all @226: days=1, length=8) + bad_price(P @228: factor=2) | ['day_loss'] | [] | True |
| robust | day_loss | bad_price(sector:metal @591: factor=0.5) + reject(RB @592: length=2) | ['day_loss'] | [] | True |
| robust | day_loss | sector_shock(sector:chem @397: size=-0.0602) + bad_price(I @394: factor=0.5) | ['day_loss'] | [] | True |
| robust | day_loss | future_perturb(all @410: scale=0.2, seed=311831) | ['day_loss'] | ['day_loss'] | False |


- 固定清单命中：S0 15 次（真实情景 1），S1 4 次（真实情景 0）。

- 正常表现（无攻击）：S0_dev 年化 -1.21% 夏普 -0.04 回撤 -33.2%；S0_holdout 年化 -1.16% 夏普 -0.05 回撤 -19.9%；S1_dev 年化 -2.33% 夏普 -0.14 回撤 -32.9%；S1_holdout 年化 -2.08% 夏普 -0.15 回撤 -19.7%。

- 同预算再搜索：修复引入的新问题 0 个；S0 上已有、S1 上仍在的问题 2 组。

## 交易执行核验与等价回放范围

任务要求交易执行部分用期货模拟赛核验。本期用户不参加模拟赛，因此执行语义只在回放中核验，事前写明的等价范围如下：

| 执行语义 | 回放中的处理 | 模拟赛能否验 |
|---|---|---|
| 锁板方向不能成交 | 最高=最低=涨/跌停时该方向不成交，顺延 | 能，本期未验 |
| 成交价不越出涨跌停 | 成交价夹在当日涨跌停内 | 能（柜台 dailyPriceLimit 校验），本期未验 |
| 部分成交、拒单、下单延迟 | 由攻击原语注入 | 部分能，本期未验 |
| 换月：旧腿平、新腿开 | 主力标签切换日开盘两腿同时成交 | 能（rollover 预演），本期未验 |
| 跳空、连续锁板、提保、流动性枯竭、板块共振 | 只能在回放中构造 | 不能（柜台造不出来） |

模拟赛柜台是 500 万固定资金的仿真成交，费率为交易所标准的 1.5 倍，本来也只能验证账本口径，不能验证大资金冲击。

## 运行来源

每条运行（臂 × 版本 × 种子）来自哪个运行目录（由 merge_runs.py 记录）：

| 来源目录 | 臂 | 运行数 |
|---|---|---|
| PandaAI EVO 分块运行（chunk1–24） | 进化搜索（MAP-Elites） | 60 |
| PandaAI EVO 分块运行（chunk1–24） | 随机搜索 | 60 |
| a3_local | LLM 红队 | 24 |
| PandaAI EVO 分块运行（chunk1–24） | 固定压力清单（基线） | 12 |


## 运行平台记录

```json
{
 "platform": "PandaAI EVO 云端工作区（研究助手 · 运行 Python 脚本 · 隔离运行）",
 "python": "3.11.14",
 "system": "Linux-5.15.0-191-generic-x86_64-with-glibc2.36",
 "cpu_count": 32,
 "workers": "1",
 "cwd": "/home/coder/project/projects/default/reports/20261117-0257-evo_chunk_124",
 "bundle": "e13_bundle_20261117_0256.tar.gz",
 "finished": "2026-11-17 02:58:13 +0800",
 "chunks": [
  {
   "chunk": 1,
   "vids": "CLEAN",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 46.7
  },
  {
   "chunk": 2,
   "vids": "CLEAN",
   "arms": "A2_evolve",
   "elapsed_s": 33.8
  },
  {
   "chunk": 3,
   "vids": "EQ",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 48.4
  },
  {
   "chunk": 4,
   "vids": "EQ",
   "arms": "A2_evolve",
   "elapsed_s": 33.6
  },
  {
   "chunk": 5,
   "vids": "V01",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 49.4
  },
  {
   "chunk": 6,
   "vids": "V01",
   "arms": "A2_evolve",
   "elapsed_s": 36.9
  },
  {
   "chunk": 7,
   "vids": "V02",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 50.3
  },
  {
   "chunk": 8,
   "vids": "V02",
   "arms": "A2_evolve",
   "elapsed_s": 35.4
  },
  {
   "chunk": 9,
   "vids": "V03",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 53.6
  },
  {
   "chunk": 10,
   "vids": "V03",
   "arms": "A2_evolve",
   "elapsed_s": 38.2
  },
  {
   "chunk": 11,
   "vids": "V04",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 56.0
  },
  {
   "chunk": 12,
   "vids": "V04",
   "arms": "A2_evolve",
   "elapsed_s": 37.8
  },
  {
   "chunk": 13,
   "vids": "V05",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 48.0
  },
  {
   "chunk": 14,
   "vids": "V05",
   "arms": "A2_evolve",
   "elapsed_s": 34.1
  },
  {
   "chunk": 15,
   "vids": "V06",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 48.1
  },
  {
   "chunk": 16,
   "vids": "V06",
   "arms": "A2_evolve",
   "elapsed_s": 33.6
  },
  {
   "chunk": 17,
   "vids": "V07",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 45.0
  },
  {
   "chunk": 18,
   "vids": "V07",
   "arms": "A2_evolve",
   "elapsed_s": 31.3
  },
  {
   "chunk": 19,
   "vids": "V08",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 48.4
  },
  {
   "chunk": 20,
   "vids": "V08",
   "arms": "A2_evolve",
   "elapsed_s": 33.5
  },
  {
   "chunk": 21,
   "vids": "V09",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 49.2
  },
  {
   "chunk": 22,
   "vids": "V09",
   "arms": "A2_evolve",
   "elapsed_s": 35.8
  },
  {
   "chunk": 23,
   "vids": "V10",
   "arms": "A0_fixed,A1_random",
   "elapsed_s": 60.9
  },
  {
   "chunk": 24,
   "vids": "V10",
   "arms": "A2_evolve",
   "elapsed_s": 38.9
  }
 ],
 "local_runs": [
  "out/a3_local"
 ]
}
```

## 适用边界

- 只测一类策略（周频截面 CTA）；缺陷由作者设计，作者同时设计了攻击语法，偏置只能减轻（封存、事前冻结），不能消除。
- 合成攻击路径是“可能发生”的情景，不是真实样本外业绩，也不预测概率。
- LLM 红队臂只看策略卡与攻击日志（黑盒），不读被测代码；读代码的白盒审查是另一种能力，不在本题范围。
- 判定器的阈值来自风险卡（单日亏损 6%、窗口回撤 22%、保证金上限 25%+2% 等），换风险卡要重新冻结。
- 健壮性类攻击（坏价格、缺数、陈旧、未来扰动）单独统计，不代表真实市场会发生。

## 术语

- **反向压力测试 reverse stress test**：普通压力测试问“发生这件事会亏多少”，反向压力测试问“发生什么事才会把策略打死”。
- **合理性约束 plausibility**：攻击参数不能超过该品种开发期的历史极值或交易所规则；组合攻击的 5 日累计冲击也不能超过历史上限（思路来自 Breuer 等 2009）。
- **变异测试 mutation testing**：故意往策略里埋已知缺陷，看测试方法能不能抓住；抓到的比例就是发现率。
- **回退测试 revert test**：把缺陷改回去（换回原策略），同一个反例不再触发，才算真正定位到了这个缺陷。
- **蜕变关系 metamorphic relation**：不知道正确答案时，用“改了输入，输出应该怎么变”查错。例如只改未来数据，过去的决策必须完全不变。
- **扰动复跑 jitter rerun**：把攻击时点前后挪 3 天、参数放大缩小 10%，3 次里至少 2 次仍触发才算稳健的发现。
- **质量多样性搜索 MAP-Elites**：按“攻击类型 × 命中的判定器”分格，每格保留最狠的攻击，再从格子里挑父本变异，避免只盯着一种打法。

