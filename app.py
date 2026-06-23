"""
app.py — PrepAI Flask backend (Stage 2: Memory wired in)
35+ routes. Memory loads on every agent run. Sessions saved after every run.
"""

import sys, os, json, time
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

sys.path.insert(0, str(Path(__file__).parent))

from core.vault import set_key, get_key, list_keys, status as vault_status, delete_key
from core.notifications import (
    get_config, save_config, get_history, unread_count,
    mark_all_read, send as notify, start_scheduler,
)
from core.ai_router import (
    ask, ask_with_jobs,
    current_engine, current_model, last_fallback_reason,
    set_preferred_engine, get_preferred_engine, engine_status,
    CLAUDE_MODELS, GEMINI_TEXT_MODELS, GROQ_MODELS,
)
from core.memory import (
    get_user_context, get_stats, get_recent_sessions,
    get_entities, get_tasks, mark_task_done,
    get_jobs, update_job_status,
    get_questions, mark_question_practiced,
    upsert_entity, log_event, get_events,
    get_latest_resume, get_task_completion_rate,
    save_tasks, _get_engine as init_db,
)
from core.leetcode import build_daily_queue
from core.hackerrank import get_full_summary as hr_summary

# Init DB on startup
init_db()

app = Flask(__name__,
            template_folder="ui/templates",
            static_folder="ui/static")
app.secret_key = os.urandom(24)


# ── Root ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Dashboard — memory-enriched ───────────────────────────────────────────────

@app.route("/api/dashboard")
def api_dashboard():
    cfg     = get_config()
    days_left = None
    interview_date = cfg.get("interview_date")
    if interview_date:
        from datetime import date
        try:
            days_left = max((date.fromisoformat(interview_date) - date.today()).days, 0)
        except ValueError:
            pass

    es  = engine_status()
    ctx = get_user_context()
    st  = get_stats()

    return jsonify({
        # Engine
        "engine":          es["current_engine"],
        "model":           es["current_model"],
        "preferred":       es["preferred"],
        "fallback_reason": last_fallback_reason(),
        # Interview
        "interview_date":  interview_date,
        "days_left":       days_left,
        # Notifications
        "unread_notifications": unread_count(),
        "notifications_enabled": cfg.get("enabled", True),
        "job_deadlines":   cfg.get("job_deadlines", []),
        # Keys
        "keys_set":        {k: v for k, v in vault_status().items()},
        "claude_has_key":  es["claude_has_key"],
        "gemini_has_key":  es["gemini_has_key"],
        "groq_has_key":    es["groq_has_key"],
        # Memory context
        "user_name":       ctx.get("name"),
        "current_role":    ctx.get("current_role"),
        "target_role":     ctx.get("target_role"),
        "skills_count":    len(ctx.get("skills", [])),
        "weak_areas":      ctx.get("weak_areas", [])[:5],
        "has_resume":      ctx.get("has_resume", False),
        # Stats
        "total_sessions":       st["total_sessions"],
        "questions_banked":     st["questions_banked"],
        "task_completion_7d":   st["task_completion_7d"],
        "jobs_tracked":         st["jobs_tracked"],
    })


# ── Engine preference ─────────────────────────────────────────────────────────

@app.route("/api/engine/status")
def api_engine_status():
    return jsonify(engine_status())


@app.route("/api/engine/prefer", methods=["POST"])
def api_engine_prefer():
    data = request.json or {}
    pref = data.get("engine", "auto")
    if pref not in ("auto", "claude", "gemini", "groq"):
        return jsonify({"error": "Invalid engine"}), 400
    set_preferred_engine(pref)
    return jsonify({"ok": True, "preferred": pref, "status": engine_status()})


# ── Focus — memory-aware daily tasks ─────────────────────────────────────────

