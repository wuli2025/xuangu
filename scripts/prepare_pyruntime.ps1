<#
.SYNOPSIS
  把「可重定位的内置 Python 运行时 + 全部依赖 + data-pipeline 源码」准备进安装包资源目录。
  CI(release.yml) 与 本地打包/调试 共用本脚本，保证 Windows 安装包自带 Python，用户机器无需自装。

.DESCRIPTION
  1) 从 astral-sh/python-build-standalone 下载 install_only 版 CPython(可整目录搬运)；
  2) 解压到 polaris-app/src-tauri/resources/pyruntime/；
  3) 用该内置 python 把 data-pipeline/requirements.txt 的依赖(akshare/pandas/numpy…)装进它自己的 site-packages；
  4) 复制 data-pipeline 源码(排除 data/output/__pycache__)到 resources/data-pipeline/。
  之后 `npm run tauri build` 会把这两个目录打进 NSIS 安装包(见 tauri.conf.json bundle.resources)。

.EXAMPLE
  pwsh ./scripts/prepare_pyruntime.ps1
#>
[CmdletBinding()]
param(
  [string]$PbsRelease = "20241016",   # python-build-standalone 发布日期 tag
  [string]$PyVersion  = "3.12.7"      # CPython 版本
)
$ErrorActionPreference = "Stop"
# 内置 python 自检会 print 中文；CI 控制台是 cp1252(charmap)→ 不强制 UTF-8 会 UnicodeEncodeError 退1。
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$repo     = Split-Path -Parent $PSScriptRoot
$pipeline = Join-Path $repo "data-pipeline"
$resDir   = Join-Path $repo "polaris-app\src-tauri\resources"
$pyDest   = Join-Path $resDir "pyruntime"
$dpDest   = Join-Path $resDir "data-pipeline"

$asset = "cpython-$PyVersion+$PbsRelease-x86_64-pc-windows-msvc-install_only.tar.gz"
$url   = "https://github.com/astral-sh/python-build-standalone/releases/download/$PbsRelease/$asset"

New-Item -ItemType Directory -Force -Path $resDir | Out-Null
$tmpTar = Join-Path $env:TEMP "pbs_$PbsRelease.tar.gz"
$tmpDir = Join-Path $env:TEMP "pbs_extract_$PbsRelease"

Write-Host "==> 下载内置 Python: $url"
Invoke-WebRequest -Uri $url -OutFile $tmpTar

Write-Host "==> 解压到 $pyDest"
if (Test-Path $pyDest) { Remove-Item -Recurse -Force $pyDest }
if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
tar -xzf $tmpTar -C $tmpDir          # Win10+ 自带 bsdtar
Move-Item (Join-Path $tmpDir "python") $pyDest

$py = Join-Path $pyDest "python.exe"
Write-Host "==> 安装依赖到内置 Python(site-packages)"
& $py -m pip install --upgrade pip --no-warn-script-location
& $py -m pip install --no-warn-script-location --no-cache-dir -r (Join-Path $pipeline "requirements.txt")

Write-Host "==> 复制 data-pipeline 源码(排除 data/output/__pycache__)"
if (Test-Path $dpDest) { Remove-Item -Recurse -Force $dpDest }
New-Item -ItemType Directory -Force -Path $dpDest | Out-Null
$exclude = @("data", "output", "__pycache__", ".pytest_cache")
Get-ChildItem -Path $pipeline -Force | Where-Object { $exclude -notcontains $_.Name } | ForEach-Object {
  Copy-Item $_.FullName -Destination $dpDest -Recurse -Force
}

Write-Host "==> 自检"
& $py -c "import akshare, pandas, numpy, requests; print('内置 Python OK · akshare', akshare.__version__, '· pandas', pandas.__version__)"
Write-Host "[OK] 内置运行时就绪: $pyDest"
Write-Host "[OK] 管线源码就绪:   $dpDest"
