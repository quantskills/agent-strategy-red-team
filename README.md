# 红队 Agent 主动寻找策略失效反例（agent-strategy-red-team）

> QuantSkills 社区项目（Community Project），未经维护者审核、认证或背书。仅供量化研究与教育示例，**不构成投资建议，不承诺收益，不自动下单**。

一个期货策略上线前，在"真可能发生"的范围内主动搜索会让它做错单或风险失控的条件，并回答：固定压力清单漏了什么，主动搜索多发现了什么、多报了多少错，修复之后有没有变差。

学术说法是反向压力测试（reverse stress testing）加基于搜索的测试。人话：普通压力测试问"发生这件事会亏多少"，红队反过来问"发生什么事才会把策略打死"，而且每条反例都要能解释、能复跑、能修。

## 结论（被测策略 S0，开发期 2020-01-02 至 2023-12-29，11 个商品期货品种）

被测策略 S0 是公开信号（63 日截面动量 + 25% 不交易带，周频），只作被测对象，不是推荐策略。每臂每个策略版本 300 次回放，A1/A2 各 5 个种子，A3 2 个种子。A0/A1/A2 在 PandaAI EVO 上运行，A3 在本机运行；本机同一冻结代码的复现与 EVO 结果逐项一致。完整报告见 [e13/out/final/report.md](e13/out/final/report.md)。

| 问题 | 结论 |
|---|---|
| 封存缺陷发现率（7 个，回退测试通过才算） | 固定清单 A0 **43%**；随机搜索 A1 **57%**（90% 区间 0.51–0.63）；质量多样性进化 A2 **46%**（0.34–0.57）；LLM 红队 A3 **50%**（0.43–0.57） |
| 只有搜索抓到、清单抓不到 | V01 信号多看一天（未来函数）、V02 波动率窗口过短（仓位层）：清单没抓到，A1 分别在 5/5 和 3/5 个种子上发现，A2 在 2/5 和 5/5 上发现；V05 静态保证金率只有 A1 在 1/5 个种子上抓到 |
| 清单更稳、随机与进化搜索容易漏 | V08 回测假设锁板也能成交、V09 部分成交后重复报单：清单必中；A1 3/5、A2 2/5；A3 分别 2/2 和 1/2 |
| 所有方法都没抓到 | V06 回撤停机基准被重置（封存）、V07 陈旧数据检查被删（公开） |
| 误报（上报后未通过扰动复跑或合理性检查） | A0 27%、A1 23%、A2 21%、A3 37%；所有上报逐字复跑 100% 一致，误报全部是"换个相邻日期就不成立" |
| 原策略上的真实情景漏洞 | 农产品板块单日集体跌停锁板（2022-01-19 起 1 天）时单日亏损超过 6%（没有板块敞口上限）；最短反例只有 1 个原语，**四个臂里只有固定清单发现了它** |
| 原策略上的软件健壮性漏洞（单独统计） | 坏价格：农产品板块某一天的收盘价和结算价偏高 14% 就触发单日亏损超预算（放大 10 倍可直接触发破产判定）；行情冻结 3 天时仍会新开仓；只改未来数据的扰动可触发窗口回撤超预算 |
| LLM 臂的实际情况 | 7200 次回放里 2850 次（40%）是模型输出无法解析或越界后的随机补位；它的发现率不能全部归功于 LLM |
| 修复（S1v2：板块净敞口上限 + 按当天实际涨跌停的数据校验 + 陈旧检测） | 原策略上 38 条反例消除 33 条（唯一的真实情景反例已消除，剩下 5 条都是健壮性类：行情冻结开仓 2 条、只改未来数据的扰动 3 条）；固定清单命中 15 → 4；同预算再搜索没有发现修复引入的新问题；但保留期年化从 -1.16% 降到 -2.08%（下降 0.92 个百分点，超过事前定的 0.5 个百分点容差，夏普下降 0.096 在 0.10 容差内） |

**它改变了什么决策：** 只用固定清单放行，会漏掉信号层和仓位层的缺陷（V01、V02）；只用搜索放行，执行层缺陷（V08、V09）和唯一的真实情景漏洞反而更容易漏。两者要一起用，而且回撤停机和数据校验这两类缺陷（V06、V07）四种方法都看不见，需要单独写单元测试。修复确实堵住了板块锁板的尾部风险，代价约每年 1 个百分点，按事前容差不能直接放行，交由决策者权衡。

## 流程（全部在跑之前冻结）

```text
冻结：被测策略与风险卡、攻击语法与合理性边界、判定器、固定清单、缺陷集、预算（sha256 → e13/out/freeze.json）
  → 四臂同预算搜索（A0 固定清单 / A1 随机 / A2 质量多样性 / A3 LLM 红队）
  → 自动裁决：逐字复跑 + 扰动复跑（3 次中 ≥2 次）+ 合理性 + 回退测试
  → 反例缩到最短 → 修复 → 四项回归（原反例 / 固定清单 / 保留期正常表现 / 同预算再搜索）→ 报告
```

攻击语法、13 个判定器、缺陷集和裁决规则见 [references/design.md](references/design.md)；组件与文件对应见 [AGENTS.md](AGENTS.md)。

## 怎么跑

