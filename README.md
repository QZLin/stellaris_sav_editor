# Stellaris Save Editor

基于 Web 的群星 (Stellaris) 存档修改工具。

## 架构

- **前端**: Next.js 16 + React 19 + Tailwind CSS 4 + shadcn/ui
- **后端**: Python 3 (Flask) — Clausewitz 格式解析器
- **通信**: REST API，前端通过 `XTransformPort` 网关代理到 Python 后端

## 功能

- 解析 `.sav` 存档（ZIP 格式，含 `gamestate` + `meta`）
- 查看/编辑国家资源（能源、矿物、合金等）
- 修改游戏日期、帝国名称
- 导出修改后的存档

## 快速开始

### 前端

```bash
pnpm install
pnpm dev
```

前端运行在 `http://localhost:3000`。

### 后端

```bash
cd mini-services/save-parser
pip install flask
python server.py
```

后端运行在 `http://localhost:3001`。

## 项目结构

```
├── src/                    # Next.js 前端
│   ├── app/
│   │   ├── page.tsx        # 主页面
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── components/ui/      # shadcn/ui 组件
│   ├── hooks/
│   └── lib/
│       ├── save-api.ts     # 后端 API 客户端
│       └── utils.ts
├── mini-services/
│   └── save-parser/
│       ├── server.py           # Flask REST API
│       ├── clausewitz_parser.py # Clausewitz 格式解析器
│       └── save_splitter.py    # 存档预拆分优化
├── package.json
├── next.config.ts
└── tsconfig.json
```

## 技术细节

### Clausewitz 格式

Paradox 引擎使用的文本格式：
- `key=value` 键值对
- `key={...}` 嵌套块
- 数字键（如 `0={...}`）表示隐式列表

### 存档预拆分

44MB 的 `gamestate` 文件会被预拆分为独立的实体文件（如 `country_0.txt`），
使得单国家操作从 10s 降到 2-67ms，无需重新解析整个文件。
