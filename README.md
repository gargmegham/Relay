# Relay

A Telegram bot for managing tasks and assignments within small teams. Admins assign tasks, track progress, send reminders, and receive automated daily digests — all through Telegram.

## Features

- **Task lifecycle**: Create, assign, complete, and view task history
- **Nudges**: Manual reminders with selectable tone (friendly/urgent/neutral), plus automatic reminders for tasks older than 3 days
- **Daily digest**: Automated summary sent to all admins at 7am ET; also available on demand via `/today`
- **Role-based access**: Password-protected admin promotion; regular users can only see and complete their own tasks
- **Pagination**: Long lists are browsable in pages of 5
- **Priority indicators**: Tasks are color-coded by age (green <3 days, yellow 3–6 days, red 7+ days)
- **Reply tracking**: Users can reply to nudge messages; replies are forwarded to the admin who sent the nudge

## Requirements

- Python 3.9+
- PostgreSQL
- Telegram bot token from [@BotFather](https://t.me/botfather)

## Environment Variables

| Variable             | Description                                                             |
| -------------------- | ----------------------------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather                                                |
| `ADMIN_PASSWORD`     | Password used to gain admin access via `/admin`                         |
| `DATABASE_URL`       | PostgreSQL connection string: `postgresql://user:pass@host:5432/dbname` |

Copy `.env.example` to `.env` and fill in the values.

## Setup

### Local

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env
python main.py
```

### Docker Compose

```bash
export TELEGRAM_BOT_TOKEN=your_token
export ADMIN_PASSWORD=your_password
docker-compose up -d
docker-compose logs -f bot
```

The compose file starts both the bot and a PostgreSQL instance.

### Render (Blueprint)

1. Push code to GitHub
2. In the Render dashboard: New → Blueprint → connect your repo
3. Render detects `render.yaml` and creates a worker service + PostgreSQL
4. Set `TELEGRAM_BOT_TOKEN` and `ADMIN_PASSWORD` in the Render dashboard; `DATABASE_URL` is auto-wired from the managed database

The bot runs as a background worker (not a web service), so free-tier sleep behavior does not apply.

## Commands

### All Users

| Command             | Description              |
| ------------------- | ------------------------ |
| `/start`            | Register your account    |
| `/list`             | View your open tasks     |
| `/done <task_id>`   | Mark a task as completed |
| `/help`             | Show command reference   |
| `/admin <password>` | Gain admin privileges    |

### Admin Only

| Command                              | Description                                                                      |
| ------------------------------------ | -------------------------------------------------------------------------------- |
| `/ask [username] [task]`             | Assign a task; omitting arguments launches interactive mode                      |
| `/nudge <username> <task_id> [tone]` | Send a reminder (tone: `friendly` \| `urgent` \| `neutral`, default: `friendly`) |
| `/history <username>`                | View all tasks (open and completed) for a user                                   |
| `/waiting`                           | View all open tasks across the team                                              |
| `/today`                             | View the daily digest on demand                                                  |
| `/users`                             | List all registered users                                                        |

## Background Jobs

| Job          | Schedule                    | Behavior                                                                                      |
| ------------ | --------------------------- | --------------------------------------------------------------------------------------------- |
| Auto-nudge   | Every 6 hours               | Sends a friendly nudge for tasks >3 days old that haven't been nudged in the last 3 days      |
| Daily digest | Daily at 12:00 UTC (7am ET) | Sends digest to all admins: tasks created today, completed today, and tasks needing attention |

Both jobs run inside the bot process using `python-telegram-bot`'s built-in job queue. The bot must be running continuously for these to fire.

## Database Schema

```sql
-- users
user_id       BIGINT PRIMARY KEY
username      TEXT
is_admin      INTEGER DEFAULT 0   -- 0 = user, 1 = admin

-- tasks
task_id              SERIAL PRIMARY KEY
description          TEXT NOT NULL
assigned_to          TEXT NOT NULL
assigned_to_user_id  BIGINT NOT NULL
status               TEXT DEFAULT 'open'   -- 'open' | 'completed'
created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
completed_date       TIMESTAMP
created_by           TEXT NOT NULL
created_by_user_id   BIGINT NOT NULL
last_nudged_at       TIMESTAMP
```

The database layer (`database.py`) uses a connection pool (1–10 connections).

## Project Structure

```
MintTelegramBot/
├── main.py              # Command handlers, callback handlers, job scheduling
├── database.py          # Database connection pool and query functions
├── requirements.txt     # Python dependencies
├── Dockerfile           # Python 3.11-slim container
├── docker-compose.yml   # Bot + PostgreSQL services
├── render.yaml          # Render deployment configuration
└── .env.example         # Environment variable template
```

## Troubleshooting

**Bot not responding** — verify `TELEGRAM_BOT_TOKEN` is set and the bot process is running. Check logs with `docker-compose logs -f bot`.

**Database connection errors** — confirm `DATABASE_URL` format and that PostgreSQL is accessible from the bot.

**Auto-nudge or digest not firing** — the job queue requires a continuously running process. Look for `"Auto-nudge job scheduled"` and `"Daily digest job scheduled"` in startup logs to confirm jobs were registered.

**Daily digest time offset** — the digest fires at 12:00 UTC, which is 7am ET (EST) or 8am ET (EDT) during daylight saving time.

## Dependencies

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) 20.7 (with job-queue extra)
- [psycopg2-binary](https://pypi.org/project/psycopg2-binary/) 2.9.9
- [python-dotenv](https://pypi.org/project/python-dotenv/) 1.0.0
