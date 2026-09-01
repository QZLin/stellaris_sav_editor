# Stellaris Save Editor

基于 Web 的群星 (Stellaris) 存档修改工具。

## 架构

- **前端**: Next.js 16 + React 19 + Tailwind CSS 4 + shadcn/ui — 包管理器 `pnpm`
- **后端**: Python 3 标准库 HTTP 服务（无第三方依赖，`http.server` 实现）— 环境管理 `uv`
- **通信**: REST API。请求路由三条路径殊途同归：
  1. 托管平台：`/api/*?XTransformPort=3001` 由平台网关直接转发到后端端口
  2. **本地部署**：Next.js 内置的 `/api/*` 兜底代理路由（`src/app/api/[...path]/route.ts`）
     自动把请求转发到 `127.0.0.1:3001`，因此本地 `pnpm dev` + `python server.py`
     与云端行为完全一致（修复了本地 `POST /api/upload 404` 问题）
  3. `NEXT_PUBLIC_API_URL` 环境变量：前端直连后端，完全绕过代理

## 功能

- 解析 `.sav` 存档（ZIP 格式，含 `gamestate` + `meta`）
- 存档预拆分：country / species_db / fleet / leaders / galactic_object 按实体拆为独立文件
- 查看/编辑国家资源（能源、矿物、合金等 17 种）
- 修改游戏日期、帝国名称、帝国旗帜、延时事件
- 导出修改后的存档（字节级精准修改，未改动的部分保持原样）

## 快速开始

### Windows 一键启动（推荐）

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

脚本会自动完成：检查 node/pnpm/uv → `pnpm install` → `uv sync` 创建 Python 虚拟环境 →
后台启动 Python 服务（端口 3001）→ 前台启动 Next.js（端口 3000）→ 打开浏览器。
按 `Ctrl+C` 停止前端并自动清理后端进程；`stop.ps1` 可强制停止全部服务。

### 手动启动（跨平台）

```bash
# 前端
pnpm install
pnpm dev                 # http://localhost:3000

# 后端 (任选其一)
cd mini-services/save-parser
uv run server.py         # uv 自动管理虚拟环境
# 或
python server.py         # 标准库实现, 无需 pip install
```

### 环境变量（可选）

| 变量 | 默认 | 说明 |
|------|------|------|
| `PORT` | `3001` | Python 后端监听端口 |
| `BACKEND_PORT` | `3001` | Next.js 代理路由转发目标端口 |
| `BACKEND_HOST` | `127.0.0.1` | 代理目标主机 |
| `BACKEND_URL` | — | 完整后端地址，覆盖端口/主机设置 |
| `NEXT_PUBLIC_API_URL` | — | 前端直连后端（绕过代理） |
| `SPLIT_BLOCKS` | `country,species_db,fleet,leaders,galactic_object` | 预拆分哪些顶层块 |
| `SAVE_VERIFY` | `0` | `=1` 时上传后执行拆分-重组字节级校验 |

## 项目结构

```
├── src/
│   ├── app/
│   │   ├── page.tsx              # 主页面 (上传 + 编辑器)
│   │   ├── api/[...path]/route.ts # /api/* 兜底代理 -> Python 后端
│   │   └── globals.css
│   ├── components/ui/            # shadcn/ui 组件
│   ├── hooks/
│   └── lib/save-api.ts           # 后端 API 客户端
├── mini-services/save-parser/
│   ├── server.py                 # REST API (ThreadingHTTPServer)
│   ├── clausewitz_parser.py      # Clausewitz 格式解析器
│   ├── save_splitter.py          # 存档预拆分优化
│   └── pyproject.toml            # uv 项目定义 (标准库, 零依赖)
├── start.ps1                     # 一键启动 (pnpm + uv)
├── stop.ps1                      # 停止前后端
├── pnpm-workspace.yaml           # pnpm 构建脚本许可
└── package.json
```

## 技术细节

### Clausewitz 格式

Paradox 引擎使用的文本格式：
- `key=value` 锭值对
- `key={...}` 嵌套块
- 数字键（如 `0={...}`）表示隐式列表
- 顶层的 `player` 块记录玩家国家

### 存档预拆分（参考 [stellaris-sav-tool](https://github.com/QZLin/stellaris-sav-tool)）

上传时把 44MB 的 `gamestate` 按实体预拆分为 ~3500 个独立文本文件
（`country_0.txt`、`fleet_42.txt`、...），核心设计：

- **字符串安全的括号计数**——引号内的 `{`/`}` 不参与深度计算，保证子块边界永远正确
- **字节级可逆**——拆分文件是原文的逐字切片，`newline=''` I/O 杜绝 Windows 换行符翻译；
  重组后与原始 `gamestate` 字节一致（`verify_roundtrip` 可自动校验）
- **O(1) 拼接**——manifest 记录每个子块的字符偏移区间，修改后用 3 次字符串切片拼回主文本，
  并自动重定基后续偏移
- **重复顶层键**——以 `__N` 后缀区分（如 `saved_event_target` 在存档中出现 108 次）

性能对比（44MB 存档实测）：

| 操作 | 无拆分 | 预拆分 |
|------|--------|--------|
| 上传响应 | ~13s（含全量解析） | ~2.5s（全量解析转后台线程） |
| 单国家读取/修改 | ~10s（44MB 重解析） | 15-260ms（单文件 20-300KB） |
| 拼回主文本 | O(44MB) 逐行重扫 | O(1) 字符偏移切片 |

### 后端并发

`ThreadingHTTPServer` + 全局状态锁；上传后全量解析在后台线程进行，
按需读取的端点（`/api/stats`、`/api/resources` 等）直接读拆分文件，无需等待。
