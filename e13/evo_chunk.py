#!/usr/bin/env python3
"""PandaAI EVO 分块运行器：文件名 evo_chunk_<k>.py 决定跑第 k 块（k=1..24：12 个策略版本 × {A0+A1, A2} 两组臂，含裁决）。

EVO "运行 Python 脚本"单次最多 120 秒、禁止多进程，且每次运行只有自己的产物目录可写、互不可见，
所以每块独立解压、独立计算、独立打包结果；24 块结果汇总后与一次性运行完全等价（预算、种子、代码都相同）。
"""
import json, os, platform, subprocess, sys, tarfile, time
from pathlib import Path

T0 = time.time()
VIDS = ["CLEAN", "EQ", "V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10"]
ARMSETS = ["A0_fixed,A1_random", "A2_evolve"]
CHUNKS = {i + 1: (v, a) for i, (v, a) in enumerate((v, a) for v in VIDS for a in ARMSETS)}   # 24 块
K = int(Path(__file__).stem.split("_")[-1])
CWD = Path.cwd()
BUNDLE_NAME = "e13_bundle_20261117_0256.tar.gz"
bundle = None
for r in [Path("/home/coder/project/projects/default"), Path(__file__).resolve().parent, CWD]:
    try:
        with open(r / BUNDLE_NAME, "rb") as fh:
            fh.read(2)
        bundle = r / BUNDLE_NAME
        break
    except OSError:
        continue
if bundle is None:
    sys.exit(f"打不开 {BUNDLE_NAME}")
dest = CWD / "lsy04_e13"
dest.mkdir(exist_ok=True)
with tarfile.open(bundle) as t:
    t.extractall(dest)
e13 = dest / "e13"
W = "1"   # EVO 沙箱禁止多进程（ProcessPoolExecutor 报 PermissionError），只能单进程顺序执行


def run(args):
    t0 = time.time()
    r = subprocess.run([sys.executable] + args, cwd=e13, capture_output=True, text=True)
    print(f"$ python {' '.join(args)}  [exit={r.returncode}] {time.time() - t0:.1f}s", flush=True)
    print(r.stdout[-1200:], flush=True)
    if r.returncode:
        print(r.stderr[-1500:], file=sys.stderr, flush=True)
        raise SystemExit(r.returncode)


VID, ARMS = CHUNKS[K]
run(["run_e13.py", "search", "--arms", ARMS, "--vids", VID, "--workers", W])
run(["run_e13.py", "adjudicate", "--workers", W])
info = {"platform": "PandaAI EVO 云端工作区（研究助手 · 运行 Python 脚本 · 隔离运行）", "chunk": K, "vids": VID, "arms": ARMS,
        "python": sys.version.split()[0], "system": platform.platform(), "cpu_count": os.cpu_count(), "workers": W,
        "cwd": str(CWD), "bundle": bundle.name, "elapsed_s": round(time.time() - T0, 1), "finished": time.strftime("%Y-%m-%d %H:%M:%S %z")}
(e13 / "out" / f"env_info_chunk{K}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
res = CWD / f"e13_chunk{K}.tar.gz"
with tarfile.open(res, "w:gz") as t:
    t.add(e13 / "out" / "runs", arcname=f"chunk{K}/runs")
    t.add(e13 / "out" / "adjudication.json", arcname=f"chunk{K}/adjudication.json")
    t.add(e13 / "out" / "attempts.jsonl", arcname=f"chunk{K}/attempts.jsonl")
    t.add(e13 / "out" / f"env_info_chunk{K}.json", arcname=f"chunk{K}/env_info.json")
print(json.dumps(info, ensure_ascii=False))
print("result:", res, res.stat().st_size, "bytes")
print(f"EVO_CHUNK_{K}_DONE")
