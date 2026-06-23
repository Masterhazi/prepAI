"""
memory.py — Persistent cross-session memory for PrepAI
SQLite via SQLAlchemy. Everything the AI learns about you persists.
"""

import os, json
from datetime import datetime, date
from pathlib import Path
from sqlalchemy import (create_engine, Column, Integer, String, Text,
    Boolean, DateTime, Float, Index, event)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


def _db_path() -> str:
    data_dir = os.environ.get("PREPAI_DATA_DIR")
    base = Path(data_dir) if data_dir else Path.home() / ".prepai"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "memory.db")


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"
    id         = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    goal       = Column(Text)
    engine     = Column(String(32))
    mode       = Column(String(16))
    steps      = Column(Integer, default=0)
    outcome    = Column(Text)
    tools_used = Column(Text)  # JSON


class Entity(Base):
    """Facts learned about the user — skills, weak areas, role, company."""
    __tablename__ = "entities"
    id         = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    category   = Column(String(64), index=True)
    key        = Column(String(128), index=True)
    value      = Column(Text)
    confidence = Column(Float, default=1.0)
    source     = Column(String(64))
    __table_args__ = (Index("ix_ent_cat_key", "category", "key"),)


class Task(Base):
    __tablename__ = "tasks"
    id         = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    task_date  = Column(String(10), index=True)
    text       = Column(Text)
    duration   = Column(String(16))
    priority   = Column(String(16), default="medium")
    done       = Column(Boolean, default=False)
    done_at    = Column(DateTime, nullable=True)
    source     = Column(String(32), default="agent")


