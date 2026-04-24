# SMS Bank Check Reminder

A lightweight Windows-friendly Python app that stores bank check records, calculates reminder dates, and sends SMS alerts **10, 3, and 1 day before** each check's due date. Uses SQLite for local persistence and Windows Task Scheduler for daily automated runs.

---

## Features

- Stores check records (title, due date, phone number) in a local SQLite database
- Sends SMS reminders at configurable offsets (default: 10, 3, 1 days before)
- Idempotent: duplicate sends are prevented via unique reminder logs
- Configurable missed-run catch-up policy (`SEND_MISSED_REMINDERS`)
- Pluggable SMS provider: Twilio or safe Mock mode for local testing
- Iran-ready: defaults to `Asia/Tehran` timezone with date-only comparisons
- CLI for database init, adding checks, listing checks, and manual run

---

## Project Structure

```
CheckReminder/
  requirements.txt
  README.md
  .env.example
  .gitignore
  src/
    __init__.py
    config.py
    db.py
    reminder_service.py
    sms_client.py
    scheduler_tick.py
    cli.py
  tests/
    __init__.py
    test_reminder_service.py
```

---

## Setup on Windows

### 1. Prerequisites

- Python 3.9+ (add to PATH during install)
- Git (optional)

### 2. Clone and set up

```cmd
git clone https://github.com/mamtech-A/CheckReminder.git
cd CheckReminder
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure `.env`

Copy `.env.example` to `.env` and fill in your values:

```cmd
copy .env.example .env
notepad .env
```

`.env` example:

```dotenv
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_FROM_NUMBER=+1234567890
TIMEZONE=Asia/Tehran
SMS_PROVIDER=twilio
DB_PATH=checkreminder.db
SEND_MISSED_REMINDERS=true
```

> **Security:** Never commit your `.env` file. It is listed in `.gitignore`.

### 4. Initialize the database

```cmd
python -m src.cli init-db
```

### 5. Add a check

```cmd
python -m src.cli add-check --title "Check #1234" --due-date 2025-06-01 --phone +989121234567
```

### 6. List checks

```cmd
python -m src.cli list-checks
```

### 7. Run manually

```cmd
python -m src.cli run-once
```

---

## Windows Task Scheduler Setup

Run the app automatically every morning:

1. Open **Task Scheduler** (search in Start menu)
2. Click **Create Basic Task…**
3. Name: `CheckReminder Daily`
4. Trigger: **Daily** at `09:00` (adjust to your preferred time)
5. Action: **Start a program**
   - Program: `C:\path\to\CheckReminder\.venv\Scripts\python.exe`
   - Arguments: `-m src.scheduler_tick`
   - Start in: `C:\path\to\CheckReminder`
6. In **Settings** tab:
   - ✅ Run task as soon as possible after a scheduled start is missed
   - ✅ If the task fails, restart every: 30 minutes, up to 3 times

---

## Timezone Policy

- Default timezone: **`Asia/Tehran`** (Iran Standard Time, UTC+3:30 / IRST/IRDT)
- All due dates are stored as plain `YYYY-MM-DD` strings
- Reminder date calculations use **local date comparisons only** (no UTC conversion)
- This avoids DST-related bugs around Iranian DST transitions

To change: set `TIMEZONE=Asia/Tehran` (or any valid IANA tz name) in `.env`.

---

## Missed-Run Behavior

Controlled by `SEND_MISSED_REMINDERS` in `.env`:

| Value | Behavior |
|-------|----------|
| `true` | If the app didn't run on a scheduled day, it will **catch up** and send any pending reminders from past offsets (up to today) that haven't been sent yet. Recommended for reliability. |
| `false` | Only sends reminders for offsets matching **today's date exactly**. Missed days are silently skipped. |

**Recommendation:** Use `true` on Windows where the machine may be off or sleeping.

---

## Running Tests

```cmd
pytest tests/ -v
```

---

## SMS Providers

| Provider | `SMS_PROVIDER` value | Notes |
|----------|---------------------|-------|
| Mock (no-op) | `mock` | Logs to console, no real SMS sent. Safe for dev/testing. |
| Twilio | `twilio` | Requires `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`. |

> **Iran note:** Twilio delivery to Iran numbers may be restricted. Consider using a local Iranian SMS gateway provider by implementing a custom `SmsClientBase` subclass in `sms_client.py`.

---

## License

MIT
