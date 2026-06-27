# Embeddable AI Chatbot — Backend

FastAPI backend powering the embeddable chatbot widget. Provides session management, streaming chat via Groq LLMs, and RAG-based knowledge ingestion.

---

## Prerequisites

- Python 3.11+
- `pip` or [`uv`](https://github.com/astral-sh/uv)

---

## Quickstart

### 1. Install dependencies

```bash
# pip
pip install -e .

# or uv
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```dotenv
GROQ_API_KEY=gsk_your_key_here
AGENT_NAME=Assistant
```

### 3. Run the server

```bash
uvicorn app.main:app --reload
```

Server starts at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### 4. Ingest knowledge base (optional)

```bash
curl -X POST http://localhost:8000/ingest \
  -F "files=@/path/to/document.pdf" \
  -F "files=@/path/to/faq.txt"
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check — returns `{"status": "ok"}` |
| `POST` | `/session/new` | Create a new chat session, returns `session_id` |
| `POST` | `/chat` | Send a message; streams SSE response |
| `POST` | `/ingest` | Upload files to the knowledge base |
| `GET` | `/docs` | List all ingested documents |
| `DELETE` | `/docs/{id}` | Delete a document by ID |

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | ✅ | — | Groq API key from [console.groq.com](https://console.groq.com) |
| `AGENT_NAME` | ✅ | — | Display name for the AI agent |
| `GROQ_MODEL` | | `llama3-8b-8192` | LLM model. Options: `llama3-8b-8192`, `llama3-70b-8192`, `mixtral-8x7b-32768` |
| `AGENT_PERSONALITY` | | — | Personality descriptor, e.g. `"helpful"` |
| `AGENT_TONE` | | — | Tone descriptor, e.g. `"friendly"` |
| `AGENT_SYSTEM_PROMPT` | | — | System prompt prepended to every conversation (max 2000 chars) |
| `CORS_ORIGINS` | | `*` | Comma-separated allowed origins, e.g. `http://localhost:3000,https://example.com` |
| `SIMILARITY_THRESHOLD` | | `0.70` | Minimum cosine similarity for RAG chunk retrieval (0–1) |
| `TOP_K` | | `5` | Number of top chunks to retrieve per query |
| `MAX_FILE_SIZE_MB` | | `20` | Max file size in MB per uploaded file |
| `MAX_FILES_PER_REQUEST` | | `10` | Max files per `/ingest` request |

---

## Running Tests

```bash
pytest
```
