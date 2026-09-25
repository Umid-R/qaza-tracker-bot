# Qaza Tracker — Telegram Bot

Telegram bot (aiogram) for prayer reminders and direct chat commands.
Talks to Supabase directly — does not go through the backend API.

## Setup
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in TELEGRAM_TOKEN, SUPABASE_URL, SUPABASE_KEY
python -m bot.tg_bot
```

## Note on shared code
`bot/database/` is a duplicate of the backend's `app/database/` code
(see [qaza-tracker-backend](../qaza-tracker-backend)), since this bot talks to
Supabase directly rather than through the API. If you change the schema or a
query here, check whether the backend's copy needs the same update.

## Deployment
Deployed on Railway (`railway.json` included), tracking `main`.