@app.route("/api/focus")
def api_focus():
    # First: load from memory for today
    today_tasks = get_tasks()
    if today_tasks:
        done  = sum(1 for t in today_tasks if t["done"])
        pct   = int(done / len(today_tasks) * 100) if today_tasks else 0
        return jsonify({
            "tasks":   today_tasks,
            "pct":     pct,
            "source":  "memory",
            "message": f"{done}/{len(today_tasks)} tasks complete today",
        })

    # No tasks yet — generate with AI based on days left
    cfg = get_config()
    interview_date = cfg.get("interview_date")
    if not interview_date:
        return jsonify({"tasks": [], "pct": 0,
                        "message": "Set your interview date in Settings to generate a daily plan."})

    from datetime import date
    try:
        days_left = max((date.fromisoformat(interview_date) - date.today()).days, 0)
    except Exception:
        days_left = 14

    # Include memory context in prompt
    ctx = get_user_context()
    weak = ctx.get("weak_areas", [])
    weak_hint = f" Focus on: {', '.join(weak[:3])}." if weak else ""

    prompt = (
        f"Generate exactly 4 specific study tasks for today. "
        f"Interview in {days_left} days.{weak_hint} "
        f"Return ONLY JSON array: "
        f'[{{"task":"...","duration":"1h","priority":"high","done":false}}]'
    )
    try:
        result = ask(prompt)
        text = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        tasks = json.loads(text)
        # Save to memory
        save_tasks(tasks, source="ai_focus")
        pct = 0
        return jsonify({"tasks": tasks, "pct": pct,
                        "days_left": days_left, "source": "ai_generated"})
    except Exception as e:
        return jsonify({"tasks": [], "pct": 0, "error": str(e)})


@app.route("/api/focus/task/<int:task_id>/complete", methods=["POST"])
def api_focus_complete(task_id):
    mark_task_done(task_id)
    return jsonify({"ok": True})


# ── AI ask ────────────────────────────────────────────────────────────────────

@app.route("/api/ask", methods=["POST"])
def api_ask():
    data   = request.json or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Empty prompt"}), 400
    try:
        return jsonify(ask(prompt))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ask/stream")
def api_ask_stream():
    prompt = request.args.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "No prompt"}), 400

    def generate():
        pref = get_preferred_engine()
        try_claude  = pref in ("auto", "claude")
        try_gemini  = pref in ("auto", "gemini")
        try_groq    = pref in ("auto", "groq")

        # Try Claude streaming first
        if try_claude and get_key("anthropic_api_key"):
            try:
                from core.ai_router import _get_claude_client, _pick_claude_model
                from anthropic import RateLimitError, APIStatusError
                client = _get_claude_client()
                model  = _pick_claude_model()
                if model:
                    with client.messages.stream(
                        model=model, max_tokens=1500,
                        system="You are PrepAI, an expert interview prep assistant. Be concise.",
                        messages=[{"role": "user", "content": prompt}],
                    ) as stream:
                        for text in stream.text_stream:
                            yield f"data: {json.dumps({'chunk':text,'engine':'claude','model':model})}\n\n"
                    yield f"data: {json.dumps({'done':True,'engine':'claude','model':model})}\n\n"
                    return
            except Exception:
                pass

        # Try Gemini
        if (try_gemini or (pref == "auto")) and get_key("gemini_api_key"):
            try:
                result = ask(prompt, force_gemini=True)
                for word in result["text"].split(" "):
                    yield f"data: {json.dumps({'chunk':word+' ','engine':'gemini','model':result.get('model','')})}\n\n"
                    time.sleep(0.012)
                yield f"data: {json.dumps({'done':True,'engine':'gemini','fallback':try_claude})}\n\n"
                return
            except Exception:
                pass

        # Try Groq
        if (try_groq or (pref == "auto")) and get_key("groq_api_key"):
            try:
                from core.ai_router import _get_groq_client, _pick_groq_model
                client = _get_groq_client()
                model  = _pick_groq_model()
                if model:
                    stream = client.chat.completions.create(
                        model=model, max_tokens=1500, stream=True,
                        messages=[
                            {"role":"system","content":"You are PrepAI, an expert interview prep assistant."},
                            {"role":"user","content":prompt},
                        ],
                    )
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content or ""
                        if delta:
                            yield f"data: {json.dumps({'chunk':delta,'engine':'groq','model':model})}\n\n"
                    yield f"data: {json.dumps({'done':True,'engine':'groq','model':model})}\n\n"
                    return
            except Exception:
                pass

        yield f"data: {json.dumps({'error':'No AI engine available. Check your API keys in Settings.'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"},
    )


