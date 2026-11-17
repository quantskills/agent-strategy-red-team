---
name: agent-strategy-red-team
description: 策略红队 Agent：在一个期货策略投入使用前，用带合理性边界的攻击语法主动搜索能让它做错单或风险失控的条件，与固定压力清单在同一预算下比较发现率、误报和新增漏洞；用埋入缺陷和回退测试判定发现，把反例缩到最短，复跑确认，并检验修复后是否引入退化。Use when a futures strategy is about to be released and the user wants to know which plausible market or execution conditions break it, beyond a fixed stress checklist. Research and education only, not investment advice.
license: GPL-3.0-only
supported-runtimes: [cursor, claude-code, codex, hermes, openclaw]
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: agent-strategy-red-team
  repository_url: https://github.com/quantskills/agent-strategy-red-team
  project_type: agent
  collection: strategy-red-team
  maintainer: ZLHad
  tags: [futures, red-team, reverse-stress-test, mutation-testing, counterexample, pandadata]
quantSkills:
  schema_version: 2.1.0
  organization: quantskills
  organization_url: https://github.com/quantskills
  repository: agent-strategy-red-team
  repository_url: https://github.com/quantskills/agent-strategy-red-team
  project_type: agent
  license: GPL-3.0-only
  maintainer: ZLHad
  collection: strategy-red-team
  catalog:
    category: "09"
    subcategory: 09.development-review-agent
  workflow:
    primary_stage: evaluation
    workflow_stages: [evaluation, risk, reporting]
  tags: [futures, red-team, reverse-stress-test, mutation-testing, counterexample, pandadata]
  requires: [skill-pandadata-api]
  platforms: [cursor, claude-code, codex, hermes, openclaw]
  status: active
  validation_level: runnable
  maintainer_type: community
  summary_zh: "期货策略上线前的红队：在合理范围内主动搜索让策略做错单或失控的反例，与固定压力清单同预算比较发现率和误报，并验证修复有没有带来退化。"
  summary_en: "Pre-release red team for futures strategies: searches plausible counterexamples, compares with a fixed stress list at equal budget, and regression-tests fixes; research only."
  interface:
    mode: not-applicable
    reason: orchestration-only
---

# 策略红队 Agent（Strategy Red Team）

> QuantSkills Community Project，仅供量化研究与教育示例，不构成投资建议，不承诺收益，不自动下单。

## 它只回答一个问题

**这个策略上线前，在"真可能发生"的范围内，什么条件会让它做错单或风险失控；固定压力清单能不能发现这些问题。**

学术说法是反向压力测试（reverse stress testing）加基于搜索的测试。人话：普通压力测试问"发生这件事会亏多少"，红队反过来问"发生什么事才会把策略打死"，并且每条反例都要能解释、能复跑、能修，修完还要证明没变差。

## 什么时候用

- 一个期货策略要放行，手里只有一份固定的压力测试清单，想知道清单漏了什么。
- 想比较不同测试方法（固定清单、随机搜索、进化搜索、LLM 红队）在同样预算下谁发现得多、谁误报少。
- 修了一个漏洞，想确认修复本身没有引入新问题。

## 流程（全部在跑之前冻结）

```text
冻结：被测策略与风险卡、攻击语法与合理性边界、判定器、固定清单、缺陷集、预算（sha256 → e13/out/freeze.json）
  → 四臂同预算搜索（A0 固定清单 / A1 随机 / A2 质量多样性 / A3 LLM 红队）
  → 自动裁决：逐字复跑 + 扰动复跑（3 次中 ≥2 次）+ 合理性 + 回退测试
  → 反例缩到最短 → 修复 → 四项回归（原反例 / 固定清单 / 保留期正常表现 / 同预算再搜索）→ 报告
```

