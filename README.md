# morning-report

A daily morning report combining Oura sleep/recovery data and Strava training data, analysed by Claude and delivered to your inbox via [Resend](https://resend.com).

Runs on your Mac via launchd — no server required.

## What's in the report

- **Recovery** — readiness and sleep scores with color coding, top contributors, SpO₂
- **Sleep & readiness trend** — day-by-day scores for the current week
- **Yesterday's training** — activity name, distance, duration, HR, power
- **Week so far** — compact activity list with totals
- **Verdict** — one-paragraph training recommendation based on recovery

## Requirements

- macOS (launchd scheduling)
- Python 3 (`/usr/bin/python3` — pre-installed on macOS)
- [Oura Ring](https://ouraring.com) with a Personal Access Token
- [Strava](https://strava.com) API application
- [Resend](https://resend.com) account + verified sending domain
- [Claude Code CLI](https://claude.ai/code) (`claude` on PATH, logged in)

## Setup

```bash
pip3 install requests resend
cd scripts
python3 morning_report.py   # first run triggers the setup wizard
```

The wizard auto-detects credentials from sibling MCP server repos if present:
- `~/Dev/oura-mcp-server/.dev.vars` → Oura token
- `~/Dev/strava-mcp-server/.dev.vars` → Strava client ID, secret, and refresh token

### Scheduling with launchd

Copy the plist to `~/Library/LaunchAgents/` and load it:

```bash
cp com.loganmurphy.morning-report.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.loganmurphy.morning-report.plist
```

Fires at **8:30 AM daily**. Retries every 30 minutes (up to 3 attempts) if sleep data hasn't synced yet.

Logs → `~/Dev/automation/logs/`

## Related

- [oura-mcp-server](https://github.com/loganmurphy/oura-mcp-server) — Oura Ring data as MCP tools for Claude
- [strava-mcp-server](https://github.com/loganmurphy/strava-mcp-server) — Strava data as MCP tools for Claude