# ── Jobs ──────────────────────────────────────────────────────────────────────

@app.route("/api/jobs", methods=["POST"])
def api_jobs():
    data     = request.json or {}
    role     = data.get("role", "Software Engineer").strip()
    location = data.get("location", "India").strip()
    prompt = (
        f"Find current job listings for '{role}' in '{location}'. "
        f"Return 6 jobs as JSON array: [{{title,company,location,"
        f"match_percent(70-99),skills(array max 4),deadline(or null),"
        f"source,url}}]. Only JSON."
    )
    try:
        result = ask_with_jobs(prompt)
        text   = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        jobs   = json.loads(text)
        # Save to memory
        from core.memory import save_job
        for j in jobs:
            save_job(j.get("title",""), j.get("company",""),
                     j.get("location",""), j.get("skills",[]),
                     j.get("deadline"), j.get("url"),
                     float(j.get("match_percent",80))/100)
        return jsonify({"jobs":jobs,"engine":result["engine"],
                        "model":result.get("model"),"grounded":result.get("grounded",False)})
    except json.JSONDecodeError:
        return jsonify({"jobs":[],"raw":result.get("text","")[:300],"engine":result.get("engine","gemini")})
    except Exception as e:
        return jsonify({"error":str(e)}),500


# ── LeetCode ──────────────────────────────────────────────────────────────────

@app.route("/api/leetcode/<username>")
def api_leetcode(username):
    if not get_key("leetcode_session_token"):
        return jsonify({"error":"LeetCode session token not set"}),400
    try:
        data = build_daily_queue(username)
        # Save weak topics to memory
        for topic in data.get("weak_topics",[]):
            upsert_entity("weak_area", topic, source="leetcode")
        return jsonify(data)
    except Exception as e:
        return jsonify({"error":str(e)}),500


# ── HackerRank ────────────────────────────────────────────────────────────────

@app.route("/api/hackerrank")
def api_hackerrank():
    if not get_key("hackerrank_api_key"):
        return jsonify({"error":"HackerRank API key not set"}),400
    try:
        return jsonify(hr_summary())
    except Exception as e:
        return jsonify({"error":str(e)}),500


# ── Notifications ─────────────────────────────────────────────────────────────

@app.route("/api/notifications")
def api_notifications():
    return jsonify({"notifications":get_history(30),"unread":unread_count(),"schedule":get_config()})

@app.route("/api/notifications/read", methods=["POST"])
def api_notifications_read():
    mark_all_read(); return jsonify({"ok":True})

@app.route("/api/notifications/test", methods=["POST"])
def api_notifications_test():
    data = request.json or {}
    msgs = {
        "reminder": ("Good morning — time to prep!","Your daily study brief is ready."),
        "countdown":("Interview in 7 days","One week to go. Focus on system design."),
        "deadline": ("Application deadline","A job closes soon!"),
        "fallback": ("AI switched engines","Continuing seamlessly on fallback engine."),
    }
    title, msg = msgs.get(data.get("type","reminder"), msgs["reminder"])
    notify(title, msg, data.get("type","reminder"))
    return jsonify({"ok":True,"title":title})

@app.route("/api/notifications/config", methods=["POST"])
def api_notifications_config():
    data = request.json or {}
    cfg  = get_config()
    for k in ("morning_hour","evening_hour","interview_date","enabled","job_deadlines"):
        if k in data: cfg[k] = data[k]
    save_config(cfg)
    return jsonify({"ok":True,"config":cfg})


