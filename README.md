<p align="center">
  <img src="docs/assets/academiareach-banner.png" alt="AcademiaReach research and outreach workflow" width="100%" />
</p>

<h1 align="center">AcademiaReach</h1>

<p align="center">
  A review-first workspace for discovering professors, researching their work, drafting thoughtful PhD outreach, and tracking every conversation.
</p>

<p align="center">
  <a href="README_CN.md">中文</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#agent-backends">Agent backends</a> ·
  <a href="docs/cloudflare-tunnel.zh-CN.md">Private deployment</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11" />
  <img src="https://img.shields.io/badge/FastAPI-Agent_Core-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-149ECA?style=flat-square&logo=react&logoColor=white" alt="React 18" />
  <img src="https://img.shields.io/badge/Codex-App_Server-111111?style=flat-square&logo=openai&logoColor=white" alt="Codex App Server" />
  <img src="https://img.shields.io/badge/Pi-SDK_Harness-F43F5E?style=flat-square" alt="Pi SDK Harness" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker ready" />
  <img src="https://img.shields.io/badge/License-MIT-FBBF24?style=flat-square" alt="MIT License" />
</p>

## What it does

AcademiaReach turns the scattered work around PhD outreach into one traceable workflow. It discovers new professors from public sources, verifies identity and contact details, recommends representative papers against an applicant profile, prepares source-grounded drafts, and keeps sending and replies under explicit human review.

It is designed as a personal research workspace, not an autonomous bulk-mailer. Drafts remain editable, sending requires an explicit action, source links stay visible, and private profile or credential files are kept outside Git.

| Area | What is included |
|---|---|
| Discovery | Parallel agent search, CSRankings candidates, region and topic filters, and a persistent `new` tag |
| Data quality | Homepage, email, and Google Scholar verification; obfuscated-email recovery; Chinese names only for mainland-China faculty; automatic deduplication |
| Research | Professor summaries, representative publications, citation-aware paper recommendations, and reading rationale tied to the applicant profile |
| Outreach | Chinese and English templates, professor-specific paper discussion, editable drafts, language-aware attachment names, and SMTP sending |
| Follow-up | IMAP reply polling, conversation history, draft and sent-mail views, per-professor task state, and live WebSocket progress |
| Operations | Direct, Pi, and Codex execution paths; concurrent workers; Docker deployment; optional Cloudflare Access protection |

## Workflow

<p align="center">
  <img src="docs/assets/outreach-workflow.svg" alt="Professor discovery, verification, recommendation, composition, review, and reply tracking workflow" width="100%" />
</p>

1. **Discover** new faculty with focused topic and region batches.
2. **Verify** names, institutional pages, email addresses, and Scholar profiles before saving.
3. **Enrich** each professor with research summaries and profile-aware paper recommendations.
4. **Compose** Chinese drafts under explicit prompt constraints, or English drafts from a fixed private template and verified evidence.
5. **Review** every subject, paragraph, and attachment before sending.
6. **Track** sent mail, replies, and the full professor-level conversation in one place.

## Agent backends

<p align="center">
  <img src="docs/assets/agent-backends.svg" alt="Direct API, Pi Harness, and Codex App Server architecture" width="100%" />
</p>

The harness engine and the model API are selected independently in Settings.

| Backend | Credentials | Web research | Best fit |
|---|---|---|---|
| `direct` | OpenAI-compatible or DeepSeek key, or local Ollama | No agent web tools | Profile generation and ordinary model calls |
| `pi` | Uses the selected OpenAI-compatible, DeepSeek, or Ollama configuration | Read-only search tool inside task-specific Pi harnesses | API-backed search, enrichment, recommendations, and composition |
| `codex` | Reuses the host `codex login` session | Codex live web research | Full agent workflow without placing a model API key in the app |

Search, professor enrichment, and paper recommendations require `pi` or `codex`. The workers run named harnesses for search, research, composition, and profile generation, with structured output schemas and isolated temporary workspaces.

## Quickstart

### Requirements

- Python 3.11
- Node.js 18 or later
- `npm`; the Pi installer provisions its pinned Bun runtime when needed
- Codex CLI only when using the `codex` backend

### 1. Install

```bash
git clone https://github.com/Joky02/AcademiaReach.git
cd AcademiaReach

conda create -n academia python=3.11 -y
conda activate academia
pip install -r backend/requirements.txt

cd frontend
npm install
cd ..
```

### 2. Create private configuration

```bash
cp backend/config/config.yaml.example backend/config/config.yaml
cp backend/config/my_profile.example.md backend/config/my_profile.md

mkdir -p backend/config/email_templates
cp backend/templates/compose_en.example.md \
  backend/config/email_templates/compose_en.md
```

Edit `backend/config/config.yaml` and `backend/config/my_profile.md`. The copied files are ignored by Git. The Settings page can later update model, profile, prompt, attachment, and email configuration.

For private prompt overrides:

```bash
mkdir -p backend/config/prompts
cp backend/prompts/compose_cn.md backend/config/prompts/compose_cn.md
```

Files under `backend/config/prompts/` override the public examples in `backend/prompts/`.

### 3. Start an agent backend

For Pi with your selected model API:

```bash
./deploy/pi-worker.sh install
./deploy/pi-worker.sh start
```

For Codex App Server:

```bash
codex login
./deploy/codex-worker.sh install
./deploy/codex-worker.sh start
```

Set `llm.agent_backend` to `pi`, `codex`, or `direct` in `backend/config/config.yaml` or select it later in Settings.

### 4. Start the app

