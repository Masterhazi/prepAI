"""
agent.py — PrepAI Agent with full memory, Groq, and Judge wired in.

Flow every run:
  1. Load user context from memory (skills, role, weak areas, past goals)
  2. Inject context into the planning prompt
  3. Execute tools — questions go through Judge before being saved
  4. Save session, tasks, jobs, entities to memory after run
  5. Stream progress events to UI throughout
"""

import json, time
from datetime import date
from typing import Generator

from core.vault import get_key
from core.ai_router import (
    get_preferred_engine,
    _get_claude_client, _pick_claude_model,
    _get_gemini_client, _get_available_gemini_models, _is_on_cooldown, _set_cooldown,
    _get_groq_client, _pick_groq_model,
    GEMINI_TEXT_MODELS, GROQ_MODELS,
)
from core.memory import (
    get_user_context, save_session, save_tasks, save_job,
    upsert_entity, log_event, get_tasks, get_stats,
)
from core.notifications import get_config, save_config, send as notify

MAX_STEPS = 12


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ══════════════════════════════════════════════════════════════════════════════

def tool_scan_jobs(role: str, location: str = "India") -> dict:
    from core.ai_router import ask_with_jobs
    prompt = (
        f"Find 5 current job listings for '{role}' in '{location}'. "
        f"Return ONLY a JSON array: "
        f'[{{"title":"...","company":"...","location":"...","skills":[],"deadline":null,"match_reason":"..."}}]'
    )
    result = ask_with_jobs(prompt)
    text = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        jobs = json.loads(text)
        # Persist each job to memory
        for j in jobs:
            save_job(
                title=j.get("title",""), company=j.get("company",""),
                location=j.get("location",""), skills=j.get("skills",[]),
                deadline=j.get("deadline"), url=j.get("url",""),
                match_score=j.get("match_percent",0)/100 if j.get("match_percent") else 0.0,
            )
        return {"jobs": jobs, "count": len(jobs), "engine": result["engine"]}
    except Exception:
        return {"jobs": [], "raw": text[:300], "engine": result["engine"]}


def tool_get_leetcode_queue(username: str) -> dict:
    from core.leetcode import build_daily_queue
    data = build_daily_queue(username)
    # Persist weak areas to memory
    for topic in data.get("weak_topics", []):
        upsert_entity("weak_area", topic, source="leetcode", confidence=0.9)
    return data


def tool_generate_timeline(role: str, days_left: int, project: str = "URL Shortener") -> dict:
    from core.ai_router import ask
    prompt = (
        f"Create a {days_left}-day interview prep timeline for '{role}'. "
        f"Project to build: {project}. "
        f"Return ONLY JSON array: "
        f'[{{"week_number":1,"title":"...","tasks":[],"focus_area":"..."}}]'
    )
    result = ask(prompt)
    text = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        weeks = json.loads(text)
        return {"timeline": weeks, "weeks": len(weeks), "engine": result["engine"]}
    except Exception:
        return {"timeline": [], "error": "Parse failed"}


def tool_generate_focus(days_left: int, weak_topics: list = None) -> dict:
    from core.ai_router import ask
    topics_hint = f" Focus on: {', '.join(weak_topics[:3])}." if weak_topics else ""
    prompt = (
        f"Generate 4 specific study tasks for today. Interview in {days_left} days.{topics_hint} "
        f"Return ONLY JSON: "
        f'[{{"task":"...","duration":"1h","priority":"high"}}]'
    )
    result = ask(prompt)
    text = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        tasks = json.loads(text)
        # Persist tasks to memory
        save_tasks(tasks, source="agent")
        return {"tasks": tasks, "count": len(tasks), "engine": result["engine"]}
    except Exception:
        return {"tasks": [], "error": "Parse failed"}