# ── API Keys ──────────────────────────────────────────────────────────────────

@app.route("/api/keys")
def api_keys():
    return jsonify({"status":vault_status(),"masked":list_keys()})

@app.route("/api/keys", methods=["POST"])
def api_keys_set():
    data  = request.json or {}
    name  = data.get("name","").strip()
    value = data.get("value","").strip()
    if not name or not value:
        return jsonify({"error":"name and value required"}),400
    set_key(name, value)
    # Clear model cache when AI keys change
    import core.ai_router as router
    router._gemini_models_cache = None
    return jsonify({"ok":True,"name":name})

@app.route("/api/keys/<name>", methods=["DELETE"])
def api_keys_delete(name):
    delete_key(name); return jsonify({"ok":True})


# ── Projects ──────────────────────────────────────────────────────────────────

@app.route("/api/projects", methods=["POST"])
def api_projects():
    data  = request.json or {}
    role  = data.get("role","backend engineer")
    stack = data.get("stack","Python")
    prompt = (
        f"Suggest 4 portfolio projects for a '{role}' targeting Google/Amazon/Flipkart. "
        f"Stack: {stack}. Return ONLY JSON: "
        f"[{{title,description,skills(array max 4),difficulty(Easy/Medium/Hard),"
        f"days_to_complete,why_it_matters}}]"
    )
    try:
        result  = ask(prompt)
        text    = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        projects= json.loads(text)
        return jsonify({"projects":projects,"engine":result["engine"],"model":result.get("model")})
    except Exception as e:
        return jsonify({"error":str(e)}),500


# ── Timeline ──────────────────────────────────────────────────────────────────

@app.route("/api/timeline", methods=["POST"])
def api_timeline():
    data    = request.json or {}
    days    = data.get("days_left",14)
    role    = data.get("role","Software Engineer")
    project = data.get("project","URL Shortener")
    prompt = (
        f"Create a {days}-day interview prep timeline for '{role}'. "
        f"Project: {project}. "
        f"Return ONLY JSON array: [{{week_number,title,tasks(array),focus_area}}]"
    )
    try:
        result   = ask(prompt)
        text     = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        timeline = json.loads(text)
        return jsonify({"timeline":timeline,"engine":result["engine"],"model":result.get("model")})
    except Exception as e:
        return jsonify({"error":str(e)}),500


# ── Memory routes ─────────────────────────────────────────────────────────────

@app.route("/api/memory")
def api_memory():
    from datetime import date
    ctx      = get_user_context()
    stats    = get_stats()
    sessions = get_recent_sessions(5)
    today_tasks = get_tasks()
    questions   = get_questions(verdict="pass", limit=5)
    failed_qs   = get_questions(verdict="fail", limit=3)

    # Build user profile dict from context
    user_profile = {}
    if ctx.get("name"):            user_profile["Name"]            = ctx["name"]
    if ctx.get("current_role"):    user_profile["Current role"]    = ctx["current_role"]
    if ctx.get("current_company"): user_profile["Current company"] = ctx["current_company"]
    if ctx.get("years_exp"):       user_profile["Experience"]      = f"{ctx['years_exp']} years"
    if ctx.get("target_role"):     user_profile["Target role"]     = ctx["target_role"]
    if ctx.get("skills"):
        user_profile["Skills detected"] = f"{len(ctx['skills'])} ({', '.join(ctx['skills'][:4])})"

    # Format sessions for display
    formatted_sessions = []
    for s in sessions:
        created = s.get("created_at","")[:10]
        formatted_sessions.append({
            "date":    created,
            "goal":    (s.get("goal","") or "")[:60],
            "outcome": "success" if s.get("outcome") else "—",
            "engine":  s.get("engine",""),
            "steps":   s.get("steps",0),
        })

    return jsonify({
        "context": {
            "weak_areas":       ctx.get("weak_areas",[]),
            "today_tasks":      [{**t, "task": t["text"]} for t in today_tasks],
            "recent_sessions":  formatted_sessions,
            "user":             user_profile,
            "streak_days":      0,  # TODO: calculate from events
            "pending_tasks":    ctx.get("pending_tasks",[]),
            "has_resume":       ctx.get("has_resume",False),
        },
        "stats":  stats,
        "question_stats": {
            "passed":  stats["questions_banked"],
            "failed":  len(failed_qs),
            "recent":  questions[:3],
        },
        "events": get_events(10),
    })

