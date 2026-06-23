"""
notifications.py — Desktop notification system
Handles: daily study reminders, interview countdowns, job deadlines, streak alerts.
Uses plyer for cross-platform desktop toasts (Windows/Mac/Linux).
Runs in a background thread alongside the main app.
"""

import json
import os
import threading
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from plyer import notification as desktop_notify

_DATA_DIR = os.environ.get("PREPAI_DATA_DIR")
DATA_DIR = Path(_DATA_DIR) if _DATA_DIR else Path.home() / ".prepai"
NOTIF_FILE = DATA_DIR / "notifications.json"
STATE_FILE = DATA_DIR / "notif_state.json"

APP_NAME = "PrepAI"
APP_ICON = None  # Set to path of .ico/.png for branded icon


# ── Notification types ────────────────────────────────────────────────────────

class NotifType:
    DAILY_MORNING   = "daily_morning"
    DAILY_EVENING   = "daily_evening"
    COUNTDOWN       = "countdown"
    DEADLINE        = "deadline"
    STREAK          = "streak"
    FALLBACK_ALERT  = "fallback_alert"


# ── State helpers ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _load_config() -> dict:
    if NOTIF_FILE.exists():
        try:
            return json.loads(NOTIF_FILE.read_text())
        except Exception:
            pass
    # Default config
    return {
        "enabled": True,
        "morning_hour": 9,
        "evening_hour": 18,
        "interview_date": None,       # "YYYY-MM-DD"
        "job_deadlines": [],          # [{"title": "...", "company": "...", "date": "YYYY-MM-DD"}]
        "streak_threshold": 1,        # notify if streak drops
    }


