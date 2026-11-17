# PandaAI EVO 运行记录（2026-11-17）

平台：PandaAI EVO 研究工作台 v1.1.17，云端工作区（Py 3.11），入口为研究助手的“运行 Python 脚本”（Lv3 事前确认、隔离运行）。
沙箱实测：Python 3.11.14、numpy 1.26.4、pandas 2.3.3，cwd `/home/coder/project/projects/default`。单次运行最多 120 秒，禁止多进程（`ProcessPoolExecutor` 报 `PermissionError`），每次运行只能写自己的产物目录 `reports/<时间>-<标题>/`，运行之间互不可见。

## 上传的文件

| 文件 | 说明 |
|---|---|
| `e13_bundle_20261117_0256.tar.gz` | sha256 `8dd26ded170cc256c939d0f2290b2feecc297f13daf6b1651f4f4a524430e0bb`（包本身保存在开发仓库）。`e13/make_bundle.sh` 打包：`futures_replay/`、`e13/*.py`、缺陷集、可移植面板 `e13/data/panel/`、`freeze.json`（02:52:51）、`envelope.json`。不含任何凭证 |
| `evo_chunk_1.py` … `evo_chunk_24.py` | 同一份 `e13/evo_chunk.py` 的 24 个副本，sha256 均为 `bfb7e7a7584bb77f3622685677034b883f0f66c27b501ac3222886327fb8e972`；文件名决定块号 |

每块在自己的产物目录里解压包、检查冻结哈希、运行 `run_e13.py search --vids <版本> --arms <臂> --workers 1` 和 `run_e13.py adjudicate --workers 1`，再把 `runs/`、`adjudication.json`、`attempts.jsonl`、`env_info.json` 打成 `e13_chunk<k>.tar.gz`。

截图公开前裁掉了顶栏（账户点数余额），其余未改动。

## 批准方式

每块弹出一次 Lv3 确认框。批准前逐块核对脚本名为 `evo_chunk_<k>.py`、sha256 与上面一致，只点“同意一次”。没有用“本对话不再询问”。截图见 `screens/01_approval_dialog_chunk2.jpg`、`screens/02_approval_sha256_chunk2.png`。

## 24 块结果（研究助手回报，产物目录见 `screens/03_all_24_done_reports_tree.jpg`）

奇数块 = A0_fixed + A1_random，偶数块 = A2_evolve；版本顺序 CLEAN, EQ, V01 … V10。

| 块 | 版本 | 臂 | 结果 | elapsed_s | 产物（字节） | sha256 前 12 位 | runId | 产物目录 |
|---:|---|---|---|---:|---:|---|---|---|
| 1 | CLEAN | A0+A1 | 成功 | 46.7 | 68731 | `68d11e76316b` | `rba195696a9ec493c8459f0b392fa2349` | `reports/20261117-0257-evo_chunk_124` |
| 2 | CLEAN | A2 | 成功 | 33.8 | 40070 | `676f69a6ef9b` | `rf8608b0cb130477ba30ee8817b69cc6b` | `reports/20261117-0300-evo_chunk_224` |
| 3 | EQ | A0+A1 | 成功 | 48.4 | 68754 | `0b0ca6c9c2d7` | `r1e7bdd9de65349559004ad1881f47e8d` | `reports/20261117-0301-evo_chunk_324` |
| 4 | EQ | A2 | 成功 | 33.6 | 40024 | `12843c765c6b` | `r640d9688453b44388f9c192bcc65b5a5` | `reports/20261117-0302-evo_chunk_424` |
| 5 | V01 | A0+A1 | 成功 | 49.4 | 70084 | `82132ff4ccd6` | `rfd3566d724294bada4ea0df8ea457183` | `reports/20261117-0303-evo_chunk_524` |
| 6 | V01 | A2 | 成功 | 36.9 | 45447 | `eef0d20a84ec` | `r8fdaa643603c45a29974ea3f2501ab6c` | `reports/20261117-0305-evo_chunk_624` |
| 7 | V02 | A0+A1 | 成功 | 50.3 | 69209 | `96e512ee6d34` | `r55f13b3510dc41008b5ee6a0024545be` | `reports/20261117-0306-evo_chunk_724` |
| 8 | V02 | A2 | 成功 | 35.4 | 41702 | `07533c39f635` | `r26f84eece2f54d638068e9583c684e33` | `reports/20261117-0307-evo_chunk_824` |
| 9 | V03 | A0+A1 | 成功 | 53.6 | 79948 | `efcafb9a2f32` | `r59e71923eb124ea0b6edafbf1db76698` | `reports/20261117-0308-evo_chunk_924` |
| 10 | V03 | A2 | 成功 | 38.2 | 51655 | `23e4376bfb8e` | `rbbdb6d0e013f4d40a1bd8e9310275730` | `reports/20261117-0309-evo_chunk_1024` |
| 11 | V04 | A0+A1 | 成功 | 56.0 | 88072 | `1e782479a2ac` | `re31aa1c933b44c019c1fcf44398fd9c4` | `reports/20261117-0310-evo_chunk_1124` |
| 12 | V04 | A2 | 成功 | 37.8 | 52646 | `c5fda0a2fb56` | `r9747f5b2a0dc41459232cd1bb7143caa` | `reports/20261117-0311-evo_chunk_1224` |
| 13 | V05 | A0+A1 | 成功 | 48.0 | 68996 | `16872c1fec11` | `refc32723e6bc4cbb95fad4cf8f10b1ca` | `reports/20261117-0312-evo_chunk_1324` |
| 14 | V05 | A2 | 成功 | 34.1 | 40032 | `37f5e59dbb2f` | `r8ba9db4180544382af10e033e2873e58` | `reports/20261117-0313-evo_chunk_1424` |
| 15 | V06 | A0+A1 | 成功 | 48.1 | 68741 | `37423e5abc08` | `rae4cbe47c8274a47a1eb0645bf36fced` | `reports/20261117-0314-evo_chunk_1524` |
| 16 | V06 | A2 | 成功 | 33.6 | 39968 | `051d6bec7dd8` | `r3f753d26314644fcb7b295600e4e2616` | `reports/20261117-0315-evo_chunk_1624` |
| 17 | V07 | A0+A1 | 成功 | 45.0 | 68729 | `e78923b1c990` | `r195e2f28b63f43308a84634082337052` | `reports/20261117-0316-evo_chunk_1724` |
| 18 | V07 | A2 | 成功 | 31.3 | 40016 | `5be67de6c122` | `r918a618804054b01b2ed9f0a57ca9be6` | `reports/20261117-0317-evo_chunk_1824` |
| 19 | V08 | A0+A1 | 成功 | 48.4 | 69372 | `3da0bb1d4e3d` | `r58337abea05e4b3bbe93cc9bc9281007` | `reports/20261117-0318-evo_chunk_1924` |
| 20 | V08 | A2 | 成功 | 33.5 | 40843 | `32cd840a15c9` | `rd3b8fb165b4143158dc88ae430f2e12f` | `reports/20261117-0319-evo_chunk_2024` |
| 21 | V09 | A0+A1 | 成功 | 49.2 | 71394 | `a763e3bacd64` | `r45af82bcd90b400195425077ab6ebac5` | `reports/20261117-0320-evo_chunk_2124` |
| 22 | V09 | A2 | 成功 | 35.8 | 43247 | `d4d06958e48c` | `rd9ea122b3dc541f9b0d69d1a35880eaf` | `reports/20261117-0321-evo_chunk_2224` |
| 23 | V10 | A0+A1 | 成功 | 60.9 | 95307 | `b37a793e363d` | `rc793fa9de0ca4e03919dca96835fb3d1` | `reports/20261117-0322-evo_chunk_2324` |
| 24 | V10 | A2 | 成功 | 38.9 | 57361 | `fca5534c80f0` | `r5387363c76934357aae0192577de7009` | `reports/20261117-0323-evo_chunk_2424` |

