# ============================================================
#  start.ps1 - Stellaris 存档修改器一键启动脚本 (Windows PowerShell)
#
#  技术栈与包管理器:
#    前端  : Next.js 16 (React 19 + Tailwind 4 + shadcn/ui) -> pnpm
#    后端  : Python 标准库 HTTP 服务                        -> uv
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File start.ps1     # 一键启动前后端
#    powershell -ExecutionPolicy Bypass -File start.ps1 -BackendOnly
#    powershell -ExecutionPolicy Bypass -File start.ps1 -NoBrowser
#
#  环境变量(可选):
#    BACKEND_PORT   后端端口 (默认 3001)
#    FRONTEND_PORT  前端端口 (默认 3000, 仅影响 pnpm dev -p)
#    SPLIT_BLOCKS   预拆分顶层块, 逗号分隔 (默认 country,species_db,fleet,
#                   leaders,galactic_object; "all" 见 save_splitter.py)
#    SAVE_VERIFY=1  上传后执行拆分-重组字节级校验(调试用)
# ============================================================

param(
    [int]$BackendPort = 3001,
    [int]$FrontendPort = 3000,
    [switch]$BackendOnly,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$BackendDir = Join-Path $Root 'mini-services/save-parser'

function Write-Step($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "    $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "    $msg" -ForegroundColor Red }

# ---------- 1. 前置检查 ----------
Write-Step '检查依赖工具 (node / pnpm / uv)'

$missing = @()
foreach ($tool in @('node', 'pnpm', 'uv')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { $missing += $tool }
}
if ($missing.Count -gt 0) {
    Write-Fail "缺少工具: $($missing -join ', ')"
    Write-Host @'
安装方式:
  node   https://nodejs.org/ (LTS)
  pnpm   npm install -g pnpm        (或 winget install pnpm.pnpm)
  uv     winget install astral-sh.uv (或 https://docs.astral.sh/uv/)
'@
    exit 1
}
Write-Ok "node $((node --version)) / pnpm $((pnpm --version)) / uv $((uv --version)) 已就绪"

# ---------- 2. 前端依赖 ----------
if (-not $BackendOnly) {
    if (-not (Test-Path (Join-Path $Root 'node_modules'))) {
        Write-Step '安装前端依赖 (pnpm install, 首次运行需要几分钟)'
        Push-Location $Root
        try {
            pnpm install
            if ($LASTEXITCODE -ne 0) { throw 'pnpm install 失败' }
        } finally { Pop-Location }
        Write-Ok '前端依赖安装完成'
    } else {
        Write-Ok '前端依赖已存在 (删除 node_modules 可强制重装)'
    }
}

# ---------- 3. 后端 Python 环境 (uv) ----------
Write-Step '准备 Python 后端环境 (uv)'
Push-Location $BackendDir
try {
    if (-not (Test-Path '.venv')) {
        # 标准库实现, 无第三方依赖; uv 会自动创建虚拟环境
        uv sync --quiet
        if ($LASTEXITCODE -ne 0) { throw 'uv sync 失败' }
        Write-Ok '已创建 .venv 虚拟环境'
    } else {
        Write-Ok '虚拟环境已存在'
    }
} finally { Pop-Location }

# ---------- 4. 启动后端 (已运行则跳过) ----------
function Test-BackendAlive([int]$Port) {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 2 | Out-Null
        return $true
    } catch { return $false }
}

$pyProc = $null
if (Test-BackendAlive $BackendPort) {
    Write-Step "Python 后端已在端口 $BackendPort 运行, 跳过启动"
} else {
    Write-Step "启动 Python 后端 (uv run server.py, 端口 $BackendPort)"
    $env:PORT = "$BackendPort"
    # 后台隐藏窗口运行; 记录 PID 以便退出时清理
    $pyProc = Start-Process -FilePath 'uv' -ArgumentList 'run', 'server.py' `
        -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Root 'backend.log') `
        -RedirectStandardError  (Join-Path $Root 'backend.err.log')

    $ok = $false
    for ($i = 0; $i -lt 40; $i++) {
        if ($pyProc.HasExited) { break }
        if (Test-BackendAlive $BackendPort) { $ok = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ok) {
        Write-Fail "后端启动失败, 详见 backend.log / backend.err.log"
        if (-not $pyProc.HasExited) { Stop-Process -Id $pyProc.Id -Force }
        exit 1
    }
    Write-Ok "Python 后端已启动 (PID $($pyProc.Id)) -> http://127.0.0.1:$BackendPort"
}

if ($BackendOnly) {
    Write-Host "`n后端已就绪. 按 Ctrl+C 结束后端服务." -ForegroundColor Cyan
    try {
        Wait-Process -Id $pyProc.Id -ErrorAction SilentlyContinue
    } catch { }
    if ($pyProc -and -not $pyProc.HasExited) { Stop-Process -Id $pyProc.Id -Force }
    exit 0
}

# ---------- 5. 启动前端 ----------
# 让 Next.js 的 /api 代理路由转发到正确端口
$env:BACKEND_PORT = "$BackendPort"

Write-Step "启动 Next.js 前端 (pnpm dev, 端口 $FrontendPort)"
Write-Host "    前端: http://localhost:$FrontendPort"
Write-Host "    后端: http://127.0.0.1:$BackendPort"
Write-Host "    (Next.js 已内置 /api/* 代理, 无需额外网关; 停止: Ctrl+C)"
if (-not $NoBrowser) {
    Start-Sleep -Seconds 2
    Start-Process "http://localhost:$FrontendPort"
}

try {
    Push-Location $Root
    # 直接调用 next dev 以便指定端口 (绕过 package.json 中的固定 -p 3000)
    pnpm exec next dev -p $FrontendPort
} finally {
    Pop-Location
    if ($pyProc -and -not $pyProc.HasExited) {
        Write-Host "`n==> 正在停止 Python 后端 (PID $($pyProc.Id))..." -ForegroundColor Cyan
        Stop-Process -Id $pyProc.Id -Force -ErrorAction SilentlyContinue
    }
}
