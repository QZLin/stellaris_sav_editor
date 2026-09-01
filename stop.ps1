# ============================================================
#  stop.ps1 - 停止 Stellaris 存档修改器的前后端进程
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File stop.ps1
#    powershell -ExecutionPolicy Bypass -File stop.ps1 -BackendOnly
# ============================================================

param(
    [int]$BackendPort = 3001,
    [int]$FrontendPort = 3000,
    [switch]$BackendOnly
)

function Stop-Port([int]$Port, [string]$Name) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "    $Name (端口 $Port): 未在运行" -ForegroundColor DarkGray
        return
    }
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
        try {
            $proc = Get-Process -Id $procId -ErrorAction Stop
            Write-Host "    停止 $Name (端口 $Port): PID $procId ($($proc.ProcessName))" -ForegroundColor Yellow
            # 结束进程树 (uv -> python / node -> next)
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            taskkill /PID $procId /T /F 2>$null | Out-Null
        } catch { }
    }
}

Write-Host "`n==> 停止 Stellaris 存档修改器服务" -ForegroundColor Cyan

if (-not $BackendOnly) {
    Stop-Port $FrontendPort 'Next.js 前端'
}
Stop-Port $BackendPort 'Python 后端'

# 清理 uv 派生的 python 子进程 (以防端口监听者是父进程)
Get-Process -Name python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*save-parser*' } |
    ForEach-Object {
        Write-Host "    停止残留 python 进程: PID $($_.Id)" -ForegroundColor Yellow
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }

Write-Host "    完成." -ForegroundColor Green
