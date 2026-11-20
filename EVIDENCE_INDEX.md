# 证据索引（按第四期评分项）

任务：LSY04-E13「红队 Agent 主动寻找策略失效反例」（TS20261020847B3A），运行平台 PandaAI EVO。

| 评分项 | 分 | 证据（文件 / 命令 / 预期结果） |
|---|---:|---|
| 完成度·核心功能 | 20 | 攻击语法 `e13/grammar.py`（10 类真实情景 + 4 类健壮性原语、历史包络夹回、5 日累计合理性）；判定器 `e13/oracles.py`（13 个，独立重算保证金与止损参考价）；四臂搜索 `e13/harness.py`、`e13/llm_arm.py`；裁决与回退测试 `e13/adjudicate.py`；最短反例 `adjudicate.py::shrink`；修复与四项回归 `e13/fixes.py`、`e13/regress.py`。完整结果 `e13/out/final/` |
| 完成度·输出可用 | 10 | `e13/out/final/report.md` 的"结论（人话）"；`report.json` 的 `plain_text`、`only_search`、`only_list`、`missed`；`counterexamples.json`（最短反例卡片）；`redteam.parquet`；README 结论表与"它改变了什么决策" |
| 方法·数据来源 | 12 | `references/api_guide.md`（接口、字段、实测口径）；`fetch_data.py` 写 `fetch_log.jsonl`；`e13/out/freeze.json` 的 `data.input_sha256_16`（逐文件指纹）与 `input_digest`；2020 年前双边口径修正 `futures_replay/data.py::fix_double_sided` |
| 方法·时点与算术 | 13 | `futures_replay/test_engine.py` 手算校验（结算价盯市、费用、乘数、锁板顺延、换月两腿、双边口径、主力链收益）；`e13/test_e13.py`（6 项：引擎手算、冻结完整、包络夹回、叠加冲击被判不合理、同攻击两次回放一致、回退测试定位 V03）；未来函数探针 `oracles.py::lookahead_probe`（对照 = 攻击减去 future_perturb） |
| 方法·对照与验证 | 10 | 冻结协议 `references/design.md`；冻结哈希 `e13/out/freeze.json`（02:52:51）与上一版 `freeze_v2_20261117_0215.json`（两者只差 `llm_arm.py`）；固定清单 A0 作同预算对照；行为等价版本 EQ 作阴性对照（四臂差分误报均为 0）；封存缺陷只在回退测试通过时计为发现；开发期 / 保留期分开（保留期只用于回归 R3）；回归容差事前写定（年化下降 ≤ 0.5pp、夏普下降 ≤ 0.10）；尝试账本 `ATTEMPTS.md` |
| 交付·平台实测 | 10 | `platform_evidence/evo/run_log.md`：A0/A1/A2 在 PandaAI EVO 研究助手"运行 Python 脚本"上分 24 块运行，24/24 成功，单块 31–61 秒；分块脚本 sha256 与逐块批准截图 `platform_evidence/evo/screens/`；运行环境 Python 3.11.14 / numpy 1.26.4 / pandas 2.3.3；EVO 上失败的整体运行尝试如实列出。A3 在本机运行（密钥不上传云端）。EVO 结果与本机同一冻结代码的复现逐项一致（离散字段 100% 相同），见本文末 |
| 交付·复现追溯 | 8 | `freeze.json`（8 个冻结文件 sha256、预算、种子、包络、数据指纹）；冻结检查在 `search` 前强制执行（冻结后改动会被拒绝，曾实际拦下一次，见 `ATTEMPTS.md` 02:45）；`adjudication.json` 每条运行带 `source`（来自哪个运行目录）；`llm_calls.jsonl.gz` 带提示词、提示词哈希与用量；同输入同种子结果逐字一致（`test_e13.py::test_determinism`）；评审面板快照（zip 附件，与 EVO 运行包内面板逐字节相同，清单 `e13/out/panel_snapshot_manifest.json`）+ `e13/verify_snapshot.py`：干净副本里装快照后自测由 2 PASS / 4 SKIPPED 变为 6 PASS（见 README"评审数据快照"） |
| 交付·异常处理 | 7 | 冻结检查失败即停；LLM 输出无法解析或越界时退回随机补位并计数（`n_fallback`、`n_invalid`，报告里显式写出）；越界参数夹回包络并记录；攻击不合理即丢弃；裁决只在逐字复跑、扰动复跑、合理性、回退测试都通过时才算发现；`merge_runs.py` 遇重复运行直接报错；`fetch_data.py` 重试与单日流量超限停止 |
| 文档·第三人上手 | 6 | `README.md`（安装、取数、冻结、搜索、裁决、汇总、回归、报告、自测、EVO 分块运行）；`AGENTS.md`（QuantSkills 2.1 声明与 Agent 行为约定）；`SKILL.md`、`CLAUDE.md`、`agents/`、`.cursor/rules/` 运行时入口 |
| 文档·局限说明 | 4 | `references/source_boundary.md`（来源、假设、参数、已知限制、风险边界）；`references/execution_scope.md`（未参加模拟赛时的等价回放范围，事前写定）；README 适用边界一节 |

## 作废与失败记录（不进入结论，原样保留）

| 内容 | 位置 | 原因 |
|---|---|---|
| 预跑 1 | `e13/out/void/prerun1_void.tar.gz` | 发现评估器三处缺陷（多成交方向、换月日旧合约未夹涨跌停、止损参考价未按加仓加权），修评估器后重新冻结 |
| LLM 臂第一次运行 | `e13/out/void/a3_run1_void.tar.gz` | 模型思考占满 max_tokens，可解析攻击 0/3600，全部随机补位 |
| 修复迭代 1 | `e13/out/final/regression_v1.json` | 板块总敞口上限使保留期年化从 -1.16% 降到 -5.08%；数据校验误杀 9 格真实扩板行情 |
| EVO 整体运行 | `platform_evidence/evo/run_log.md` | 无终端、不可写、禁止多进程、超过 120 秒 |

## EVO 结果与本机复现的比对

`e13/out/final/` 是 EVO 版本：A0/A1/A2 来自 EVO 上 24 块的结果包（`platform_evidence/evo/evo_chunks_manifest.json` 记录每个包的 runId、字节数与 sha256），A3 来自本机（`a3_local`）。报告的"运行来源"与"运行平台记录"两节逐条列出来源和每块耗时。

同一份冻结代码在本机的运行（A0/A1/A2 = `local_run2`）作复现对照，比对结果 `platform_evidence/evo/compare_evo_vs_local.json`：发现矩阵、各臂汇总、发现所需回放次数逐字节相同；132 个运行文件的 588506 个离散字段与裁决的 40109 个离散字段全部相同；浮点数只有 312/58520 个在末位不同（最大相对差 3.9e-13，不同 CPU 的舍入）。EVO 环境 Python 3.11.14 / numpy 1.26.4 / pandas 2.3.3，本机 Python 3.11.13 / numpy 1.26.4 / pandas 2.1.4。

复现命令：

```bash
cd e13
python merge_runs.py out/final_evo <下载目录>/e13_chunk*.tar.gz --extra out/a3_local
python summarize.py out/final_evo && python regress.py --runs out/final_evo --fix v2 && python report_e13.py out/final_evo
```
