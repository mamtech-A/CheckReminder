"""Local Flask web panel for CheckReminder."""

import re
from datetime import date

from flask import Flask, flash, redirect, render_template_string, request, url_for

from .config import load_settings
from .db import add_check, delete_check, get_check, get_connection, init_db, list_checks, update_check
from .reminder_service import build_added_check_message
from .sms_client import SmsDeliveryError, _mask_phone, build_sms_client

try:
    import jdatetime
except ImportError:  # pragma: no cover - optional dependency fallback
    jdatetime = None

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>CheckReminder Panel</title>
  <style>
    body { margin: 0; font-family: Segoe UI, sans-serif; background: #f5f7fb; color: #102038; }
    .wrap { max-width: 1100px; margin: 24px auto; padding: 0 16px; display: grid; gap: 16px; }
    .card { background: #fff; border: 1px solid #d9e2ec; border-radius: 14px; padding: 18px; box-shadow: 0 6px 24px rgba(15,23,42,.06); }
    h1, h2 { margin: 0 0 12px; }
    .sub { margin: 0; color: #4b5a73; }
    .msg { border-radius: 10px; padding: 10px; margin-bottom: 8px; }
    .ok { background: #ecfdf3; color: #027a48; border: 1px solid #abefc6; }
    .err { background: #fef3f2; color: #b42318; border: 1px solid #fecdca; }
    form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .full { grid-column: 1 / -1; }
    label { display:block; margin-bottom: 6px; color:#4b5a73; font-size: .85rem; }
    input, textarea, button, a.btn { width:100%; box-sizing:border-box; border-radius:10px; padding:10px; font: inherit; }
    input, textarea { border: 1px solid #d9e2ec; }
    textarea { min-height: 84px; resize: vertical; }
    button, a.btn { display:inline-block; border: none; background:#0d8b8d; color:#fff; text-decoration:none; text-align:center; cursor:pointer; }
    button:hover, a.btn:hover { background:#0b6c6e; }
    .btns { display:flex; gap:8px; }
    table { width:100%; border-collapse: collapse; }
    th, td { padding: 9px; border-bottom: 1px solid #d9e2ec; text-align:left; }
    th { font-size:.82rem; color:#4b5a73; text-transform:uppercase; }
    @media (max-width: 760px) { form { grid-template-columns: 1fr; } .btns { flex-direction: column; } }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="card">
      <h1>CheckReminder Web Panel</h1>
      <p class="sub">Add, edit, and delete checks from the browser.</p>
    </section>

    <section class="card">
      {% for category, message in messages %}
        <div class="msg {{ 'ok' if category == 'success' else 'err' }}">{{ message }}</div>
      {% endfor %}

      <h2>{{ 'Edit Check' if edit_check else 'Add Check' }}</h2>
      <form method="post" action="{{ url_for('edit_check_view', check_id=edit_check['id']) if edit_check else url_for('add_check_view') }}">
        <div>
          <label for="title">Title</label>
          <input id="title" name="title" required value="{{ edit_check['title'] if edit_check else '' }}" placeholder="Check #1234">
        </div>
        <div>
          <label for="due_date">Due Date (Jalali YYYY-MM-DD)</label>
          <input id="due_date" name="due_date" required value="{{ format_input_date(edit_check['due_date']) if edit_check else '' }}" placeholder="1405-02-05">
        </div>
        <div>
          <label for="phone">Phone</label>
          <input id="phone" name="phone" required value="{{ edit_check['phone_number'] if edit_check else '' }}" placeholder="+989121234567">
        </div>
        <div>
          <label for="amount">Amount</label>
          <input id="amount" name="amount" value="{{ edit_check['amount'] if edit_check else '' }}" placeholder="25000000">
        </div>
        <div>
          <label for="description">Description</label>
          <textarea id="description" name="description" placeholder="Optional notes">{{ edit_check['description'] if edit_check and edit_check['description'] else '' }}</textarea>
        </div>
        <div class="full btns">
          <button type="submit">{{ 'Save Changes' if edit_check else 'Add Check' }}</button>
          {% if edit_check %}
            <a class="btn" href="{{ url_for('index') }}">Cancel</a>
          {% endif %}
        </div>
      </form>
    </section>

    <section class="card">
      <h2>Checks</h2>
      {% if rows %}
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Title</th><th>Due Date</th><th>Phone</th><th>Amount</th><th>Description</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for row in rows %}
          <tr>
            <td>{{ row['id'] }}</td>
            <td>{{ row['title'] }}</td>
            <td title="{{ row['due_date'] }}">{{ format_display_date(row['due_date']) }}</td>
            <td>{{ mask_phone(row['phone_number']) }}</td>
            <td>{{ row['amount'] or '-' }}</td>
            <td>{{ row['description'] or '-' }}</td>
            <td>
              <div class="btns">
                <a class="btn" href="{{ url_for('edit_check_view', check_id=row['id']) }}">Edit</a>
                <form method="post" action="{{ url_for('delete_check_view', check_id=row['id']) }}" onsubmit="return confirm('Delete this check?');">
                  <button type="submit">Delete</button>
                </form>
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
        <p class="sub">No checks yet. Add one from the form above.</p>
      {% endif %}
    </section>
  </div>
</body>
</html>
"""


def _validate_date(value: str) -> str:
    if not _DATE_RE.match(value):
        raise ValueError("Date must be in YYYY-MM-DD format")
    year, month, day = map(int, value.split("-"))

    if jdatetime is None:
        date.fromisoformat(value)
        return value

    try:
        jalali_date = jdatetime.date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"Invalid Jalali date: {exc}") from exc

    return jalali_date.togregorian().isoformat()


def _validate_phone(value: str) -> str:
    cleaned = value.strip()
    if not _PHONE_RE.match(cleaned):
        raise ValueError("Phone must be in E.164 style, e.g. +989121234567")
    return cleaned


def _format_display_date(value: str) -> str:
    """Render stored ISO dates in the Persian calendar for the table."""
    if jdatetime is None:
        return value

    gregorian_date = date.fromisoformat(value)
    return jdatetime.date.fromgregorian(date=gregorian_date).strftime("%Y/%m/%d")


def _format_input_date(value: str) -> str:
    """Render stored ISO dates as Jalali values for form fields."""
    if jdatetime is None:
        return value

    gregorian_date = date.fromisoformat(value)
    return jdatetime.date.fromgregorian(date=gregorian_date).strftime("%Y-%m-%d")


def create_app() -> Flask:
    settings = load_settings()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "checkreminder-dev-key"

    def _open_conn():
        conn = get_connection(settings.db_path)
        init_db(conn)
        return conn

    def _render(edit_check=None):
        conn = _open_conn()
        try:
            rows = list_checks(conn, active_only=True)
        finally:
            conn.close()
        from flask import get_flashed_messages

        return render_template_string(
            PAGE_TEMPLATE,
            rows=rows,
            edit_check=edit_check,
            messages=get_flashed_messages(with_categories=True),
            mask_phone=_mask_phone,
            format_display_date=_format_display_date,
            format_input_date=_format_input_date,
        )

    @app.get("/")
    def index():
        return _render()

    @app.post("/add")
    def add_check_view():
        title = request.form.get("title", "").strip()
        due_date_input = request.form.get("due_date", "").strip()
        phone = request.form.get("phone", "").strip()
        amount = request.form.get("amount", "").strip()
        description = request.form.get("description", "").strip()

        if not title:
            flash("Title is required", "error")
            return redirect(url_for("index"))

        try:
            due_date = _validate_date(due_date_input)
            phone = _validate_phone(phone)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("index"))

        conn = _open_conn()
        try:
            add_check(
                conn,
                title=title,
                due_date=due_date,
                phone_number=phone,
                amount=amount,
                description=description,
            )

            sms_client = build_sms_client(settings)
            immediate_body = build_added_check_message(title=title, amount=amount, due_date=due_date)
            try:
                message_id = sms_client.send_sms(phone, immediate_body)
                flash(f"Check added and immediate SMS sent. message_id={message_id}", "success")
            except SmsDeliveryError as exc:
                flash(f"Check added, but immediate SMS failed: {exc}", "error")
        finally:
            conn.close()

        return redirect(url_for("index"))

    @app.get("/edit/<int:check_id>")
    def edit_check_page(check_id: int):
        conn = _open_conn()
        try:
            check = get_check(conn, check_id)
        finally:
            conn.close()
        if check is None:
            flash("Check not found", "error")
            return redirect(url_for("index"))
        return _render(edit_check=check)

    @app.post("/edit/<int:check_id>")
    def edit_check_view(check_id: int):
        title = request.form.get("title", "").strip()
        due_date_input = request.form.get("due_date", "").strip()
        phone = request.form.get("phone", "").strip()
        amount = request.form.get("amount", "").strip()
        description = request.form.get("description", "").strip()

        if not title:
            flash("Title is required", "error")
            return redirect(url_for("edit_check_page", check_id=check_id))

        try:
          due_date = _validate_date(due_date_input)
          phone = _validate_phone(phone)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("edit_check_page", check_id=check_id))

        conn = _open_conn()
        try:
            if get_check(conn, check_id) is None:
                flash("Check not found", "error")
                return redirect(url_for("index"))
            update_check(
                conn,
                check_id=check_id,
                title=title,
                due_date=due_date,
                phone_number=phone,
                amount=amount,
                description=description,
            )
            flash("Check updated successfully", "success")
        finally:
            conn.close()

        return redirect(url_for("index"))

    @app.post("/delete/<int:check_id>")
    def delete_check_view(check_id: int):
        conn = _open_conn()
        try:
            if get_check(conn, check_id) is None:
                flash("Check not found", "error")
            else:
                delete_check(conn, check_id)
                flash("Check deleted successfully", "success")
        finally:
            conn.close()
        return redirect(url_for("index"))

    return app


def run_web_panel(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    app = create_app()
    app.run(host=host, port=port, debug=debug)