def tool_generate_interview_questions(role: str, company: str = "",
                                       category: str = "technical",
                                       count: int = 5) -> dict:
    """Generate questions AND run them through the Judge before returning."""
    from core.ai_router import ask
    from core.judge import judge_questions_batch

    company_str = f" at {company}" if company else ""
    prompt = (
        f"Generate {count} realistic {category} interview questions for "
        f"a '{role}' position{company_str}. "
        f"Questions must be specific, verifiable, and grounded in real interview patterns. "
        f"Return ONLY JSON: "
        f'[{{"question":"...","category":"{category}"}}]'
    )
    result = ask(prompt)
    text = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        questions = json.loads(text)
    except Exception:
        return {"questions": [], "passed": 0, "failed": 0, "error": "Parse failed"}

    # Run every question through the Judge
    passed, failed, flagged = [], [], []
    for event in judge_questions_batch(questions, role, company, result["engine"]):
        if event["type"] == "verdict":
            q = {"question": event["question"], "verdict": event["verdict"],
                 "confidence": event["confidence"], "judge_engine": event["judge_engine"]}
            if event["verdict"] == "pass":     passed.append(q)
            elif event["verdict"] == "fail":   failed.append(q)
            else:                               flagged.append(q)

    return {
        "questions": passed,  # Only return verified questions
        "passed": len(passed), "failed": len(failed), "flagged": len(flagged),
        "total_generated": len(questions),
        "engine": result["engine"],
    }


def tool_suggest_projects(role: str, stack: str = "Python", count: int = 3) -> dict:
    from core.ai_router import ask
    prompt = (
        f"Suggest {count} portfolio projects for a '{role}' role. Stack: {stack}. "
        f"Return ONLY JSON: "
        f'[{{"title":"...","description":"...","skills":[],"days_to_complete":7,"why_it_matters":"..."}}]'
    )
    result = ask(prompt)
    text = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        projects = json.loads(text)
        return {"projects": projects, "count": len(projects), "engine": result["engine"]}
    except Exception:
        return {"projects": [], "error": "Parse failed"}


def tool_analyse_readiness(days_left: int, leetcode_data: dict = None,
                            jobs: list = None) -> dict:
    from core.ai_router import ask
    # Pull historical completion rate from memory
    from core.memory import get_task_completion_rate
    completion = get_task_completion_rate(7)

    context = f"Interview in {days_left} days. Task completion rate (7d): {completion*100:.0f}%."
    if leetcode_data and not leetcode_data.get("error"):
        streak = leetcode_data.get("streak", 0)
        weak   = leetcode_data.get("weak_topics", [])
        context += f" LeetCode streak: {streak} days. Weak: {', '.join(weak[:3])}."
    if jobs:
        skills = set()
        for j in jobs[:3]:
            skills.update(j.get("skills", []))
        context += f" Target skills from listings: {', '.join(list(skills)[:6])}."

    prompt = (
        f"{context} Assess interview readiness. "
        f"Return ONLY JSON: "
        f'{{"readiness_score":0-100,"strengths":[],"gaps":[],'
        f'"top_priority":"...","estimated_ready_in_days":0}}'
    )
    result = ask(prompt)
    text = result["text"].strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        assessment = json.loads(text)
        # Persist gaps as weak areas
        for gap in assessment.get("gaps", []):
            upsert_entity("weak_area", gap, source="agent", confidence=0.85)
        return {**assessment, "engine": result["engine"]}
    except Exception:
        return {"readiness_score": 0, "error": "Parse failed"}


def tool_set_interview_date(interview_date: str) -> dict:
    cfg = get_config()
    cfg["interview_date"] = interview_date
    save_config(cfg)
    notify("Interview date set", f"Prep plan starts now. Interview: {interview_date}", "info")
    log_event("interview_date_set", f"Interview scheduled: {interview_date}")
    return {"saved": True, "interview_date": interview_date}


def tool_set_job_deadline(title: str, company: str, deadline_date: str) -> dict:
    cfg = get_config()
    deadlines = cfg.get("job_deadlines", [])
    # Dedup
    if not any(d.get("company") == company and d.get("title") == title for d in deadlines):
        deadlines.append({"title": title, "company": company, "date": deadline_date})
        cfg["job_deadlines"] = deadlines
        save_config(cfg)
    return {"saved": True, "job": f"{title} at {company}", "deadline": deadline_date}


def tool_answer_question(question: str) -> dict:
    from core.ai_router import ask
    result = ask(question)
    return {"answer": result["text"], "engine": result["engine"]}


# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS: dict[str, dict] = {
    "scan_jobs": {
        "fn": tool_scan_jobs,
        "description": "Scan live job boards using Google Search. Returns and saves current listings.",
        "parameters": {
            "role":     {"type":"string","description":"Job role to search"},
            "location": {"type":"string","description":"Location","default":"India"},
        },
        "required": ["role"],
    },
    "get_leetcode_queue": {
        "fn": tool_get_leetcode_queue,
        "description": "Fetch user's personal LeetCode history, streak, and weak topics. Saves weak areas to memory.",
        "parameters": {
            "username": {"type":"string","description":"LeetCode username"},
        },
        "required": ["username"],
    },
    "generate_timeline": {
        "fn": tool_generate_timeline,
        "description": "Create a week-by-week interview prep timeline.",
        "parameters": {
            "role":      {"type":"string","description":"Target role"},
            "days_left": {"type":"integer","description":"Days until interview"},
            "project":   {"type":"string","description":"Main project to build","default":"URL Shortener"},
        },
        "required": ["role","days_left"],
    },
    "generate_focus": {
        "fn": tool_generate_focus,
        "description": "Generate today's study tasks based on weak areas. Saves tasks to memory.",
        "parameters": {
            "days_left":    {"type":"integer","description":"Days until interview"},
            "weak_topics":  {"type":"array","description":"Topics to focus on","default":[]},
        },
        "required": ["days_left"],
    },
    "generate_interview_questions": {
        "fn": tool_generate_interview_questions,
        "description": "Generate interview questions and run each through the Judge. Only verified questions are returned and saved.",
        "parameters": {
            "role":     {"type":"string","description":"Target role"},
            "company":  {"type":"string","description":"Target company","default":""},
            "category": {"type":"string","description":"technical / system-design / behavioural","default":"technical"},
            "count":    {"type":"integer","description":"Questions to generate","default":5},
        },
        "required": ["role"],
    },
    "suggest_projects": {
        "fn": tool_suggest_projects,
        "description": "Suggest portfolio projects for the target role and stack.",
        "parameters": {
            "role":  {"type":"string","description":"Target role"},
            "stack": {"type":"string","description":"Primary stack","default":"Python"},
            "count": {"type":"integer","description":"Number of projects","default":3},
        },
        "required": ["role"],
    },
    "analyse_readiness": {
        "fn": tool_analyse_readiness,
        "description": "Score interview readiness using task history, LeetCode data, and job skills. Saves gaps to memory.",
        "parameters": {
            "days_left":    {"type":"integer","description":"Days until interview"},
            "leetcode_data":{"type":"object","description":"Output from get_leetcode_queue","default":{}},
            "jobs":         {"type":"array","description":"Output from scan_jobs","default":[]},
        },
        "required": ["days_left"],
    },
    "set_interview_date": {
        "fn": tool_set_interview_date,
        "description": "Save the interview date and schedule notifications.",
        "parameters": {
            "interview_date": {"type":"string","description":"Date YYYY-MM-DD"},
        },
        "required": ["interview_date"],
    },
    "set_job_deadline": {
        "fn": tool_set_job_deadline,
        "description": "Track a job application deadline for notifications.",
        "parameters": {
            "title":         {"type":"string","description":"Job title"},
            "company":       {"type":"string","description":"Company name"},
            "deadline_date": {"type":"string","description":"Deadline YYYY-MM-DD"},
        },
        "required": ["title","company","deadline_date"],
    },
    "answer_question": {
        "fn": tool_answer_question,
        "description": "Answer any interview prep question directly.",
        "parameters": {
            "question": {"type":"string","description":"The question"},
        },
        "required": ["question"],
    },
}


def _execute_tool(name: str, args: dict) -> dict:
    if name not in TOOLS:
        return {"error": f"Unknown tool: {name}"}
    spec = TOOLS[name]
    for param, pspec in spec["parameters"].items():
        if param not in args and "default" in pspec:
            args[param] = pspec["default"]
    try:
        result = spec["fn"](**args)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        return {"error": str(e), "tool": name}


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _claude_tool_schema() -> list:
    schemas = []
    for name, spec in TOOLS.items():
        props = {p: {"type": ps["type"], "description": ps["description"]}
                 for p, ps in spec["parameters"].items()}
        schemas.append({
            "name": name,
            "description": spec["description"],
            "input_schema": {"type":"object","properties":props,"required":spec.get("required",[])},
        })
    return schemas


def _gemini_function_schema() -> list:
    from google.genai import types as gt
    type_map = {"string":"STRING","integer":"INTEGER","array":"ARRAY",
                "object":"OBJECT","boolean":"BOOLEAN"}
    decls = []
    for name, spec in TOOLS.items():
        props = {p: gt.Schema(type=type_map.get(ps["type"],"STRING"),
                              description=ps["description"])
                 for p, ps in spec["parameters"].items()}
        decls.append(gt.FunctionDeclaration(
            name=name, description=spec["description"],
            parameters=gt.Schema(type="OBJECT", properties=props,
                                 required=spec.get("required",[])),
        ))
    return decls


