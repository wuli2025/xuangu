<#
  SENTIO · 斐波那契趋势选股 — 每日盘后自动调度
  注册 Windows 计划任务：交易日(周一~周五) 15:30 收盘后自动跑 run_fib.py --quick，
  刷新当日选股候选与回测，产出 fib_strategy.json（前端「斐波选股」页直接看最新）。

  用法（在 data-pipeline 目录下 PowerShell 执行）：
    .\schedule_daily.ps1 install     # 安装/更新 每日 15:30 计划任务
    .\schedule_daily.ps1 uninstall   # 卸载
    .\schedule_daily.ps1 status      # 查看任务状态
    .\schedule_daily.ps1 run         # 立即手动跑一次（验证）
    .\schedule_daily.ps1 install -Time 15:45   # 自定义时间

  说明：A股 15:00 收盘，15:30 数据基本就绪。周末/节假日新浪当日无新数据，脚本会复用上次。
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet('install', 'uninstall', 'status', 'run')]
  [string]$Action = 'status',
  [string]$Time = '15:30'
)

$ErrorActionPreference = 'Stop'
$TaskName = 'SENTIO-Fib-DailyScan'
$Dir = $PSScriptRoot
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { $Py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $Py) { $Py = (Get-Command py -ErrorAction SilentlyContinue).Source }

function Install-Task {
  if (-not $Py) { Write-Error '未找到 python，请先安装 Python 3 + akshare/pandas'; return }
  $action = New-ScheduledTaskAction -Execute $Py `
    -Argument 'run_fib.py --quick' -WorkingDirectory $Dir
  # 工作日触发；用 At 指定时间
  $trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $Time
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description 'SENTIO 斐波那契趋势策略：交易日盘后自动选股+回测' -Force | Out-Null

  Write-Host "[OK] 已注册计划任务 '$TaskName'：周一~周五 $Time 自动跑斐波那契选股" -ForegroundColor Green
  Write-Host "     解释器 : $Py"
  Write-Host "     工作目录: $Dir"
  Write-Host "     产物    : output/fib_strategy.json + ../polaris-app/public/sentio/fib_strategy.json"
  Write-Host "     卸载    : .\schedule_daily.ps1 uninstall"
}

function Uninstall-Task {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] 已卸载计划任务 '$TaskName'" -ForegroundColor Yellow
  }
  else { Write-Host "未发现计划任务 '$TaskName'，无需卸载" }
}

function Show-Status {
  $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if (-not $t) {
    Write-Host "计划任务 '$TaskName' 未安装。运行 .\schedule_daily.ps1 install 安装。" -ForegroundColor Yellow
    return
  }
  $info = Get-ScheduledTaskInfo -TaskName $TaskName
  Write-Host "计划任务 '$TaskName'" -ForegroundColor Cyan
  Write-Host "  状态      : $($t.State)"
  Write-Host "  上次运行  : $($info.LastRunTime)  (结果 $($info.LastTaskResult))"
  Write-Host "  下次运行  : $($info.NextRunTime)"
}

function Run-Now {
  if (-not $Py) { Write-Error '未找到 python'; return }
  Write-Host "立即手动跑一次斐波那契选股（--quick）…" -ForegroundColor Cyan
  Push-Location $Dir
  try {
    $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
    & $Py run_fib.py --quick
  }
  finally { Pop-Location }
}

switch ($Action) {
  'install' { Install-Task }
  'uninstall' { Uninstall-Task }
  'status' { Show-Status }
  'run' { Run-Now }
}
