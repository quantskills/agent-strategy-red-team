#!/bin/bash
# 打包上传 EVO：代码 + 冻结记录 + 可移植面板（不含任何凭证）。用法：bash make_bundle.sh
set -euo pipefail
cd "$(dirname "$0")/.."
OUTF=e13_bundle_20261117_0256.tar.gz
tar --exclude='__pycache__' --exclude='e13/out/runs' --exclude='*.pyc' -czf "$OUTF" \
  futures_replay e13/*.py e13/*.sh e13/defects e13/requirements.txt e13/data/panel e13/out/freeze.json e13/out/envelope.json
shasum -a 256 "$OUTF"
ls -lh "$OUTF"