| 组件 | 文件 | 要点 |
|---|---|---|
| 回放账本 | `futures_replay/` | 真实合约逐日结算价盯市；换月两腿按旧合约开盘平仓；锁板方向不成交；手算测试见 `futures_replay/test_engine.py` |
| 攻击语法 | `e13/grammar.py` | 10 类真实情景 + 4 类软件健壮性异常；参数上界来自开发期历史包络或交易所规则；组合攻击的 5 日累计冲击不超过历史上限 |
| 判定器 | `e13/oracles.py` | 13 个，分硬不变量、风险预算、蜕变关系；判定器自己按真实乘数和含提保的保证金率重算，不信被测策略自报 |
| 搜索臂 | `e13/harness.py`、`e13/llm_arm.py` | 预算按回放次数计，四臂相同；LLM 臂只看策略卡和攻击日志（黑盒） |
| 缺陷集 | `e13/defects/sealed.py` | 7 个封存 + 3 个公开 + 行为等价的阴性对照 EQ |
| 裁决 | `e13/adjudicate.py` | 只有回退测试通过（把缺陷改回去同一反例不再触发）才算发现 |
| 修复与回归 | `e13/fixes.py`、`e13/regress.py` | 修复独立成文件，不改冻结代码；容差事前写定 |
| 报告 | `e13/summarize.py`、`e13/report_e13.py` | report.md / report.html / report.json / redteam.parquet / counterexamples.json |

## 怎么跑

```bash
pip install -r requirements.txt
python fetch_data.py                         # PandaData 拉取（需要凭证）；可移植面板 e13/data/panel/ 由 freeze 生成，不随仓库分发
cd e13
python run_e13.py freeze                     # 冻结（已冻结时勿重复，改动冻结文件后 search 会拒绝运行）
python run_e13.py search --arms A0_fixed,A1_random,A2_evolve
LLMX_BASE_URL=... REDTEAM_MODEL=... LLMX_API_KEY=... python run_e13.py search --arms A3_llm   # LLM 臂，密钥只走环境变量
python run_e13.py adjudicate
python summarize.py out && python regress.py --runs out --fix v2 && python report_e13.py out
python test_e13.py                           # 离线自测
```

在 PandaAI EVO 上：EVO 的“运行 Python 脚本”单次最多 120 秒、禁止多进程、每次运行互不可见，所以实验拆成 24 块（12 个版本 × {A0+A1, A2}）。把 `e13/make_bundle.sh` 打出的包和 `e13/evo_chunk.py` 的 24 份副本（`evo_chunk_1.py` … `evo_chunk_24.py`，文件名决定块号）上传到工作区根目录，逐块运行；每块在自己的产物目录里解压、搜索、裁决并打包 `e13_chunk<k>.tar.gz`。下载后在本机用 `python merge_runs.py <新目录> e13_chunk*.tar.gz --extra out/a3_local` 合并，再跑汇总、回归和报告。LLM 臂需要模型密钥，密钥不上传云端，在本机用同一份冻结代码运行后合并。

## Agent 行为约定

1. 先冻结再搜索；冻结后改动任何冻结文件，`run_e13.py search` 会拒绝运行，必须重新冻结并在 `ATTEMPTS.md` 记录原因。
2. 真实情景与软件健壮性异常分开统计；健壮性类不代表真实市场会发生。
3. 只有"无攻击时同窗口不出现"的违规算攻击引起；只有回退测试通过才算定位到缺陷。
4. 每条反例给出最短形式、起始交易日、合理性依据；不输出交易指令。
5. 修复独立成文件；回归四项任何一项不过，都如实报告"修复引入退化"。
6. 交易执行核验：用户不参加期货模拟赛时，执行语义只在回放中核验，等价范围见 [references/execution_scope.md](references/execution_scope.md)。

## 数据来源

PandaData 期货接口（主力合约、合约信息、日线），口径与实测发现见 [references/api_guide.md](references/api_guide.md)；假设、参数、限制与风险边界见 [references/source_boundary.md](references/source_boundary.md)。

## 参考文件

- [references/design.md](references/design.md) 冻结协议、指标定义、裁决规则
- [references/execution_scope.md](references/execution_scope.md) 期货模拟赛核验与等价回放范围
- [references/api_guide.md](references/api_guide.md) 数据接口与实测口径
- [references/source_boundary.md](references/source_boundary.md) 来源、假设、参数、限制、风险边界
- [ATTEMPTS.md](ATTEMPTS.md) 尝试账本（所有影响被测对象或判定口径的改动）

## 边界与免责

只测一类策略（周频截面 CTA）；缺陷由作者设计，偏置只能减轻（封存、事前冻结）不能消除；合成攻击路径不是真实样本外业绩。本项目仅供量化研究与教育示例，不构成投资建议，不承诺收益。
