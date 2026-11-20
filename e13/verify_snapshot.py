"""安装并核对评审用的冻结面板快照：python e13/verify_snapshot.py <LSY04-E13_红队Agent主动寻找策略失效反例_冻结面板快照.zip>

快照随量枢院成果附件提供（行情数据不随公开仓库分发）。本脚本：
1. 把 zip 里 e13/data/panel/ 下的文件解压到仓库对应位置（拒绝越界路径）；
2. 逐文件核对 sha256 与仓库里提交的清单 e13/out/panel_snapshot_manifest.json；
3. 核对面板记录的原始输入指纹与冻结记录 e13/out/freeze.json 的 data.input_digest 一致。
通过后运行 python e13/test_e13.py，依赖面板的 4 项检查不再 SKIPPED。
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "e13" / "out" / "panel_snapshot_manifest.json"
FREEZE = REPO / "e13" / "out" / "freeze.json"
PANEL = REPO / "e13" / "data" / "panel"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(zpath: str) -> int:
    man = json.loads(MANIFEST.read_text())
    with zipfile.ZipFile(zpath) as z:
        for m in z.namelist():
            if not m.startswith("e13/data/panel/") or m.endswith("/"):
                continue
            dest = (REPO / m).resolve()
            if not str(dest).startswith(str(PANEL.resolve())):
                raise SystemExit(f"拒绝越界路径：{m}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(m))
    bad = []
    for name, info in man["files"].items():
        p = PANEL / name
        if not p.exists():
            bad.append(f"缺少 {name}")
        elif sha(p) != info["sha256"]:
            bad.append(f"sha256 不一致 {name}")
    meta = json.loads((PANEL / "panel_meta.json").read_text())
    digest = hashlib.sha256(json.dumps(meta["fingerprints"], sort_keys=True).encode()).hexdigest()[:16]
    fz = json.loads(FREEZE.read_text())
    if digest != fz["data"]["input_digest"] or meta["fingerprints"] != fz["data"]["input_sha256_16"]:
        bad.append(f"面板输入指纹 {digest} 与冻结记录 {fz['data']['input_digest']} 不一致")
    if bad:
        print("核对失败：\n  " + "\n  ".join(bad))
        return 1
    print(f"核对通过：{len(man['files'])} 个文件 sha256 与清单一致；面板输入指纹 {digest} = freeze.json data.input_digest（冻结于 {fz['frozen_at']}）；"
          f"品种 {','.join(meta['products'])}，{meta['dates'][0]}–{meta['dates'][-1]} 共 {len(meta['dates'])} 个交易日。")
    print("下一步：python e13/test_e13.py")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
