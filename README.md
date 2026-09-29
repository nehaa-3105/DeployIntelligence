# DeployIntelligence

> "Deployment analysis that learns from every outcome."

Analyses proposed deployments against a persistent memory of past incidents.  
In **baseline mode** it produces a generic LLM-driven risk assessment.  
In **memory-informed mode** it retrieves structurally similar historical deployments from Hindsight and tells you: *"I've seen this before."*

---

## Architecture

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite 5 (single-page, no router library) |
| Backend API | FastAPI (Python) |
| Memory | [Hindsight](https://hindsight.vectorize.io) — persistent deployment memory |
| LLM | Google Gemini (via `google-genai` SDK) |
| Ledger | JSON file (`data/deployments.json`) |

---

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Default | Description |
|---|---|---|---|
| `HINDSIGHT_API_KEY` | ✅ | — | Hindsight Cloud API key |
| `HINDSIGHT_BASE_URL` | — | `https://api.hindsight.vectorize.io` | Hindsight base URL |
| `HINDSIGHT_BANK_ID` | — | `deployment-memory` | Memory bank identifier |
| `GEMINI_API_KEY` | ✅ (for analysis) | — | Google Gemini API key |
| `GEMINI_MODEL` | — | `gemini-3.8-flash` | Gemini model name |
| `DATA_DIR` | — | `./data` | Directory for the JSON ledger |
| `CORS_ORIGINS` | — | *(localhost defaults included)* | Extra allowed CORS origins (comma-separated) |

Frontend env (in `frontend/.env` or set at build time):

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | Backend URL for production builds. Leave empty in dev (Vite proxy handles it). |

---

## Local setup

### Prerequisites

- Python 3.11+
- Node.js 18+

### Backend

```bash
# Install Python dependencies
pip install -r requirements.txt

# Copy and fill in credentials
cp .env.example .env
# edit .env — add HINDSIGHT_API_KEY and GEMINI_API_KEY

# Seed the memory bank (run once, or to reset)
py -3 -m src.ingestion --reset

# Start the API server
py -3 -m uvicorn api:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:5173
```

The Vite dev server proxies all `/analyze`, `/feedback`, `/health`, `/deployments`, and `/memory/*` requests to `localhost:8000`.

---

## Demo reset procedure

If you want to wipe the memory bank and start fresh:

```bash
# Wipe Hindsight bank + local ledger, then re-seed all 10 records
py -3 -m src.ingestion --reset
```

This deletes the remote Hindsight bank, clears `data/deployments.json`, recreates the bank, and re-ingests the 10 canonical seed deployments.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check — returns `{status, service, records}` |
| `POST` | `/analyze` | Run baseline + memory-informed analysis |
| `POST` | `/feedback` | Record actual deployment outcome (Phase 5) |
| `GET` | `/deployments` | Return all ledger records sorted by ID desc |
| `GET` | `/memory/overview` | Deterministic patterns/lessons/by-service from ledger |

Full request/response schemas are in `api.py` (Pydantic models).  
Interactive docs available at `http://localhost:8000/docs` when the server is running.

---

## Local ledger persistence

`data/deployments.json` is a local JSON file — it is **not** committed to git (`.gitignore` excludes it).  
If you delete it or run `--reset`, all ledger state is lost and you must re-run ingestion.  
Hindsight memories are stored remotely in your Hindsight bank; deleting the ledger file does **not** delete them — use `--reset` to wipe both together.

---

## Production deployment

1. Set `VITE_API_BASE_URL=https://your-api.example.com` in the frontend build environment.
2. Add your domain(s) to `CORS_ORIGINS` in the backend `.env`.
3. Build the frontend: `cd frontend && npm run build` — output is in `frontend/dist/`.
4. Serve `frontend/dist/` as static files from your preferred host.
5. Run the backend with `uvicorn api:app --host 0.0.0.0 --port 8000`.

---

## What does not exist

- Authentication / authorisation
- Multi-user support
- Deployment pipeline integration
- Real-time webhooks
- Pagination (ledger is small by design)
- Charts or analytics dashboards