def _groq_tool_schema() -> list:
    """Groq uses OpenAI-compatible function calling schema."""
    schemas = []
    for name, spec in TOOLS.items():
        props = {}
        for p, ps in spec["parameters"].items():
            prop = {"type": ps["type"], "description": ps["description"]}
            if ps["type"] == "array":
                prop["items"] = {"type": "string"}
            props[p] = prop
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": spec.get("required", []),
                },
            },
        })
    return schemas


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT — memory-aware
# ══════════════════════════════════════════════════════════════════════════════

def _build_system_prompt(ctx: dict) -> str:
    lines = [
        "You are PrepAI Agent — an autonomous interview preparation assistant.",
        "Use the available tools to gather real data and build a complete prep plan.",
        "",
        "Rules:",
        "- Always call tools to gather real data before giving advice",
        "- Use scan_jobs to understand what skills are actually needed",
        "- Use generate_interview_questions for questions (they go through a Judge automatically)",
        "- Use analyse_readiness AFTER gathering job and LeetCode data",
        "- Use generate_timeline and generate_focus to create actionable plans",
        "- Save interview dates and job deadlines when you find them",
        "- Give a concise final summary with bullet points",
        "",
    ]

    # Inject memory context
    if ctx.get("name"):
        lines.append(f"User: {ctx['name']}")
    if ctx.get("current_role"):
        lines.append(f"Current role: {ctx['current_role']}" +
                     (f" at {ctx['current_company']}" if ctx.get("current_company") else ""))
    if ctx.get("years_exp"):
        lines.append(f"Experience: {ctx['years_exp']} years")
    if ctx.get("skills"):
        lines.append(f"Known skills: {', '.join(ctx['skills'][:10])}")
    if ctx.get("weak_areas"):
        lines.append(f"Known weak areas: {', '.join(ctx['weak_areas'][:5])}")
    if ctx.get("target_role"):
        lines.append(f"Target role: {ctx['target_role']}")
    if ctx.get("past_companies"):
        lines.append(f"Past companies: {', '.join(ctx['past_companies'][:4])}")
    if ctx.get("pending_tasks"):
        lines.append(f"Pending tasks from last session: {'; '.join(ctx['pending_tasks'][:3])}")
    if ctx.get("recent_goals"):
        lines.append(f"Recent session goals: {'; '.join(ctx['recent_goals'][:2])}")

    return "\n".join(lines)


def _build_goal_prompt(goal: str, context: dict) -> str:
    parts = [f"Goal: {goal}"]
    if context.get("interview_date"):
        try:
            days = (date.fromisoformat(context["interview_date"]) - date.today()).days
            parts.append(f"Interview: {context['interview_date']} ({days} days away)")
        except Exception:
            parts.append(f"Interview: {context['interview_date']}")
    for key in ("role","location","leetcode_username","stack"):
        if context.get(key):
            parts.append(f"{key.replace('_',' ').title()}: {context[key]}")
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# AGENT RUNNERS
# ══════════════════════════════════════════════════════════════════════════════

def _run_claude_agent(goal: str, context: dict, system: str) -> Generator:
    client = _get_claude_client()
    model  = _pick_claude_model()
    if not model:
        yield {"type":"error","text":"All Claude models on cooldown."}
        return

    yield {"type":"engine","engine":"claude","model":model}
    messages = [{"role":"user","content":_build_goal_prompt(goal, context)}]
    tools    = _claude_tool_schema()

    for step in range(MAX_STEPS):
        yield {"type":"thinking","step":step+1}
        try:
            resp = _get_claude_client().messages.create(
                model=model, max_tokens=2000,
                system=system, tools=tools, messages=messages,
            )
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "529" in err:
                _set_cooldown(model, 60)
            yield {"type":"error","text":str(e)}
            return

        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":        text_parts.append(block.text)
            elif block.type == "tool_use":  tool_calls.append(block)

        if text_parts:
            yield {"type":"thought","text":" ".join(text_parts)}

        if not tool_calls:
            yield {"type":"final","text":" ".join(text_parts)}
            return

        tool_results = []
        for tc in tool_calls:
            yield {"type":"tool_start","tool":tc.name,"args":dict(tc.input)}
            result = _execute_tool(tc.name, dict(tc.input))
            yield {"type":"tool_done","tool":tc.name,"result":_summarise(tc.name, result)}
            tool_results.append({"type":"tool_result","tool_use_id":tc.id,
                                  "content":json.dumps(result)})

        messages.append({"role":"assistant","content":resp.content})
        messages.append({"role":"user","content":tool_results})

    yield {"type":"final","text":"Agent reached max steps. Review results above."}


