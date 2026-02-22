import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from database import Database

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Suppress verbose HTTP logs from httpx
logging.getLogger('httpx').setLevel(logging.WARNING)

# Environment variables
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

# Initialize database
db = Database(DATABASE_URL)

# Store context for nudge replies
nudge_context = {}

# Store context for pending task creation (interactive /ask)
task_creation_context = {}


def escape_html(text: str) -> str:
    """Escape special characters for Telegram HTML parse mode."""
    if not text:
        return text
    # Escape HTML special characters
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def create_pagination_keyboard(page: int, total_pages: int, callback_prefix: str):
    """Create pagination keyboard with Previous/Next buttons."""
    keyboard = []
    buttons = []

    # Previous button
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"{callback_prefix}:{page-1}"))

    # Page counter
    buttons.append(InlineKeyboardButton(f"Page {page}/{total_pages}", callback_data="noop"))

    # Next button
    if page < total_pages:
        buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"{callback_prefix}:{page+1}"))

    if buttons:
        keyboard.append(buttons)

    return InlineKeyboardMarkup(keyboard) if keyboard else None


def create_user_selection_keyboard(exclude_user_id: int = None):
    """Create inline keyboard with all non-admin users for task assignment."""
    users = db.get_all_non_admin_users()

    # Filter out the requesting user to prevent self-assignment
    if exclude_user_id:
        users = [u for u in users if u['user_id'] != exclude_user_id]

    if not users:
        return None

    keyboard = []
    row = []

    # Create buttons in rows of 2
    for user in users:
        button = InlineKeyboardButton(
            f"@{user['username']}",
            callback_data=f"ask_user:{user['user_id']}:{user['username']}"
        )
        row.append(button)

        if len(row) == 2:
            keyboard.append(row)
            row = []

    # Add remaining buttons
    if row:
        keyboard.append(row)

    # Add cancel button
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="ask_cancel")])

    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command - register user as task assignee."""
    user = update.effective_user
    username = user.username or user.first_name

    # Add user to database (preserves existing admin status automatically)
    db.add_user(user.id, username, is_admin=False)

    welcome_message = (
        f"Welcome {username}!\n\n"
        "You've been registered as a task assignee. You can now receive task assignments from admins.\n\n"
        "Use /help to see available commands."
    )

    await update.message.reply_text(welcome_message, reply_to_message_id=update.message.message_id)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /admin command - grant admin privileges with password."""
    user = update.effective_user
    username = user.username or user.first_name

    if not context.args:
        await update.message.reply_text(
            "Usage: /admin <password>\n\n"
            "Please provide the admin password.",
            reply_to_message_id=update.message.message_id
        )
        return

    password = ' '.join(context.args)

    if password == ADMIN_PASSWORD:
        db.grant_admin(user.id, username)
        await update.message.reply_text(
            f"Admin privileges granted.",
            reply_to_message_id=update.message.message_id
        )
        logger.info(f"Admin privileges granted to user {user.id} ({username})")
    else:
        await update.message.reply_text("Incorrect password. Access denied.", reply_to_message_id=update.message.message_id)
        logger.warning(f"Failed admin login attempt by user {user.id} ({username})")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /ask command - create and assign a task (admin only)."""
    user = update.effective_user
    username = user.username or user.first_name

    # Check if user is admin
    if not db.is_admin(user.id):
        await update.message.reply_text("This command is only available to admins.", reply_to_message_id=update.message.message_id)
        return

    # Interactive mode: show user selection keyboard
    if len(context.args) == 0:
        keyboard = create_user_selection_keyboard(exclude_user_id=user.id)

        if not keyboard:
            await update.message.reply_text(
                "No users available for task assignment.\n\n"
                "Users need to register with /start first.",
                reply_to_message_id=update.message.message_id
            )
            return

        await update.message.reply_text(
            "👥 <b>Select a user to assign a task:</b>",
            reply_to_message_id=update.message.message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        return

    # Traditional mode: parse username and task from arguments
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /ask <username> <task description>\n\n"
            "Example: /ask john Please review the quarterly report.\n\n"
            "Or use <code>/ask</code> without arguments to select a user interactively.",
            reply_to_message_id=update.message.message_id,
            parse_mode='HTML'
        )
        return

    assigned_to_username = context.args[0].lstrip('@')
    task_description = ' '.join(context.args[1:])

    # Prevent self-assignment
    if assigned_to_username.lower() == username.lower():
        await update.message.reply_text(
            "You cannot assign tasks to yourself.",
            reply_to_message_id=update.message.message_id
        )
        return

    # Get the assigned user from database
    assigned_user = db.get_user_by_username(assigned_to_username)

    if not assigned_user:
        await update.message.reply_text(
            f"User {assigned_to_username} not found.\n\n"
            "They need to start the bot first with /start.",
            reply_to_message_id=update.message.message_id
        )
        return

    # Create the task
    task_id = db.create_task(
        description=task_description,
        assigned_to=assigned_to_username,
        assigned_to_user_id=assigned_user['user_id'],
        created_by=username,
        created_by_user_id=user.id
    )

    # Notify the assignee
    try:
        await context.bot.send_message(
            chat_id=assigned_user['user_id'],
            text=f"New task assigned by {username}:\n\n"
                 f"Task #{task_id}: {task_description}\n\n"
                 f"Use /list to see all your tasks."
        )
        await update.message.reply_text(
            f"Task #{task_id} created and assigned to @{assigned_to_username}",
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        logger.error(f"Error notifying user: {e}")
        await update.message.reply_text(
            f"Task #{task_id} created, but couldn't notify @{assigned_to_username}.\n\n"
            "They may have blocked the bot.",
            reply_to_message_id=update.message.message_id
        )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """Handle the /list command - show user's assigned tasks."""
    user = update.effective_user
    username = user.username or user.first_name

    # Ensure user is in database
    db.add_user(user.id, username, is_admin=False)

    # Get user's open tasks
    tasks = db.get_user_tasks(user.id, status='open')

    if not tasks:
        await update.message.reply_text(
            "You have no open tasks. Great job!",
            reply_to_message_id=update.message.message_id
        )
        return

    # Pagination
    items_per_page = 5
    total_pages = (len(tasks) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_tasks = tasks[start_idx:end_idx]

    message = f"📋 <b>YOUR OPEN TASKS</b> ({len(tasks)})\n"
    message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, task in enumerate(page_tasks, 1):
        created_date = datetime.fromisoformat(task['created_at'])
        days_ago = (datetime.now() - created_date).days

        # Priority indicator based on age
        if days_ago >= 7:
            priority_icon = "🔴"
        elif days_ago >= 3:
            priority_icon = "🟡"
        else:
            priority_icon = "🟢"

        message += f"{priority_icon} <b>Task</b> <code>#{task['task_id']}</code>\n"
        message += f"📝 {escape_html(task['description'])}\n"
        message += f"👨‍💼 Assigned by: @{task['created_by']}\n"
        message += f"📅 Created: {days_ago} day{'s' if days_ago != 1 else ''} ago\n"

        if i < len(page_tasks):
            message += "\n"

    message += "\n━━━━━━━━━━━━━━━━━━━━━\n"
    message += "💡 Use <code>/done &lt;task_id&gt;</code> to mark as completed"

    # Add pagination keyboard
    keyboard = create_pagination_keyboard(page, total_pages, f"list:{user.id}")

    await update.message.reply_text(
        message,
        reply_to_message_id=update.message.message_id,
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /done command - mark a task as completed."""
    user = update.effective_user
    username = user.username or user.first_name

    if not context.args:
        await update.message.reply_text(
            "Usage: /done <task_id>\n"
            "Example: /done 5",
            reply_to_message_id=update.message.message_id
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task ID must be a number.", reply_to_message_id=update.message.message_id)
        return

    # Get task details before marking as completed
    task = db.get_task_by_id(task_id)

    if not task:
        await update.message.reply_text(f"Task #{task_id} not found.", reply_to_message_id=update.message.message_id)
        return

    if task['assigned_to_user_id'] != user.id:
        await update.message.reply_text("You can only complete tasks assigned to you.", reply_to_message_id=update.message.message_id)
        return

    if task['status'] == 'completed':
        await update.message.reply_text(f"Task #{task_id} is already completed.", reply_to_message_id=update.message.message_id)
        return

    # Mark task as completed
    if db.mark_task_completed(task_id, user.id):
        await update.message.reply_text(
            f"Task #{task_id} marked as completed!\n"
            f'"{task["description"]}"',
            reply_to_message_id=update.message.message_id
        )

        # Notify the admin who created the task
        try:
            await context.bot.send_message(
                chat_id=task['created_by_user_id'],
                text=f"{username} completed a task:\n\n"
                     f"Task #{task_id}: {escape_html(task['description'])}"
            )
        except Exception as e:
            logger.error(f"Error notifying admin: {e}")
    else:
        await update.message.reply_text(
            f"Could not complete task #{task_id}. Please try again.",
            reply_to_message_id=update.message.message_id
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /help command - show available commands."""
    user = update.effective_user
    is_admin = db.is_admin(user.id)

    help_text = (
        "Available commands:\n\n"
        "/start - Register as a task assignee\n"
        "/list - View your assigned tasks\n"
        "/done <task_id> - Mark a task as completed\n"
        "/help - Show this help message\n"
    )

    if is_admin:
        help_text += (
            "\nAdmin commands:\n"
            "/ask <username> <task> - Assign a task to a user\n"
            "/nudge <username> <task_id> [tone] - Send reminder (default: friendly)\n"
            "/history <username> - View user's task history\n"
            "/waiting - View all open tasks\n"
            "/today - Get daily digest\n"
            "/users - List all users\n"
        )
    else:
        help_text += "\n/admin <password> - Gain admin privileges\n"

    await update.message.reply_text(help_text, reply_to_message_id=update.message.message_id)


async def nudge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /nudge command - send manual reminder (admin only)."""
    user = update.effective_user
    username = user.username or user.first_name

    # Check if user is admin
    if not db.is_admin(user.id):
        await update.message.reply_text("This command is only available to admins.", reply_to_message_id=update.message.message_id)
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /nudge <username> <task_id> [tone]\n\n"
            "Tones: friendly (default), urgent, neutral\n\n"
            "Examples:\n"
            "/nudge john 5\n"
            "/nudge john 5 urgent",
            reply_to_message_id=update.message.message_id
        )
        return

    target_username = context.args[0].lstrip('@')

    try:
        task_id = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Task ID must be a number.", reply_to_message_id=update.message.message_id)
        return

    # Default tone is friendly
    tone = context.args[2].lower() if len(context.args) > 2 else 'friendly'
    if tone not in ['friendly', 'urgent', 'neutral']:
        await update.message.reply_text(
            "Tone must be one of: friendly, urgent, neutral",
            reply_to_message_id=update.message.message_id
        )
        return

    # Get task details
    task = db.get_task_by_id(task_id)

    if not task:
        await update.message.reply_text(f"Task #{task_id} not found.", reply_to_message_id=update.message.message_id)
        return

    if task['status'] == 'completed':
        await update.message.reply_text(f"Task #{task_id} is already completed.", reply_to_message_id=update.message.message_id)
        return

    if task['assigned_to'] != target_username:
        await update.message.reply_text(
            f"Task #{task_id} is not assigned to @{target_username}.",
            reply_to_message_id=update.message.message_id
        )
        return

    # Create nudge message based on tone
    created_date = datetime.fromisoformat(task['created_at'])
    days_ago = (datetime.now() - created_date).days

    nudge_messages = {
        'friendly': f"Hey {target_username}, {username} is waiting on: \"{escape_html(task['description'])}\" (asked {days_ago} day(s) ago). Quick update?",
        'urgent': f"{target_username}, this is urgent! {username} needs: \"{escape_html(task['description'])}\" (asked {days_ago} day(s) ago). Please respond ASAP!",
        'neutral': f"{target_username}, reminder from {username}: \"{escape_html(task['description'])}\" (asked {days_ago} day(s) ago). Please provide an update."
    }

    nudge_message = nudge_messages[tone]

    # Send nudge to assignee
    try:
        sent_message = await context.bot.send_message(
            chat_id=task['assigned_to_user_id'],
            text=nudge_message
        )

        # Store nudge context for reply handling
        nudge_context[task['assigned_to_user_id']] = {
            'task_id': task_id,
            'admin_id': user.id,
            'admin_username': username,
            'nudge_message_id': sent_message.message_id
        }

        # Update nudge in database
        db.update_nudge(task_id)

        await update.message.reply_text(
            f"Nudge sent to @{target_username} for task #{task_id}",
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        logger.error(f"Error sending nudge: {e}")
        await update.message.reply_text(
            f"Could not send nudge to @{target_username}.\n\n"
            "They may have blocked the bot.",
            reply_to_message_id=update.message.message_id
        )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1, target_username: str = None):
    """Handle the /history command - show user's task history (admin only)."""
    user = update.effective_user

    # Check if user is admin
    if not db.is_admin(user.id):
        await update.message.reply_text("This command is only available to admins.", reply_to_message_id=update.message.message_id)
        return

    # Get target username from args if not provided (callback will provide it)
    if target_username is None:
        if not context.args:
            await update.message.reply_text(
                "Usage: /history <username>\n\n"
                "Example: /history john",
                reply_to_message_id=update.message.message_id
            )
            return
        target_username = context.args[0].lstrip('@')

    # Get user from database
    target_user = db.get_user_by_username(target_username)

    if not target_user:
        await update.message.reply_text(
            f"User @{target_username} not found.",
            reply_to_message_id=update.message.message_id
        )
        return

    # Get all tasks for user
    all_tasks = db.get_user_tasks(target_user['user_id'])

    if not all_tasks:
        await update.message.reply_text(
            f"No tasks found for @{target_username}.",
            reply_to_message_id=update.message.message_id
        )
        return

    # Pagination for all tasks combined
    items_per_page = 5
    total_pages = (len(all_tasks) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_tasks = all_tasks[start_idx:end_idx]

    # Count open and completed
    open_count = sum(1 for t in all_tasks if t['status'] == 'open')
    completed_count = sum(1 for t in all_tasks if t['status'] == 'completed')

    message = f"📊 <b>TASK HISTORY</b> for @{target_username}\n"
    message += f"🔵 Open: {open_count} • ✅ Completed: {completed_count}\n"
    message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, task in enumerate(page_tasks, 1):
        if task['status'] == 'open':
            created_date = datetime.fromisoformat(task['created_at'])
            days_ago = (datetime.now() - created_date).days

            # Priority indicator for open tasks
            if days_ago >= 7:
                priority_icon = "🔴"
            elif days_ago >= 3:
                priority_icon = "🟡"
            else:
                priority_icon = "🟢"

            message += f"{priority_icon} <b>Open Task</b> <code>#{task['task_id']}</code>\n"
            message += f"📝 {escape_html(task['description'])}\n"
            message += f"👨‍💼 Created by: @{task['created_by']}\n"
            message += f"📅 Age: {days_ago} day{'s' if days_ago != 1 else ''}\n"
        else:
            completed_date = datetime.fromisoformat(task['completed_date'])
            message += f"✅ <b>Completed</b> <code>#{task['task_id']}</code>\n"
            message += f"📝 {escape_html(task['description'])}\n"
            message += f"⏰ Completed: {completed_date.strftime('%Y-%m-%d')}\n"

        if i < len(page_tasks):
            message += "\n"

    message += "\n━━━━━━━━━━━━━━━━━━━━━"

    # Add pagination keyboard
    keyboard = create_pagination_keyboard(page, total_pages, f"history:{target_username}")

    await update.message.reply_text(
        message,
        reply_to_message_id=update.message.message_id,
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def waiting_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """Handle the /waiting command - show all open tasks (admin only)."""
    user = update.effective_user

    # Check if user is admin
    if not db.is_admin(user.id):
        await update.message.reply_text("This command is only available to admins.", reply_to_message_id=update.message.message_id)
        return

    # Get all open tasks
    open_tasks = db.get_all_open_tasks()

    if not open_tasks:
        await update.message.reply_text(
            "No open tasks in the system. All clear!",
            reply_to_message_id=update.message.message_id
        )
        return

    # Pagination
    items_per_page = 5
    total_pages = (len(open_tasks) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_tasks = open_tasks[start_idx:end_idx]

    message = f"⏳ <b>ALL OPEN TASKS</b> ({len(open_tasks)})\n"
    message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, task in enumerate(page_tasks, 1):
        created_date = datetime.fromisoformat(task['created_at'])
        days_ago = (datetime.now() - created_date).days

        # Priority indicator based on age
        if days_ago >= 7:
            priority_icon = "🔴"
        elif days_ago >= 3:
            priority_icon = "🟡"
        else:
            priority_icon = "🟢"

        message += f"{priority_icon} <b>Task</b> <code>#{task['task_id']}</code>\n"
        message += f"📝 {escape_html(task['description'])}\n"
        message += f"👤 Assigned to: @{task['assigned_to']}\n"
        message += f"👨‍💼 Created by: @{task['created_by']}\n"
        message += f"📅 Age: {days_ago} day{'s' if days_ago != 1 else ''}\n"

        if task['last_nudged_at']:
            nudge_date = datetime.fromisoformat(task['last_nudged_at'])
            nudge_days_ago = (datetime.now() - nudge_date).days
            message += f"🔔 Last nudge: {nudge_days_ago} day{'s' if nudge_days_ago != 1 else ''} ago\n"

        if i < len(page_tasks):
            message += "\n"

    message += "\n━━━━━━━━━━━━━━━━━━━━━"

    # Add pagination keyboard
    keyboard = create_pagination_keyboard(page, total_pages, "waiting")

    await update.message.reply_text(
        message,
        reply_to_message_id=update.message.message_id,
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """Handle the /today command - show daily digest (admin only)."""
    user = update.effective_user

    # Check if user is admin
    if not db.is_admin(user.id):
        await update.message.reply_text("This command is only available to admins.", reply_to_message_id=update.message.message_id)
        return

    # Get today's summary
    summary = db.get_todays_tasks()

    # Combine all tasks for pagination
    all_tasks = []
    for task in summary['created_today']:
        all_tasks.append(('created', task))
    for task in summary['completed_today']:
        all_tasks.append(('completed', task))

    # Tasks that need attention (3+ days old)
    old_tasks = [
        t for t in summary['open_tasks']
        if (datetime.now() - datetime.fromisoformat(t['created_at'])).days >= 3
    ]
    for task in old_tasks:
        all_tasks.append(('old', task))

    # Pagination
    items_per_page = 5

    message = f"📅 <b>DAILY DIGEST</b> • {datetime.now().strftime('%Y-%m-%d')}\n"
    message += f"➕ Created: {len(summary['created_today'])} • ✅ Completed: {len(summary['completed_today'])}\n"
    message += f"🔵 Total Open: {len(summary['open_tasks'])} • ⚠️ Needs Attention: {len(old_tasks)}\n"
    message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

    if not all_tasks:
        message += "✨ No activity today and no tasks needing attention."
        await update.message.reply_text(
            message,
            reply_to_message_id=update.message.message_id,
            parse_mode='HTML'
        )
        return

    total_pages = (len(all_tasks) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_tasks = all_tasks[start_idx:end_idx]

    for i, (task_type, task) in enumerate(page_tasks, 1):
        if task_type == 'created':
            message += f"➕ <b>Created</b> <code>#{task['task_id']}</code>\n"
            message += f"📝 {escape_html(task['description'])}\n"
            message += f"👤 Assigned to: @{task['assigned_to']}\n"
        elif task_type == 'completed':
            message += f"✅ <b>Completed</b> <code>#{task['task_id']}</code>\n"
            message += f"📝 {escape_html(task['description'])}\n"
            message += f"👤 By: @{task['assigned_to']}\n"
        else:  # old
            days_ago = (datetime.now() - datetime.fromisoformat(task['created_at'])).days

            # Priority indicator
            if days_ago >= 7:
                priority_icon = "🔴"
            else:
                priority_icon = "🟡"

            message += f"{priority_icon} <b>Needs Attention</b> <code>#{task['task_id']}</code>\n"
            message += f"📝 {escape_html(task['description'])}\n"
            message += f"👤 Assigned to: @{task['assigned_to']}\n"
            message += f"📅 Age: {days_ago} day{'s' if days_ago != 1 else ''}\n"

        if i < len(page_tasks):
            message += "\n"

    message += "\n━━━━━━━━━━━━━━━━━━━━━"

    # Add pagination keyboard
    keyboard = create_pagination_keyboard(page, total_pages, "today")

    await update.message.reply_text(
        message,
        reply_to_message_id=update.message.message_id,
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """Handle the /users command - list all users (admin only)."""
    user = update.effective_user

    # Check if user is admin
    if not db.is_admin(user.id):
        await update.message.reply_text("This command is only available to admins.", reply_to_message_id=update.message.message_id)
        return

    # Get all users except the requesting user
    all_users = db.get_all_users_except(user.id)

    if not all_users:
        await update.message.reply_text(
            "No other users found.\n\n"
            "Users need to register with /start first.",
            reply_to_message_id=update.message.message_id
        )
        return

    # Pagination
    items_per_page = 5
    total_pages = (len(all_users) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_users = all_users[start_idx:end_idx]

    message = f"👥 <b>ALL USERS</b> ({len(all_users)})\n"
    message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, usr in enumerate(page_users, 1):
        admin_badge = "👑 " if usr['is_admin'] else ""
        message += f"{admin_badge}<b>@{usr['username']}</b>\n"
        if usr['is_admin']:
            message += f"   Role: Admin\n"
        else:
            message += f"   Role: User\n"

        if i < len(page_users):
            message += "\n"

    message += "\n━━━━━━━━━━━━━━━━━━━━━"

    # Add pagination keyboard
    keyboard = create_pagination_keyboard(page, total_pages, "users")

    await update.message.reply_text(
        message,
        reply_to_message_id=update.message.message_id,
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination button clicks and interactive task creation."""
    query = update.callback_query
    await query.answer()

    # Parse callback data: format is "command:page" or "command:page:extra"
    data_parts = query.data.split(':')

    if data_parts[0] == "noop":
        # Page counter button, do nothing
        return

    # Get the user who initiated the query
    user = update.effective_user
    username = user.username or user.first_name

    # Handle interactive task assignment user selection
    if data_parts[0] == "ask_user":
        selected_user_id = int(data_parts[1])
        selected_username = data_parts[2]

        # Clear any existing nudge context to avoid conflicts
        if user.id in nudge_context:
            del nudge_context[user.id]

        # Store task creation context
        task_creation_context[user.id] = {
            'selected_user_id': selected_user_id,
            'selected_username': selected_username,
            'admin_username': username
        }

        # Update message to ask for task description
        await query.edit_message_text(
            f"✅ Selected: <b>@{selected_username}</b>\n\n"
            f"📝 Now send the task description as your next message.",
            parse_mode='HTML'
        )
        return

    # Handle cancel button for task creation
    if data_parts[0] == "ask_cancel":
        await query.edit_message_text(
            "❌ Task creation cancelled."
        )
        return

    command = data_parts[0]

    # Call appropriate command with page number
    if command == "list":
        user_id = int(data_parts[1]) if len(data_parts) > 2 else user.id
        page = int(data_parts[2]) if len(data_parts) > 2 else int(data_parts[1])

        # Get user's open tasks
        tasks = db.get_user_tasks(user_id, status='open')

        if not tasks:
            return

        # Pagination
        items_per_page = 5
        total_pages = (len(tasks) + items_per_page - 1) // items_per_page
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_tasks = tasks[start_idx:end_idx]

        message = f"📋 <b>YOUR OPEN TASKS</b> ({len(tasks)})\n"
        message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, task in enumerate(page_tasks, 1):
            created_date = datetime.fromisoformat(task['created_at'])
            days_ago = (datetime.now() - created_date).days

            if days_ago >= 7:
                priority_icon = "🔴"
            elif days_ago >= 3:
                priority_icon = "🟡"
            else:
                priority_icon = "🟢"

            message += f"{priority_icon} <b>Task</b> <code>#{task['task_id']}</code>\n"
            message += f"📝 {escape_html(task['description'])}\n"
            message += f"👨‍💼 Assigned by: @{task['created_by']}\n"
            message += f"📅 Created: {days_ago} day{'s' if days_ago != 1 else ''} ago\n"

            if i < len(page_tasks):
                message += "\n"

        message += "\n━━━━━━━━━━━━━━━━━━━━━\n"
        message += "💡 Use <code>/done &lt;task_id&gt;</code> to mark as completed"

        keyboard = create_pagination_keyboard(page, total_pages, f"list:{user_id}")
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='HTML')

    elif command == "history":
        # Format: history:username:page
        target_username = data_parts[1] if len(data_parts) > 1 else None
        page = int(data_parts[2]) if len(data_parts) > 2 else 1

        if not target_username:
            return

        # Get user from database
        target_user = db.get_user_by_username(target_username)
        if not target_user:
            return

        # Get all tasks
        all_tasks = db.get_user_tasks(target_user['user_id'])
        if not all_tasks:
            return

        # Pagination
        items_per_page = 5
        total_pages = (len(all_tasks) + items_per_page - 1) // items_per_page
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_tasks = all_tasks[start_idx:end_idx]

        open_count = sum(1 for t in all_tasks if t['status'] == 'open')
        completed_count = sum(1 for t in all_tasks if t['status'] == 'completed')

        message = f"📊 <b>TASK HISTORY</b> for @{target_username}\n"
        message += f"🔵 Open: {open_count} • ✅ Completed: {completed_count}\n"
        message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, task in enumerate(page_tasks, 1):
            if task['status'] == 'open':
                created_date = datetime.fromisoformat(task['created_at'])
                days_ago = (datetime.now() - created_date).days

                if days_ago >= 7:
                    priority_icon = "🔴"
                elif days_ago >= 3:
                    priority_icon = "🟡"
                else:
                    priority_icon = "🟢"

                message += f"{priority_icon} <b>Open Task</b> <code>#{task['task_id']}</code>\n"
                message += f"📝 {escape_html(task['description'])}\n"
                message += f"👨‍💼 Created by: @{task['created_by']}\n"
                message += f"📅 Age: {days_ago} day{'s' if days_ago != 1 else ''}\n"
            else:
                completed_date = datetime.fromisoformat(task['completed_date'])
                message += f"✅ <b>Completed</b> <code>#{task['task_id']}</code>\n"
                message += f"📝 {escape_html(task['description'])}\n"
                message += f"⏰ Completed: {completed_date.strftime('%Y-%m-%d')}\n"

            if i < len(page_tasks):
                message += "\n"

        message += "\n━━━━━━━━━━━━━━━━━━━━━"

        keyboard = create_pagination_keyboard(page, total_pages, f"history:{target_username}")
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='HTML')

    elif command == "waiting":
        # Format: waiting:page
        page = int(data_parts[1]) if len(data_parts) > 1 else 1

        # Get all open tasks
        open_tasks = db.get_all_open_tasks()
        if not open_tasks:
            return

        # Pagination
        items_per_page = 5
        total_pages = (len(open_tasks) + items_per_page - 1) // items_per_page
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_tasks = open_tasks[start_idx:end_idx]

        message = f"⏳ <b>ALL OPEN TASKS</b> ({len(open_tasks)})\n"
        message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, task in enumerate(page_tasks, 1):
            created_date = datetime.fromisoformat(task['created_at'])
            days_ago = (datetime.now() - created_date).days

            if days_ago >= 7:
                priority_icon = "🔴"
            elif days_ago >= 3:
                priority_icon = "🟡"
            else:
                priority_icon = "🟢"

            message += f"{priority_icon} <b>Task</b> <code>#{task['task_id']}</code>\n"
            message += f"📝 {escape_html(task['description'])}\n"
            message += f"👤 Assigned to: @{task['assigned_to']}\n"
            message += f"👨‍💼 Created by: @{task['created_by']}\n"
            message += f"📅 Age: {days_ago} day{'s' if days_ago != 1 else ''}\n"

            if task['last_nudged_at']:
                nudge_date = datetime.fromisoformat(task['last_nudged_at'])
                nudge_days_ago = (datetime.now() - nudge_date).days
                message += f"🔔 Last nudge: {nudge_days_ago} day{'s' if nudge_days_ago != 1 else ''} ago\n"

            if i < len(page_tasks):
                message += "\n"

        message += "\n━━━━━━━━━━━━━━━━━━━━━"

        keyboard = create_pagination_keyboard(page, total_pages, "waiting")
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='HTML')

    elif command == "today":
        # Format: today:page
        page = int(data_parts[1]) if len(data_parts) > 1 else 1

        # Get today's summary
        summary = db.get_todays_tasks()

        # Combine all tasks for pagination
        all_tasks = []
        for task in summary['created_today']:
            all_tasks.append(('created', task))
        for task in summary['completed_today']:
            all_tasks.append(('completed', task))

        old_tasks = [
            t for t in summary['open_tasks']
            if (datetime.now() - datetime.fromisoformat(t['created_at'])).days >= 3
        ]
        for task in old_tasks:
            all_tasks.append(('old', task))

        if not all_tasks:
            return

        # Pagination
        items_per_page = 5
        total_pages = (len(all_tasks) + items_per_page - 1) // items_per_page
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_tasks = all_tasks[start_idx:end_idx]

        message = f"📅 <b>DAILY DIGEST</b> • {datetime.now().strftime('%Y-%m-%d')}\n"
        message += f"➕ Created: {len(summary['created_today'])} • ✅ Completed: {len(summary['completed_today'])}\n"
        message += f"🔵 Total Open: {len(summary['open_tasks'])} • ⚠️ Needs Attention: {len(old_tasks)}\n"
        message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, (task_type, task) in enumerate(page_tasks, 1):
            if task_type == 'created':
                message += f"➕ <b>Created</b> <code>#{task['task_id']}</code>\n"
                message += f"📝 {escape_html(task['description'])}\n"
                message += f"👤 Assigned to: @{task['assigned_to']}\n"
            elif task_type == 'completed':
                message += f"✅ <b>Completed</b> <code>#{task['task_id']}</code>\n"
                message += f"📝 {escape_html(task['description'])}\n"
                message += f"👤 By: @{task['assigned_to']}\n"
            else:
                days_ago = (datetime.now() - datetime.fromisoformat(task['created_at'])).days

                if days_ago >= 7:
                    priority_icon = "🔴"
                else:
                    priority_icon = "🟡"

                message += f"{priority_icon} <b>Needs Attention</b> <code>#{task['task_id']}</code>\n"
                message += f"📝 {escape_html(task['description'])}\n"
                message += f"👤 Assigned to: @{task['assigned_to']}\n"
                message += f"📅 Age: {days_ago} day{'s' if days_ago != 1 else ''}\n"

            if i < len(page_tasks):
                message += "\n"

        message += "\n━━━━━━━━━━━━━━━━━━━━━"

        keyboard = create_pagination_keyboard(page, total_pages, "today")
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='HTML')

    elif command == "users":
        # Format: users:page
        page = int(data_parts[1]) if len(data_parts) > 1 else 1

        # Get all users except the requesting user
        all_users = db.get_all_users_except(user.id)
        if not all_users:
            return

        # Pagination
        items_per_page = 5
        total_pages = (len(all_users) + items_per_page - 1) // items_per_page
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_users = all_users[start_idx:end_idx]

        message = f"👥 <b>ALL USERS</b> ({len(all_users)})\n"
        message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, usr in enumerate(page_users, 1):
            admin_badge = "👑 " if usr['is_admin'] else ""
            message += f"{admin_badge}<b>@{usr['username']}</b>\n"
            if usr['is_admin']:
                message += f"   Role: Admin\n"
            else:
                message += f"   Role: User\n"

            if i < len(page_users):
                message += "\n"

        message += "\n━━━━━━━━━━━━━━━━━━━━━"

        keyboard = create_pagination_keyboard(page, total_pages, "users")
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='HTML')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular messages (for nudge replies and task creation)."""
    user = update.effective_user
    username = user.username or user.first_name

    # Priority 1: Check if this user has a pending nudge context
    # (Nudge replies are identified by replying to the nudge message)
    if user.id in nudge_context:
        context_data = nudge_context[user.id]
        task_id = context_data['task_id']
        admin_id = context_data['admin_id']
        admin_username = context_data['admin_username']
        nudge_message_id = context_data.get('nudge_message_id')

        # Verify the user is replying to the nudge message
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != nudge_message_id:
            # Not a reply to the nudge, fall through to check other contexts
            pass
        else:
            # Get task details
            task = db.get_task_by_id(task_id)

            if task and task['status'] == 'open':
                # Reset nudge timer
                db.update_nudge(task_id)

                # Forward reply to admin
                reply_text = (
                    f"Reply from @{username} regarding task #{task_id}:\n"
                    f'"{task["description"]}"\n\n'
                    f"Their response:\n{update.message.text}"
                )

                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=reply_text
                    )

                    await update.message.reply_text(
                        f"Your update has been forwarded to {admin_username}.\n\n"
                        "Thank you!",
                        reply_to_message_id=update.message.message_id
                    )
                except Exception as e:
                    logger.error(f"Error forwarding reply: {e}")
                    await update.message.reply_text(
                        "Thanks for your update!",
                        reply_to_message_id=update.message.message_id
                    )

                # Clear context
                del nudge_context[user.id]
            return

    # Priority 2: Check if this user has a pending task creation context
    # (Only process if NOT replying to a message to avoid conflict with nudges)
    if user.id in task_creation_context:
        # If user is replying to a message, ignore (likely a nudge reply or other conversation)
        if update.message.reply_to_message:
            return

        context_data = task_creation_context[user.id]
        selected_user_id = context_data['selected_user_id']
        selected_username = context_data['selected_username']
        admin_username = context_data['admin_username']

        # Get task description from message
        task_description = update.message.text

        # Create the task
        task_id = db.create_task(
            description=task_description,
            assigned_to=selected_username,
            assigned_to_user_id=selected_user_id,
            created_by=admin_username,
            created_by_user_id=user.id
        )

        # Notify the assignee
        try:
            await context.bot.send_message(
                chat_id=selected_user_id,
                text=f"New task assigned by {admin_username}:\n\n"
                     f"Task #{task_id}: {task_description}\n\n"
                     f"Use /list to see all your tasks."
            )
            await update.message.reply_text(
                f"✅ Task <code>#{task_id}</code> created and assigned to @{selected_username}\n\n"
                f"📝 {escape_html(task_description)}",
                reply_to_message_id=update.message.message_id,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error notifying user: {e}")
            await update.message.reply_text(
                f"✅ Task <code>#{task_id}</code> created, but couldn't notify @{selected_username}.\n\n"
                f"They may have blocked the bot.",
                reply_to_message_id=update.message.message_id,
                parse_mode='HTML'
            )

        # Clear the context
        del task_creation_context[user.id]
        return


async def auto_nudge_job(context: ContextTypes.DEFAULT_TYPE):
    """Automatic nudge job that runs periodically."""
    logger.info("Running auto-nudge job...")

    # Get all open tasks
    open_tasks = db.get_all_open_tasks()

    for task in open_tasks:
        created_date = datetime.fromisoformat(task['created_at'])
        days_old = (datetime.now() - created_date).days

        # Check if task is 3+ days old
        if days_old < 3:
            continue

        # Check if we've already sent a nudge recently
        if task['last_nudged_at']:
            last_nudge = datetime.fromisoformat(task['last_nudged_at'])
            days_since_nudge = (datetime.now() - last_nudge).days

            # Only nudge if it's been 3+ days since last nudge
            if days_since_nudge < 3:
                continue

        # Send auto-nudge
        nudge_message = (
            f"Hey {task['assigned_to']}, {task['created_by']} is waiting on: "
            f"\"{escape_html(task['description'])}\" (asked {days_old} day(s) ago). "
            f"Quick update?"
        )

        try:
            sent_message = await context.bot.send_message(
                chat_id=task['assigned_to_user_id'],
                text=nudge_message
            )

            # Store nudge context
            nudge_context[task['assigned_to_user_id']] = {
                'task_id': task['task_id'],
                'admin_id': task['created_by_user_id'],
                'admin_username': task['created_by'],
                'nudge_message_id': sent_message.message_id
            }

            # Update database
            db.update_nudge(task['task_id'])

            logger.info(f"Auto-nudge sent for task #{task['task_id']}")

        except Exception as e:
            logger.error(f"Error sending auto-nudge for task #{task['task_id']}: {e}")


def main():
    """Start the bot."""
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables!")
        return

    if not ADMIN_PASSWORD:
        logger.error("ADMIN_PASSWORD not found in environment variables!")
        return

    # Create application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("nudge", nudge_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("waiting", waiting_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("users", users_command))

    # Add callback query handler for pagination
    application.add_handler(CallbackQueryHandler(pagination_callback))

    # Add message handler for nudge replies
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    # Add auto-nudge job (runs every 6 hours)
    job_queue = application.job_queue
    if job_queue is not None:
        job_queue.run_repeating(
            auto_nudge_job,
            interval=timedelta(hours=6),
            first=timedelta(seconds=10)  # First run after 10 seconds
        )
        logger.info("Auto-nudge job scheduled")
    else:
        logger.warning("Job queue not available - auto-nudge disabled")

    # Start the bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