```bash
pip install -r requirements.txt
python fetch_data.py                         # PandaData 拉取（需要凭证），生成本地数据
cd e13
python run_e13.py freeze                     # 冻结（已冻结时勿重复；改动冻结文件后 search 会拒绝运行）
python run_e13.py search --arms A0_fixed,A1_random,A2_evolve
LLMX_BASE_URL=... REDTEAM_MODEL=... LLMX_API_KEY=... python run_e13.py search --arms A3_llm   # 密钥只走环境变量
python run_e13.py adjudicate
python summarize.py out && python regress.py --runs out --fix v2 && python report_e13.py out
python test_e13.py                           # 离线自测
```

可移植面板 `e13/data/panel/`（npz + json）由 PandaData 数据生成，不随公开仓库分发（评审用快照见下一节）；`fetch_data.py` 拉取后 `run_e13.py freeze` 会重建，指纹与 `e13/out/freeze.json` 的 `data.input_sha256_16` 比对。

**在 PandaAI EVO 上：** EVO 的"运行 Python 脚本"单次最多 120 秒、禁止多进程、每次运行互不可见，所以实验拆成 24 块（12 个版本 × {A0+A1, A2}）。把 `bash e13/make_bundle.sh` 打出的包和 `e13/evo_chunk.py` 的 24 份副本（`evo_chunk_1.py` … `evo_chunk_24.py`，文件名决定块号）上传到工作区根目录，在研究助手里逐块运行；每块产出 `e13_chunk<k>.tar.gz`。下载后用 `python merge_runs.py <新目录> e13_chunk*.tar.gz --extra out/a3_local` 合并，再跑汇总、回归和报告。本仓库的 EVO 运行记录见 [platform_evidence/evo/run_log.md](platform_evidence/evo/run_log.md)。LLM 臂需要模型密钥，密钥不上传云端，在本机用同一份冻结代码运行。

## 评审数据快照（不用 PandaData 账号也能复跑）

原冻结面板 `e13/data/panel/` 作为量枢院成果附件 `LSY04-E13_frozen_panel_snapshot.zip` 提供（sha256 `1a3639feac47abee93af931c24874ff7933a7357068c1060d720b1cfdb95cb64`），与 EVO 运行包 `e13_bundle_20261117_0256.tar.gz` 里的面板逐字节相同。

```bash
python e13/verify_snapshot.py LSY04-E13_frozen_panel_snapshot.zip   # 解压到 e13/data/panel/ 并核对
python e13/test_e13.py                                              # 6 PASS, 0 SKIPPED
```

`verify_snapshot.py` 逐文件核对 sha256（清单 `e13/out/panel_snapshot_manifest.json`），并核对面板里记录的 406 个原始输入指纹与冻结记录 `e13/out/freeze.json` 完全相同（`input_digest` 3a216d03b7f24ea8）。在不含本机任何数据的干净副本里实测：装快照前自测为 2 PASS、4 SKIPPED，装上后 6 项全部通过（包络夹回、叠加冲击合理性、同攻击复跑一致、回退测试定位 V03）。

## 输出

`report.md / report.html / report.json`（`plain_text` 为人话结论）、`redteam.parquet`（每臂 × 版本 × 种子一行）、`counterexamples.json`（最短反例卡片：原语、起始交易日、合理性依据、触发的判定器）、`detection_matrix.csv`、`evals_to_detect.csv`、`arm_summary.csv`、`clean_vulnerabilities.csv`、`regression_v1.json` / `regression_v2.json`（两次修复迭代的四项回归）、`adjudication.json`、`attempts.jsonl`、`llm_calls.jsonl.gz`（LLM 臂每次调用的提示词、提示词哈希、用量与解析数）、`runs.tar.gz`（每次回放的攻击与判定器读数）。

## 运行记录与作废结果

所有影响被测对象或判定口径的改动都记在 [ATTEMPTS.md](ATTEMPTS.md)，包括：被测策略选型两次尝试；预跑 1 发现评估器三处缺陷后作废（`e13/out/void/prerun1_void.tar.gz`）；LLM 臂第一次运行因思考占满 token 全部退化为随机补位后作废（`e13/out/void/a3_run1_void.tar.gz`）；修复迭代 1 回归失败、迭代 2 超出保留期容差后停止迭代；EVO 上整体运行失败后改为分块。

## 数据来源、假设、参数、限制与风险

数据来源是 PandaData 期货接口（主力合约、合约信息、日线，口径见 [references/api_guide.md](references/api_guide.md)）；回放假设（开盘成交 ±1 跳、单日成交不超过成交量 10%、锁板方向不成交、保证金率 +3 个百分点、费用 1bp）、参数（开发期与保留期、回放窗口、预算与种子、风险卡阈值）和已知限制逐条列在 [references/source_boundary.md](references/source_boundary.md)。

**主要限制：** 只测一类策略（周频截面 CTA）与 10 类缺陷；缺陷与攻击语法由同一作者设计，偏置只能用封存缺陷与事前冻结减轻，不能消除。合成攻击路径是"可能发生"的情景，不是真实样本外业绩，也不给发生概率。日频回放不建模日内执行（日内参与率与冲击见 skill-futures-capacity-boundary）。用户未参加期货模拟赛，执行语义只在回放中核验，等价范围见 [references/execution_scope.md](references/execution_scope.md)。LLM 臂的模型路线与冻结时记录的不同（网关无通道，改用同名模型的官方接口），见 `ATTEMPTS.md`。完整说明见 [references/source_boundary.md](references/source_boundary.md)。

**QuantSkills Community Project，仅供量化研究与教育示例，不构成投资建议，不承诺收益。**