@app.route("/api/memory/stats")
def api_memory_stats():
    return jsonify({
        "stats":          get_stats(),
        "recent_sessions":get_recent_sessions(5),
        "pending_tasks":  get_tasks(),
        "completion_rate":get_task_completion_rate(7),
    })

@app.route("/api/memory/entities")
def api_memory_entities():
    cat = request.args.get("category")
    return jsonify({"entities": get_entities(cat)})

@app.route("/api/memory/entity", methods=["POST"])
def api_memory_entity():
    data = request.json or {}
    upsert_entity(
        category   = data.get("category","skill"),
        key        = data.get("key",""),
        value      = data.get("value",""),
        confidence = float(data.get("confidence",1.0)),
        source     = "user",
    )
    return jsonify({"ok":True})

@app.route("/api/memory/jobs")
def api_memory_jobs():
    status = request.args.get("status")
    return jsonify({"jobs": get_jobs(status)})

@app.route("/api/memory/jobs/<int:job_id>/status", methods=["POST"])
def api_memory_job_status(job_id):
    data = request.json or {}
    update_job_status(job_id, data.get("status","seen"), data.get("notes",""))
    return jsonify({"ok":True})

@app.route("/api/memory/questions")
def api_memory_questions():
    role    = request.args.get("role")
    verdict = request.args.get("verdict","pass")
    return jsonify({"questions": get_questions(role=role, verdict=verdict, limit=30)})

@app.route("/api/memory/task/<int:task_id>/complete", methods=["POST"])
def api_memory_task_complete(task_id):
    mark_task_done(task_id)
    return jsonify({"ok":True})

@app.route("/api/memory/clear", methods=["POST"])
def api_memory_clear():
    """Clear memory entities. If category given, clears that category only. Otherwise clears all entities."""
    data = request.json or {}
    cat  = data.get("category")
    from core.memory import _db, Entity
    with _db() as s:
        if cat:
            s.query(Entity).filter_by(category=cat).delete()
        else:
            s.query(Entity).delete()
        s.commit()
    return jsonify({"ok":True,"cleared":cat})

@app.route("/api/memory/reset", methods=["POST"])
def api_memory_reset():
    """Hard reset — wipes all memory. Asks for confirmation."""
    data = request.json or {}
    if data.get("confirm") != "RESET":
        return jsonify({"error":"Send confirm=RESET to proceed"}),400
    import core.memory as mem
    mem.Base.metadata.drop_all(mem._engine)
    mem.Base.metadata.create_all(mem._engine)
    log_event("memory_reset","Full memory reset by user")
    return jsonify({"ok":True})


# ── Resume ────────────────────────────────────────────────────────────────────

@app.route("/api/resume")
def api_resume():
    return jsonify({"resume": get_latest_resume()})

@app.route("/api/resume/upload", methods=["POST"])
def api_resume_upload():
    if "file" not in request.files:
        return jsonify({"error":"No file uploaded"}),400
    f    = request.files["file"]
    name = f.filename or "resume"
    ext  = Path(name).suffix.lower()
    if ext not in (".pdf",".docx",".doc"):
        return jsonify({"error":"Only PDF and DOCX supported"}),400

    import tempfile
    from core.resume import parse_resume
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        f.save(tmp.name)
        try:
            data = parse_resume(tmp.name)
            os.unlink(tmp.name)
            clean = {k:v for k,v in data.items() if k != "raw_text"}
            import json as _json
            skills = data.get("skills",[])
            if isinstance(skills,str):
                try: skills = _json.loads(skills)
                except: skills = []
            fields_extracted = sum(1 for v in clean.values() if v)
            return jsonify({"ok":True,"resume":clean,
                           "fields_extracted":fields_extracted,
                           "name": data.get("name",""),
                           "role": data.get("current_role",""),
                           "skills_count": len(skills)})
        except Exception as e:
            os.unlink(tmp.name)
            return jsonify({"error":str(e)}),500


