[English](./README.md) | **中文**

# 🎓 AcademiaReach — PhD 自动套磁系统

> 全自动查找导师 → 生成个性化套磁邮件 → 发送 → 跟踪回复，配备 Web UI 实时监控。

![Python](https://img.shields.io/badge/Python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green) ![React](https://img.shields.io/badge/React-18-61dafb) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 📑 目录

- [功能概览](#功能概览)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [使用指南](#使用指南)
- [API 参考](#api-参考)

---

## 功能概览

| 模块 | 功能 |
|------|------|
| **导师搜索** | LLM + Serper API 自动搜索海内外导师，支持自定义关键词 / 地区，也可手动添加 |
| **邮件撰写** | 根据导师研究方向 + 用户 Profile，LLM 生成个性化套磁邮件（中/英文自动切换） |
| **邮件发送** | 草稿人工审核 → 编辑 → 确认发送（SMTP），支持附带中/英文 PDF 简历 |
| **回复跟踪** | IMAP 轮询收件箱，双策略匹配导师回复（FROM 匹配 + 主题匹配），自动更新状态 |
| **Agent 自定义** | 搜索偏好、邮件风格、额外要求均可通过前端 UI 自定义，注入到 Agent System Prompt |
| **邮箱验证** | 前端一键验证 SMTP / IMAP 凭据并保存到配置 |
| **Web UI** | Dashboard / 导师管理 / 草稿审核 / 发送状态 / 回复跟踪 / 设置 |
| **实时进度** | WebSocket 推送搜索和邮件生成进度到前端 |

---

## 技术栈

**后端**
- Python 3.11, FastAPI, Uvicorn
- LangChain (OpenAI / DeepSeek / Ollama 多后端)
- SQLite (aiosqlite), Pydantic v2
- SMTP 发送, IMAP 收件, WebSocket

**前端**
- React 18, TypeScript, Vite
- TailwindCSS, Lucide Icons
- Axios, React Router

---

## 项目结构

```
AcademiaReach/
├── backend/
│   ├── config/
│   │   ├── config.yaml.example  # 配置模板（复制为 config.yaml 后填入真实信息）
│   │   └── my_profile.md        # 个人 Profile（研究背景、发表论文等）
│   ├── core/
│   │   ├── models.py            # Pydantic 数据模型
│   │   ├── database.py          # SQLite 异步 CRUD
│   │   └── llm.py               # LLM 统一接口（多后端切换）
│   ├── agents/
│   │   ├── search_agent.py      # 导师搜索 Agent（LLM 规划 + Serper 搜索 + 信息提取）
│   │   └── compose_agent.py     # 邮件撰写 Agent（中英文 Prompt + 自定义风格注入）
│   ├── services/
│   │   ├── send_service.py      # SMTP 邮件发送 + 简历附件
│   │   └── reply_tracker.py     # IMAP 回复跟踪（FROM + SUBJECT 双策略匹配）
│   ├── api/
│   │   ├── routes.py            # REST API + WebSocket 路由
│   │   └── websocket.py         # WebSocket 连接管理
│   ├── main.py                  # FastAPI 入口 + 启动回复轮询
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx    # 系统概览 + 实时日志
│   │   │   ├── Professors.tsx   # 导师管理（搜索 / 手动添加 / 详情）
│   │   │   ├── Drafts.tsx       # 邮件草稿审核 / 编辑
│   │   │   ├── Sent.tsx         # 已发送邮件列表
│   │   │   ├── Replies.tsx      # 导师回复跟踪
│   │   │   └── Settings.tsx     # 设置（Profile / 关键词 / Agent自定义 / 简历 / 邮箱验证）
│   │   ├── components/
│   │   │   ├── GlobalTaskIndicator.tsx  # 全局搜索/生成任务状态栏
│   │   │   ├── ProfessorDetail.tsx      # 导师详情抽屉
│   │   │   └── SearchModal.tsx          # 搜索配置弹窗
│   │   ├── services/api.ts     # Axios API 封装 + WebSocket
│   │   ├── App.tsx              # 路由 & 侧边栏布局
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
├── .gitignore
└── README.md
```

---

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/your-username/AcademiaReach.git
cd AcademiaReach
```

### 2. 后端环境

```bash
conda create -n academia python=3.11 -y
conda activate academia
pip install -r backend/requirements.txt
```

### 3. 前端环境

```bash
cd frontend
npm install        # 需要 Node.js >= 18
```

### 4. 配置

```bash
cp backend/config/config.yaml.example backend/config/config.yaml
cp backend/config/my_profile.example.md backend/config/my_profile.md
```

编辑 `backend/config/config.yaml`，填入：
- **LLM API Key** — OpenAI / DeepSeek / Ollama 任选其一（支持兼容 OpenAI 格式的第三方 API）
- **Serper API Key** — 用于导师搜索（[serper.dev](https://serper.dev) 免费申请）
- **SMTP 凭据** — 发件邮箱（也可在前端设置页验证并保存）
- **IMAP 凭据** — 收件邮箱，用于回复跟踪

编辑 `backend/config/my_profile.md`，用 Markdown 填写你的研究背景、发表论文、技能等。

### 5. 启动

```bash
# 终端 1：后端
conda activate academia
uvicorn backend.main:app --reload --port 8000

# 终端 2：前端
cd frontend
npm run dev
```

访问 **http://localhost:5173** 打开 Web UI。

---

## 配置说明

### config.yaml

```yaml
llm:
  provider: openai                  # openai / deepseek / ollama
  openai:
    api_key: "sk-..."
    model: "gpt-4o"
    base_url: "https://api.openai.com/v1"
  deepseek:
    api_key: "sk-..."
    model: "deepseek-chat"
    base_url: "https://api.deepseek.com/v1"
  ollama:
    model: "llama3"
    base_url: "http://localhost:11434"

search:
  serper_api_key: "..."
  keywords:
    - "machine learning"
    - "natural language processing"
  regions: ["US", "UK", "China"]
  max_professors: 20

smtp:
  host: "smtp.gmail.com"
  port: 587
  username: "you@gmail.com"
  password: "app-password"
  use_tls: true

imap:
  host: "imap.gmail.com"
  port: 993
  username: "you@gmail.com"
  password: "app-password"
  use_ssl: true
  poll_interval: 300              # 回复检查间隔（秒）

# 可选：自定义 Agent 行为（也可在前端设置页编辑）
prompts:
  search_preference: ""           # 搜索偏好
  compose_style_cn: ""            # 中文邮件风格
  compose_style_en: ""            # 英文邮件风格
  compose_extra_cn: ""            # 中文邮件额外要求
  compose_extra_en: ""            # 英文邮件额外要求
```

### my_profile.md

用 Markdown 写你的研究背景、发表论文、竞赛经历、目标方向等。系统会将此内容传给 LLM，用于匹配导师和生成个性化邮件。

### 简历附件

在前端设置页上传中/英文 PDF 简历，发送邮件时会自动根据导师地区附上对应语言的简历。

---

## 使用指南

1. **Dashboard** — 查看导师总数、已发送、已回复等统计，以及实时搜索/生成日志
2. **导师管理** — 点击"自动搜索"配置关键词和地区后启动 LLM+Serper 搜索，或手动添加导师；点击导师卡片查看详情
3. **邮件草稿** — 点击"生成草稿"为所有未生成邮件的导师批量生成套磁邮件；可预览、编辑正文和主题、跳过不需要的
4. **已发送** — 查看所有已发送邮件及发送时间
5. **回复跟踪** — 系统每 5 分钟自动轮询 IMAP 收件箱（双策略：FROM 精确匹配 + SUBJECT 主题匹配），也可手动点击"检查回复"
6. **设置** — 编辑 Profile / 搜索关键词与地区 / 自定义 Agent 行为 / 上传简历 / 验证邮箱凭据

---

## API 参考

### 统计 & 导师

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stats` | 系统统计概览 |
| GET | `/api/professors` | 导师列表 |
| GET | `/api/professors/{id}` | 导师详情 |
| POST | `/api/professors` | 手动添加导师 |
| DELETE | `/api/professors/{id}` | 删除导师 |
| POST | `/api/search/start` | 启动自动搜索 |
| POST | `/api/search/stop` | 终止搜索 |

### 邮件草稿 & 发送

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/drafts` | 草稿列表（`?status=pending/sent`） |
| GET | `/api/drafts/{id}` | 草稿详情 |
| PUT | `/api/drafts/{id}` | 编辑草稿 |
| POST | `/api/compose/start` | 批量生成邮件草稿 |
| POST | `/api/send/{id}` | 发送单封邮件 |
| POST | `/api/send/batch` | 批量发送 |

### 回复跟踪

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/replies` | 回复列表 |
| POST | `/api/replies/check` | 手动触发回复检查 |
| PUT | `/api/replies/{id}/read` | 标记已读 |

### 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config/profile` | 获取 Profile |
| PUT | `/api/config/profile` | 更新 Profile |
| GET | `/api/config/settings` | 获取系统配置（脱敏） |
| PUT | `/api/config/keywords` | 更新搜索关键词 / 地区 |
| GET | `/api/config/prompts` | 获取自定义 Prompt |
| PUT | `/api/config/prompts` | 更新自定义 Prompt |
| GET | `/api/config/cv` | 简历上传状态 |
| POST | `/api/config/cv/{lang}` | 上传简历（`cn` / `en`） |
| GET | `/api/config/email` | 获取邮箱配置（脱敏） |
| POST | `/api/config/email/verify` | 验证 SMTP / IMAP 连接 |
| WS | `/api/ws/progress` | WebSocket 实时进度推送 |

---

## License

MIT