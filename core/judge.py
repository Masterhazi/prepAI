"""
judge.py — Strict interview question validator.
Never uses the same engine that generated the content.
Claude generates → Gemini/Groq judges. Etc.
"""

import json, time
from typing import Generator
from core.vault import get_key

FILLER_PATTERNS = [
    "tell me about yourself","what are your strengths","what are your weaknesses",
    "where do you see yourself in 5 years","why do you want to work here",
    "what is your greatest achievement","describe yourself in three words",
    "do you have any questions for us","what motivates you","are you a team player",
]

ROLE_PATTERNS = {
    "software engineer":["system design","data structures","algorithms","complexity",
        "distributed","api design","database","caching","concurrency","scalability"],
    "backend engineer":["rest api","microservices","database design","sql","nosql",
        "kafka","redis","load balancing","authentication","rate limiting","async"],
    "frontend engineer":["react","component","state management","performance",
        "accessibility","css","responsive","typescript","dom"],
    "data engineer":["etl","pipeline","spark","airflow","data warehouse",
        "partitioning","schema","batch","streaming","data quality"],
    "ml engineer":["model deployment","feature engineering","training","overfitting",
        "evaluation","serving","mlops","vector"],
}


def _pick_judge_engine(source_engine: str) -> str:
    rotation = {"claude":["gemini","groq"],"gemini":["groq","claude"],"groq":["claude","gemini"]}
    keys = {"claude":get_key("anthropic_api_key"),"gemini":get_key("gemini_api_key"),"groq":get_key("groq_api_key")}
    for candidate in rotation.get(source_engine, ["gemini","groq"]):
        if keys.get(candidate): return candidate
    return source_engine


def _call_engine(engine: str, prompt: str) -> str:
    if engine == "claude":
        from core.ai_router import _get_claude_client, _pick_claude_model
        client = _get_claude_client()
        model  = _pick_claude_model() or "claude-haiku-4-5"
        resp = client.messages.create(model=model, max_tokens=600,
            system="You are a strict interview question validator. Be precise.",
            messages=[{"role":"user","content":prompt}])
        return resp.content[0].text
    elif engine == "gemini":
        from core.ai_router import _get_gemini_client, _get_available_gemini_models, GEMINI_TEXT_MODELS, _is_on_cooldown
        client = _get_gemini_client()
        models = _get_available_gemini_models(client) or GEMINI_TEXT_MODELS
        model  = next((m for m in models if not _is_on_cooldown(m)), models[0])
        return client.models.generate_content(model=model, contents=prompt).text
    elif engine == "groq":
        from core.ai_router import _get_groq_client, GROQ_MODELS, _is_on_cooldown
        client = _get_groq_client()
        model  = next((m for m in GROQ_MODELS if not _is_on_cooldown(m)), GROQ_MODELS[0])
        resp = client.chat.completions.create(model=model, max_tokens=600, messages=[
            {"role":"system","content":"You are a strict interview question validator."},
            {"role":"user","content":prompt}])
        return resp.choices[0].message.content
    return ""


def _heuristic_check(question: str, role: str) -> dict | None:
    q = question.lower().strip()
    for f in FILLER_PATTERNS:
        if f in q:
            return {"verdict":"fail","confidence":0.0,
                    "reason":f"Filler: matches generic pattern '{f}'","criteria":{}}
    if len(question.split()) < 10:
        return {"verdict":"fail","confidence":0.05,
                "reason":"Too vague — fewer than 10 words","criteria":{}}
    q_lower = question.lower()
    if not any(c in q_lower for c in ["?","explain","describe","design","implement",
                                        "how would","what would","walk me through",
                                        "tell me about a time","discuss","compare",
                                        "what is","what are","why would","when would"]):
        return {"verdict":"fail","confidence":0.1,
                "reason":"Not clearly a question or task","criteria":{}}
    return None