def _run_gemini_agent(goal: str, context: dict, system: str) -> Generator:
    from google.genai import types as gt
    client = _get_gemini_client()
    models = _get_available_gemini_models(client) or GEMINI_TEXT_MODELS
    model  = next((m for m in models if not _is_on_cooldown(m)), models[0])

    yield {"type":"engine","engine":"gemini","model":model}
    functions = _gemini_function_schema()
    tool_cfg  = gt.Tool(function_declarations=functions)
    history   = [gt.Content(role="user",
                             parts=[gt.Part(text=f"{system}\n\n{_build_goal_prompt(goal,context)}")])]

    for step in range(MAX_STEPS):
        yield {"type":"thinking","step":step+1}
        try:
            resp = client.models.generate_content(
                model=model, contents=history,
                config=gt.GenerateContentConfig(tools=[tool_cfg], max_output_tokens=2000),
            )
        except Exception as e:
            err = str(e).lower()
            if "quota" in err or "rate" in err or "429" in err:
                _set_cooldown(model, 60)
            yield {"type":"error","text":str(e)}
            return

        candidate = resp.candidates[0] if resp.candidates else None
        if not candidate:
            yield {"type":"error","text":"Gemini returned no candidate."}
            return

        parts    = candidate.content.parts if candidate.content else []
        texts    = [p.text for p in parts if hasattr(p,"text") and p.text]
        fn_calls = [p.function_call for p in parts
                    if hasattr(p,"function_call") and p.function_call]

        if texts:
            yield {"type":"thought","text":" ".join(texts)}

        if not fn_calls:
            yield {"type":"final","text":" ".join(texts)}
            return

        history.append(candidate.content)
        fn_parts = []
        for fc in fn_calls:
            args = dict(fc.args) if fc.args else {}
            yield {"type":"tool_start","tool":fc.name,"args":args}
            result = _execute_tool(fc.name, args)
            yield {"type":"tool_done","tool":fc.name,"result":_summarise(fc.name, result)}
            fn_parts.append(gt.Part(
                function_response=gt.FunctionResponse(
                    name=fc.name, response={"result":json.dumps(result)})
            ))
        history.append(gt.Content(role="user", parts=fn_parts))

    yield {"type":"final","text":"Agent reached max steps."}


def _run_groq_agent(goal: str, context: dict, system: str) -> Generator:
    client = _get_groq_client()
    model  = _pick_groq_model()
    if not model:
        yield {"type":"error","text":"All Groq models on cooldown."}
        return

    yield {"type":"engine","engine":"groq","model":model}
    messages = [
        {"role":"system","content":system},
        {"role":"user","content":_build_goal_prompt(goal,context)},
    ]
    tools = _groq_tool_schema()

    for step in range(MAX_STEPS):
        yield {"type":"thinking","step":step+1}
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=2000,
                messages=messages, tools=tools, tool_choice="auto",
            )
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err:
                _set_cooldown(model, 60)
            yield {"type":"error","text":str(e)}
            return

        msg        = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        text       = msg.content or ""

        if text:
            yield {"type":"thought","text":text}

        if not tool_calls:
            yield {"type":"final","text":text}
            return

        messages.append({"role":"assistant","content":msg.content or "",
                         "tool_calls":msg.tool_calls})

        for tc in tool_calls:
            fn   = tc.function
            args = json.loads(fn.arguments or "{}")
            yield {"type":"tool_start","tool":fn.name,"args":args}
            result = _execute_tool(fn.name, args)
            yield {"type":"tool_done","tool":fn.name,"result":_summarise(fn.name, result)}
            messages.append({
                "role":"tool","tool_call_id":tc.id,
                "name":fn.name,"content":json.dumps(result),
            })

    yield {"type":"final","text":"Agent reached max steps."}


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC INTERFACE
# ══════════════════════════════════════════════════════════════════════════════

