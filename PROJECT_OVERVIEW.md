# LLM-Filter-Probe - 项目概览

## 目录

1. [项目定位与价值](#项目定位与价值)
2. [核心能力](#核心能力)
3. [系统架构](#系统架构)
4. [技术栈](#技术栈)
5. [运行与开发](#运行与开发)
6. [目录结构](#目录结构)
7. [配置与扩展](#配置与扩展)
8. [相关文档](#相关文档)

---

## 项目定位与价值

LLM-Filter-Probe 是一款面向内容安全与风控研究的敏感词逆向定位工具。本项目采用“宏观二分 + 微观精确定位”的混合算法，旨在通过最小化的 API 交互开销，精准还原 NEWAPI 及各类 LLM 中转服务商在用户输入侧 (Prompt) 实施的关键词拦截字典。

---

## 核心能力

- **混合算法**
  - 长文本：采用二分法快速收敛定位范围。
  - 短文本：通过双向挤压算法精准到词汇级。
  - 自动切换阈值：根据文本长度智能选择算法（默认 35 字符）。
- **精准定位策略**
  - 采用“先切片，后挤压”的原则，有效处理多个敏感词紧密相邻的复杂场景。
  - 通过前向扫描隔离首个敏感目标，再对其进行精确的边界收缩，确保结果的完整性。
- **物理位置推进**
  - 扫描过程中不依赖掩码来改变文本，而是通过记录已发现词汇的坐标，从物理位置上推进扫描，确保所有坐标计算的准确性。
- **黄金流程三阶段精炼**
  - **验证阶段**：对所有候选片段进行 API 再次验证，过滤掉“幻觉长句”。
  - **精炼阶段**：处理候选片段中的包含关系，提取最终的核心关键词。
  - **清点阶段**：用核心关键词重新进行全局搜索，得到最准确的位置和数量。
- **等长延迟掩码**
  - 敏感词替换为相同长度的 `*`，保持文本长度不变，坐标系始终一致。
  - 在获取信号量后、发送请求前应用掩码，充分利用并发任务的发现结果。
  - 若掩码后文本为空，直接跳过 API 请求。
- **实时反馈**
  - 通过 WebSocket 推送扫描进度与结果。
  - 提供结果搜索与分页功能。
- **灵活配置**
  - 支持 `settings/presets/algorithm/API` 多维度配置，并允许用户自定义覆盖。
  - 采用统一的配置定义，集中管理所有配置相关的定义。
- **完整日志**
  - 提供详细的扫描日志与导出支持，确保问题可追溯。
  - 使用结构化日志工具，提供统一的日志记录接口。

---

## 系统架构

```
前端 (Vue 3 + Vite)
  ├─ 扫描界面 / 设置面板 / 日志查看
  ├─ 搜索与分页功能
  └─ WebSocket + REST 与后端交互
        ↓
后端 (FastAPI + Python)
  ├─ 中间件：日志、错误处理、CORS
  ├─ 路由层：REST API / WebSocket
  ├─ 服务层：ScanService
  ├─ 核心层：
  │   ├─ TextScanner（文本扫描协调器）
  │   ├─ BinarySearcher（宏观二分查找）
  │   ├─ PrecisionScanner（微观精确定位）
  │   ├─ GlobalMaskManager（全局掩码管理）
  │   └─ StructuredLogger（结构化日志）
  └─ 配置系统：
      ├─ ConfigManager（配置管理与热重载）
      ├─ ConfigDefinitions（配置定义统一）
      └─ 凭证/设置/预设/算法配置
        ↓
上游 LLM API（OpenAI / 中转服务）```

**分层职责（简表）**：
- **中间件**：统一处理日志、异常和跨域请求。
- **路由层**：定义对外 API 接口与 WebSocket 事件。
- **服务层**：负责业务逻辑编排与会话管理。
- **核心层**：实现核心算法引擎、策略选择、掩码管理和日志记录。
- **配置层**：集中加载、合并配置并支持热重载。

---

## 技术栈

- **后端**：Python 3.9+、FastAPI、Uvicorn/Gunicorn、tenacity
- **前端**：Vue 3、Vite、Pinia
- **通信**：REST + WebSocket
- **部署**：一键脚本 / Docker Compose / Nginx+Gunicorn（生产）

---

## 运行与开发

优先推荐使用一键脚本（自动安装依赖并启动前后端）：

- **Windows**：
```bash
start_system.bat
```
- **macOS / Linux**：
```bash
bash start_system.sh
```

**访问地址**：
```
http://localhost:19001
```

**手动方式（可选）**：
- 终端 1（后端）
```bash
cd backend
# Windows: venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
python -m uvicorn main:app --reload
```
- 终端 2（前端）
```bash
cd frontend
npm run dev
```

更多部署方式见《[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)》。

---

## 目录结构

```
LLM-Filter-Probe/
├── backend/
│   ├── core/
│   │   ├── engine/                # API 探测/构建/分析/重试
│   │   ├── scanner/               # 宏观二分/微观精确定位/扫描协调器
│   │   ├── config_manager.py      # 配置管理与热重载
│   │   ├── config_definitions.py  # 配置定义统一
│   │   ├── global_mask_manager.py # 全局掩码管理
│   │   ├── structured_logger.py   # 结构化日志工具
│   │   ├── event_bus.py           # 事件总线
│   │   └── constants.py           # 常量
│   ├── routes/ (api.py, websocket.py)
│   ├── services/ (scan_service.py)
│   ├── middleware/ (logging.py, error_handler.py)
│   ├── models/ (request.py, response.py)
│   ├── app.py / main.py
│   
├── frontend/
│   └── src/ (components / stores / utils / constants / App.vue / main.js)
│
├── config/
│   ├── API/credentials.json
│   ├── settings/{default.json, user.json}
│   ├── presets/{official.json, relay.json, custom.json}
│   └── algorithm/default.json
│
├── docs/ (ALGORITHM.md / ARCHITECTURE.md / CONFIGURATION.md / QUICKSTART.md)
├── DEPLOYMENT_GUIDE.md
├── PARAMETER_REFERENCE.md
├── PROJECT_OVERVIEW.md
├── CHANGELOG.md
├── docker-compose.yml
├── requirements.txt
├── start_system.bat
└── start_system.sh
```

---

## 配置与扩展

- **配置来源与优先级**：
  1) `settings/default.json`（系统默认）
  2) `settings/user.json`（用户覆盖）
  3) `presets/*`（拦截/重试规则）
  4) `algorithm/default.json`（算法参数）
  5) `API/credentials.json`（上游地址与密钥）
- **热重载**：每次扫描前重新加载配置，修改后无需重启。
- **可扩展点**：
  - **扫描策略**：新增策略并在策略选择器中注册。
  - **预设规则**：新增/调整 `block/retry` 规则集。
  - **引擎适配**：为不同上游 API 增加请求/响应适配器。
  - **掩码管理**：通过 `GlobalMaskManager` 扩展掩码策略。
  - **日志记录**：通过 `StructuredLogger` 扩展日志功能。

## 相关文档

- [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) - 部署与运维指南
- [PARAMETER_REFERENCE.md](./PARAMETER_REFERENCE.md) - 参数与调优手册
- [CHANGELOG.md](./CHANGELOG.md) - 版本迭代记录