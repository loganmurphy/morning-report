#!/usr/bin/env python3
"""Daily morning report: Oura + Strava → Claude → email via Resend."""

import getpass
import json
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path

import requests
import resend

CONFIG_PATH = Path(__file__).parent / "config.json"
OURA_BASE = "https://api.ouraring.com/v2/usercollection"
STRAVA_BASE = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
MAX_RETRIES = 3
RETRY_DELAY_SECS = 1800  # 30 minutes


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return run_setup_wizard()
    return json.loads(CONFIG_PATH.read_text())


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def read_dev_vars(path: Path) -> dict:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def run_setup_wizard() -> dict:
    print("\n=== Morning Report — First-time Setup ===\n")
    print("Credentials are saved to config.json (gitignored — keep it private).\n")

    config: dict = {}

    oura_vars = read_dev_vars(Path.home() / "Dev/oura-mcp-server/.dev.vars")
    strava_vars = read_dev_vars(Path.home() / "Dev/strava-mcp-server/.dev.vars")

    # Oura token
    default_oura = oura_vars.get("OURA_API_TOKEN", "")
    if default_oura:
        ans = input("Found Oura token in oura-mcp-server/.dev.vars — use it? [Y/n]: ").strip().lower()
        config["oura_token"] = default_oura if ans != "n" else input("Oura Personal Access Token: ").strip()
    else:
        config["oura_token"] = input("Oura Personal Access Token: ").strip()

    # Strava client credentials (ID + secret)
    default_id = strava_vars.get("STRAVA_CLIENT_ID", "")
    default_secret = strava_vars.get("STRAVA_CLIENT_SECRET", "")
    if default_id and default_secret:
        ans = input("Found STRAVA_CLIENT_ID + STRAVA_CLIENT_SECRET in strava-mcp-server/.dev.vars — use them? [Y/n]: ").strip().lower()
        if ans != "n":
            config["strava_client_id"] = default_id
            config["strava_client_secret"] = default_secret
        else:
            config["strava_client_id"] = input("Strava Client ID: ").strip()
            config["strava_client_secret"] = getpass.getpass("Strava Client Secret: ")
    else:
        config["strava_client_id"] = input("Strava Client ID: ").strip()
        config["strava_client_secret"] = getpass.getpass("Strava Client Secret: ")

    # Strava refresh token (written by pnpm connect-local)
    default_refresh = strava_vars.get("STRAVA_REFRESH_TOKEN", "")
    if default_refresh:
        ans = input("Found STRAVA_REFRESH_TOKEN in strava-mcp-server/.dev.vars — use it? [Y/n]: ").strip().lower()
        config["strava_refresh_token"] = default_refresh if ans != "n" else getpass.getpass("Strava Refresh Token: ")
    else:
        config["strava_refresh_token"] = getpass.getpass("Strava Refresh Token: ")

    config["strava_access_token"] = ""
    config["strava_token_expires_at"] = 0

    # Resend
    print("\nGet your Resend API key at resend.com/api-keys")
    config["resend_api_key"] = getpass.getpass("Resend API key: ")
    config["report_from"] = "reports@loganmurphy.dev"
    recipient = input("Send report to [loganmurphy1984@gmail.com]: ").strip()
    config["report_recipient"] = recipient or "loganmurphy1984@gmail.com"

    save_config(config)
    print("\n✓ Config saved. Run the script again to generate today's report.\n")
    return config


def get_strava_token(config: dict) -> str:
    if config.get("strava_access_token") and config.get("strava_token_expires_at", 0) > time.time() + 60:
        return config["strava_access_token"]

    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": config["strava_client_id"],
        "client_secret": config["strava_client_secret"],
        "refresh_token": config["strava_refresh_token"],
        "grant_type": "refresh_token",
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    config["strava_access_token"] = data["access_token"]
    config["strava_refresh_token"] = data["refresh_token"]
    config["strava_token_expires_at"] = data["expires_at"]
    save_config(config)
    return data["access_token"]