def run_agent(goal: str, context: dict = None) -> Generator:
    """
    Main entry. Loads memory → runs agent → saves session.
    Yields SSE-compatible event dicts throughout.
    """
    context = context or {}
    pref    = get_preferred_engine()

    # ── Load memory context ───────────────────────────────────────────────────
    mem_ctx = get_user_context()
    # Merge: explicit context overrides memory
    for k, v in mem_ctx.items():
        if v and not context.get(k):
            context[k] = v

    # Use memory interview date if not provided
    if not context.get("interview_date"):
        cfg = get_config()
        if cfg.get("interview_date"):
            context["interview_date"] = cfg["interview_date"]

    system = _build_system_prompt(mem_ctx)
    yield {"type":"context_loaded","has_resume":mem_ctx.get("has_resume",False),
           "skills_count":len(mem_ctx.get("skills",[])),"weak_areas":mem_ctx.get("weak_areas",[])}

    # ── Run the right engine ──────────────────────────────────────────────────
    tools_used  = []
    final_text  = ""
    engine_used = "unknown"
    steps_used  = 0

    def _track(events):
        nonlocal final_text, engine_used, steps_used
        for ev in events:
            if ev["type"] == "engine":    engine_used = ev["engine"]
            if ev["type"] == "thinking":  steps_used  = ev["step"]
            if ev["type"] == "tool_done": tools_used.append(ev["tool"])
            if ev["type"] == "final":     final_text  = ev["text"]
            yield ev

    if pref == "claude":
        yield from _track(_run_claude_agent(goal, context, system))
    elif pref == "gemini":
        yield from _track(_run_gemini_agent(goal, context, system))
    elif pref == "groq":
        yield from _track(_run_groq_agent(goal, context, system))
    else:
        # Auto: Claude → Gemini → Groq
        success = False
        for runner, engine_name in [
            (_run_claude_agent, "claude"),
            (_run_gemini_agent, "gemini"),
            (_run_groq_agent,   "groq"),
        ]:
            key_map = {"claude":"anthropic_api_key",
                       "gemini":"gemini_api_key","groq":"groq_api_key"}
            if not get_key(key_map[engine_name]):
                continue
            had_error = False
            for ev in _track(runner(goal, context, system)):
                if ev["type"] == "error":
                    had_error = True
                    yield {"type":"fallback",
                           "text":f"{engine_name.title()} unavailable — trying next engine. ({ev['text']})"}
                    break
                yield ev
            if not had_error:
                success = True
                break
        if not success:
            yield {"type":"error","text":"No API keys configured. Add at least one key in Settings."}

    # ── Save session to memory ────────────────────────────────────────────────
    if final_text or tools_used:
        try:
            save_session(
                goal=goal, engine=engine_used, mode="agent",
                steps=steps_used, outcome=final_text[:2000],
                tools_used=tools_used,
            )
            log_event("agent_session", f"Goal: {goal[:80]}",
                      detail=f"Engine: {engine_used}, steps: {steps_used}, tools: {len(tools_used)}")
        except Exception as e:
            pass  # Never let memory save errors break the UX


# ── Helpers ───────────────────────────────────────────────────────────────────

def _summarise(tool_name: str, result: dict) -> str:
    if result.get("error"): return f"Error: {result['error']}"
    fns = {
        "scan_jobs":                   lambda r: f"Found {r.get('count',0)} listings",
        "get_leetcode_queue":          lambda r: f"Streak {r.get('streak',0)}d, {len(r.get('daily_queue',[]))} problems",
        "generate_timeline":           lambda r: f"{r.get('weeks',0)}-week plan created",
        "generate_focus":              lambda r: f"{r.get('count',0)} tasks saved to memory",
        "generate_interview_questions":lambda r: f"{r.get('passed',0)} passed judge, {r.get('failed',0)} rejected",
        "suggest_projects":            lambda r: f"{r.get('count',0)} projects suggested",
        "analyse_readiness":           lambda r: f"Score {r.get('readiness_score','?')}/100 — gaps saved to memory",
        "set_interview_date":          lambda r: f"Date saved: {r.get('interview_date','')}",
        "set_job_deadline":            lambda r: f"Tracked: {r.get('job','')}",
        "answer_question":             lambda r: (r.get("answer","")[:100]+"…") if len(r.get("answer",""))>100 else r.get("answer",""),
    }
    fn = fns.get(tool_name)
    return fn(result) if fn else json.dumps(result)[:150]


def available_tools() -> list:
    return [{"name":k,"description":v["description"]} for k,v in TOOLS.items()]
