# CheckReminder

Minimal reminder app for bank checks with SQLite storage and SMS sending.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.cli init-db
python -m src.cli web-panel
```

Open `http://127.0.0.1:5000`.

## Required `.env` (SMS.ir legacy mode)

```dotenv
SMS_PROVIDER=smsir
SMSIR_USE_LEGACY_GET=true
SMSIR_USERNAME=your_smsir_username
SMSIR_API_KEY=your_smsir_api_key
SMSIR_LINE_NUMBER=your_smsir_line_number
DB_PATH=checkreminder.db
TIMEZONE=Asia/Tehran
SEND_MISSED_REMINDERS=true
```

## Core commands

```bash
python -m src.cli web-panel
python -m src.cli add-check --title "Check #1234" --amount 25000000 --due-date 2026-05-01 --phone 09356895959
python -m src.cli run-once
```

## Notes

- Adding a check now sends an immediate SMS confirmation.
- Scheduled reminders are sent on 10, 3, and 1 days before due date.
