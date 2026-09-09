# (=^･ω･^=) CourseCat

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![SUSTech](https://img.shields.io/badge/SUSTech-TIS-8f000b)](https://tis.sustech.edu.cn)
[![CI](https://github.com/WilloTwisper/SUSTech-CourseCat/actions/workflows/test.yml/badge.svg)](https://github.com/WilloTwisper/SUSTech-CourseCat/actions)

[中文](./README.md) | **English**

A serial, rate-limit compliant course enrollment helper for SUSTech TIS
([tis.sustech.edu.cn](https://tis.sustech.edu.cn)), ready to use out of the box. A complete
rewrite of [SUSTech_Tools](https://github.com/GhostFrankWu/SUSTech_Tools) and
[SUSTech-tis-cheater](https://github.com/vollate/SUSTech-tis-cheater), which broke after
the Fall 2026 TIS changes (see their issue #36). Rebuilt around a configurable adapter
layer + mock rehearsal + precise scheduling — when TIS changes again, only config needs
updating, no code reading required.

> **If it helps, please ⭐ Star and recommend it to friends** (one-click share in the Web footer).
> For personal study and research only. You are responsible for your own actions;
> make sure they comply with school regulations and applicable laws (see disclaimer below).

## Design principles (speed vs. limits)

The school's limits are hard constraints: **per-user rate limiting, request interval ≥1500ms
(observed 2024-09), every valid request refreshes the limit window**. Flooding with
concurrency only gets 429s — slower, not faster. So all engineering goes into
"making every allowed request count":

| Optimization | Notes |
| --- | --- |
| Strict serial + single connection | `httpx` single keep-alive connection + HTTP/2, never trips limits with concurrency |
| Precise pacing | `perf_counter`-based scheduler, zero accumulated drift |
| 429 adaptive backoff | Doubles interval on limits (up to 16×), recovers to baseline |
| Scheduled grab | `--at HH:MM:SS` with optional SNTP clock sync (`--use-ntp`), first request lands on the millisecond |
| Warm-up | TLS/HTTP2 handshake + session check done before T0, T0 is pure enrollment |
| Pre-encoded payloads | Form encoded once at startup, zero serialization in the hot loop |
| Strict priority | Lower-priority courses untouched until higher ones succeed/skip; failures logged for review |
| Result classification | Success/enrolled/conflict/full/not-open/rate-limited/expired-session drive different strategies |

**Explicitly not done**: multithreading/multi-account/proxy pools, UA spoofing or traffic
obfuscation, captcha bypassing, breaking interval limits. Honest UA, same traffic volume as
manual enrollment.

## Install (pick one)

**Option 1: one click (recommended)** — download the repo ZIP, unzip, double-click:

- `启动抢课猫-Web.bat` → installs env and opens the Web UI
- `启动抢课猫-TUI.bat` → fullscreen terminal UI

**Option 2: install from GitHub:**

```powershell
pip install "git+https://github.com/WilloTwisper/SUSTech-CourseCat.git"
coursecat-web
```

**Option 3: from source:**

```powershell
git clone https://github.com/WilloTwisper/SUSTech-CourseCat.git
cd SUSTech-CourseCat
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Optional: Windows desktop notifications via `pip install winotify`.

## Step zero: rehearse first (strongly recommended)

Built-in mock TIS server (MOCK-101 always succeeds / MOCK-102 always conflicts /
MOCK-103 succeeds on 3rd try / MOCK-104 always full / MOCK-105 429s twice then succeeds):

```powershell
copy courses.example.txt courses.txt
.venv\Scripts\coursecat --rehearse --courses courses.txt --report report.json
```

Zero external requests to verify: session detection, priority order, conflict/full skips,
429 backoff, report output.

## One-click usage (recommended)

**Web UI (same style as the TIS page, recommended):**

```powershell
.venv\Scripts\coursecat-web
```

Opens `http://127.0.0.1:8766/` (localhost only): crimson header, category tabs
(Enrolled/GenEd Required/GenEd Electives/In-Program…), full course table with
codes/credits/hours/schedule/capacity, green enroll buttons — mirroring the TIS page.
Grab console on top: priority queue (↑↓×), mode (now/scheduled/waitlist),
interval, full-rotation, start/stop, live log, banner + beep on success.
Click 🌙 for dark mode, EN for English (Chinese by default).

```powershell
.venv\Scripts\coursecat-web --port 8766 --no-browser   # custom port / no auto-open
```

**Fullscreen TUI (no flags to memorize):**

```powershell
.venv\Scripts\coursecat-tui
```

**CLI wizard:**

```powershell
.venv\Scripts\coursecat
```

**Bare command = one-click wizard**: no cookies → auto browser login (isolated temp
profile, deleted after capture); no course list → interactive picker; then pick a mode
(now/scheduled/waitlist/rehearse) and go.

Step-by-step commands:

| Command | Purpose |
| --- | --- |
| `coursecat --login` | Auto login via Edge/Chrome, captures TIS session into `cookies.txt` (captcha/2FA friendly, real browser) |
| `coursecat --pick` | Interactive picker: keyword search + live seats (left/capacity), priority order, writes `courses.txt` |
| `coursecat` | Wizard mode chaining everything above |

Smart defaults: `*.sustech.edu.cn` bypasses system proxies automatically;
expired sessions trigger a one-click re-login prompt.

Interactive details (modern TUI, `rich` + `prompt_toolkit`, plain-text fallback):

- Picker completes as you type (with seats), arrow keys, Enter to add, queue preview at bottom
- Scheduled grabs show a live countdown panel; high-precision wait for the last 3s
- Success pops a green panel + beep + (optional) desktop notification/webhook
- **Ctrl+C semantics**: first press = graceful stop (finishes current beat, prints summary),
  second press during summary = force quit; cancels wizard/scheduled waits, **never starts a grab by accident**

## Real flow

### 1. Import login state (pick one)

| Method | Command | Notes |
| --- | --- | --- |
| Cookie file (recommended) | `--cookies cookies.txt` | Three formats: Netscape cookies.txt, Chrome/Fiddler `.har`, or raw pasted `Cookie:` header |
| Inline | `--cookie SESSION=xxx` | Repeatable |
| CAS account (experimental) | `--cas-login` | Password in memory only, never saved; captchas/CAS changes fall back to browser path with a clear error |

> Get cookies: log into TIS in browser → F12 → Network → any XHR request → copy the
> `Cookie:` request header into `cookies.txt` (first line `Cookie: ...` is recognized).
> Works the same if TIS switches to a single cookie (e.g. `SESSION`), no hardcoding.

### 2. Find exact course names into courses.txt

```powershell
.venv\Scripts\coursecat --cookies cookies.txt --list data
# write wanted "task names" into courses.txt, one per line, highest priority first
```

### 3a. Grab now

```powershell
.venv\Scripts\coursecat --cookies cookies.txt --courses courses.txt --interval-ms 1600
```

Interactive while running (foreground TTY): Enter or `s` = skip current course; `q` = stop. Ctrl+C also stops safely.

### 3b. Scheduled grab (the moment enrollment opens)

```powershell
.venv\Scripts\coursecat --cookies cookies.txt --courses courses.txt --at 10:00:00 --use-ntp
```

- `--use-ntp` calibrates the local clock via SNTP (UDP/123), prints offset in ms
- Second warm-up 2s before T0, first enrollment request fires exactly at T0
- If T0 returns "not open", retries continue on beat to catch the opening window

### 4. Common variants

| Goal | Flags |
| --- | --- |
| Wait for drops on full courses | `--retry-full` (FULL keeps retrying instead of skipping) |
| Grab backups while waiting | `--retry-full --cascade` (full courses rotate to the back, backups never starve) |
| Confirm conflicts manually | `--no-auto-skip` |
| Submit to cart only | `--submit-target rwtjzgwc` |
| Next-day schedule | `--at "2026-09-08 10:00:00"` (`--at 10:00` also works for today) |
| Broken semester-start certs | `--tls-no-verify` (emergency only) |
| Success push | `--webhook https://...` (POSTs `{"content": ...}`, Discord/Bark/WeCom compatible) |

### 5. Rush-day tactics (first-come-first-served / scheduled batch releases)

- Displayed "seats left" is a catalog snapshot that goes stale in seconds during rush;
  **the only truth is each server verdict**. On FULL with cached seats left, the log
  prints a quota snapshot for post-mortem.
- If drops are released in batches at fixed times (e.g. daily 13:00), enter 2s early
  so the request stream crosses the release point:

```powershell
.venv\Scripts\coursecat --cookies cookies.txt --courses courses.txt `
  --at "2026-09-09 12:59:58" --use-ntp --retry-full --cascade --report report.json
```

- `--use-ntp` clock sync is critical: 1s off either way can miss the whole batch
- Full with no release window in sight → `--retry-full` waiting is pointless, save power

### Ops

- Every run writes `logs/run_YYYYmmdd_HHMMSS.log` (per-request details);
  `--report report.json` adds full attempt records (course/status/message/latency/timestamp)
- Picker: type `r` to refresh live seats for the current list (per-category queries, rate-limit protected)
- Catalog cache older than 12h triggers a refresh prompt (seat snapshots expire)
- Session dying mid waitlist run: automatic "re-login in browser and continue?" prompt (max 3), remaining queue preserved

## If TIS changes again (issue #36 class)

1. Log into browser → F12 → Network, replay one enrollment click
2. Compare `[endpoints]`: paths changed → edit `config.toml`; form fields changed → edit
   `src/enroll_helper/tis/client.py::build_enroll_body`
3. Response fields changed (`jg`/`message`) → edit `[keywords]` and `parser.classify`
4. Run `--rehearse` to verify end-to-end, then go live

Missing semester info, non-JSON responses etc. surface as explicit Chinese errors with
checkpoints (never silent crashes).

## Project structure

```
src/enroll_helper/
├── cli.py            # CLI orchestration: session→semester→catalog→queue→(timed)→engine→report
├── config.py         # TOML/JSON config + CLI overrides + interval floor enforcement
├── engine.py         # serial enrollment engine: strict priority/state machine/interactive skip/stats
├── pacer.py          # drift-free pacer + 429 penalize/recover
├── clocksync.py      # SNTP calibration + precise waiting
├── session.py        # cookie import (Netscape/HAR/raw header) + httpx client factory
├── cas.py            # experimental CAS login (in-memory credentials, never saved)
├── login.py          # one-click login: launches real browser, captures session via CDP
├── picker.py         # interactive picker: search/seats/priority queue
├── schedule.py       # class-time parsing + conflict detection (odd/even weeks, days, periods)
├── tis/              # adapter layer: endpoints/models/parser/client
├── tui.py            # terminal output layer (rich/prompt_toolkit, plain-text fallback)
├── tui_app.py        # fullscreen TUI (textual): queue/settings/log/add-course modal
├── webserver.py      # web backend (stdlib only): REST + event stream
├── web/              # web frontend: single-page app mirroring the TIS page (zh/en toggle)
├── notify.py         # beep/Windows notification/webhook/JSON report
└── mockserver.py     # mock TIS (rehearsal + dual testing use)
tests/                # 60+ unit and integration tests (pytest)
```

## FAQ

| Symptom | Cause / fix |
| --- | --- |
| `查询请求频率过高` / `jg=-1` | Separate rate limit on the query API (stricter than enrollment). The tool backs off and retries automatically; wait it out, **don't** run multiple instances |
| Session suspected expired / login page | SESSION expired: `coursecat --login` or Re-login in Web UI |
| Empty catalog / course not found | Hit Refresh first (~30s first time); check semester |
| System proxy/TUN breaks connections | `*.sustech.edu.cn` bypasses env proxies by default; TUN intercepts at NIC level — add the domain to DIRECT rules |
| Red names in `冲突课程` column | Time conflict with your enrolled courses; turn on Hide-conflicts to hide them |
| Suspect another TIS revamp | Run `--doctor` for the contract check, then follow the section above |

## Disclaimer

For personal study and research only. You are responsible for your own actions; make sure
they comply with school regulations and applicable laws. This tool circumvents no security
mechanisms and guarantees nothing; the author is not liable for bans or other consequences.
Request strategy and pacing are kept at manual-enrollment scale — do not modify the code to
exceed limits; that breaks rules and empirically runs slower.
