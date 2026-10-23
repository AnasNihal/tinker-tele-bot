# Tinker Telegram Attendance Bot

A Telegram bot project for attendance and leave tracking, with a small Flask endpoint for deployment health checks.

The bot reads its Telegram token and administrator IDs from environment variables. It uses a monthly leave allowance and stores attendance data in local files.

## Configure and run

1. Set `BOT_TOKEN` and `ADMIN_IDS` in the deployment environment.
2. Install dependencies and start the bot:

```bash
pip install -r requirements.txt
python bot.py
```

Do not commit bot tokens or other credentials.
