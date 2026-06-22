<#
  SENTIO 量化系统 · 多任务自动调度（Windows 计划任务）
  一次注册多个定时任务，覆盖「盘前更新 → 盘后选股 → 收盘复检 → 周末全量」完整运维节律：

    ┌ SENTIO-1-Premarket   交易日 09:00  增量更新行情(datastore)     —— 开盘前备好最新数据
    ├ SENTIO-2-PostClose   交易日 15:30  选股+AI排雷+纸上交易+监控   —— 盘后主运行(run_fib.py --quick)
    ├ SENTIO-3-HealthCheck 交易日 15:55  系统健康复检(monitor)       —— 四层状态/告警
    └ SENTIO-4-WeeklyFull  每周六 10:00  全量回测(含参数寻优)        —— 周末深跑(run_fib.py 全量)

  用法（在 data-pipeline 目录 PowerShell 执行）：
    .\schedule_quant.ps1 install     # 注册/更新 全部 4 个任务
    .\schedule_quant.ps1 uninstall   # 卸载全部
    .\schedule_quant.ps1 status      # 查看全部任务状态
    .\schedule_quant.ps1 run         # 立即手动跑一遍盘后主运行(验证)

  说明：A股 15:00 收盘、15:30 数据就绪；周末/节假日新浪当日无新数据时复用上次。
        若要跑大宇宙(中证800)，先设环境变量 $env:SENTIO_WATCHLIST="universe.json" 再 install。
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet('install', 'uninstall', 'status', 'run')]
  [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$Dir = $PSScriptRoot
$Py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Py) { $Py = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $Py) { $Py = (Get-Command py -ErrorAction SilentlyContinue).Source }

# 把宇宙选择透传给计划任务（盘前/盘后据此跑 watchlist 或 universe）
$WL = if ($env:SENTIO_WATCHLIST) { $env:SENTIO_WATCHLIST } else { 'watchlist.json' }

# ── 任务表 ──
$Tasks = @(
  @{ Name = 'SENTIO-1-Premarket';   Time = '09:00'; Weekly = $true;  Arg = 'datastore.py update-watchlist'; Limit = 25; Desc = '盘前增量更新行情' }
  @{ Name = 'SENTIO-2-PostClose';   Time = '15:30'; Weekly = $true;  Arg = 'run_fib.py --quick';            Limit = 25; Desc = '盘后选股+AI排雷+纸上交易+监控' }
  @{ Name = 'SENTIO-3-HealthCheck'; Time = '15:55'; Weekly = $true;  Arg = 'monitor.py';                    Limit = 10; Desc = '系统健康复检/告警' }
  @{ Name = 'SENTIO-4-WeeklyFull';  Time = '10:00'; Weekly = $false; Arg = 'run_fib.py';                    Limit = 40; Desc = '周末全量回测(含参数寻优)' }
)

function Install-All {
  if (-not $Py) { Write-Error '未找到 python，请先安装 Python 3 + akshare/pandas'; return }
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

  foreach ($t in $Tasks) {
    $action = New-ScheduledTaskAction -Execute $Py -Argument $t.Arg -WorkingDirectory $Dir
    if ($t.Weekly) {
      $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $t.Time
    }
    else {
      $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At $t.Time
    }
    # 每个任务单独建 settings（不复制对象，避免 ExecutionTimeLimit XML 格式错）
    $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
      -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5) `
      -ExecutionTimeLimit (New-TimeSpan -Minutes $t.Limit)
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
      -Settings $s -Principal $principal -Description "SENTIO 量化 · $($t.Desc)" -Force | Out-Null
    $when = if ($t.Weekly) { "周一~周五 $($t.Time)" } else { "每周六 $($t.Time)" }
    Write-Host ("[OK] {0,-22} {1}  ——  {2}" -f $t.Name, $when, $t.Desc) -ForegroundColor Green
  }
  Write-Host ''
  Write-Host "全部 $($Tasks.Count) 个任务已注册。" -ForegroundColor Cyan
  Write-Host "  解释器 : $Py"
  Write-Host "  工作目录: $Dir"
  Write-Host "  宇宙    : $WL  (set `$env:SENTIO_WATCHLIST 后重新 install 可切大宇宙)"
  Write-Host "  卸载    : .\schedule_quant.ps1 uninstall"
}

function Uninstall-All {
  foreach ($t in $Tasks) {
    if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
      Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
      Write-Host "[OK] 已卸载 $($t.Name)" -ForegroundColor Yellow
    }
  }
}

function Show-Status {
  Write-Host "SENTIO 量化系统 · 计划任务状态" -ForegroundColor Cyan
  foreach ($t in $Tasks) {
    $task = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
    if (-not $task) {
      Write-Host ("  [未安装] {0,-22} {1}" -f $t.Name, $t.Desc) -ForegroundColor DarkGray
      continue
    }
    $info = Get-ScheduledTaskInfo -TaskName $t.Name
    Write-Host ("  [{0,-9}] {1,-22} 下次 {2}  上次结果 {3}" -f $task.State, $t.Name, $info.NextRunTime, $info.LastTaskResult) -ForegroundColor Green
  }
}

function Run-Now {
  if (-not $Py) { Write-Error '未找到 python'; return }
  Write-Host "立即手动跑盘后主运行（run_fib.py --quick）验证…" -ForegroundColor Cyan
  Push-Location $Dir
  try {
    $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
    & $Py run_fib.py --quick
  }
  finally { Pop-Location }
}

switch ($Action) {
  'install' { Install-All }
  'uninstall' { Uninstall-All }
  'status' { Show-Status }
  'run' { Run-Now }
}
