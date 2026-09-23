# SSC CGL AI Preparation OS — V3.1 Cloud-Ready

This version is designed so your **Realme Pad 2 is the main study device**. The Python/FastAPI server, database and AI calls can run in the cloud; the tablet opens the web app like a normal study app and can install it to the home screen.

## Architecture

```text
Realme Pad 2 / phone / PC browser
            |
            v
       Cloud FastAPI
        /         \
       v           v
PostgreSQL      AI provider
(Supabase)     (OpenAI/Ollama)
```

The core learning pipeline remains:

`source → atomic concepts → teaching pack → flashcards → questions → validation → test → error analysis → adaptive revision`

## V3.1 fixes and improvements

This build includes the debugging work from the previous V3 review:

- Fixed the local authentication bug: blank `APP_PASSWORD` no longer forces Basic Authentication.
- Mounted `/static` correctly.
- Added working PWA icons and manifest files.
- Added a favicon.
- Fixed PDF export for `<`, `>`, `&`, quotes and line breaks.
- Added a real test-taking screen to the frontend.
- Added test question navigation and answer capture.
- Added test result/review screens.
- Made objective-question scoring deterministic; AI analyzes mistakes instead of deciding the score.
- Added a fallback so a temporary AI error does not destroy the test score.
- Added basic spaced-review scheduling so reviewed cards are not immediately shown again.
- Added lightweight database migration for the new review columns.
- Added topic validation when creating tests/sources.
- Added safer client-side HTML escaping in the study UI.
- Added `.venv/` and common local artifacts to `.gitignore`.
- Pinned the main Python dependencies for reproducible deployment.
- Kept OpenAI imported lazily so the local UI can still start even when only Ollama is installed.

## Important cost reality

Free hosting/database tiers can change, sleep, pause or impose quotas. AI inference is a separate cost: a hosted model API is not guaranteed to remain free forever. The code therefore keeps the AI provider behind one interface so it can be changed later.

## Cloud deployment target

For a simple personal setup:

- **GitHub** — source code and version control.
- **Render** — FastAPI web service.
- **Supabase** — PostgreSQL database.
- **OpenAI API** — AI generation/validation, using a model available to your account.
- **Realme Pad 2** — browser/PWA client.

Do not use local SQLite as the permanent database on an ephemeral web-service filesystem. Keep `DATABASE_URL` connected to PostgreSQL for the cloud build.

## Environment variables

### Cloud

```env
DATABASE_URL=postgresql://...
AI_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=...
APP_USERNAME=student
APP_PASSWORD=your-private-password
```

### Local with SQLite + Ollama

```env
DATABASE_URL=
DATABASE_PATH=data/ssc_cgl.db
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=your-model-name
APP_USERNAME=student
APP_PASSWORD=
```

Never commit `.env` or an API key to GitHub.

## GitHub → Render → Supabase walkthrough

Read `DEPLOY_GUIDE.md` in this repository. It is written for a beginner and uses the web interfaces as much as possible so you do not have to fight with PowerShell again.

## Local fallback

If `DATABASE_URL` is empty, the application creates a local SQLite database at `data/ssc_cgl.db`. The cloud configuration should use PostgreSQL.

## Current features

- Tablet-friendly responsive UI
- PWA install support
- Subjects, topics and sources
- PDF/DOCX/TXT source ingestion
- Layered AI pipeline
- Atomic concept extraction
- Teaching notes
- Flashcards
- Question generation
- Validation layer
- Real test-taking UI
- Deterministic MCQ grading
- AI error analysis
- Weakness tracking
- Adaptive revision priority
- Spaced flashcard review queue
- Anki CSV export
- PDF notes export
- PostgreSQL cloud support
- SQLite local fallback
- Password protection
- Health endpoint

## Verification performed on this package

The Python modules compile successfully. The app was exercised with a local SQLite database through FastAPI's test client, including:

- open access when no password is configured;
- Basic Authentication when a password is configured;
- subject/topic/source creation;
- test creation and retrieval;
- deterministic MCQ scoring;
- review scheduling;
- PWA manifest/icon routes;
- PDF generation with HTML-sensitive characters.

The OpenAI path was not live-tested with a real API key in this environment, so deployment credentials and model availability still need to be checked at deployment time.
