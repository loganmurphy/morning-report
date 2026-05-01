# morning-report

Daily health and training digest — Oura + Strava data, analysed by Claude, delivered to your inbox. Runs on macOS via launchd at 8:30 AM.

## Report sections

- **Recovery** — readiness and sleep scores, top contributors, SpO₂
- **Trend** — sleep and readiness scores day-by-day for the current week
- **Yesterday** — activity name, distance, duration, HR, power
- **Week so far** — compact activity list with totals
- **Verdict** — training recommendation based on recovery score

## Setup

```bash
pip3 install requests resend
python3 scripts/morning_report.py
```

First run launches a setup wizard. It auto-detects credentials from the sibling MCP server repos if they're present on disk.

### Scheduling

Schedule a daily hardware wake at 8:55 AM so the Mac is up when launchd fires the job at 9:00:

```bash
sudo pmset repeat wake MTWRFSU 08:55:00
```

Install the launchd job:

```bash
cp com.yourname.morning-report.plist.example com.yourname.morning-report.plist
# edit: replace yourname + paths with your own
launchctl load ~/Library/LaunchAgents/com.yourname.morning-report.plist
```

The Mac returns to sleep on its own after the report finishes, based on your normal Energy Saver timeout. Logs → `logs/`.

## Dependencies

- Python 3 (pre-installed on macOS)
- [Claude Code CLI](https://claude.ai/code) — `claude` on PATH, logged in
- [Resend](https://resend.com) account + API key (free tier, verified domain for custom from address)
- [Oura](https://ouraring.com) Personal Access Token
- [Strava](https://strava.com) API application credentials

## Related

- [oura-mcp-server](https://github.com/loganmurphy/oura-mcp-server) — Oura Ring sleep, readiness, and activity data as MCP tools for Claude
- [strava-mcp-server](https://github.com/loganmurphy/strava-mcp-server) — Strava training data as MCP tools for Claude
