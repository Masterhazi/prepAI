"""
hackerrank.py — Personal HackerRank data via personal API key
Fetches YOUR badges, contest scores, skill certifications.
"""

import requests
from core.vault import get_key

BASE_URL = "https://www.hackerrank.com/rest"


def _headers() -> dict:
    key = get_key("hackerrank_api_key")
    if not key:
        raise ValueError("HackerRank API key not set. Add it in Settings.")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def get_profile() -> dict:
    """Fetch your HackerRank profile and badge summary."""
    try:
        r = requests.get(f"{BASE_URL}/hackers/me", headers=_headers(), timeout=10)
        if r.status_code == 401:
            return {"error": "Invalid API key. Check your HackerRank key in Settings."}
        data = r.json().get("model", {})
        return {
            "username": data.get("username"),
            "name": data.get("name"),
            "level": data.get("level"),
            "points": data.get("points"),
            "rank": data.get("rank"),
            "skills": data.get("skills", []),
        }
    except Exception as e:
        return {"error": str(e)}


def get_badges() -> list:
    """Fetch earned badges from your account."""
    try:
        r = requests.get(f"{BASE_URL}/hackers/me/badges", headers=_headers(), timeout=10)
        badges = r.json().get("models", [])
        return [
            {
                "name": b.get("badge_name"),
                "type": b.get("type"),
                "stars": b.get("stars"),
                "solved": b.get("solved"),
            }
            for b in badges
        ]
    except Exception as e:
        return [{"error": str(e)}]


def get_certifications() -> list:
    """Fetch skill certifications you've earned."""
    try:
        r = requests.get(
            f"{BASE_URL}/hackers/me/certificates", headers=_headers(), timeout=10
        )
        certs = r.json().get("models", [])
        return [
            {
                "name": c.get("certificate", {}).get("label"),
                "slug": c.get("certificate", {}).get("slug"),
                "score": c.get("score"),
                "completed_at": c.get("completed_at"),
            }
            for c in certs
        ]
    except Exception as e:
        return [{"error": str(e)}]


def get_submissions(track: str = "python", limit: int = 10) -> list:
    """Fetch recent submissions for a specific track."""
    try:
        r = requests.get(
            f"{BASE_URL}/contests/master/tracks/{track}/submissions",
            headers=_headers(),
            params={"limit": limit, "offset": 0},
            timeout=10,
        )
        models = r.json().get("models", [])
        return [
            {
                "challenge": m.get("challenge", {}).get("slug"),
                "score": m.get("score"),
                "status": m.get("status"),
                "language": m.get("language"),
                "created_at": m.get("created_at"),
            }
            for m in models
        ]
    except Exception as e:
        return [{"error": str(e)}]


def get_full_summary() -> dict:
    """Single call to get everything relevant for the dashboard."""
    profile = get_profile()
    if "error" in profile:
        return {"error": profile["error"], "source": "hackerrank"}

    badges = get_badges()
    certs = get_certifications()

    # Summarise badge strength by category
    badge_summary = {}
    for b in badges:
        name = b.get("name", "")
        stars = b.get("stars", 0)
        if name:
            badge_summary[name] = stars

    return {
        "profile": profile,
        "badge_count": len(badges),
        "badge_summary": badge_summary,
        "certifications": certs,
        "cert_count": len(certs),
    }


if __name__ == "__main__":
    print("HackerRank module ready.")
    print("Set your API key via: vault.set_key('hackerrank_api_key', '...')")
    print("Then call: get_full_summary()")
