import os
import logging
import asyncio
from datetime import datetime, date
from flask import Flask, render_template_string
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "0").split(",") if x.strip()]
PORT = int(os.environ.get("PORT", 8080))
MAX_LEAVES = 2  # leaves per month

DB_FILE = "attendance.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f:
            return json.load(f)
    return {"users": {}, "attendance": {}}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def today_key():
    return date.today().isoformat()

def month_key():
    return date.today().strftime("%Y-%m")

# --- BOT HANDLERS ---

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    uid = str(user.id)
    if uid not in db["users"]:
        db["users"][uid] = {"name": user.first_name, "username": user.username or ""}
        save_db(db)
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\nWelcome to *TinkerHub Attendance Bot*.\n\n"
        "Commands:\n"
        "✅ /attend — Mark today's attendance\n"
        "📊 /balance — Check your leave balance\n"
        "📋 /report — Today's report (admin only)\n"
        "👥 /monthly — Monthly summary (admin only)",
        parse_mode="Markdown"
    )

async def attend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("✅ Present", callback_data="attend_present"),
            InlineKeyboardButton("🏖️ Leave", callback_data="attend_leave"),
        ]
    ]
    await update.message.reply_text(
        f"📅 *{date.today().strftime('%A, %d %B %Y')}*\n\nMark your attendance for today:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    uid = str(user.id)
    data = query.data
    db = load_db()

    if uid not in db["users"]:
        db["users"][uid] = {"name": user.first_name, "username": user.username or ""}

    tk = today_key()
    mk = month_key()

    if "attendance" not in db:
        db["attendance"] = {}
    if tk not in db["attendance"]:
        db["attendance"][tk] = {}

    status = "present" if data == "attend_present" else "leave"
    db["attendance"][tk][uid] = {"status": status, "time": datetime.now().strftime("%H:%M")}
    save_db(db)

    if status == "present":
        await query.edit_message_text(f"✅ *Present* marked for today!\n\nHave a great day, {user.first_name}! 🚀", parse_mode="Markdown")
    else:
        # count leaves this month
        leaves = sum(
            1 for day_data in db["attendance"].values()
            if uid in day_data and day_data[uid]["status"] == "leave"
            and day_data.get == mk or True  # simplified count
        )
        # proper count
        leaves = 0
        for dk, day_data in db["attendance"].items():
            if dk.startswith(mk) and uid in day_data and day_data[uid]["status"] == "leave":
                leaves += 1
        remaining = max(0, MAX_LEAVES - leaves)
        await query.edit_message_text(
            f"🏖️ *Leave* marked for today.\n\nLeaves used this month: *{leaves}/{MAX_LEAVES}*\nRemaining: *{remaining}*",
            parse_mode="Markdown"
        )

async def balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    mk = month_key()
    db = load_db()
    leaves = 0
    for dk, day_data in db["attendance"].items():
        if dk.startswith(mk) and uid in day_data and day_data[uid]["status"] == "leave":
            leaves += 1
    remaining = max(0, MAX_LEAVES - leaves)
    await update.message.reply_text(
        f"📊 *Your Leave Balance — {date.today().strftime('%B %Y')}*\n\n"
        f"Leaves used: *{leaves}/{MAX_LEAVES}*\n"
        f"Remaining: *{remaining}*",
        parse_mode="Markdown"
    )

async def report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only command.")
        return
    db = load_db()
    tk = today_key()
    day_data = db["attendance"].get(tk, {})
    if not day_data:
        await update.message.reply_text(f"📋 No attendance marked yet for today ({tk}).")
        return
    lines = [f"📋 *Attendance Report — {date.today().strftime('%d %B %Y')}*\n"]
    present, leave = 0, 0
    for uid, rec in day_data.items():
        name = db["users"].get(uid, {}).get("name", f"User {uid}")
        icon = "✅" if rec["status"] == "present" else "🏖️"
        lines.append(f"{icon} {name} — {rec['status'].title()} ({rec['time']})")
        if rec["status"] == "present": present += 1
        else: leave += 1
    lines.append(f"\n*Total: {present} Present, {leave} on Leave*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def monthly(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only command.")
        return
    db = load_db()
    mk = month_key()
    summary = {}
    for dk, day_data in db["attendance"].items():
        if not dk.startswith(mk): continue
        for uid, rec in day_data.items():
            if uid not in summary:
                summary[uid] = {"present": 0, "leave": 0}
            summary[uid][rec["status"]] += 1
    if not summary:
        await update.message.reply_text(f"No data for {date.today().strftime('%B %Y')} yet.")
        return
    lines = [f"📅 *Monthly Summary — {date.today().strftime('%B %Y')}*\n"]
    for uid, counts in summary.items():
        name = db["users"].get(uid, {}).get("name", f"User {uid}")
        lines.append(f"👤 {name}: ✅ {counts['present']} days | 🏖️ {counts['leave']} leaves")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def send_morning_reminder(app):
    db = load_db()
    keyboard = [[
        InlineKeyboardButton("✅ Present", callback_data="attend_present"),
        InlineKeyboardButton("🏖️ Leave", callback_data="attend_leave"),
    ]]
    markup = InlineKeyboardMarkup(keyboard)
    for uid in db["users"]:
        try:
            await app.bot.send_message(
                chat_id=int(uid),
                text=f"🌅 Good morning! Mark your attendance for *{date.today().strftime('%A, %d %B')}*:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Could not message {uid}: {e}")

# --- FLASK DASHBOARD ---

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>TinkerHub Attendance Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, sans-serif; background: #f0f4f8; color: #1a202c; }
    .header { background: #6c5ce7; color: white; padding: 24px 32px; }
    .header h1 { font-size: 22px; font-weight: 700; }
    .header p { font-size: 13px; opacity: 0.8; margin-top: 4px; }
    .container { max-width: 900px; margin: 32px auto; padding: 0 20px; }
    .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 32px; }
    .card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    .card .num { font-size: 36px; font-weight: 800; }
    .card .label { font-size: 12px; color: #718096; margin-top: 4px; text-transform: uppercase; letter-spacing: .05em; }
    .present .num { color: #38a169; }
    .leave .num { color: #e53e3e; }
    .total .num { color: #6c5ce7; }
    table { width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    th { background: #6c5ce7; color: white; padding: 12px 16px; text-align: left; font-size: 13px; font-weight: 600; }
    td { padding: 12px 16px; border-bottom: 1px solid #f0f4f8; font-size: 14px; }
    tr:last-child td { border-bottom: none; }
    .badge { display: inline-block; padding: 3px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }
    .badge-present { background: #c6f6d5; color: #276749; }
    .badge-leave { background: #fed7d7; color: #9b2c2c; }
    .section-title { font-size: 16px; font-weight: 700; margin-bottom: 12px; color: #2d3748; }
    .refresh { font-size: 12px; color: #a0aec0; margin-bottom: 8px; }
  </style>
</head>
<body>
  <div class="header">
    <h1>🏢 TinkerHub Attendance Dashboard</h1>
    <p>{{ today }} &nbsp;·&nbsp; Admin View</p>
  </div>
  <div class="container">
    <div class="cards">
      <div class="card present"><div class="num">{{ present }}</div><div class="label">✅ Present Today</div></div>
      <div class="card leave"><div class="num">{{ leave }}</div><div class="label">🏖️ On Leave</div></div>
      <div class="card total"><div class="num">{{ total }}</div><div class="label">👥 Total Marked</div></div>
    </div>
    <p class="refresh">Auto-refreshes every 30 seconds</p>
    <p class="section-title">Today's Attendance</p>
    <table>
      <tr><th>Name</th><th>Status</th><th>Time</th></tr>
      {% for row in rows %}
      <tr>
        <td>{{ row.name }}</td>
        <td><span class="badge badge-{{ row.status }}">{{ row.status | title }}</span></td>
        <td>{{ row.time }}</td>
      </tr>
      {% endfor %}
      {% if not rows %}
      <tr><td colspan="3" style="text-align:center;color:#a0aec0;padding:32px">No attendance marked yet today</td></tr>
      {% endif %}
    </table>
  </div>
  <script>setTimeout(() => location.reload(), 30000)</script>
</body>
</html>
"""

flask_app = Flask(__name__)

@flask_app.route("/")
def dashboard():
    db = load_db()
    tk = today_key()
    day_data = db["attendance"].get(tk, {})
    rows = []
    present = leave = 0
    for uid, rec in day_data.items():
        name = db["users"].get(uid, {}).get("name", f"User {uid}")
        rows.append({"name": name, "status": rec["status"], "time": rec["time"]})
        if rec["status"] == "present": present += 1
        else: leave += 1
    return render_template_string(DASHBOARD_HTML, rows=rows, present=present, leave=leave,
                                   total=present+leave, today=date.today().strftime("%A, %d %B %Y"))

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

# --- MAIN ---

async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set!")

    # Start Flask in background thread
    Thread(target=run_flask, daemon=True).start()
    logger.info(f"Dashboard running on http://localhost:{PORT}")

    # Build bot application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("attend", attend))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("monthly", monthly))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Morning reminder scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_morning_reminder, "cron", hour=9, minute=0, args=[application])
    scheduler.start()

    logger.info("Bot is running!")
    async with application:
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await asyncio.Event().wait()  # run forever

if __name__ == "__main__":
    asyncio.run(main())     