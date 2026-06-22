#!/usr/bin/env bash
# 把「可重定位的内置 Python 运行时 + 全部依赖 + data-pipeline 源码」准备进安装包资源目录(macOS/Linux)。
# CI(build-mac.yml) 与 本地打包 共用本脚本，保证 .dmg 自带 Python，用户机器无需自装。
#
# 用法: bash scripts/prepare_pyruntime.sh [PBS_RELEASE] [PY_VERSION] [TARGET_TRIPLE]
#   TARGET_TRIPLE: aarch64-apple-darwin(默认) | x86_64-apple-darwin | x86_64-unknown-linux-gnu
set -euo pipefail

PBS_RELEASE="${1:-20241016}"
PY_VERSION="${2:-3.12.7}"
TARGET="${3:-aarch64-apple-darwin}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
PIPELINE="$REPO/data-pipeline"
RESDIR="$REPO/polaris-app/src-tauri/resources"
PYDEST="$RESDIR/pyruntime"
DPDEST="$RESDIR/data-pipeline"

# python-build-standalone 的 triple 与 rust target 同名
ASSET="cpython-${PY_VERSION}+${PBS_RELEASE}-${TARGET}-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/${ASSET}"

mkdir -p "$RESDIR"
TMP="$(mktemp -d)"
echo "==> 下载内置 Python: $URL"
curl -fL "$URL" -o "$TMP/py.tar.gz"

echo "==> 解压到 $PYDEST"
rm -rf "$PYDEST"
mkdir -p "$TMP/x"
tar -xzf "$TMP/py.tar.gz" -C "$TMP/x"
mv "$TMP/x/python" "$PYDEST"

PY="$PYDEST/bin/python3"
echo "==> 安装依赖到内置 Python(site-packages)"
"$PY" -m pip install --upgrade pip --no-warn-script-location
"$PY" -m pip install --no-warn-script-location --no-cache-dir -r "$PIPELINE/requirements.txt"

echo "==> 复制 data-pipeline 源码(排除 data/output/__pycache__)"
rm -rf "$DPDEST"
mkdir -p "$DPDEST"
( cd "$PIPELINE" && tar --exclude=data --exclude=output --exclude=__pycache__ --exclude='*.pyc' -cf - . ) \
  | ( cd "$DPDEST" && tar -xf - )

echo "==> 自检"
"$PY" -c "import akshare, pandas, numpy, requests; print('内置 Python OK · akshare', akshare.__version__, '· pandas', pandas.__version__)"
echo "[OK] 内置运行时就绪: $PYDEST"
echo "[OK] 管线源码就绪:   $DPDEST"
