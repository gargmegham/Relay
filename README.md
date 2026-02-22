# 📋 Telegram Task Management Bot

A feature-rich Telegram bot for managing tasks and assignments within teams. Assign tasks, track progress, send reminders, and get daily digests - all through Telegram!

## ✨ Features

### 👥 User Management
- **User Registration**: Users register via `/start` command
- **Admin System**: Password-protected admin access via `/admin` command
- **Role-Based Permissions**: Separate commands for admins and regular users
- **User Directory**: Admins can view all registered users with `/users` command

### 📝 Task Management
- **Create Tasks**: Admins can assign tasks to team members (`/ask`)
  - Interactive mode with user selection keyboard
  - Self-assignment prevention
- **View Tasks**: Users see their open tasks with pagination (`/list`)
- **Complete Tasks**: Mark tasks as done (`/done`)
- **Task History**: Admins can view complete task history per user (`/history`)
- **All Open Tasks**: Admins see all pending tasks across the team (`/waiting`)

### 🔔 Reminders & Nudges
- **Manual Nudges**: Admins can send reminders with different tones (`/nudge`)
  - Friendly, Urgent, or Neutral tones
- **Auto-Nudges**: Automatic reminders for tasks older than 3 days (runs every 6 hours)
- **Reply Tracking**: Users can reply directly to nudges, forwarded to the admin

### 📊 Analytics & Reporting
- **Daily Digest**: Summary of created, completed, and aging tasks (`/today`)
- **Priority Indicators**: Visual color-coding based on task age
  - 🟢 Recent (<3 days)
  - 🟡 Warning (3-6 days)
  - 🔴 Urgent (≥7 days)

### 🎨 User Interface
- **Pagination**: Browse long lists with Previous/Next buttons (5 items per page)
- **Rich Formatting**: Markdown formatting with icons and visual separators
- **Reply Threading**: All bot responses reply to user commands for better context

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- PostgreSQL database
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))

### Environment Variables

Create a `.env` file in the project root:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
ADMIN_PASSWORD=your_admin_password_here
DATABASE_URL=postgresql://user:password@localhost:5432/taskbot
```

### Installation

#### Option 1: Local Development

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Telebot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

4. **Run the bot**
   ```bash
   python main.py
   ```

#### Option 2: Docker Compose

1. **Set environment variables**
   ```bash
   export TELEGRAM_BOT_TOKEN=your_token
   export ADMIN_PASSWORD=your_password
   ```

2. **Start services**
   ```bash
   docker-compose up -d
   ```

3. **View logs**
   ```bash
   docker-compose logs -f bot
   ```

#### Option 3: Render Deployment

**Method 1: Using render.yaml (Recommended)**

1. **Push your code to GitHub**
   ```bash
   git add .
   git commit -m "Add Render configuration"
   git push origin main
   ```

2. **Deploy on Render**
   - Go to [Render Dashboard](https://dashboard.render.com/)
   - Click "New" → "Blueprint"
   - Connect your GitHub repository
   - Render will automatically detect `render.yaml` and create services

3. **Set environment variables** in Render dashboard:
   - `TELEGRAM_BOT_TOKEN` - Your bot token from BotFather
   - `ADMIN_PASSWORD` - Your admin password
   - `DATABASE_URL` will be auto-configured from the PostgreSQL service

**Method 2: Manual Setup**

1. **Create PostgreSQL Database**
   - Go to Render Dashboard
   - Click "New" → "PostgreSQL"
   - Choose free tier and create database
   - Copy the "Internal Database URL"

2. **Deploy the Bot**
   - Click "New" → "Web Service"
   - Connect your GitHub repository
   - Set build command: (leave empty, uses Dockerfile)
   - Add environment variables:
     - `TELEGRAM_BOT_TOKEN`
     - `ADMIN_PASSWORD`
     - `DATABASE_URL` (paste the internal database URL)
   - Click "Create Web Service"

3. **Note**: Render free tier services may sleep after inactivity. For 24/7 operation, consider upgrading to a paid plan.

## 📖 Command Reference

### User Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Register as a task assignee | `/start` |
| `/list` | View your open tasks | `/list` |
| `/done <task_id>` | Mark a task as completed | `/done 5` |
| `/help` | Show available commands | `/help` |
| `/admin <password>` | Gain admin privileges | `/admin secretpass` |

### Admin Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/ask <username> <task>` | Assign a task to a user | `/ask john Please review the report` |
| `/nudge <username> <task_id> [tone]` | Send a reminder (default: friendly) | `/nudge john 5` or `/nudge john 5 urgent` |
| `/history <username>` | View user's task history | `/history john` |
| `/waiting` | View all open tasks | `/waiting` |
| `/today` | Get daily digest | `/today` |
| `/users` | List all users | `/users` |

### Nudge Tones

- **friendly** (default): Casual, gentle reminder
- **urgent**: Strong, immediate action required
- **neutral**: Professional, standard reminder

## 🗄️ Database Schema

### Users Table
```sql
user_id BIGINT PRIMARY KEY
username TEXT
is_admin INTEGER DEFAULT 0
```

### Tasks Table
```sql
task_id SERIAL PRIMARY KEY
description TEXT NOT NULL
assigned_to TEXT NOT NULL
assigned_to_user_id BIGINT NOT NULL
status TEXT DEFAULT 'open'
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
completed_date TIMESTAMP
created_by TEXT NOT NULL
created_by_user_id BIGINT NOT NULL
last_nudged_at TIMESTAMP
```

## 🏗️ Architecture

```
Telebot/
├── main.py              # Bot application & command handlers
├── database.py          # Database operations & queries
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker container definition
├── docker-compose.yml   # Multi-container setup
├── render.yaml          # Render deployment config
└── .env                 # Environment variables (not in git)
```

## 🔧 Configuration

### Auto-Nudge Settings
- **Trigger**: Tasks older than 3 days
- **Frequency**: Every 6 hours
- **Cooldown**: Won't re-nudge if nudged within last 3 days

### Pagination
- **Items per page**: 5
- **Commands with pagination**: `/list`, `/history`, `/waiting`, `/today`

### Logging
- **Level**: INFO
- **Format**: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- **HTTP logs**: Suppressed (httpx set to WARNING)

## 🛡️ Security

- **Admin Authentication**: Password-protected admin access
- **User Verification**: All admin commands check user permissions
- **Database Security**: Connection pooling with prepared statements
- **Input Validation**: Task IDs, usernames validated before processing

## 🐛 Troubleshooting

### Bot not responding
- Check if bot token is valid
- Verify environment variables are set
- Check logs: `docker-compose logs -f bot`

### Database connection failed
- Ensure PostgreSQL is running
- Verify DATABASE_URL format
- Check database credentials

### Auto-nudge not working
- Job queue requires `python-telegram-bot` installed
- Check logs for job scheduler status
- Verify job queue is initialized (look for "Auto-nudge job scheduled" log)

### Pagination buttons not working
- Ensure CallbackQueryHandler is registered
- Check for errors in callback handler logs

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

This project is open source and available under the MIT License.

## 🙏 Acknowledgments

- Built with [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- Database: [PostgreSQL](https://www.postgresql.org/)
- Icons: Unicode emoji standard

## 📞 Support

For issues, questions, or feature requests:
- Open an issue on GitHub
- Check existing documentation
- Review command reference above

---

**Made with ❤️ for better team task management**
