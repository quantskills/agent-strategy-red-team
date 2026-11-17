"""E13 主流程：冻结 → 四臂同预算搜索 → 自动裁决 → 汇总。

python run_e13.py freeze            # 写 freeze.json（代码、缺陷、包络、预算的 sha256），之后改动会被拒
python run_e13.py search [--arms A0,A1,A2,A3] [--budget 300]
python run_e13.py adjudicate
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

PRODUCTS = ["RB", "I", "CU", "AL", "M", "P", "MA", "TA", "SA", "AP", "JD"]
DEV = ("20200102", "20231229")
OUT = HERE / "out"
FROZEN_FILES = ["grammar.py", "oracles.py", "harness.py", "adjudicate.py", "llm_arm.py", "defects/sealed.py",
                "../futures_replay/sim.py", "../futures_replay/data.py"]
BUDGET = {"evals_per_run": 300, "seeds": {"A0_fixed": [0], "A1_random": [1, 2, 3, 4, 5], "A2_evolve": [1, 2, 3, 4, 5], "A3_llm": [1, 2]},
          "window": {"pre": 15, "post": 60}, "llm_model": os.getenv("REDTEAM_MODEL", "DeepSeek-V4-flash"), "llm_batch": 30}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


PANEL_DIR = HERE / "data" / "panel"


def load():
    """优先读随包携带的可移植面板（EVO 上无需 PandaData 凭证）；没有时从本地数据构建并保存。"""
    from futures_replay.data import build_panel, load_panel, save_panel
    from futures_replay.sim import Config
    from grammar import envelope
    if (PANEL_DIR / "panel_meta.json").exists():
        panel = load_panel(PANEL_DIR)
    else:
        panel = build_panel(PRODUCTS)
        save_panel(panel, PANEL_DIR)
    env_p = OUT / "envelope.json"
    if env_p.exists():
        env = json.loads(env_p.read_text())
    else:
        env = envelope(panel, *DEV)
    return panel, env, Config()


def freeze():
    OUT.mkdir(parents=True, exist_ok=True)
    panel, env, cfg = load()
    (OUT / "envelope.json").write_text(json.dumps(env, ensure_ascii=False, indent=1))
    from futures_replay.data import manifest_of
    from defects.sealed import OPEN, SEALED, VARIANTS
    fz = {"frozen_at": time.strftime("%Y-%m-%d %H:%M:%S"), "files": {f: sha(HERE / f) for f in FROZEN_FILES},
          "envelope_sha256": sha(OUT / "envelope.json"), "budget": BUDGET, "config": cfg.to_dict(),
          "variants": list(VARIANTS), "open_defects": OPEN, "sealed_defects": SEALED,
          "data": manifest_of(panel), "dev_window": DEV}
    (OUT / "freeze.json").write_text(json.dumps(fz, ensure_ascii=False, indent=1))
    print("frozen", fz["frozen_at"])


def check_frozen():
    fz = json.loads((OUT / "freeze.json").read_text())
    bad = [f for f, h in fz["files"].items() if sha(HERE / f) != h]
    if bad:
        raise SystemExit(f"冻结后文件被改动：{bad}。如确需改动，重新 freeze 并在尝试账本里记录原因。")
    return fz


def _job(args):
    arm, vid, seed, budget = args
    from harness import Evaluator, run_fixed, run_random, run_evolve
    from llm_arm import run_llm
    panel, env, cfg = load()
    ev = Evaluator(panel, env, cfg, DEV)
    t = time.time()
    fn = {"A0_fixed": run_fixed, "A1_random": run_random, "A2_evolve": run_evolve}.get(arm)
    if arm == "A3_llm":
        res = run_llm(ev, vid, budget, seed, OUT / "llm_calls.jsonl", batch=BUDGET["llm_batch"])
    else:
        res = fn(ev, vid, budget, seed)
    p = OUT / "runs" / f"{arm}__{vid}__s{seed}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False, default=float) + "\n")
    return {"arm": arm, "vid": vid, "seed": seed, "n": len(res), "evals": ev.n_eval, "sec": round(time.time() - t, 1)}


def search(arms, budget, workers, vids=None):
    check_frozen()
    from defects.sealed import VARIANTS
    vlist = [v for v in VARIANTS if (not vids or v in vids)]
    jobs = [(a, v, s, budget) for a in arms for v in vlist for s in BUDGET["seeds"][a]]
    t = time.time()
    log = []
    if workers <= 1:   # 沙箱不允许多进程时的顺序执行路径，结果与并行一致
        for j in jobs:
            r = _job(j)
            log.append(r)
            print(r, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(_job, jobs):
                log.append(r)
                print(r, flush=True)
    with open(OUT / "attempts.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "action": "search", "arms": arms, "budget": budget,
                            "jobs": log, "sec": round(time.time() - t, 1)}, ensure_ascii=False) + "\n")


def _adj_job(path):
    from harness import Evaluator
    from adjudicate import adjudicate_run
    panel, env, cfg = load()
    ev = Evaluator(panel, env, cfg, DEV)
    res = [json.loads(l) for l in open(path)]
    arm, vid, s = Path(path).stem.split("__")
    out = adjudicate_run(ev, vid, res, int(s[1:]))
    out.update({"arm": arm, "vid": vid, "seed": int(s[1:]), "n_evals": len(res),
                "n_invalid": sum(1 for r in res if r.get("invalid")),
                "n_fallback": sum(1 for r in res if r.get("llm_fallback")),
                "n_hits_raw": sum(1 for r in res if r["oracles"])})
    return out


def adjudicate(workers):
    check_frozen()
    paths = sorted(str(p) for p in (OUT / "runs").glob("*.jsonl"))
    t = time.time()
    if workers <= 1:
        res = [_adj_job(pth) for pth in paths]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            res = list(ex.map(_adj_job, paths))
    (OUT / "adjudication.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print("adjudicated", len(res), "runs in", round(time.time() - t, 1), "s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["freeze", "search", "adjudicate"])
    ap.add_argument("--arms", default="A0_fixed,A1_random,A2_evolve")
    ap.add_argument("--budget", type=int, default=BUDGET["evals_per_run"])
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--vids", default="", help="只跑这些版本（逗号分隔），用于在有单次时限的平台上分块执行；默认全部")
    a = ap.parse_args()
    if a.cmd == "freeze":
        freeze()
    elif a.cmd == "search":
        search(a.arms.split(","), a.budget, a.workers, [v for v in a.vids.split(",") if v])
    else:
        adjudicate(a.workers)
