# Beginner Deployment Guide — GitHub → Supabase → Render

The goal is simple:

**You do not run the study server on the slow PC.**

Your tablet opens a normal web address. The cloud server does the work.

---

## 1. Create the GitHub repository

Open GitHub in your browser and sign in.

Create a new repository, for example:

`ssc-cgl-ai-study-os`

You can keep it private.

Then upload the **contents of this ZIP**, not the ZIP file itself.

After upload, the top level of the repository should contain files such as:

```text
README.md
DEPLOY_GUIDE.md
requirements.txt
render.yaml
Dockerfile
app/
prompts/
```

Do **not** upload:

```text
.env
.venv/
data/ssc_cgl.db
exports/
```

---

## 2. Create the Supabase database

Go to Supabase and create a new project.

When the project is ready, open its database connection settings and copy a PostgreSQL connection string.

You will eventually give this value to Render as:

`DATABASE_URL`

Keep this value private.

You do not need to manually create the study tables. The application creates them when it starts.

---

## 3. Create the Render web service

Open Render and choose **New → Web Service**.

Connect your GitHub account and select the repository you just created.

Use these settings:

```text
Runtime: Python
Build Command: pip install -r requirements.txt
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

The included `render.yaml` already contains the same core configuration.

---

## 4. Add environment variables in Render

Add these variables under the service's environment settings:

```text
DATABASE_URL = your Supabase PostgreSQL connection string
AI_PROVIDER = openai
OPENAI_API_KEY = your OpenAI API key
OPENAI_MODEL = a model available to your account
APP_USERNAME = student
APP_PASSWORD = choose-a-private-password
```

Do not put the OpenAI key into the HTML or JavaScript.

For your first deployment, use a strong password for `APP_PASSWORD` because the application is reachable from the internet.

---

## 5. Deploy

Click Deploy.

Wait for the build and startup logs to finish.

The health check should become healthy at:

```text
/health
```

Render will provide a public service URL.

---

## 6. Open it on the Realme Pad 2

Open the Render URL in Chrome on the tablet.

The browser will ask for the Basic Authentication credentials if a password was configured.

Use:

```text
Username: student
Password: the APP_PASSWORD you chose
```

After the app opens, use the browser menu and choose **Add to Home screen** or **Install app**.

Now the study system behaves much more like an installed study app, while the actual server runs in the cloud.

---

## 7. First test of the system

Do this in order:

1. Add a subject, e.g. `English`.
2. Add a topic, e.g. `Subject-Verb Agreement`.
3. Upload one source PDF/DOCX or paste source text.
4. Build a study pack.
5. Confirm flashcards/questions appear.
6. Start a small test, such as 10 questions.
7. Submit the test.
8. Check the score and error analysis.
9. Start flashcard review.

Do not upload your entire library on day one. First prove the complete loop works with one topic.

---

## 8. If deployment fails

Look at the Render deployment log and copy the **first red error**, not the last line.

Send that error or a screenshot here.

Do not paste your `OPENAI_API_KEY` or `DATABASE_URL` into chat.

---

## 9. Important cloud behavior

The Render free web service can sleep when inactive. The first request after sleeping can therefore take longer than a warm request.

For persistent study data, PostgreSQL is used instead of relying on the web container's local filesystem.

Keep regular database backups/export functionality on the roadmap before the study library becomes large.