_PROMPT = """You are a strict interview question validator for a {role} position{co}.

Evaluate this question on 5 criteria. STRICT — reject anything:
- Generic filler not specific to the role
- Not verifiable as a real interview pattern
- Too vague to be actionable
- Clearly AI-fabricated with no grounding

Question: "{question}"

Return ONLY this JSON:
{{
  "specificity":    {{"score":0-10,"comment":"..."}},
  "verifiability":  {{"score":0-10,"comment":"..."}},
  "relevance":      {{"score":0-10,"comment":"..."}},
  "non_redundancy": {{"score":0-10,"comment":"..."}},
  "grounding":      {{"score":0-10,"comment":"..."}},
  "overall_verdict":"pass" or "fail" or "flagged",
  "confidence":0.0-1.0,
  "reason":"one sentence"
}}

Rules: pass = ALL scores>=6 AND avg>=7. flagged = avg 5-6. fail = any<4 OR avg<5."""


def judge_question(question: str, role: str, company: str,
                   source_engine: str, category: str = "technical") -> dict:
    heuristic = _heuristic_check(question, role)
    if heuristic: return {**heuristic, "judge_engine":"heuristic", "skipped_ai":True}

    judge_engine = _pick_judge_engine(source_engine)
    prompt = _PROMPT.format(role=role, co=f" at {company}" if company else "",
                            question=question)
    try:
        raw = _call_engine(judge_engine, prompt)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(raw)
        criteria = {k: result[k] for k in
            ["specificity","verifiability","relevance","non_redundancy","grounding"]
            if k in result}
        scores = [v["score"] for v in criteria.values() if isinstance(v, dict)]
        avg = sum(scores)/len(scores) if scores else 0
        return {"verdict":result.get("overall_verdict","fail"),
                "confidence":float(result.get("confidence", avg/10)),
                "reason":result.get("reason",""),
                "criteria":criteria,"avg_score":round(avg,1),
                "judge_engine":judge_engine,"skipped_ai":False}
    except Exception as e:
        msg = str(e).lower()

        quota_errors = [
            "resource_exhausted",
            "quota",
            "429",
            "rate limit",
            "exceeded your current quota"
        ]

        # Judge unavailable → fallback to heuristics only
        if any(x in msg for x in quota_errors):

            return {
                "verdict": "flagged",
                "confidence": 0.45,
                "reason":
                    f"Cross-model judge unavailable "
                    f"(quota exhausted on {judge_engine}). "
                    f"Passed heuristic checks only.",
                "criteria": {},
                "judge_engine": "heuristic-only",
                "skipped_ai": True
            }

        # Any other unexpected error
        return {
            "verdict": "flagged",
            "confidence": 0.35,
            "reason":
                f"Judge failed unexpectedly ({judge_engine}). "
                f"Question saved for manual review.",
            "criteria": {},
            "judge_engine": "heuristic-only",
            "skipped_ai": True
        }


def judge_questions_batch(questions: list[dict], role: str, company: str,
                          source_engine: str) -> Generator:
    from core.memory import save_question
    passed, failed, flagged = 0, 0, 0
    for i, q_obj in enumerate(questions):
        question = q_obj.get("question","") if isinstance(q_obj, dict) else str(q_obj)
        category = q_obj.get("category","technical") if isinstance(q_obj, dict) else "technical"
        yield {"type":"judging","index":i+1,"total":len(questions),
               "question":(question[:80]+"…") if len(question)>80 else question}
        vd = judge_question(question, role, company, source_engine, category)
        verdict = vd["verdict"]
        save_question(question=question, category=category, role=role, company=company,
                      source_engine=source_engine, verdict=verdict,
                      judge_engine=vd.get("judge_engine","unknown"),
                      judge_reason=vd.get("reason",""),
                      confidence=vd.get("confidence",0.0))
        if verdict=="pass": passed+=1
        elif verdict=="fail": failed+=1
        else: flagged+=1
        yield {"type":"verdict","index":i+1,"question":question,"verdict":verdict,
               "confidence":vd.get("confidence",0),"reason":vd.get("reason",""),
               "avg_score":vd.get("avg_score"),"judge_engine":vd.get("judge_engine")}
        time.sleep(0.25)
    yield {"type":"batch_done","passed":passed,"failed":failed,"flagged":flagged,
           "total":len(questions),
           "pass_rate":round(passed/len(questions)*100,1) if questions else 0}