# ── Judge ─────────────────────────────────────────────────────────────────────

@app.route("/api/judge", methods=["POST"])
def api_judge():
    """Judge a list of questions via SSE stream."""
    data      = request.json or {}
    questions = data.get("questions",[])
    role      = data.get("role","Software Engineer")
    company   = data.get("company","")
    source_engine = data.get("source_engine", current_engine())

    if not questions:
        return jsonify({"error":"No questions provided"}),400

    def generate():
        from core.judge import judge_questions_batch
        for event in judge_questions_batch(questions, role, company, source_engine):
            yield f"data: {json.dumps(event)}\n\n"

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


# ── Agent ─────────────────────────────────────────────────────────────────────

@app.route("/api/agent/tools")
def api_agent_tools():
    from core.agent import available_tools
    return jsonify({
        "tools":          available_tools(),
        "preferred":      get_preferred_engine(),
        "engine_status":  engine_status(),
        "memory_context": get_user_context(),
    })

@app.route("/api/agent/run")
def api_agent_run():
    goal     = request.args.get("goal","").strip()
    role     = request.args.get("role","").strip()
    location = request.args.get("location","India").strip()
    lc_user  = request.args.get("lc_username","").strip()
    stack    = request.args.get("stack","Python").strip()

    if not goal:
        return jsonify({"error":"No goal provided"}),400

    cfg     = get_config()
    context = {
        "interview_date":    cfg.get("interview_date"),
        "role":              role or None,
        "location":          location or None,
        "leetcode_username": lc_user or None,
        "stack":             stack or None,
    }

    def generate():
        from core.agent import run_agent
        try:
            for event in run_agent(goal, context):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','text':str(e)})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})



# ── Judge on demand ───────────────────────────────────────────────────────────

@app.route("/api/judge/run")
def api_judge_run():
    """SSE stream — judge a list of questions on demand."""
    role     = request.args.get("role","Software Engineer")
    company  = request.args.get("company","")
    engine   = request.args.get("source_engine","claude")
    raw_qs   = request.args.get("questions","")
    try:
        questions = json.loads(raw_qs) if raw_qs else []
    except Exception:
        questions = [{"question":raw_qs,"category":"technical"}]

    def generate():
        from core.judge import judge_questions_batch
        try:
            for event in judge_questions_batch(questions, role, company, engine):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','text':str(e)})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"},
    )


@app.route("/api/questions/practice/<int:qid>", methods=["POST"])
def api_question_practice(qid):
    from core.memory import mark_question_practiced
    mark_question_practiced(qid)
    return jsonify({"ok":True})


@app.route("/api/questions/generate", methods=["POST"])
def api_questions_generate():
    """Generate + judge questions for a role/company, stream results."""
    data    = request.json or {}
    role    = data.get("role","Software Engineer")
    company = data.get("company","")
    category= data.get("category","technical")
    count   = int(data.get("count",5))

    from core.agent import tool_generate_interview_questions
    result = tool_generate_interview_questions(role=role, company=company,
                                               category=category, count=count)
    return jsonify(result)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser, threading
    start_scheduler()
    threading.Thread(
        target=lambda: (time.sleep(1.2), webbrowser.open("http://127.0.0.1:5000")),
        daemon=True,
    ).start()
    print("\n  PrepAI at http://127.0.0.1:5000  —  Ctrl+C to quit\n")
    app.run(debug=False, port=5000, threaded=True)
