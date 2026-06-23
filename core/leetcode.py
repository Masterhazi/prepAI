"""
leetcode.py — Personal LeetCode data via session token
Fetches YOUR solve history, streak, weak topics — not generic lists.
"""

import requests
from core.vault import get_key

GRAPHQL_URL = "https://leetcode.com/graphql"


def _session() -> requests.Session:
    token = get_key("leetcode_session_token")
    if not token:
        raise ValueError("LeetCode session token not set. Add it in Settings.")

    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com",
        "User-Agent": "Mozilla/5.0",
        "Cookie": f"LEETCODE_SESSION={token}",
        "x-csrftoken": "prepai",
    })
    return s


def get_profile(username: str) -> dict:
    """Fetch public profile stats for a username."""
    query = """
    query userPublicProfile($username: String!) {
      matchedUser(username: $username) {
        username
        submitStats {
          acSubmissionNum {
            difficulty
            count
            submissions
          }
        }
        userCalendar {
          streak
          totalActiveDays
        }
      }
    }
    """
    try:
        s = _session()
        r = s.post(GRAPHQL_URL, json={"query": query, "variables": {"username": username}})
        data = r.json().get("data", {}).get("matchedUser", {})
        stats = data.get("submitStats", {}).get("acSubmissionNum", [])
        calendar = data.get("userCalendar", {})

        result = {
            "username": data.get("username", username),
            "streak": calendar.get("streak", 0),
            "active_days": calendar.get("totalActiveDays", 0),
            "solved": {},
        }
        for s_item in stats:
            diff = s_item.get("difficulty", "").lower()
            result["solved"][diff] = {
                "count": s_item.get("count", 0),
                "submissions": s_item.get("submissions", 0),
            }
        return result

    except Exception as e:
        return {"error": str(e), "username": username}


def get_recent_submissions(username: str, limit: int = 10) -> list:
    """Get the user's most recent accepted submissions."""
    query = """
    query recentAcSubmissions($username: String!, $limit: Int!) {
      recentAcSubmissionList(username: $username, limit: $limit) {
        id
        title
        titleSlug
        timestamp
        lang
      }
    }
    """
    try:
        s = _session()
        r = s.post(GRAPHQL_URL, json={
            "query": query,
            "variables": {"username": username, "limit": limit}
        })
        return r.json().get("data", {}).get("recentAcSubmissionList", [])
    except Exception as e:
        return [{"error": str(e)}]


def get_topic_problems(tags: list[str], difficulty: str = "MEDIUM", limit: int = 5) -> list:
    """
    Fetch problems filtered by topic tags.
    Used to build personalised study queues based on weak areas.
    tags: e.g. ["dynamic-programming", "graph"]
    difficulty: "EASY" | "MEDIUM" | "HARD"
    """
    query = """
    query problemsetQuestionList($categorySlug: String, $limit: Int, $filters: QuestionListFilterInput) {
      problemsetQuestionList: questionList(
        categorySlug: $categorySlug
        limit: $limit
        filters: $filters
      ) {
        questions: data {
          frontendQuestionId: questionFrontendId
          title
          titleSlug
          difficulty
          topicTags { name slug }
          stats
        }
      }
    }
    """
    filters = {"difficulty": difficulty, "tags": tags}
    try:
        s = _session()
        r = s.post(GRAPHQL_URL, json={
            "query": query,
            "variables": {
                "categorySlug": "",
                "limit": limit,
                "filters": filters
            }
        })
        questions = (
            r.json()
            .get("data", {})
            .get("problemsetQuestionList", {})
            .get("questions", [])
        )
        return [
            {
                "id": q.get("frontendQuestionId"),
                "title": q.get("title"),
                "slug": q.get("titleSlug"),
                "difficulty": q.get("difficulty"),
                "tags": [t["name"] for t in q.get("topicTags", [])],
                "url": f"https://leetcode.com/problems/{q.get('titleSlug')}/",
            }
            for q in questions
        ]
    except Exception as e:
        return [{"error": str(e)}]


def analyse_weak_topics(solved_data: dict) -> list[str]:
    """
    Given solve stats, return a ranked list of weak topic tags to focus on.
    This is a heuristic — in full version this would compare against submission history.
    """
    # Topics relevant to most backend / SWE roles
    important_topics = [
        "dynamic-programming",
        "graph",
        "tree",
        "binary-search",
        "sliding-window",
        "hash-table",
        "two-pointers",
        "heap-priority-queue",
    ]
    total = solved_data.get("solved", {}).get("all", {}).get("count", 0)

    # Simple heuristic: if low total solves, prioritise foundational topics
    if total < 50:
        return important_topics[:4]
    elif total < 150:
        return important_topics[2:6]
    else:
        return important_topics[4:]


def build_daily_queue(username: str, target_difficulty: str = "MEDIUM") -> dict:
    """
    Build a personalised daily problem queue for the user.
    Combines profile stats + weak topic analysis.
    """
    profile = get_profile(username)
    if "error" in profile:
        return {"error": profile["error"]}

    weak_topics = analyse_weak_topics(profile)
    problems = get_topic_problems(weak_topics[:2], difficulty=target_difficulty, limit=3)

    # Add one easy warm-up and one hard stretch
    easy = get_topic_problems(["array", "string"], difficulty="EASY", limit=1)
    hard = get_topic_problems(weak_topics[:1], difficulty="HARD", limit=1)

    queue = easy + problems + hard

    return {
        "username": username,
        "streak": profile.get("streak", 0),
        "weak_topics": weak_topics,
        "daily_queue": queue,
        "target_count": len(queue),
    }


if __name__ == "__main__":
    print("LeetCode module ready.")
    print("Set your session token via: vault.set_key('leetcode_session_token', '...')")
    print("Then call: build_daily_queue('your_username')")
