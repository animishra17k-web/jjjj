import csv
import html
import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

load_dotenv()

from .ai import evaluate
from .db import db
from .pipeline import run

app = FastAPI(title="SSC CGL AI Preparation OS V3")
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
EXPORT = ROOT.parent / "exports"
EXPORT.mkdir(exist_ok=True)

# auto_error=False is critical: local installs commonly leave APP_PASSWORD blank.
# In that mode the app should stay open instead of forcing HTTP Basic auth.
security = HTTPBasic(auto_error=False)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    password = os.getenv("APP_PASSWORD", "").strip()
    if not password:
        return True

    username = os.getenv("APP_USERNAME", "student").strip() or "student"
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    ok = secrets.compare_digest(credentials.username, username) and secrets.compare_digest(
        credentials.password, password
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


@app.get("/", response_class=HTMLResponse)
def home(_: bool = Depends(auth)):
    return (STATIC / "index.html").read_text(encoding="utf8")


@app.get("/health")
def health():
    return {"ok": True, "service": "ssc-cgl-ai-v3"}


@app.get("/manifest.json")
def manifest(_: bool = Depends(auth)):
    return FileResponse(STATIC / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
def sw(_: bool = Depends(auth)):
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/favicon.ico")
def favicon():
    path = STATIC / "icons" / "icon-192.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Favicon not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/subjects")
def subjects(_: bool = Depends(auth)):
    c = db()
    rows = [dict(x) for x in c.execute("SELECT * FROM subjects ORDER BY name").fetchall()]
    c.close()
    return rows


@app.post("/api/subjects")
def add_subject(name: str = Form(...), _: bool = Depends(auth)):
    name = name.strip()
    if not name:
        return JSONResponse({"error": "Subject name is required"}, status_code=400)
    c = db()
    c.execute("INSERT INTO subjects(name) VALUES(?) ON CONFLICT(name) DO NOTHING", (name,))
    c.commit()
    row = c.execute("SELECT * FROM subjects WHERE name=?", (name,)).fetchone()
    c.close()
    return dict(row)


@app.get("/api/topics")
def topics(_: bool = Depends(auth)):
    c = db()
    rows = [
        dict(x)
        for x in c.execute(
            """SELECT topics.*, subjects.name subject
               FROM topics JOIN subjects ON subjects.id=topics.subject_id
               ORDER BY subjects.name, topics.name"""
        ).fetchall()
    ]
    c.close()
    return rows


@app.post("/api/topics")
def add_topic(subject_id: int = Form(...), name: str = Form(...), _: bool = Depends(auth)):
    name = name.strip()
    if not name:
        return JSONResponse({"error": "Topic name is required"}, status_code=400)

    c = db()
    subject = c.execute("SELECT id FROM subjects WHERE id=?", (subject_id,)).fetchone()
    if not subject:
        c.close()
        return JSONResponse({"error": "Subject not found"}, status_code=404)

    existing = c.execute(
        "SELECT * FROM topics WHERE subject_id=? AND name=?", (subject_id, name)
    ).fetchone()
    if existing:
        c.close()
        return dict(existing)

    c.execute("INSERT INTO topics(subject_id,name) VALUES(?,?)", (subject_id, name))
    c.commit()
    row = c.execute(
        "SELECT * FROM topics WHERE subject_id=? AND name=?", (subject_id, name)
    ).fetchone()
    c.close()
    return dict(row)


@app.post("/api/sources")
async def add_source(
    topic_id: int = Form(...),
    title: str = Form(""),
    content: str = Form(""),
    file: UploadFile | None = File(None),
    _: bool = Depends(auth),
):
    if file and file.filename:
        raw = await file.read()
        name = file.filename.lower()
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            import io

            content = "\n".join(
                (page.extract_text() or "") for page in PdfReader(io.BytesIO(raw)).pages
            )
        elif name.endswith(".docx"):
            from docx import Document
            import io

            content = "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
        else:
            content = raw.decode("utf8", "ignore")

    if not content.strip():
        return JSONResponse({"error": "Empty source"}, status_code=400)

    title = title.strip() or (file.filename if file else "Untitled source")
    c = db()
    topic = c.execute("SELECT id FROM topics WHERE id=?", (topic_id,)).fetchone()
    if not topic:
        c.close()
        return JSONResponse({"error": "Topic not found"}, status_code=404)

    c.execute(
        "INSERT INTO sources(topic_id,title,source_type,content) VALUES(?,?,?,?)",
        (topic_id, title, "file" if file else "text", content),
    )
    c.commit()
    sid = c.execute(
        "SELECT id FROM sources WHERE topic_id=? AND title=? ORDER BY id DESC LIMIT 1",
        (topic_id, title),
    ).fetchone()["id"]
    c.close()
    return {"id": sid}


@app.post("/api/topics/{topic_id}/build")
def build(topic_id: int, question_count: int = 60, _: bool = Depends(auth)):
    try:
        return run(topic_id, min(max(question_count, 10), 100))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def _normalize_answer(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _is_correct(question: dict, user_answer: str | None) -> bool:
    """Deterministic MCQ grading; AI is used for error analysis, not the score."""
    user = _normalize_answer(user_answer)
    expected = _normalize_answer(question.get("answer"))
    if not user or not expected:
        return False

    if user == expected:
        return True

    options = question.get("options") or []
    if isinstance(options, dict):
        options = list(options.values())

    # Support answers stored as A/B/C/D, 1/2/3/4, zero-based index, or full option text.
    letters = "abcdefghijklmnopqrstuvwxyz"
    for idx, option in enumerate(options):
        option_text = option.get("text") if isinstance(option, dict) else option
        option_text = str(option_text)
        letter = letters[idx]
        one_based = str(idx + 1)
        zero_based = str(idx)
        if expected in {letter, one_based, zero_based} and user in {letter, one_based, zero_based, _normalize_answer(option_text)}:
            return True
        if expected == _normalize_answer(option_text) and user in {
            _normalize_answer(option_text),
            letter,
            one_based,
            zero_based,
        }:
            return True

    return False


@app.get("/api/topics/{topic_id}/questions")
def questions(topic_id: int, limit: int = 20, _: bool = Depends(auth)):
    c = db()
    rows = c.execute(
        """SELECT id,difficulty,qtype,prompt,options
           FROM questions WHERE topic_id=? ORDER BY RANDOM() LIMIT ?""",
        (topic_id, min(max(limit, 1), 100)),
    ).fetchall()
    c.close()

    out = []
    for row in rows:
        x = dict(row)
        try:
            x["options"] = json.loads(x.get("options") or "[]")
        except json.JSONDecodeError:
            x["options"] = []
        out.append(x)
    return out


@app.post("/api/tests")
def create_test(
    title: str = Form(...),
    topic_id: int = Form(...),
    question_ids: str = Form(...),
    _: bool = Depends(auth),
):
    try:
        ids = list(dict.fromkeys(int(x) for x in question_ids.split(",") if x.strip()))
    except ValueError:
        return JSONResponse({"error": "question_ids must be comma-separated integers"}, status_code=400)
    if not ids:
        return JSONResponse({"error": "At least one question is required"}, status_code=400)

    c = db()
    valid_ids = {
        row["id"]
        for row in c.execute(
            "SELECT id FROM questions WHERE topic_id=? AND id IN (%s)"
            % ",".join("?" for _ in ids),
            (topic_id, *ids),
        ).fetchall()
    }
    ordered_ids = [qid for qid in ids if qid in valid_ids]
    if not ordered_ids:
        c.close()
        return JSONResponse({"error": "No valid questions found for this topic"}, status_code=400)

    c.execute(
        "INSERT INTO tests(title,topic_id,total) VALUES(?,?,?)",
        (title.strip() or "SSC CGL Test", topic_id, len(ordered_ids)),
    )
    row = c.execute(
        "SELECT id FROM tests WHERE title=? AND topic_id=? ORDER BY id DESC LIMIT 1",
        (title.strip() or "SSC CGL Test", topic_id),
    ).fetchone()
    test_id = row["id"]
    for qid in ordered_ids:
        c.execute("INSERT INTO answers(test_id,question_id) VALUES(?,?)", (test_id, qid))
    c.commit()
    c.close()
    return {"test_id": test_id, "total": len(ordered_ids)}


@app.get("/api/tests/{test_id}")
def get_test(test_id: int, _: bool = Depends(auth)):
    c = db()
    test = c.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()
    if not test:
        c.close()
        return JSONResponse({"error": "Test not found"}, status_code=404)
    qs = c.execute(
        """SELECT q.id,q.difficulty,q.qtype,q.prompt,q.options
           FROM answers a JOIN questions q ON q.id=a.question_id
           WHERE a.test_id=? ORDER BY a.id""",
        (test_id,),
    ).fetchall()
    c.close()

    items = []
    for q in qs:
        item = dict(q)
        try:
            item["options"] = json.loads(item.get("options") or "[]")
        except json.JSONDecodeError:
            item["options"] = []
        items.append(item)
    return {"test": dict(test), "questions": items}


@app.post("/api/tests/{test_id}/submit")
def submit(test_id: int, answers_json: str = Form(...), _: bool = Depends(auth)):
    try:
        answers = json.loads(answers_json)
        if not isinstance(answers, dict):
            raise ValueError("answers_json must contain an object")
    except Exception as exc:
        return JSONResponse({"error": f"Invalid answers_json: {exc}"}, status_code=400)

    c = db()
    test = c.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()
    qs = c.execute(
        "SELECT q.* FROM answers a JOIN questions q ON q.id=a.question_id WHERE a.test_id=? ORDER BY a.id",
        (test_id,),
    ).fetchall()
    c.close()
    if not test:
        return JSONResponse({"error": "Test not found"}, status_code=404)

    question_dicts = [dict(q) for q in qs]
    deterministic = []
    for q in question_dicts:
        user_answer = answers.get(str(q["id"]), "")
        q_for_grading = dict(q)
        try:
            q_for_grading["options"] = json.loads(q_for_grading.get("options") or "[]")
        except (TypeError, json.JSONDecodeError):
            q_for_grading["options"] = []
        deterministic.append(
            {
                "question_id": q["id"],
                "correct": _is_correct(q_for_grading, user_answer),
            }
        )

    # AI analyzes why answers were missed; it is not trusted to decide the score.
    try:
        ai_result = evaluate(test["title"], question_dicts, [answers.get(str(q["id"]), "") for q in question_dicts], deterministic)
    except TypeError:
        # Compatibility with older ai.py files that do not yet accept deterministic grading.
        try:
            ai_result = evaluate(
                test["title"],
                question_dicts,
                [answers.get(str(q["id"]), "") for q in question_dicts],
            )
        except Exception:
            ai_result = {"items": [], "weaknesses": [], "repair_actions": []}
    except Exception:
        ai_result = {"items": [], "weaknesses": [], "repair_actions": []}

    ai_by_id = {int(x["question_id"]): x for x in ai_result.get("items", []) if str(x.get("question_id", "")).isdigit()}
    correct_count = sum(1 for x in deterministic if x["correct"])
    total = len(deterministic)
    percentage = round((correct_count / total) * 100, 2) if total else 0

    result_items = []
    for x in deterministic:
        ai_item = ai_by_id.get(x["question_id"], {})
        result_items.append(
            {
                "question_id": x["question_id"],
                "correct": x["correct"],
                "error_type": "" if x["correct"] else ai_item.get("error_type", "other"),
                "error_detail": "" if x["correct"] else ai_item.get("error_detail", "Review this question and the relevant rule/concept."),
                "repair_skill": ai_item.get("repair_skill", ""),
            }
        )

    result = {
        "score": correct_count,
        "total": total,
        "percentage": percentage,
        "items": result_items,
        "weaknesses": ai_result.get("weaknesses", []),
        "repair_actions": ai_result.get("repair_actions", []),
    }

    c = db()
    for item in result["items"]:
        c.execute(
            """UPDATE answers SET user_answer=?,correct=?,error_type=?,error_detail=?
               WHERE test_id=? AND question_id=?""",
            (
                answers.get(str(item["question_id"]), ""),
                int(item["correct"]),
                item["error_type"],
                item["error_detail"],
                test_id,
                item["question_id"],
            ),
        )

    for weakness in result["weaknesses"]:
        label = str(weakness.get("label", "other")).strip() or "other"
        severity = float(weakness.get("severity", 1) or 1)
        c.execute(
            """INSERT INTO weaknesses(topic_id,label,severity,occurrences)
               VALUES(?,?,?,1)
               ON CONFLICT(topic_id,label) DO UPDATE SET
                   severity=excluded.severity,
                   occurrences=occurrences+1,
                   last_seen=CURRENT_TIMESTAMP""",
            (test["topic_id"], label, severity),
        )

    mastery = percentage
    revision_priority = max(1, round(11 - (mastery / 10), 2))
    c.execute("UPDATE tests SET submitted_at=CURRENT_TIMESTAMP,score=? WHERE id=?", (percentage, test_id))
    c.execute(
        "UPDATE topics SET mastery=?,revision_priority=? WHERE id=?",
        (mastery, revision_priority, test["topic_id"]),
    )
    c.execute(
        "INSERT INTO events(layer,event_type,topic_id,payload) VALUES(?,?,?,?)",
        ("ADAPT", "test_evaluated", test["topic_id"], json.dumps(result, ensure_ascii=False)),
    )
    c.commit()
    c.close()
    return result


@app.get("/api/review/queue")
def review_queue(limit: int = 20, _: bool = Depends(auth)):
    c = db()
    rows = c.execute(
        """SELECT f.id,f.front,f.back,f.topic_id,t.name topic
           FROM flashcards f
           JOIN topics t ON t.id=f.topic_id
           LEFT JOIN (
               SELECT r1.* FROM reviews r1
               WHERE r1.id=(SELECT MAX(r2.id) FROM reviews r2 WHERE r2.flashcard_id=r1.flashcard_id)
           ) r ON r.flashcard_id=f.id
           WHERE r.id IS NULL OR r.next_review IS NULL OR r.next_review <= CURRENT_TIMESTAMP
           ORDER BY t.revision_priority DESC, f.id
           LIMIT ?""",
        (min(max(limit, 1), 100),),
    ).fetchall()
    c.close()
    return [dict(x) for x in rows]


@app.post("/api/review/{flashcard_id}")
def review_flashcard(flashcard_id: int, rating: str = Form(...), _: bool = Depends(auth)):
    if rating not in {"again", "hard", "good", "easy"}:
        return JSONResponse({"error": "rating must be again, hard, good or easy"}, status_code=400)

    c = db()
    card = c.execute("SELECT id FROM flashcards WHERE id=?", (flashcard_id,)).fetchone()
    if not card:
        c.close()
        return JSONResponse({"error": "Flashcard not found"}, status_code=404)

    last = c.execute(
        "SELECT interval_days FROM reviews WHERE flashcard_id=? ORDER BY id DESC LIMIT 1",
        (flashcard_id,),
    ).fetchone()
    previous = float(last["interval_days"] or 0) if last else 0
    if rating == "again":
        interval = 0.04  # roughly one hour
    elif rating == "hard":
        interval = max(1, previous * 1.5 if previous else 1)
    elif rating == "good":
        interval = max(1, previous * 3 if previous else 3)
    else:
        interval = max(2, previous * 5 if previous else 7)

    if os.getenv("DATABASE_URL", "").strip():
        c.execute(
            """INSERT INTO reviews(flashcard_id,rating,interval_days,next_review)
               VALUES(?,?,?,CURRENT_TIMESTAMP + (? * INTERVAL '1 day'))""",
            (flashcard_id, rating, interval, interval),
        )
    else:
        c.execute(
            """INSERT INTO reviews(flashcard_id,rating,interval_days,next_review)
               VALUES(?,?,?,datetime(CURRENT_TIMESTAMP, '+' || CAST(? AS TEXT) || ' days'))""",
            (flashcard_id, rating, interval, interval),
        )
    c.commit()
    c.close()
    return {"ok": True, "next_interval_days": round(interval, 2)}


@app.get("/api/dashboard")
def dashboard(_: bool = Depends(auth)):
    c = db()
    topics_rows = c.execute(
        """SELECT topics.*,subjects.name subject
           FROM topics JOIN subjects ON subjects.id=topics.subject_id
           ORDER BY revision_priority DESC, mastery ASC"""
    ).fetchall()
    weaknesses_rows = c.execute(
        """SELECT weaknesses.*,topics.name topic
           FROM weaknesses JOIN topics ON topics.id=weaknesses.topic_id
           ORDER BY severity DESC,occurrences DESC LIMIT 30"""
    ).fetchall()
    cards = c.execute("SELECT COUNT(*) n FROM flashcards").fetchone()["n"]
    qs = c.execute("SELECT COUNT(*) n FROM questions").fetchone()["n"]
    tests = c.execute("SELECT COUNT(*) n FROM tests WHERE submitted_at IS NOT NULL").fetchone()["n"]
    c.close()
    return {
        "topics": [dict(x) for x in topics_rows],
        "weaknesses": [dict(x) for x in weaknesses_rows],
        "totals": {"flashcards": cards, "questions": qs, "tests_completed": tests},
    }


@app.get("/api/topics/{topic_id}/export/anki")
def anki(topic_id: int, _: bool = Depends(auth)):
    c = db()
    rows = c.execute("SELECT front,back FROM flashcards WHERE topic_id=?", (topic_id,)).fetchall()
    c.close()
    path = EXPORT / f"anki_{topic_id}.csv"
    with open(path, "w", newline="", encoding="utf8-sig") as f:
        csv.writer(f).writerows([['Front', 'Back']] + [[r['front'], r['back']] for r in rows])
    return FileResponse(path, filename=path.name, media_type="text/csv")


@app.get("/api/topics/{topic_id}/export/pdf")
def pdf(topic_id: int, _: bool = Depends(auth)):
    c = db()
    row = c.execute(
        """SELECT artifacts.content,topics.name topic,subjects.name subject
           FROM artifacts JOIN topics ON topics.id=artifacts.topic_id
           JOIN subjects ON subjects.id=topics.subject_id
           WHERE topic_id=? AND artifact_type='study_pack'
           ORDER BY artifacts.id DESC LIMIT 1""",
        (topic_id,),
    ).fetchone()
    c.close()
    if not row:
        return JSONResponse({"error": "No study pack"}, status_code=404)

    pack = json.loads(row["content"])
    out = EXPORT / f"notes_{topic_id}.pdf"
    doc = SimpleDocTemplate(
        str(out), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            f"{html.escape(str(row['subject']))} — {html.escape(str(row['topic']))}",
            styles["Title"],
        )
    ]

    def safe_text(value) -> str:
        # Escape ReportLab mini-markup characters and preserve line breaks safely.
        return html.escape(str(value), quote=True).replace("\n", "<br/>")

    def add(value):
        if isinstance(value, dict):
            for key, item in value.items():
                story.append(Paragraph(safe_text(str(key).title()), styles["Heading2"]))
                add(item)
        elif isinstance(value, list):
            for item in value:
                add(item)
        else:
            story.append(Paragraph(safe_text(value), styles["BodyText"]))
            story.append(Spacer(1, 5))

    add(pack.get("notes", []))
    doc.build(story)
    return FileResponse(out, filename=out.name, media_type="application/pdf")
