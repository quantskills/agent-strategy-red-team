"""合并分块运行结果：python merge_runs.py <out_dir> <chunk_tar_or_dir>... [--extra <run_dir>]...

EVO 上每块产出 e13_chunk<k>.tar.gz（chunk<k>/runs、adjudication.json、attempts.jsonl、env_info.json）。
本脚本把它们和本机运行目录（如 A3 LLM 臂的 out/a3_local）合成一个运行目录，供 summarize / regress / report_e13 使用。
只做拼接与去重校验，不重算任何结果；同一 (arm, vid, seed) 出现两次直接报错。
"""
from __future__ import annotations

import json
import shutil
import sys
import tarfile
from pathlib import Path


def _safe_extract(tar_path: Path, dest: Path):
    with tarfile.open(tar_path) as t:
        for m in t.getmembers():
            p = (dest / m.name).resolve()
            if not str(p).startswith(str(dest.resolve())) or m.issym() or m.islnk():
                raise SystemExit(f"拒绝解压可疑路径：{m.name}")
        t.extractall(dest)


def main(argv):
    out = Path(argv[0])
    srcs, extras, i = [], [], 1
    while i < len(argv):
        if argv[i] == "--extra":
            extras.append(Path(argv[i + 1]))
            i += 2
        else:
            srcs.append(Path(argv[i]))
            i += 1
    if out.exists():
        raise SystemExit(f"{out} 已存在，换一个目录名，避免覆盖")
    (out / "runs").mkdir(parents=True)
    stage = out / "_chunks"
    stage.mkdir()
    dirs = []
    for s in srcs:
        if s.suffix == ".gz":
            _safe_extract(s, stage)
            dirs.extend(sorted(p for p in stage.iterdir() if p.is_dir() and p not in dirs))
        else:
            dirs.append(s)
    dirs = list(dict.fromkeys(dirs)) + extras
    adj, seen, attempts, envs = [], set(), [], []
    for d in dirs:
        for r in json.loads((d / "adjudication.json").read_text()):
            key = (r["arm"], r["vid"], r["seed"])
            if key in seen:
                raise SystemExit(f"重复的运行 {key}（来自 {d}）")
            seen.add(key)
            r["source"] = d.name
            adj.append(r)
        for f in (d / "runs").glob("*.jsonl"):
            if (out / "runs" / f.name).exists():
                raise SystemExit(f"重复的运行文件 {f.name}")
            shutil.copy2(f, out / "runs" / f.name)
        if (d / "attempts.jsonl").exists():
            attempts.extend(l for l in (d / "attempts.jsonl").read_text().splitlines() if l.strip())
        if (d / "env_info.json").exists():
            envs.append(json.loads((d / "env_info.json").read_text()))
        for extra_file in ("llm_calls.jsonl",):
            if (d / extra_file).exists():
                shutil.copy2(d / extra_file, out / extra_file)
    (out / "adjudication.json").write_text(json.dumps(adj, ensure_ascii=False, indent=1))
    (out / "attempts.jsonl").write_text("\n".join(attempts) + "\n")
    if envs:
        e0 = {k: v for k, v in envs[0].items() if k not in ("chunk", "vids", "arms", "elapsed_s")}
        e0["chunks"] = [{k: e.get(k) for k in ("chunk", "vids", "arms", "elapsed_s")} for e in envs]
        e0["local_runs"] = [str(x) for x in extras]
        (out / "env_info.json").write_text(json.dumps(e0, ensure_ascii=False, indent=1))
    shutil.rmtree(stage)
    by_arm = {}
    for r in adj:
        by_arm[r["arm"]] = by_arm.get(r["arm"], 0) + 1
    print(f"合并 {len(adj)} 个运行：{by_arm}；运行文件 {len(list((out / 'runs').glob('*.jsonl')))} 个 → {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
