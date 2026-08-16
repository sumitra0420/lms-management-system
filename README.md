# LMS Management System

An AI-assisted pipeline for extracting quiz questions from vocational assessment
`.docx` files, verifying the extraction against the source document, and syncing
the result into Canvas LMS.

This guide sets up a **fully local demo** — everything runs on your own machine,
using your own AI API key. No AWS account, no shared credentials, nothing calls
out to anyone else's infrastructure except the AI provider you choose.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Python 3.12
- Node.js (for the Angular frontend)
- An API key from **one** of:
  - [Anthropic](https://console.anthropic.com/) (Claude) — recommended
  - [OpenAI](https://platform.openai.com/) (GPT)

## 1. Clone and check out the demo branch

```bash
git clone <this-repo-url>
cd lms-management-system
git checkout verify-extraction-flow
```

## 2. Start Postgres + local storage

```bash
docker-compose up -d postgres minio minio-init
```

This starts:
- **Postgres** — the app's database
- **MinIO** — a local S3-compatible file store (so uploaded `.docx` files never
  leave your machine)

Confirm it worked: open `http://localhost:9001` (login `minioadmin` / `minioadmin`)
and check that a bucket named `lms-management-uploads` exists.

## 3. Configure the backend

```bash
cd backend
cp .env.example .env
```

Open `.env` and fill in your AI API key under **either** "Option A: Direct
Anthropic API" or "Option B: Direct OpenAI API" (uncomment the block you're
using, leave the other commented out). Everything else in `.env.example` is
already set up to work with the MinIO/Postgres containers from step 2 — no
other changes needed.

## 4. Run the backend

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Database tables are created automatically on first startup — no migration step
needed.

## 5. Run the frontend

In a new terminal:

```bash
cd frontend
npm install
npm start
```

## 6. Use the app

Open `http://localhost:4200`, upload a `.docx` quiz file, and watch it go
through extraction → verification → review. The Canvas sync step will fail
unless you also have Canvas credentials configured — everything up to and
including reviewing extracted questions works without it.

## Troubleshooting

- **Upload fails / CORS error in browser console**: confirm `minio` is running
  (`docker-compose ps`) and that `.env`'s `S3_ENDPOINT_URL` is
  `http://localhost:9000`.
- **"Bucket does not exist"**: `minio-init` creates the bucket automatically on
  first `docker-compose up` — check `docker-compose logs minio-init` for
  errors, or create the bucket manually via the MinIO console at
  `http://localhost:9001`.
- **Extraction fails immediately with an auth error**: double-check exactly one
  model option block is uncommented in `.env`, and that `MODEL_A_PROVIDER` /
  `MODEL_B_PROVIDER` match the key you're using (`"anthropic"` or `"openai"`).
- **Model IDs**: direct Anthropic model IDs look like `claude-haiku-4-5-20251001`
  — current IDs are listed at
  [docs.anthropic.com/en/docs/about-claude/models](https://docs.anthropic.com/en/docs/about-claude/models).
  Any valid OpenAI model ID (e.g. `gpt-4o-mini`) works for the OpenAI option.
