**English** | [中文](./README_CN.md)

# 🎓 AcademiaReach — Automated PhD Application Outreach System

> Auto-discover professors → Deep-research their work → Generate personalized cold emails → Send → Track replies — all with a modern Web UI.

![Python](https://img.shields.io/badge/Python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green) ![React](https://img.shields.io/badge/React-18-61dafb) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Usage Guide](#usage-guide)
- [API Reference](#api-reference)

---

## Features

| Module | Description |
|--------|-------------|
| **Professor Search** | LLM + Serper API auto-discovers professors worldwide; supports custom keywords / regions and manual entry |
| **Deep Research** | Before composing, automatically searches for each professor's representative papers and analyzes them with LLM |
| **Email Composition** | LLM generates personalized cold emails based on professor's research + your profile (auto CN/EN switching) |
| **Email Sending** | Human-reviewed drafts → edit → confirm → send via SMTP, with optional CN/EN PDF CV attachment |
| **Reply Tracking** | IMAP inbox polling with dual matching strategy (FROM address + SUBJECT line) to catch replies reliably |
| **Agent Customization** | Search preferences, email style, and extra instructions are all editable via the UI and injected into Agent prompts |
| **Email Verification** | One-click SMTP / IMAP credential verification and save from the frontend |
| **Web UI** | Dashboard / Professor Management / Draft Review / Sent Mail / Reply Tracking / Settings |
| **Real-time Progress** | WebSocket pushes search and composition progress to the frontend live |

---

## Tech Stack

**Backend**
- Python 3.11, FastAPI, Uvicorn
- LangChain (OpenAI / DeepSeek / Ollama multi-backend)
- SQLite (aiosqlite), Pydantic v2
- SMTP sending, IMAP receiving, WebSocket

**Frontend**
- React 18, TypeScript, Vite
- TailwindCSS, Lucide Icons
- Axios, React Router

---

## Project Structure

```
AcademiaReach/
├── backend/
│   ├── config/
│   │   ├── config.yaml.example  # Config template (copy to config.yaml and fill in)
│   │   └── my_profile.md        # Your profile (research background, publications, etc.)
│   ├── core/
│   │   ├── models.py            # Pydantic data models
│   │   ├── database.py          # Async SQLite CRUD
│   │   └── llm.py               # Unified LLM interface (multi-backend)
│   ├── agents/
│   │   ├── search_agent.py      # Professor Search Agent (LLM planning + Serper + extraction)
│   │   └── compose_agent.py     # Email Compose Agent (Deep Research + CN/EN prompts + custom style)
│   ├── services/
│   │   ├── send_service.py      # SMTP email sending + CV attachment
│   │   └── reply_tracker.py     # IMAP reply tracking (FROM + SUBJECT dual matching)
│   ├── api/
│   │   ├── routes.py            # REST API + WebSocket routes
│   │   └── websocket.py         # WebSocket connection manager
│   ├── main.py                  # FastAPI entry point + reply polling startup
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx    # System overview + live logs
│   │   │   ├── Professors.tsx   # Professor management (search / add / detail)
│   │   │   ├── Drafts.tsx       # Draft review / editing
│   │   │   ├── Sent.tsx         # Sent email list
│   │   │   ├── Replies.tsx      # Reply tracking
│   │   │   └── Settings.tsx     # Settings (Profile / Keywords / Agent customization / CV / Email)
│   │   ├── components/
│   │   │   ├── GlobalTaskIndicator.tsx  # Global search/compose task status bar
│   │   │   ├── ProfessorDetail.tsx      # Professor detail drawer
│   │   │   └── SearchModal.tsx          # Search configuration modal
│   │   ├── services/api.ts     # Axios API wrapper + WebSocket
│   │   ├── App.tsx              # Router & sidebar layout
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
├── .gitignore
├── README.md
└── README_CN.md
```

---

## Getting Started

### 1. Clone

```bash
git clone https://github.com/your-username/AcademiaReach.git
cd AcademiaReach
```

### 2. Backend Setup

```bash
conda create -n academia python=3.11 -y
conda activate academia
pip install -r backend/requirements.txt
```

### 3. Frontend Setup

```bash
cd frontend
npm install        # Requires Node.js >= 18
```

### 4. Configuration

```bash
cp backend/config/config.yaml.example backend/config/config.yaml
cp backend/config/my_profile.example.md backend/config/my_profile.md
```

Edit `backend/config/config.yaml` and fill in:
- **LLM API Key** — OpenAI / DeepSeek / Ollama (also supports OpenAI-compatible third-party APIs)
- **Serper API Key** — For professor search (free at [serper.dev](https://serper.dev))
- **SMTP credentials** — Outgoing email (can also be verified and saved from the UI)
- **IMAP credentials** — Incoming email, used for reply tracking

Edit `backend/config/my_profile.md` with your research background, publications, skills, etc. in Markdown.

### 5. Launch

```bash
# Terminal 1: Backend
conda activate academia
uvicorn backend.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Configuration

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
  poll_interval: 300              # Reply check interval (seconds)

# Optional: customize Agent behavior (also editable in the Settings UI)
prompts:
  search_preference: ""           # Search preference
  compose_style_cn: ""            # Chinese email style
  compose_style_en: ""            # English email style
  compose_extra_cn: ""            # Chinese email extra instructions
  compose_extra_en: ""            # English email extra instructions
```

### my_profile.md

Write your research background, publications, competitions, target directions, etc. in Markdown. The system feeds this to the LLM for professor matching and personalized email generation.

### CV Attachment

Upload CN/EN PDF CVs in the Settings page. When sending emails, the system automatically attaches the appropriate CV based on the professor's region.

---

## Usage Guide

1. **Dashboard** — View stats (total professors, sent, replied) and live search/compose logs
2. **Professors** — Click "Auto Search" to configure keywords and regions, then let LLM+Serper find professors; or add manually. Click a professor card for details
3. **Drafts** — Click "Generate Drafts" to batch-compose emails for all professors without drafts. Deep Research runs automatically for each professor before composing. Preview, edit subject/body, or skip as needed
4. **Sent** — View all sent emails and timestamps
5. **Replies** — System polls IMAP every 5 minutes (dual strategy: FROM exact match + SUBJECT match). You can also click "Check Replies" manually
6. **Settings** — Edit Profile / Search keywords & regions / Customize Agent behavior / Upload CV / Verify email credentials

---

## API Reference

### Stats & Professors

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stats` | System statistics overview |
| GET | `/api/professors` | List professors |
| GET | `/api/professors/{id}` | Professor detail |
| POST | `/api/professors` | Add professor manually |
| DELETE | `/api/professors/{id}` | Delete professor |
| POST | `/api/search/start` | Start auto search |
| POST | `/api/search/stop` | Stop search |

### Drafts & Sending

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/drafts` | List drafts (`?status=pending/sent`) |
| GET | `/api/drafts/{id}` | Draft detail |
| PUT | `/api/drafts/{id}` | Edit draft |
| POST | `/api/compose/start` | Batch generate email drafts |
| POST | `/api/send/{id}` | Send single email |
| POST | `/api/send/batch` | Batch send |

### Reply Tracking

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/replies` | List replies |
| POST | `/api/replies/check` | Manually trigger reply check |
| PUT | `/api/replies/{id}/read` | Mark as read |

### Configuration

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/config/profile` | Get profile |
| PUT | `/api/config/profile` | Update profile |
| GET | `/api/config/settings` | Get system config (sanitized) |
| PUT | `/api/config/keywords` | Update search keywords / regions |
| GET | `/api/config/prompts` | Get custom prompts |
| PUT | `/api/config/prompts` | Update custom prompts |
| GET | `/api/config/cv` | CV upload status |
| POST | `/api/config/cv/{lang}` | Upload CV (`cn` / `en`) |
| GET | `/api/config/email` | Get email config (sanitized) |
| POST | `/api/config/email/verify` | Verify SMTP / IMAP connection |
| WS | `/api/ws/progress` | WebSocket real-time progress |

---

## License

MIT