```bash
# Terminal 1
conda activate academia
TAOCI_CODEX_SOCKET=/tmp/taoci-codex-$(id -u)/worker.sock \
TAOCI_PI_SOCKET=/tmp/taoci-pi-$(id -u)/worker.sock \
  uvicorn backend.main:app --reload --port 8000

# Terminal 2
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). FastAPI documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

## Configuration

The public template is [`backend/config/config.yaml.example`](backend/config/config.yaml.example). Its core model section is:

```yaml
llm:
  agent_backend: "codex"       # direct / pi / codex
  provider: "openai"           # openai / deepseek / ollama for direct/pi
  codex:
    model: ""                  # empty uses the Codex account default
    timeout_seconds: 600
  pi:
    timeout_seconds: 600
  openai:
    api_key: "your-openai-api-key"
    model: "gpt-4o"
    base_url: "https://api.openai.com/v1"

search:
  agent:
    timeout_seconds: 120
    batch_size: 3
    parallel_batches: 2
  keywords: ["machine learning", "natural language processing"]
  regions: ["US", "UK", "China"]
  max_professors: 20
```

| Local path | Purpose | Tracked by Git |
|---|---|---|
| `backend/config/config.yaml` | Model, SMTP, IMAP, and search settings | No |
| `backend/config/my_profile.md` | Applicant research profile | No |
| `backend/config/prompts/` | Private prompt overrides | No |
| `backend/config/email_templates/` | Private fixed email templates | No |
| `backend/config/*.pdf` | CV and transcript attachments | No |
| `backend/config/papers/` | Applicant papers | No |
| `backend/data/` and `*.db` | Runtime database | No |

Do not force-add these files. Before publishing changes, check `git status` and scan staged content for credentials or personal details.

## Deployment

The Compose stack contains the FastAPI backend, the Pi worker, the React/Nginx frontend, and an optional Cloudflare Tunnel connector. It deliberately does not publish a host port in the protected deployment profile.

For a private domain protected by Cloudflare Access, follow [`docs/cloudflare-tunnel.zh-CN.md`](docs/cloudflare-tunnel.zh-CN.md):

```bash
cp .env.example .env
cp deploy/cloudflare/config.yml.example deploy/cloudflare/config.yml
docker compose --profile tunnel up -d --build
```

The Codex worker remains on the host and communicates with the container through a Unix socket. The backend never mounts the Codex login directory. On WSL, keep worker sockets under `/tmp`, not under `/mnt/c`.

## Project layout

```text
AcademiaReach/
├── backend/
│   ├── agents/          # search, enrichment, recommendation, composition
│   ├── api/             # REST and WebSocket routes
│   ├── config/          # public examples and ignored private runtime data
│   ├── core/            # models, database, backend clients, prompts
│   ├── prompts/         # commit-safe task prompts
│   └── services/        # SMTP sending and IMAP reply tracking
├── codex_worker/        # Codex App Server bridge
├── pi_worker/           # Pi SDK harness worker
├── frontend/            # React, TypeScript, Vite, TailwindCSS
├── deploy/              # worker and Cloudflare deployment scripts
├── docs/                # deployment guide and README artwork
└── docker-compose.yml
```

## API

The full OpenAPI schema is served at `/docs`. Frequently used routes include:

| Method | Route | Purpose |
|---|---|---|
| `GET` / `POST` | `/api/professors` | List or add professors |
| `POST` | `/api/professors/dedupe` | Merge existing duplicates |
| `POST` | `/api/professors/{id}/enrich/start` | Start background enrichment |
| `POST` | `/api/search/start` | Start batched professor discovery |
| `GET` | `/api/search/status` | Read search task state |
| `GET` / `PUT` / `DELETE` | `/api/drafts/{id}` | Review and manage a draft |
| `POST` | `/api/compose/start` | Generate drafts in the background |
| `POST` | `/api/send/{id}` | Send an approved draft |
| `POST` | `/api/replies/check` | Poll for replies now |
| `GET` | `/api/codex/status` | Check the Codex worker |
| `GET` | `/api/pi/status` | Check the Pi worker |
| `WS` | `/api/ws/progress` | Stream task progress |

## Development

```bash
# Backend tests
python -m unittest discover -s backend/tests -v

# Codex worker tests
.run/codex-venv/bin/python -m unittest codex_worker.test_server -v

# Pi type check
cd pi_worker && npm run check

# Frontend production build
cd frontend && npm run build
```

When changing shared task behavior, keep the public prompts generic and place applicant-specific wording only in ignored overrides.

## Troubleshooting

| Symptom | Check |
|---|---|
| Search or enrichment says a harness is required | Select `pi` or `codex`, then confirm `/api/pi/status` or `/api/codex/status` |
| Codex reports a stale or missing configuration | Run `./deploy/codex-worker.sh restart` and inspect `./deploy/codex-worker.sh logs` |
| Pi is unavailable | Run `./deploy/pi-worker.sh restart` and inspect `./deploy/pi-worker.sh logs` |
| Worker socket is missing on WSL | Keep `TAOCI_*_SOCKET_DIR` under `/tmp`, not the Windows-mounted project directory |
| Drafts send but replies do not appear | Verify IMAP credentials in Settings and run the manual reply check |
| Tunnel is healthy but the app is blocked | Check the Cloudflare Access policy, team name, and application AUD tag |

## Contributing

Issues and focused pull requests are welcome. Please keep changes scoped, add tests for shared behavior, and never commit real profiles, email credentials, API keys, attachments, Tunnel credentials, or private prompt overrides.

## License

[MIT](LICENSE)