def save_config(config: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    NOTIF_FILE.write_text(json.dumps(config, indent=2))
    print(f"  [notifications] Config saved.")


def get_config() -> dict:
    return _load_config()


# ── Core notify function ──────────────────────────────────────────────────────

def send(title: str, message: str, notif_type: str = "info", timeout: int = 8):
    """Send a desktop notification."""
    try:
        desktop_notify.notify(
            title=f"{APP_NAME} · {title}",
            message=message,
            app_name=APP_NAME,
            app_icon=APP_ICON,
            timeout=timeout,
        )
        _log_sent(title, message, notif_type)
        print(f"  [notif] {title}: {message}")
    except Exception as e:
        print(f"  [notif] Could not send desktop notification: {e}")
        print(f"  [notif] {title}: {message}")


def _log_sent(title: str, message: str, notif_type: str):
    state = _load_state()
    history = state.get("history", [])
    history.insert(0, {
        "title": title,
        "message": message,
        "type": notif_type,
        "sent_at": datetime.now().isoformat(),
        "read": False,
    })
    state["history"] = history[:50]  # keep last 50
    _save_state(state)


def get_history(limit: int = 20) -> list:
    state = _load_state()
    return state.get("history", [])[:limit]


def mark_all_read():
    state = _load_state()
    for item in state.get("history", []):
        item["read"] = True
    _save_state(state)


def unread_count() -> int:
    state = _load_state()
    return sum(1 for n in state.get("history", []) if not n.get("read"))


# ── Scheduled notification logic ──────────────────────────────────────────────

def _already_sent_today(key: str) -> bool:
    state = _load_state()
    sent_dates = state.get("sent_dates", {})
    return sent_dates.get(key) == date.today().isoformat()


def _mark_sent_today(key: str):
    state = _load_state()
    sent_dates = state.get("sent_dates", {})
    sent_dates[key] = date.today().isoformat()
    state["sent_dates"] = sent_dates
    _save_state(state)


def check_and_fire(config: dict = None):
    """
    Run all notification checks. Call this every minute from the scheduler.
    """
    if config is None:
        config = _load_config()

    if not config.get("enabled", True):
        return

    now = datetime.now()
    today = date.today()

    # 1. Morning daily reminder
    morning_hour = config.get("morning_hour", 9)
    if now.hour == morning_hour and now.minute < 5:
        if not _already_sent_today("morning"):
            send(
                "Good morning — time to prep!",
                "Your daily study brief is ready. Let's hit your targets today.",
                NotifType.DAILY_MORNING,
            )
            _mark_sent_today("morning")

    # 2. Evening coding session
    evening_hour = config.get("evening_hour", 18)
    if now.hour == evening_hour and now.minute < 5:
        if not _already_sent_today("evening"):
            send(
                "LeetCode time",
                "Your coding session is scheduled. 3 problems queued and ready.",
                NotifType.DAILY_EVENING,
            )
            _mark_sent_today("evening")

    # 3. Interview countdown
    interview_date_str = config.get("interview_date")
    if interview_date_str:
        try:
            interview_date = date.fromisoformat(interview_date_str)
            days_left = (interview_date - today).days

            for threshold, urgency in [(7, ""), (3, "⚠ "), (1, "🔴 ")]:
                key = f"countdown_{threshold}"
                if days_left == threshold and not _already_sent_today(key):
                    send(
                        f"{urgency}Interview in {days_left} day{'s' if days_left != 1 else ''}",
                        _countdown_message(days_left),
                        NotifType.COUNTDOWN,
                    )
                    _mark_sent_today(key)
                    break
        except ValueError:
            pass

    # 4. Job application deadlines
    for job in config.get("job_deadlines", []):
        try:
            deadline = date.fromisoformat(job["date"])
            days_left = (deadline - today).days
            key = f"deadline_{job.get('company', '')}_{job['date']}"

            if days_left in (3, 1, 0) and not _already_sent_today(key):
                urgency = "Today!" if days_left == 0 else f"In {days_left} day{'s' if days_left != 1 else ''}"
                send(
                    f"Application deadline: {job.get('company', 'Company')}",
                    f"{job.get('title', 'Role')} at {job.get('company', '')} — {urgency}",
                    NotifType.DEADLINE,
                )
                _mark_sent_today(key)
        except (ValueError, KeyError):
            pass


def _countdown_message(days_left: int) -> str:
    messages = {
        7: "One week to go. Focus on system design and hard LeetCode problems.",
        3: "3 days left. Wrap up your project and run a mock interview today.",
        1: "Tomorrow is the day. Review your notes, rest well tonight.",
    }
    return messages.get(days_left, f"{days_left} days to your interview. Stay focused.")


def notify_ai_fallback(from_engine: str, to_engine: str, reason: str):
    """Fire when the AI router switches engines."""
    send(
        f"AI switched to {to_engine.title()}",
        f"{from_engine.title()} {reason}. Seamlessly continuing with {to_engine.title()}.",
        NotifType.FALLBACK_ALERT,
        timeout=5,
    )


# ── Background scheduler thread ───────────────────────────────────────────────

_scheduler_running = False
_scheduler_thread: threading.Thread | None = None


def start_scheduler():
    """Start the notification scheduler in a background daemon thread."""
    global _scheduler_running, _scheduler_thread

    if _scheduler_running:
        return

    _scheduler_running = True

    def _loop():
        print("  [notifications] Scheduler started.")
        while _scheduler_running:
            try:
                check_and_fire()
            except Exception as e:
                print(f"  [notifications] Scheduler error: {e}")
            time.sleep(60)  # check every minute

    _scheduler_thread = threading.Thread(target=_loop, daemon=True)
    _scheduler_thread.start()


def stop_scheduler():
    global _scheduler_running
    _scheduler_running = False
    print("  [notifications] Scheduler stopped.")


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Sending test notifications...")

    send("Daily reminder", "Time to study — your plan is ready.", NotifType.DAILY_MORNING)
    time.sleep(1)

    send("Interview countdown", "7 days to go. Focus on system design.", NotifType.COUNTDOWN)
    time.sleep(1)

    send("Application deadline", "Flipkart Backend Engineer closes in 3 days!", NotifType.DEADLINE)

    print(f"\nUnread count: {unread_count()}")
    print("\nRecent history:")
    for n in get_history(5):
        print(f"  [{n['type']}] {n['title']}: {n['message']}")