class Question(Base):
    __tablename__ = "questions"
    id             = Column(Integer, primary_key=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    question       = Column(Text)
    category       = Column(String(64))
    role           = Column(String(128))
    company        = Column(String(128))
    source_engine  = Column(String(32))
    judge_engine   = Column(String(32))
    verdict        = Column(String(16))  # pass / fail / flagged
    judge_reason   = Column(Text)
    confidence     = Column(Float, default=0.0)
    practiced      = Column(Boolean, default=False)
    practice_count = Column(Integer, default=0)


class Job(Base):
    __tablename__ = "jobs"
    id          = Column(Integer, primary_key=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    title       = Column(String(256))
    company     = Column(String(128), index=True)
    location    = Column(String(128))
    skills      = Column(Text)  # JSON
    deadline    = Column(String(16))
    url         = Column(Text)
    status      = Column(String(32), default="seen")
    match_score = Column(Float, default=0.0)
    notes       = Column(Text)


class ResumeData(Base):
    __tablename__ = "resume_data"
    id              = Column(Integer, primary_key=True)
    parsed_at       = Column(DateTime, default=datetime.utcnow)
    filename        = Column(String(256))
    name            = Column(String(128))
    current_role    = Column(String(128))
    current_company = Column(String(128))
    years_exp       = Column(Float, default=0.0)
    skills          = Column(Text)
    education       = Column(Text)
    past_companies  = Column(Text)
    past_roles      = Column(Text)
    projects        = Column(Text)
    target_role     = Column(String(128))
    raw_text        = Column(Text)


class MemoryEvent(Base):
    __tablename__ = "events"
    id         = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    event_type = Column(String(64))
    title      = Column(String(256))
    detail     = Column(Text)
    meta       = Column(Text)  # JSON


_engine = None
_Session = None


def _get_engine():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{_db_path()}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        @event.listens_for(_engine, "connect")
        def _set_pragmas(conn, _):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-32000")
        Base.metadata.create_all(_engine)
        _Session = sessionmaker(bind=_engine)
    return _engine


def _db():
    _get_engine()
    return _Session()


# ── Sessions ──────────────────────────────────────────────────────────────────

def save_session(goal, engine, mode, steps, outcome, tools_used):
    with _db() as s:
        obj = Session(goal=goal, engine=engine, mode=mode, steps=steps,
                      outcome=outcome, tools_used=json.dumps(tools_used))
        s.add(obj); s.commit(); return obj.id


def get_recent_sessions(limit=10):
    with _db() as s:
        rows = s.query(Session).order_by(Session.created_at.desc()).limit(limit).all()
        return [{"id": r.id, "goal": r.goal, "engine": r.engine, "mode": r.mode,
                 "steps": r.steps, "outcome": r.outcome,
                 "tools_used": json.loads(r.tools_used or "[]"),
                 "created_at": str(r.created_at)} for r in rows]


# ── Entities ──────────────────────────────────────────────────────────────────

def upsert_entity(category, key, value="", confidence=1.0, source="agent"):
    with _db() as s:
        ex = s.query(Entity).filter_by(category=category, key=key).first()
        if ex:
            ex.value      = value or ex.value
            ex.confidence = max(ex.confidence, confidence)
            ex.updated_at = datetime.utcnow()
        else:
            s.add(Entity(category=category, key=key, value=value,
                         confidence=confidence, source=source))
        s.commit()


def get_entities(category=None):
    with _db() as s:
        q = s.query(Entity)
        if category: q = q.filter_by(category=category)
        return [{"category": e.category, "key": e.key, "value": e.value,
                 "confidence": e.confidence, "source": e.source}
                for e in q.order_by(Entity.confidence.desc()).all()]



def _get_entity_value(category: str, by_cat: dict):
    """Get the stored value for a singleton entity (role, company, target_role)."""
    with _db() as s:
        e = s.query(Entity).filter_by(category=category).order_by(
            Entity.confidence.desc()).first()
        if e:
            # If value is set and non-empty, use value; otherwise use key
            return e.value if e.value and e.value != e.key else e.key
    return (by_cat.get(category) or [None])[0]


def get_user_context():
    """Rich context injected into every agent run — AI always knows you."""
    entities = get_entities()
    by_cat = {}
    for e in entities:
        by_cat.setdefault(e["category"], []).append(e["key"])
    resume = get_latest_resume()
    today  = date.today().isoformat()
    with _db() as s:
        pending = s.query(Task).filter(
            Task.done == False, Task.task_date >= today
        ).order_by(Task.priority.desc()).limit(5).all()
        pending_tasks = [t.text for t in pending]
    recent = get_recent_sessions(3)
    return {
        "name":            resume.get("name") if resume else None,
        "current_role":    resume.get("current_role") if resume else (by_cat.get("role") or [None])[0],
        "current_company": resume.get("current_company") if resume else (by_cat.get("company") or [None])[0],
        "years_exp":       resume.get("years_exp") if resume else None,
        "skills":          json.loads(resume["skills"]) if resume and resume.get("skills") else by_cat.get("skill", []),
        "weak_areas":      by_cat.get("weak_area", []),
        "target_role":     resume.get("target_role") if resume else _get_entity_value("target_role", by_cat),
        "past_companies":  json.loads(resume["past_companies"]) if resume and resume.get("past_companies") else [],
        "pending_tasks":   pending_tasks,
        "recent_goals":    [s["goal"] for s in recent],
        "has_resume":      resume is not None,
    }


# ── Tasks ─────────────────────────────────────────────────────────────────────

def save_tasks(tasks, task_date=None, source="agent"):
    today = task_date or date.today().isoformat()
    with _db() as s:
        for t in tasks:
            text = t.get("task", "")
            if not s.query(Task).filter_by(task_date=today, text=text).first():
                s.add(Task(task_date=today, text=text,
                           duration=t.get("duration", ""),
                           priority=t.get("priority", "medium"), source=source))
        s.commit()


def get_tasks(task_date=None):
    today = task_date or date.today().isoformat()
    with _db() as s:
        rows = s.query(Task).filter_by(task_date=today).order_by(Task.priority.desc()).all()
        return [{"id": r.id, "text": r.text, "duration": r.duration,
                 "priority": r.priority, "done": r.done} for r in rows]


def mark_task_done(task_id):
    with _db() as s:
        t = s.query(Task).get(task_id)
        if t:
            t.done = True; t.done_at = datetime.utcnow(); s.commit()
            log_event("task_done", t.text)


def get_task_completion_rate(days=7):
    with _db() as s:
        total = s.query(Task).count()
        done  = s.query(Task).filter_by(done=True).count()
        return round(done / total, 2) if total else 0.0


# ── Questions ─────────────────────────────────────────────────────────────────

def save_question(question, category, role, company, source_engine,
                  verdict, judge_engine, judge_reason, confidence):
    with _db() as s:
        obj = Question(question=question, category=category, role=role,
                       company=company, source_engine=source_engine,
                       verdict=verdict, judge_engine=judge_engine,
                       judge_reason=judge_reason, confidence=confidence)
        s.add(obj); s.commit(); return obj.id


def get_questions(role=None, verdict="pass", limit=20):
    with _db() as s:
        q = s.query(Question).filter_by(verdict=verdict)
        if role: q = q.filter(Question.role.ilike(f"%{role}%"))
        return [{"id": r.id, "question": r.question, "category": r.category,
                 "role": r.role, "company": r.company,
                 "confidence": r.confidence, "practiced": r.practiced}
                for r in q.order_by(Question.confidence.desc()).limit(limit).all()]


def mark_question_practiced(qid):
    with _db() as s:
        q = s.query(Question).get(qid)
        if q:
            q.practiced = True; q.practice_count += 1; s.commit()


# ── Jobs ──────────────────────────────────────────────────────────────────────

def save_job(title, company, location, skills, deadline=None, url=None, match_score=0.0):
    with _db() as s:
        if s.query(Job).filter_by(title=title, company=company).first():
            return None
        j = Job(title=title, company=company, location=location,
                skills=json.dumps(skills), deadline=deadline or "",
                url=url or "", match_score=match_score)
        s.add(j); s.commit(); return j.id


def update_job_status(job_id, status, notes=""):
    with _db() as s:
        j = s.query(Job).get(job_id)
        if j:
            j.status = status
            if notes: j.notes = notes
            s.commit()
            log_event("job_status", f"{j.title} at {j.company} → {status}")


def get_jobs(status=None):
    with _db() as s:
        q = s.query(Job)
        if status: q = q.filter_by(status=status)
        return [{"id": r.id, "title": r.title, "company": r.company,
                 "location": r.location, "skills": json.loads(r.skills or "[]"),
                 "deadline": r.deadline, "url": r.url, "status": r.status,
                 "match_score": r.match_score}
                for r in q.order_by(Job.created_at.desc()).all()]


# ── Resume ────────────────────────────────────────────────────────────────────

def save_resume(data):
    with _db() as s:
        r = ResumeData(**{k: v for k, v in {
            "filename":        data.get("filename", ""),
            "name":            data.get("name", ""),
            "current_role":    data.get("current_role", ""),
            "current_company": data.get("current_company", ""),
            "years_exp":       data.get("years_exp", 0.0),
            "skills":          json.dumps(data.get("skills", [])),
            "education":       json.dumps(data.get("education", [])),
            "past_companies":  json.dumps(data.get("past_companies", [])),
            "past_roles":      json.dumps(data.get("past_roles", [])),
            "projects":        json.dumps(data.get("projects", [])),
            "target_role":     data.get("target_role", ""),
            "raw_text":        data.get("raw_text", "")[:50000],
        }.items()})
        s.add(r); s.commit()
        for skill in data.get("skills", []):
            upsert_entity("skill", skill, source="resume")
        if data.get("current_role"):    upsert_entity("role",        data["current_role"],    source="resume")
        if data.get("current_company"): upsert_entity("company",     data["current_company"], source="resume")
        if data.get("target_role"):     upsert_entity("target_role", data["target_role"],     source="resume")
        return r.id


def get_latest_resume():
    with _db() as s:
        r = s.query(ResumeData).order_by(ResumeData.parsed_at.desc()).first()
        if not r: return None
        return {"filename": r.filename, "name": r.name, "current_role": r.current_role,
                "current_company": r.current_company, "years_exp": r.years_exp,
                "skills": r.skills, "education": r.education,
                "past_companies": r.past_companies, "past_roles": r.past_roles,
                "projects": r.projects, "target_role": r.target_role}


# ── Events ────────────────────────────────────────────────────────────────────

def log_event(event_type, title, detail="", metadata=None):
    with _db() as s:
        s.add(MemoryEvent(event_type=event_type, title=title,
                          detail=detail, meta=json.dumps(metadata or {})))
        s.commit()


def get_events(limit=30):
    with _db() as s:
        rows = s.query(MemoryEvent).order_by(MemoryEvent.created_at.desc()).limit(limit).all()
        return [{"type": r.event_type, "title": r.title,
                 "detail": r.detail, "created_at": str(r.created_at)} for r in rows]


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats():
    with _db() as s:
        return {
            "total_sessions":      s.query(Session).count(),
            "questions_banked":    s.query(Question).filter_by(verdict="pass").count(),
            "questions_practiced": s.query(Question).filter_by(practiced=True).count(),
            "jobs_tracked":        s.query(Job).count(),
            "jobs_applied":        s.query(Job).filter_by(status="applied").count(),
            "task_completion_7d":  get_task_completion_rate(7),
        }


if __name__ == "__main__":
    _get_engine()
    upsert_entity("skill", "Python", source="test")
    upsert_entity("weak_area", "Dynamic Programming", source="test")
    import json
    print(json.dumps(get_user_context(), indent=2))
    print(get_stats())
    print("memory.py OK")


# ════════════════════════════════════════════════════════════════════════════════
# AGENT-FACING API
# ════════════════════════════════════════════════════════════════════════════════

_active_session: dict = {}


def start_session(goal: str, engine: str, context: dict) -> int:
    global _active_session
    with _db() as s:
        sess = Session(goal=goal, engine=engine,
                       mode=context.get("mode", "agent"),
                       steps=0, outcome="", tools_used="[]")
        s.add(sess); s.commit()
        _active_session = {"id": sess.id, "goal": goal, "engine": engine, "tools": []}
        return sess.id


def end_session(session_id: int, outcome: str, tools_used: list, steps: int):
    global _active_session
    with _db() as s:
        sess = s.query(Session).get(session_id)
        if sess:
            sess.outcome    = outcome
            sess.tools_used = json.dumps(tools_used)
            sess.steps      = steps
            s.commit()
    log_event("session_end", _active_session.get("goal", "")[:80], detail=(outcome or "")[:200])
    _active_session = {}


def remember(key: str, value, source: str = "agent"):
    """Store a fact. Lists/dicts serialised to JSON."""
    if isinstance(value, (list, dict)):
        val_str = json.dumps(value)
        if isinstance(value, list) and key in ("weak_topics", "skills"):
            cat = "skill" if key == "skills" else "weak_area"
            for item in value[:20]:
                upsert_entity(cat, str(item), source=source)
    else:
        val_str = str(value)
    cat_map = {
        "weak_topics":"weak_area", "skills":"skill",
        "current_role":"role", "current_company":"company",
        "target_role":"target_role", "leetcode_username":"preference",
        "leetcode_streak":"stat", "interview_date":"preference",
        "last_readiness":"stat", "last_focus_date":"stat",
        "current_timeline":"stat", "carry_forward_tasks":"stat",
    }
    upsert_entity(cat_map.get(key, "preference"), key, value=val_str, source=source)


def recall(key: str):
    """Retrieve a remembered value by key. Returns None if not found."""
    for e in get_entities():
        if e["key"] == key:
            try:    return json.loads(e["value"])
            except: return e["value"]
    return None


def build_agent_context() -> str:
    """Rich context string injected into the agent system prompt."""
    ctx   = get_user_context()
    parts = []
    if ctx.get("name"):            parts.append(f"User: {ctx['name']}")
    if ctx.get("current_role"):    parts.append(f"Role: {ctx['current_role']} at {ctx.get('current_company','?')}")
    if ctx.get("years_exp"):       parts.append(f"Experience: {ctx['years_exp']} years")
    if ctx.get("target_role"):     parts.append(f"Target: {ctx['target_role']}")
    if ctx.get("skills"):          parts.append(f"Skills: {', '.join(ctx['skills'][:10])}")
    if ctx.get("weak_areas"):      parts.append(f"Weak areas: {', '.join(ctx['weak_areas'][:5])}")
    if ctx.get("pending_tasks"):   parts.append(f"Pending today: {', '.join(ctx['pending_tasks'][:3])}")
    if ctx.get("recent_goals"):    parts.append(f"Recent goals: {' | '.join(ctx['recent_goals'][:2])}")
    if not ctx.get("has_resume"):  parts.append("No resume yet — ask user to upload one.")
    return "\n".join(parts) if parts else "First session — no prior context."


def get_incomplete_from_yesterday() -> list[dict]:
    """Tasks from yesterday that were not completed."""
    from datetime import timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with _db() as s:
        rows = s.query(Task).filter_by(task_date=yesterday, done=False).all()
        return [{"task": r.text, "duration": r.duration, "priority": r.priority} for r in rows]