24/24 成功，02:57–03:24 完成，单块最长 60.9 秒（限时 120 秒）。runId、产物目录与字节数取自各产物目录的 `result.json` 和文件本身，见 `evo_chunks_manifest.json`；块 1 的 `result.json` 截图见 `screens/04_chunk1_result_json.jpg`。

## 在 EVO 上失败或作废的尝试（如实保留）

| 时间 | 尝试 | 结果 |
|---|---|---|
| 02:33–02:43 | 让研究助手在“终端”里解压并 `bash evo_run.sh` | 工作区没有终端；助手自写的 step1–3 脚本在项目根和 `/tmp` 都没有写权限 |
| 02:45 | 一次性运行器 `evo_runner.py` | 按目录扫描找包，沙箱禁止列目录；助手还擅自改了脚本，被拒绝 |
| 02:50 | `evo_runner2.py`（按绝对路径打开包） | 多进程被禁止（`PermissionError`），且整体超过 120 秒被终止 |
| 02:56 | 改为 24 个单进程分块 | 全部成功（上表） |

旧包 `e13_bundle_20261117_0232.tar.gz` 里有一个冻结后被改动的 `futures_replay/data.py`，冻结检查会拒绝运行，因此从未用它跑实验；`0245` 包只用于失败的 `evo_runner*.py`。

## 结果取回与比对

服务器按小时计费且未开自动续费，03:25 到点停机（24 块已全部完成）。用户重新开机后，11:46 通过工作区文件下载接口取回 24 个结果包（`evo_chunks_manifest.json` 记录每个包的字节数、sha256 与 runId，本机解码后逐个校验 sha256 一致），用 `e13/merge_runs.py` 与本机 A3 结果合并为 `e13/out/final/`。24 个原始结果包原样保存在 `chunks/`。

与本机同一冻结代码的运行（A0/A1/A2 = local_run2）逐项比对，见 `compare_evo_vs_local.json`：

- 发现矩阵、各臂汇总、发现所需回放次数三张表逐字节相同；
- 132 个 A0–A2 运行文件里 588506 个离散字段（判定器命中、攻击参数、成交等）全部相同；58520 个浮点数中 312 个在末位不同，最大相对差 3.9e-13（不同 CPU 的浮点舍入）；
- 裁决结果 40109 个离散字段全部相同。

因此报告结论在 EVO 与本机上完全一致；`e13/out/final/` 采用 EVO 版本（报告"运行平台记录"一节列出每块的平台、版本与耗时）。