def fetch_oura(config: dict, endpoint: str, params: dict) -> dict:
    resp = requests.get(
        f"{OURA_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {config['oura_token']}"},
        params=params,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_strava_activities(config: dict, after_ts: int, before_ts: int) -> list:
    token = get_strava_token(config)
    resp = requests.get(
        f"{STRAVA_BASE}/athlete/activities",
        headers={"Authorization": f"Bearer {token}"},
        params={"after": after_ts, "before": before_ts, "per_page": 50},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def meters_to_miles(m: float) -> float:
    return round(m / 1609.34, 2)


def secs_to_min(s: int) -> int:
    return round(s / 60)


def build_prompt(today: date, sleep_data: dict, readiness_data: dict, spo2_data: dict, activities: list, sleep_week: dict, readiness_week: dict) -> str:
    yesterday = today - timedelta(days=1)
    monday = today - timedelta(days=today.weekday())

    for a in activities:
        a["_miles"] = meters_to_miles(a.get("distance", 0))
        a["_duration_min"] = secs_to_min(a.get("moving_time", 0))

    yesterday_acts = [a for a in activities if a.get("start_date_local", "").startswith(yesterday.isoformat())]
    week_summary = [
        {
            "day": a["start_date_local"][:10],
            "name": a["name"],
            "type": a["type"],
            "miles": a["_miles"],
            "duration_min": a["_duration_min"],
        }
        for a in activities
    ]
    yesterday_summary = [
        {
            "name": a["name"],
            "type": a["type"],
            "miles": a["_miles"],
            "duration_min": a["_duration_min"],
            "avg_hr": a.get("average_heartrate"),
            "avg_watts": a.get("average_watts"),
            "weighted_avg_watts": a.get("weighted_average_watts"),
            "trainer": a.get("trainer", False),
        }
        for a in yesterday_acts
    ]
    total_miles = sum(a["_miles"] for a in activities)

    sleep = (sleep_data.get("data") or [{}])[0]
    readiness = (readiness_data.get("data") or [{}])[0]
    spo2 = (spo2_data.get("data") or [{}])[0]

    sleep_trend = [
        {"date": d["day"], "score": d.get("score")}
        for d in (sleep_week.get("data") or [])
        if d.get("day") != today.isoformat()
    ]
    readiness_trend = [
        {"date": d["day"], "score": d.get("score")}
        for d in (readiness_week.get("data") or [])
        if d.get("day") != today.isoformat()
    ]

    return f"""Generate a morning health and training report as an HTML email fragment.
Output ONLY the HTML — no markdown fences, no explanation, no wrapper tags (<html>/<head>/<body>).
Use inline styles throughout. This renders inside a 600px white card in Gmail.

Font stack: system-ui, -apple-system, BlinkMacSystemFont, sans-serif.
Base text: #1a1a1a, 15px, line-height 1.6.

TODAY: {today.strftime("%A, %B %d %Y")}

--- RAW DATA ---

Sleep ({today.isoformat()}):
{json.dumps(sleep, indent=2)}

Readiness ({today.isoformat()}):
{json.dumps(readiness, indent=2)}

SpO2 ({today.isoformat()}):
{json.dumps(spo2, indent=2)}

Sleep trend this week (Mon–yesterday):
{json.dumps(sleep_trend, indent=2)}

Readiness trend this week (Mon–yesterday):
{json.dumps(readiness_trend, indent=2)}

Yesterday's activities ({yesterday.isoformat()}):
{json.dumps(yesterday_summary, indent=2)}

Week so far ({monday.strftime("%b %d")}–{today.strftime("%b %d")}):
{json.dumps(week_summary, indent=2)}
Total: {total_miles:.1f} mi across {len(activities)} activities

--- FORMAT ---

1. HEADER
   <h1> with "🌅 Morning Report — {today.strftime("%A, %B %d")}"
   Style: font-size:22px; font-weight:700; color:#1a1a1a; margin:0 0 24px 0; padding-bottom:16px; border-bottom:2px solid #f0f0f0

2. RECOVERY section
   <h2> "Recovery" — font-size:13px; font-weight:600; text-transform:uppercase; letter-spacing:0.08em; color:#6b7280; margin:0 0 16px 0
   Show readiness and sleep as two separate score blocks, each on its own line:
     Score block: flex row with align-items:baseline; gap:8px
       - Large number: font-size:32px; font-weight:700; line-height:1; color per threshold
       - Label: font-size:14px; color:#6b7280; margin-left:4px
     ≥85 → #16a34a (green), 70–84 → #d97706 (amber), <70 → #dc2626 (red)
     16px vertical gap between the two score blocks
   Contributors: each on its own line below the scores, 12px top margin
     Format: "Label — value" in 14px; label in #6b7280, value color-coded by threshold
     Show 2–3 most notable (notably high or low only)
   SpO₂ avg on its own line at 14px if available

3. SLEEP & READINESS TREND section ({monday.strftime("%b %d")}–{today.strftime("%b %d")})
   <h2> same style
   Compact table or row-per-day layout: one row per day with date abbreviation (Mon, Tue…), sleep score, readiness score
   Color-code each score inline using the same thresholds (≥85 green, 70–84 amber, <70 red)
   Today's row highlighted with a subtle background (#f8fafc) and bold text
   Skip days with no data (e.g. Monday if today is Monday)

4. YESTERDAY'S TRAINING section
   <h2> same style as above
   If no activity: "Rest day" in #6b7280
   If activity exists, render the stat block exactly like this structure:
     <div style="font-weight:700;font-size:16px;margin-bottom:10px;">Activity Name</div>
     <div style="display:block;margin-bottom:6px;font-size:14px;"><span style="color:#6b7280;">Distance</span> &nbsp; <span style="color:#1a1a1a;">X.X mi</span></div>
     <div style="display:block;margin-bottom:6px;font-size:14px;"><span style="color:#6b7280;">Duration</span> &nbsp; <span style="color:#1a1a1a;">XX min</span></div>
     <div style="display:block;margin-bottom:6px;font-size:14px;"><span style="color:#6b7280;">Avg HR</span> &nbsp; <span style="color:#1a1a1a;">XXX bpm</span></div>  (if available)
     <div style="display:block;margin-bottom:6px;font-size:14px;"><span style="color:#6b7280;">Avg Power</span> &nbsp; <span style="color:#1a1a1a;">XXX W</span></div>  (if available)
     <div style="display:block;margin-bottom:6px;font-size:14px;"><span style="color:#6b7280;">Normalized Power</span> &nbsp; <span style="color:#1a1a1a;">XXX W</span></div>  (if available — never abbreviate as NP)
     <div style="display:block;margin-bottom:6px;font-size:14px;"><span style="color:#6b7280;">Location</span> &nbsp; <span style="color:#1a1a1a;">Indoor / Outdoor</span></div>
   Each stat MUST be its own <div> with display:block — never put multiple stats in one element

5. WEEK SO FAR section ({monday.strftime("%b %d")}–{today.strftime("%b %d")})
   <h2> same style
   Total miles + activity count as a summary line
   Compact bullet list: each activity on one line — "Mon · Run · 3.2 mi · 28 min"
   Day abbreviation from the date field

6. VERDICT
   <h2> same style
   Two sentences in a lightly styled box: background:#f8fafc; border-left:3px solid #3b82f6; padding:12px 16px; border-radius:0 6px 6px 0
   Sentence 1: recovery status based on readiness score
   Sentence 2: concrete training recommendation (≥85: quality work; 70–84: moderate effort; <70: easy or rest)

Spacing between sections: margin-bottom:28px on each section div.
No horizontal rules between sections except the one under the header.
"""


def generate_report(prompt: str) -> str:
    claude_bin = Path.home() / ".local/bin/claude"
    result = subprocess.run(
        [str(claude_bin), "-p", prompt],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error: {result.stderr.strip()}")
    html = result.stdout.strip()
    # Strip markdown code fences if Claude wrapped the output anyway
    if html.startswith("```"):
        html = "\n".join(html.split("\n")[1:])
    if html.endswith("```"):
        html = "\n".join(html.split("\n")[:-1])
    return html.strip()


def send_email(config: dict, html_fragment: str, subject: str) -> None:
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px 16px;background-color:#f3f4f6;font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:12px;padding:32px;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
    {html_fragment}
  </div>
</body>
</html>"""

    resend.api_key = config["resend_api_key"]
    resend.Emails.send({
        "from": config["report_from"],
        "to": config["report_recipient"],
        "subject": subject,
        "html": full_html,
    })


def main() -> None:
    config = load_config()

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    monday_ts = int(time.mktime(monday.timetuple()))
    tomorrow_ts = int(time.mktime((today + timedelta(days=1)).timetuple()))

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"[{today}] Fetching Oura data (attempt {attempt}/{MAX_RETRIES})...")

        sleep_data = fetch_oura(config, "daily_sleep", {"start_date": today.isoformat(), "end_date": today.isoformat()})

        if not sleep_data.get("data"):
            if attempt < MAX_RETRIES:
                print(f"  Sleep data not ready. Retrying in 30 minutes...")
                time.sleep(RETRY_DELAY_SECS)
                continue
            else:
                print("  Sleep data unavailable after all retries — sending partial report.")

        readiness_data = fetch_oura(config, "daily_readiness", {"start_date": today.isoformat(), "end_date": today.isoformat()})
        spo2_data = fetch_oura(config, "daily_spo2", {"start_date": today.isoformat(), "end_date": today.isoformat()})
        sleep_week = fetch_oura(config, "daily_sleep", {"start_date": monday.isoformat(), "end_date": today.isoformat()})
        readiness_week = fetch_oura(config, "daily_readiness", {"start_date": monday.isoformat(), "end_date": today.isoformat()})
        activities = fetch_strava_activities(config, monday_ts, tomorrow_ts)

        print("  Generating report via Claude...")
        prompt = build_prompt(today, sleep_data, readiness_data, spo2_data, activities, sleep_week, readiness_week)
        html_fragment = generate_report(prompt)

        subject = f"🌅 Morning Report — {today.strftime('%A, %B %d')}"
        print(f"  Sending to {config['report_recipient']}...")
        send_email(config, html_fragment, subject)

        print("  ✓ Report sent.")
        break


if __name__ == "__main__":
    main()
