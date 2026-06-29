import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
import sqlite3
import os
import sys
from datetime import datetime, timedelta

# ===== КОНФИГУРАЦИЯ =====
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YOUR_USER_ID = 1307172745
DB_NAME = "chat_bot.db"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Глобальные переменные
user_states = {}
tracked_chats = []
fixed_chats = []
BOT_USERNAME = None


# ===== БАЗА ДАННЫХ =====
def init_db():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_chats (
                user_id INTEGER,
                chat_id INTEGER,
                chat_title TEXT,
                chat_type TEXT,
                PRIMARY KEY (user_id, chat_id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_blocked BOOLEAN DEFAULT 0,
                last_message_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Базы данных инициализированы")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

def add_chat_to_db(user_id, chat_id, chat_title, chat_type):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO user_chats (user_id, chat_id, chat_title, chat_type) VALUES (?, ?, ?, ?)',
            (user_id, chat_id, chat_title, chat_type)
        )
        conn.commit()
        conn.close()
        logger.info(f"Чат добавлен: {chat_title} ({chat_id})")
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления чата: {e}")
        return False

def get_user_chats(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT chat_id, chat_title, chat_type FROM user_chats WHERE user_id = ? ORDER BY chat_title',
            (user_id,)
        )
        chats = cursor.fetchall()
        conn.close()
        return chats
    except Exception as e:
        logger.error(f"Ошибка получения чатов: {e}")
        return []

def remove_chat_from_db(user_id, chat_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления чата: {e}")
        return False

def add_user_to_db(user_id, username, first_name, last_name):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_message_time)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, username or '', first_name or '', last_name or ''))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления пользователя: {e}")
        return False

def get_user(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, last_name, is_blocked FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        return user
    except Exception as e:
        logger.error(f"Ошибка получения пользователя: {e}")
        return None

def block_user(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_blocked = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        logger.info(f"Пользователь {user_id} заблокирован")
        return True
    except Exception as e:
        logger.error(f"Ошибка блокировки пользователя: {e}")
        return False

def unblock_user(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_blocked = 0 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        logger.info(f"Пользователь {user_id} разблокирован")
        return True
    except Exception as e:
        logger.error(f"Ошибка разблокировки пользователя: {e}")
        return False

def get_all_users():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, first_name, last_name, is_blocked, last_message_time 
            FROM users 
            ORDER BY is_blocked DESC, last_message_time DESC
        ''')
        users = cursor.fetchall()
        conn.close()
        return users
    except Exception as e:
        logger.error(f"Ошибка получения пользователей: {e}")
        return []

def get_blocked_users():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, first_name, last_name, last_message_time 
            FROM users 
            WHERE is_blocked = 1
            ORDER BY last_message_time DESC
        ''')
        users = cursor.fetchall()
        conn.close()
        return users
    except Exception as e:
        logger.error(f"Ошибка получения заблокированных пользователей: {e}")
        return []

def cleanup_old_users(days=30):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM users 
            WHERE is_blocked = 0 
            AND last_message_time < datetime("now", "-? days")
        ''', (days,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logger.info(f"Удалено {deleted} старых НЕзаблокированных пользователей")
        return deleted
    except Exception as e:
        logger.error(f"Ошибка очистки пользователей: {e}")
        return 0


# ===== КЛАВИАТУРЫ =====
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 Список чатов", callback_data="list_chats")],
        [InlineKeyboardButton("👁 Отслеживание", callback_data="tracking_menu")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="users_menu")],
        [InlineKeyboardButton("🚫 Черный список", callback_data="blocked_menu")],
        [InlineKeyboardButton("🔄 Обновить чаты", callback_data="refresh_chats")]
    ]
    
    for chat_id in fixed_chats:
        chat_title = "Чат"
        for cid, title, ctype in get_user_chats(YOUR_USER_ID):
            if cid == chat_id:
                chat_title = title[:20]
                break
        keyboard.insert(0, [InlineKeyboardButton(f"⚡ {chat_title}", callback_data=f"quick_send_{chat_id}")])
    
    return InlineKeyboardMarkup(keyboard)

def get_quick_send_keyboard(chat_id):
    keyboard = [
        [InlineKeyboardButton("📝 Текст", callback_data=f"quick_text_{chat_id}")],
        [InlineKeyboardButton("📷 Фото", callback_data=f"quick_media_{chat_id}_photo")],
        [InlineKeyboardButton("🎥 Видео", callback_data=f"quick_media_{chat_id}_video")],
        [InlineKeyboardButton("📄 Документ", callback_data=f"quick_media_{chat_id}_document")],
        [InlineKeyboardButton("🎨 Стикер", callback_data=f"quick_media_{chat_id}_sticker")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_chats_keyboard(user_id, page=0, per_page=5):
    chats = get_user_chats(user_id)
    keyboard = []
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(chats))
    
    for chat_id, chat_title, chat_type in chats[start_idx:end_idx]:
        is_fixed = "⭐ " if chat_id in fixed_chats else ""
        is_tracking = "👁 " if chat_id in tracked_chats else ""
        keyboard.append([
            InlineKeyboardButton(
                f"{is_fixed}{is_tracking}{chat_title[:25]}", 
                callback_data=f"chat_{chat_id}"
            )
        ])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"page_{page-1}"))
    if end_idx < len(chats):
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_chat_actions_keyboard(chat_id):
    is_tracking = chat_id in tracked_chats
    is_fixed = chat_id in fixed_chats
    
    keyboard = []
    
    if is_tracking:
        keyboard.append([InlineKeyboardButton("🛑 Остановить отслеживание", callback_data=f"stop_track_{chat_id}")])
    else:
        keyboard.append([InlineKeyboardButton("👁 Начать отслеживание", callback_data=f"start_track_{chat_id}")])
    
    if is_fixed:
        keyboard.append([InlineKeyboardButton("⭐ Открепить", callback_data=f"unfix_chat_{chat_id}")])
    else:
        keyboard.append([InlineKeyboardButton("⭐ Закрепить", callback_data=f"fix_chat_{chat_id}")])
    
    keyboard.append([InlineKeyboardButton("📤 Отправить сообщение", callback_data=f"send_to_{chat_id}")])
    keyboard.append([InlineKeyboardButton("📝 Ответить на сообщение", callback_data=f"reply_in_chat_{chat_id}")])
    keyboard.append([InlineKeyboardButton("📜 Последние сообщения", callback_data=f"last_messages_{chat_id}")])
    keyboard.append([InlineKeyboardButton("🗑 Удалить чат", callback_data=f"delete_{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="list_chats")])
    
    return InlineKeyboardMarkup(keyboard)

def get_tracking_keyboard():
    chats = get_user_chats(YOUR_USER_ID)
    keyboard = []
    
    for chat_id, chat_title, chat_type in chats:
        is_tracking = "🟢" if chat_id in tracked_chats else "⚪️"
        keyboard.append([
            InlineKeyboardButton(
                f"{is_tracking} {chat_title[:30]}", 
                callback_data=f"chat_{chat_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_users_keyboard(page=0, per_page=10):
    users = get_all_users()
    keyboard = []
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(users))
    
    for user in users[start_idx:end_idx]:
        user_id, username, first_name, last_name, is_blocked, last_time = user
        name = first_name or "Без имени"
        status = "🚫" if is_blocked else "✅"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {name} (@{username or 'нет'})", 
                callback_data=f"user_{user_id}"
            )
        ])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"users_page_{page-1}"))
    if end_idx < len(users):
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"users_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_blocked_keyboard(page=0, per_page=10):
    users = get_blocked_users()
    keyboard = []
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(users))
    
    for user in users[start_idx:end_idx]:
        user_id, username, first_name, last_name, last_time = user
        name = first_name or "Без имени"
        keyboard.append([
            InlineKeyboardButton(
                f"🚫 {name} (@{username or 'нет'})", 
                callback_data=f"user_{user_id}"
            )
        ])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"blocked_page_{page-1}"))
    if end_idx < len(users):
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"blocked_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_user_actions_keyboard(user_id):
    user = get_user(user_id)
    if not user:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="users_menu")]])
    
    is_blocked = user[4]
    
    keyboard = []
    
    if is_blocked:
        keyboard.append([InlineKeyboardButton("✅ Разблокировать", callback_data=f"unblock_user_{user_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")])
    
    keyboard.append([InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="users_menu")])
    
    return InlineKeyboardMarkup(keyboard)

def get_last_messages_keyboard(chat_id, messages):
    keyboard = []
    for i, (msg_id, text, user_name) in enumerate(messages[:10], 1):
        keyboard.append([
            InlineKeyboardButton(
                f"{i}. {user_name}: {text[:30]}", 
                callback_data=f"reply_msg_{chat_id}_{msg_id}"
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"chat_{chat_id}")])
    return InlineKeyboardMarkup(keyboard)


# ===== ОБРАБОТЧИКИ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_USERNAME
    
    user_id = update.effective_user.id
    
    if not BOT_USERNAME:
        bot_info = await context.bot.get_me()
        BOT_USERNAME = bot_info.username
    
    if user_id != YOUR_USER_ID:
        user = update.effective_user
        add_user_to_db(user_id, user.username, user.first_name, user.last_name)
        
        user_data = get_user(user_id)
        if user_data and user_data[4] == 1:
            logger.info(f"Заблокированный пользователь {user_id} написал боту")
            return
        
        try:
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=f"👤 <b>Новый пользователь</b>\n\n"
                     f"🆔 ID: <code>{user_id}</code>\n"
                     f"📛 Имя: {user.first_name or 'Нет'}\n"
                     f"🔗 Юзернейм: @{user.username or 'Нет'}\n"
                     f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")],
                    [InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")]
                ])
            )
        except:
            pass
        
        return
    
    await update.message.reply_text(
        "👋 <b>Главное меню</b>\n\n"
        "Выберите действие:",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global fixed_chats, tracked_chats
    
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return
    
    data = query.data
    
    if data == "main_menu":
        await query.edit_message_text(
            "👋 <b>Главное меню</b>\n\nВыберите действие:",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    
    elif data == "users_menu":
        users = get_all_users()
        if not users:
            await query.edit_message_text(
                "👥 <b>Нет пользователей</b>\n\nПока никто не писал боту.",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
            )
            return
        
        await query.edit_message_text(
            f"👥 <b>Пользователи</b> ({len(users)})\n\n"
            "✅ - активен\n🚫 - заблокирован",
            parse_mode='HTML',
            reply_markup=get_users_keyboard()
        )
    
    elif data.startswith("users_page_"):
        page = int(data.split("_")[2])
        await query.edit_message_text(
            "👥 <b>Пользователи</b>\n\n✅ - активен\n🚫 - заблокирован",
            parse_mode='HTML',
            reply_markup=get_users_keyboard(page)
        )
    
    elif data == "blocked_menu":
        blocked_users = get_blocked_users()
        if not blocked_users:
            await query.edit_message_text(
                "🚫 <b>Черный список пуст</b>\n\nНет заблокированных пользователей.",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
            )
            return
        
        await query.edit_message_text(
            f"🚫 <b>Черный список</b> ({len(blocked_users)})\n\n"
            "Нажмите на пользователя для разблокировки:",
            parse_mode='HTML',
            reply_markup=get_blocked_keyboard()
        )
    
    elif data.startswith("blocked_page_"):
        page = int(data.split("_")[2])
        await query.edit_message_text(
            "🚫 <b>Черный список</b>",
            parse_mode='HTML',
            reply_markup=get_blocked_keyboard(page)
        )
    
    elif data.startswith("user_"):
        user_id = int(data.split("_")[1])
        user = get_user(user_id)
        if not user:
            await query.edit_message_text("❌ Пользователь не найден", reply_markup=get_main_keyboard())
            return
        
        user_id, username, first_name, last_name, is_blocked = user
        
        text = f"👤 <b>Информация о пользователе</b>\n\n"
        text += f"🆔 ID: <code>{user_id}</code>\n"
        text += f"📛 Имя: {first_name or 'Нет'}\n"
        text += f"🔗 Юзернейм: @{username or 'Нет'}\n"
        text += f"📊 Статус: {'🚫 Заблокирован' if is_blocked else '✅ Активен'}"
        
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=get_user_actions_keyboard(user_id)
        )
    
    elif data.startswith("block_user_"):
        user_id = int(data.split("_")[2])
        if block_user(user_id):
            await query.edit_message_text(
                f"🚫 <b>Пользователь заблокирован</b>\n\nID: <code>{user_id}</code>",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )
        else:
            await query.edit_message_text("❌ Ошибка блокировки", reply_markup=get_main_keyboard())
    
    elif data.startswith("unblock_user_"):
        user_id = int(data.split("_")[2])
        if unblock_user(user_id):
            await query.edit_message_text(
                f"✅ <b>Пользователь разблокирован</b>\n\nID: <code>{user_id}</code>",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )
        else:
            await query.edit_message_text("❌ Ошибка разблокировки", reply_markup=get_main_keyboard())
    
    elif data.startswith("reply_user_"):
        user_id = int(data.split("_")[2])
        user_states[YOUR_USER_ID] = {'action': 'reply_to_user', 'user_id': user_id}
        await query.edit_message_text(
            f"✏️ <b>Ответ пользователю</b>\n\n"
            f"ID: <code>{user_id}</code>\n\n"
            "Отправьте текст, фото, видео, документ или стикер.\n"
            "Бот автоматически определит тип.\n\n"
            "Нажмите 🔙 Назад чтобы выйти",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
        )
    
    elif data == "tracking_menu":
        await query.edit_message_text(
            "👁 <b>Управление отслеживанием</b>\n\n"
            "🟢 - отслеживается\n"
            "⚪️ - не отслеживается\n\n"
            "Выберите чат:",
            parse_mode='HTML',
            reply_markup=get_tracking_keyboard()
        )
    
    elif data.startswith("quick_send_"):
        chat_id = int(data.split("_")[2])
        chat_title = "Чат"
        for cid, title, ctype in get_user_chats(user_id):
            if cid == chat_id:
                chat_title = title
                break
        
        await query.edit_message_text(
            f"⚡ <b>Быстрая отправка</b>\n\n"
            f"📌 {chat_title}\n"
            f"<code>ID: {chat_id}</code>\n\n"
            f"Выберите что отправить:",
            parse_mode='HTML',
            reply_markup=get_quick_send_keyboard(chat_id)
        )
    
    elif data.startswith("quick_text_"):
        chat_id = int(data.split("_")[2])
        user_states[user_id] = {'action': 'send_message', 'chat_id': chat_id}
        await query.edit_message_text(
            f"✏️ <b>Режим отправки текста</b>\n\n"
            f"Чат: <code>{chat_id}</code>\n\n"
            "Теперь можете писать текст.\n"
            "Сообщения будут уходить в этот чат.\n\n"
            "Нажмите 🔙 Назад чтобы выйти",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
        )
    
    elif data.startswith("quick_media_"):
        parts = data.split("_")
        chat_id = int(parts[2])
        media_type = parts[3]
        
        user_states[user_id] = {
            'action': 'send_media',
            'chat_id': chat_id,
            'media_type': media_type
        }
        
        emoji = {"photo": "📷", "video": "🎥", "document": "📄", "sticker": "🎨"}.get(media_type, "📎")
        await query.edit_message_text(
            f"{emoji} <b>Режим отправки {media_type}</b>\n\n"
            f"Чат: <code>{chat_id}</code>\n\n"
            f"Отправьте {media_type}.\n\n"
            "Нажмите 🔙 Назад чтобы выйти",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
        )
    
    elif data == "list_chats":
        await show_chats(query, user_id, 0)
    
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        await show_chats(query, user_id, page)
    
    elif data.startswith("chat_"):
        chat_id = int(data.split("_")[1])
        await show_chat_actions(query, user_id, chat_id)
    
    elif data.startswith("fix_chat_"):
        chat_id = int(data.split("_")[2])
        if chat_id not in fixed_chats:
            fixed_chats.append(chat_id)
        
        await query.edit_message_text(
            f"⭐ <b>Чат закреплен</b>\n\n"
            f"Теперь он в главном меню",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    
    elif data.startswith("unfix_chat_"):
        chat_id = int(data.split("_")[2])
        if chat_id in fixed_chats:
            fixed_chats.remove(chat_id)
        
        await query.edit_message_text(
            f"⭐ <b>Чат откреплен</b>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    
    elif data.startswith("start_track_"):
        chat_id = int(data.split("_")[2])
        if chat_id not in tracked_chats:
            tracked_chats.append(chat_id)
            logger.info(f"Начато отслеживание чата {chat_id}")
            
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=f"🟢 Начато отслеживание чата {chat_id}"
            )
        
        await show_chat_actions(query, user_id, chat_id)
    
    elif data.startswith("stop_track_"):
        chat_id = int(data.split("_")[2])
        if chat_id in tracked_chats:
            tracked_chats.remove(chat_id)
            logger.info(f"Остановлено отслеживание чата {chat_id}")
            
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=f"🔴 Остановлено отслеживание чата {chat_id}"
            )
        
        await show_chat_actions(query, user_id, chat_id)
    
    elif data.startswith("send_to_"):
        chat_id = int(data.split("_")[2])
        user_states[user_id] = {'action': 'send_any', 'chat_id': chat_id}
        await query.edit_message_text(
            f"📤 <b>Режим отправки</b>\n\n"
            f"Чат: <code>{chat_id}</code>\n\n"
            "Теперь можете отправлять ЛЮБЫЕ сообщения:\n"
            "✅ Текст\n✅ Фото\n✅ Видео\n✅ Документ\n✅ Стикер\n\n"
            "Бот сам определит тип.\n\n"
            "Нажмите 🔙 Назад чтобы выйти",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
        )
    
    elif data.startswith("reply_in_chat_"):
        chat_id = int(data.split("_")[2])
        try:
            updates = await context.bot.get_updates(limit=20)
            messages = []
            for update in updates:
                if update.message and update.message.chat.id == chat_id:
                    msg_text = update.message.text or "Медиа"
                    user_name = update.message.from_user.first_name or "Unknown"
                    messages.append((update.message.message_id, msg_text[:50], user_name))
            
            if not messages:
                await query.edit_message_text(
                    "📭 <b>Нет сообщений</b>\n\n"
                    "В этом чате пока нет сообщений",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"chat_{chat_id}")]])
                )
                return
            
            await query.edit_message_text(
                "📝 <b>Выберите сообщение для ответа</b>\n\n"
                "Нажмите на сообщение, на которое хотите ответить:",
                parse_mode='HTML',
                reply_markup=get_last_messages_keyboard(chat_id, messages)
            )
        except Exception as e:
            logger.error(f"Ошибка получения сообщений: {e}")
            await query.edit_message_text(
                f"❌ Ошибка: {e}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"chat_{chat_id}")]])
            )
    
    elif data.startswith("reply_msg_"):
        parts = data.split("_")
        chat_id = int(parts[2])
        message_id = int(parts[3])
        
        user_states[YOUR_USER_ID] = {'action': 'reply_in_chat', 'chat_id': chat_id, 'message_id': message_id}
        
        await query.edit_message_text(
            f"✏️ <b>Напишите ответ</b>\n\n"
            f"Чат: <code>{chat_id}</code>\n"
            f"Сообщение ID: <code>{message_id}</code>\n\n"
            "Отправьте текст, фото, видео, документ или стикер\n\n"
            "Нажмите 🔙 Назад чтобы выйти",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
        )
    
    elif data.startswith("last_messages_"):
        chat_id = int(data.split("_")[2])
        try:
            updates = await context.bot.get_updates(limit=20)
            messages = []
            for update in updates:
                if update.message and update.message.chat.id == chat_id:
                    msg_text = update.message.text or "Медиа"
                    user_name = update.message.from_user.first_name or "Unknown"
                    messages.append((update.message.message_id, msg_text[:50], user_name))
            
            if not messages:
                await query.edit_message_text(
                    "📭 <b>Нет сообщений</b>",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"chat_{chat_id}")]])
                )
                return
            
            text = f"📜 <b>Последние сообщения</b>\n\n"
            for i, (msg_id, msg_text, user_name) in enumerate(messages[:10], 1):
                text += f"{i}. {user_name}: {msg_text}\n"
            
            await query.edit_message_text(
                text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"chat_{chat_id}")]])
            )
        except Exception as e:
            await query.edit_message_text(
                f"❌ Ошибка: {e}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"chat_{chat_id}")]])
            )
    
    elif data.startswith("delete_"):
        chat_id = int(data.split("_")[1])
        remove_chat_from_db(user_id, chat_id)
        if chat_id in fixed_chats:
            fixed_chats.remove(chat_id)
        if chat_id in tracked_chats:
            tracked_chats.remove(chat_id)
        
        await query.edit_message_text(
            f"🗑 <b>Чат удален</b>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    
    elif data == "refresh_chats":
        await query.edit_message_text(
            "🔄 <b>Обновление чатов...</b>",
            parse_mode='HTML'
        )
        await refresh_all_chats(query, context)


async def show_chats(query, user_id, page):
    chats = get_user_chats(user_id)
    
    if not chats:
        await query.edit_message_text(
            "📭 <b>Нет сохраненных чатов</b>\n\n"
            "Чтобы добавить чат:\n"
            "1. Добавьте бота в чат\n"
            "2. Напишите любое сообщение в чате\n"
            "3. Нажмите 'Обновить чаты'",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
        return
    
    total = len(chats)
    text = f"📋 <b>Ваши чаты</b> ({total})\n\n"
    
    start_idx = page * 5
    end_idx = min(start_idx + 5, total)
    
    for chat_id, chat_title, chat_type in chats[start_idx:end_idx]:
        emoji = "👥" if chat_type == "group" else "👤"
        is_fixed = "⭐ " if chat_id in fixed_chats else ""
        is_tracking = "👁 " if chat_id in tracked_chats else ""
        text += f"{is_fixed}{is_tracking}{emoji} {chat_title}\n<code>{chat_id}</code>\n\n"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=get_chats_keyboard(user_id, page)
    )


async def show_chat_actions(query, user_id, chat_id):
    chats = get_user_chats(user_id)
    chat_info = next((c for c in chats if c[0] == chat_id), None)
    
    if chat_info:
        title = chat_info[1]
        text = f"📌 <b>{title}</b>\n\n<code>ID: {chat_id}</code>\n\n"
    else:
        text = f"📌 <b>Чат</b>\n\n<code>ID: {chat_id}</code>\n\n"
    
    is_tracking = chat_id in tracked_chats
    is_fixed = chat_id in fixed_chats
    
    status = "🟢 Отслеживается" if is_tracking else "⚪️ Не отслеживается"
    fixed = "⭐ Закреплен" if is_fixed else "⚪️ Не закреплен"
    text += f"{status}\n{fixed}"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=get_chat_actions_keyboard(chat_id)
    )


async def send_tracking_notification(context, chat, user, message_text, file_id=None, file_type=None, is_reply_to_bot=False):
    username = user.username or "Нет"
    first_name = user.first_name or "Нет"
    user_id = user.id
    time = datetime.now().strftime("%H:%M:%S")
    user_info = f"@{username}" if username != "Нет" else first_name
    
    if is_reply_to_bot:
        label = "🤖 <b>ОТВЕТ БОТУ</b>"
    else:
        label = "💬 <b>ОБЫЧНОЕ СООБЩЕНИЕ</b>"
    
    notification = (
        f"📨 <b>Отслеживание</b>\n"
        f"{label}\n\n"
        f"📌 {chat.title}\n"
        f"👤 {user_info} (ID: {user_id})\n"
        f"💬 {message_text}\n"
        f"🕐 {time}"
    )
    
    try:
        if file_type == "photo":
            await context.bot.send_photo(
                chat_id=YOUR_USER_ID,
                photo=file_id,
                caption=notification[:1024],
                parse_mode='HTML'
            )
        elif file_type == "video":
            await context.bot.send_video(
                chat_id=YOUR_USER_ID,
                video=file_id,
                caption=notification[:1024],
                parse_mode='HTML'
            )
        elif file_type == "document":
            await context.bot.send_document(
                chat_id=YOUR_USER_ID,
                document=file_id,
                caption=notification[:1024],
                parse_mode='HTML'
            )
        elif file_type == "audio":
            await context.bot.send_audio(
                chat_id=YOUR_USER_ID,
                audio=file_id,
                caption=notification[:1024],
                parse_mode='HTML'
            )
        elif file_type == "voice":
            await context.bot.send_voice(
                chat_id=YOUR_USER_ID,
                voice=file_id,
                caption=notification[:1024],
                parse_mode='HTML'
            )
        elif file_type == "sticker":
            await context.bot.send_sticker(
                chat_id=YOUR_USER_ID,
                sticker=file_id
            )
        else:
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=notification,
                parse_mode='HTML'
            )
        logger.info(f"Уведомление отправлено для чата {chat.id}")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")


async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_USERNAME, fixed_chats, tracked_chats
    
    user_id = update.effective_user.id
    chat = update.effective_chat
    chat_id = chat.id
    chat_type = chat.type
    
    if not BOT_USERNAME:
        bot_info = await context.bot.get_me()
        BOT_USERNAME = bot_info.username
    
    logger.info(f"📩 Сообщение от {user_id} в {chat_id} ({chat_type})")
    
    # ===== ЛИЧНЫЙ ЧАТ С БОТОМ (НЕ ВЛАДЕЛЕЦ) =====
    if chat_type == "private" and user_id != YOUR_USER_ID:
        user = update.effective_user
        add_user_to_db(user_id, user.username, user.first_name, user.last_name)
        
        # ПРОВЕРКА НА БЛОКИРОВКУ
        user_data = get_user(user_id)
        if user_data and user_data[4] == 1:
            logger.info(f"Заблокированный пользователь {user_id} написал боту - ИГНОРИРУЕМ")
            return  # МОЛЧА ИГНОРИРУЕМ
        
        message_text = "Медиа"
        file_id = None
        file_type = None
        
        if update.message.text:
            message_text = update.message.text
        elif update.message.photo:
            message_text = "📷 Фото"
            file_id = update.message.photo[-1].file_id
            file_type = "photo"
        elif update.message.video:
            message_text = "🎥 Видео"
            file_id = update.message.video.file_id
            file_type = "video"
        elif update.message.document:
            message_text = f"📄 {update.message.document.file_name or 'Документ'}"
            file_id = update.message.document.file_id
            file_type = "document"
        elif update.message.sticker:
            message_text = "🎨 Стикер"
            file_id = update.message.sticker.file_id
            file_type = "sticker"
        elif update.message.audio:
            message_text = "🎵 Аудио"
            file_id = update.message.audio.file_id
            file_type = "audio"
        elif update.message.voice:
            message_text = "🎤 Голосовое"
            file_id = update.message.voice.file_id
            file_type = "voice"
        
        try:
            notification = (
                f"👤 <b>Сообщение от пользователя</b>\n\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"📛 Имя: {user.first_name or 'Нет'}\n"
                f"🔗 Юзернейм: @{user.username or 'Нет'}\n"
                f"💬 {message_text}\n"
                f"🕐 {datetime.now().strftime('%H:%M:%S')}"
            )
            
            if file_type == "photo":
                await context.bot.send_photo(
                    chat_id=YOUR_USER_ID,
                    photo=file_id,
                    caption=notification[:1024],
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")],
                        [InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")]
                    ])
                )
            elif file_type == "sticker":
                await context.bot.send_sticker(
                    chat_id=YOUR_USER_ID,
                    sticker=file_id
                )
                await context.bot.send_message(
                    chat_id=YOUR_USER_ID,
                    text=notification,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")],
                        [InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")]
                    ])
                )
            elif file_type in ["video", "document", "audio", "voice"]:
                if file_type == "video":
                    await context.bot.send_video(
                        chat_id=YOUR_USER_ID,
                        video=file_id,
                        caption=notification[:1024],
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")],
                            [InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")]
                        ])
                    )
                elif file_type == "document":
                    await context.bot.send_document(
                        chat_id=YOUR_USER_ID,
                        document=file_id,
                        caption=notification[:1024],
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")],
                            [InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")]
                        ])
                    )
                elif file_type == "audio":
                    await context.bot.send_audio(
                        chat_id=YOUR_USER_ID,
                        audio=file_id,
                        caption=notification[:1024],
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")],
                            [InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")]
                        ])
                    )
                elif file_type == "voice":
                    await context.bot.send_voice(
                        chat_id=YOUR_USER_ID,
                        voice=file_id,
                        caption=notification[:1024],
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")],
                            [InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")]
                        ])
                    )
            else:
                await context.bot.send_message(
                    chat_id=YOUR_USER_ID,
                    text=notification,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")],
                        [InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")]
                    ])
                )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")
        
        return
    
    # ===== ГРУППОВЫЕ ЧАТЫ =====
    if chat_type in ["group", "supergroup"]:
        chat_title = chat.title or "Без названия"
        
        if user_id == YOUR_USER_ID:
            if add_chat_to_db(YOUR_USER_ID, chat_id, chat_title, chat_type):
                await context.bot.send_message(
                    chat_id=YOUR_USER_ID,
                    text=f"✅ Чат добавлен: {chat_title}\nID: <code>{chat_id}</code>",
                    parse_mode='HTML'
                )
        
        # ===== ОТСЛЕЖИВАНИЕ =====
        if chat_id in tracked_chats:
            user = update.effective_user
            
            is_reply_to_bot = False
            if update.message and update.message.reply_to_message:
                reply_to = update.message.reply_to_message
                if reply_to.from_user and reply_to.from_user.is_bot:
                    if reply_to.from_user.username == BOT_USERNAME:
                        is_reply_to_bot = True
            
            message_text = ""
            file_id = None
            file_type = None
            
            if update.message:
                if update.message.text:
                    message_text = update.message.text
                elif update.message.photo:
                    message_text = "📷 Фото"
                    file_id = update.message.photo[-1].file_id
                    file_type = "photo"
                elif update.message.video:
                    message_text = "🎥 Видео"
                    file_id = update.message.video.file_id
                    file_type = "video"
                elif update.message.document:
                    message_text = f"📄 {update.message.document.file_name or 'Документ'}"
                    file_id = update.message.document.file_id
                    file_type = "document"
                elif update.message.sticker:
                    message_text = "🎨 Стикер"
                    file_id = update.message.sticker.file_id
                    file_type = "sticker"
                elif update.message.audio:
                    message_text = "🎵 Аудио"
                    file_id = update.message.audio.file_id
                    file_type = "audio"
                elif update.message.voice:
                    message_text = "🎤 Голосовое"
                    file_id = update.message.voice.file_id
                    file_type = "voice"
                else:
                    message_text = "📎 Другое сообщение"
                
                await send_tracking_notification(
                    context, chat, user, message_text, 
                    file_id, file_type, is_reply_to_bot
                )
        
        return
    
    # ===== ПРИВАТНЫЙ ЧАТ С ВЛАДЕЛЬЦЕМ =====
    if chat_type == "private" and user_id == YOUR_USER_ID:
        # Если есть состояние - обрабатываем
        if user_id in user_states:
            state = user_states[user_id]
            action = state['action']
            
            # Отправка текста
            if action == 'send_message' and update.message and update.message.text:
                chat_id = state['chat_id']
                try:
                    await context.bot.send_message(chat_id=chat_id, text=update.message.text)
                    await update.message.reply_text(f"✅ Отправлено")
                    # НЕ удаляем состояние, чтобы можно было продолжать писать
                except Exception as e:
                    await update.message.reply_text(f"❌ Ошибка: {e}")
                return
            
            # Отправка любого медиа
            elif action == 'send_any' and update.message:
                chat_id = state['chat_id']
                try:
                    if update.message.text:
                        await context.bot.send_message(chat_id=chat_id, text=update.message.text)
                    elif update.message.photo:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=update.message.photo[-1].file_id,
                            caption=update.message.caption
                        )
                    elif update.message.video:
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=update.message.video.file_id,
                            caption=update.message.caption
                        )
                    elif update.message.document:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=update.message.document.file_id,
                            caption=update.message.caption
                        )
                    elif update.message.sticker:
                        await context.bot.send_sticker(
                            chat_id=chat_id,
                            sticker=update.message.sticker.file_id
                        )
                    elif update.message.audio:
                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=update.message.audio.file_id,
                            caption=update.message.caption
                        )
                    elif update.message.voice:
                        await context.bot.send_voice(
                            chat_id=chat_id,
                            voice=update.message.voice.file_id,
                            caption=update.message.caption
                        )
                    else:
                        await update.message.reply_text("❌ Неподдерживаемый тип")
                        return
                    
                    await update.message.reply_text("✅ Отправлено")
                    # НЕ удаляем состояние
                except Exception as e:
                    await update.message.reply_text(f"❌ Ошибка: {e}")
                return
            
            # Отправка медиа (конкретный тип)
            elif action == 'send_media' and update.message:
                chat_id = state['chat_id']
                media_type = state['media_type']
                
                try:
                    if media_type == "photo" and update.message.photo:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=update.message.photo[-1].file_id,
                            caption=update.message.caption
                        )
                        await update.message.reply_text("✅ Фото отправлено")
                    elif media_type == "video" and update.message.video:
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=update.message.video.file_id,
                            caption=update.message.caption
                        )
                        await update.message.reply_text("✅ Видео отправлено")
                    elif media_type == "document" and update.message.document:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=update.message.document.file_id,
                            caption=update.message.caption
                        )
                        await update.message.reply_text("✅ Документ отправлен")
                    elif media_type == "sticker" and update.message.sticker:
                        await context.bot.send_sticker(
                            chat_id=chat_id,
                            sticker=update.message.sticker.file_id
                        )
                        await update.message.reply_text("✅ Стикер отправлен")
                    else:
                        await update.message.reply_text(f"❌ Отправьте {media_type}")
                        return
                    # НЕ удаляем состояние
                except Exception as e:
                    await update.message.reply_text(f"❌ Ошибка: {e}")
                return
            
            # Ответ пользователю
            elif action == 'reply_to_user' and update.message:
                target_user_id = state['user_id']
                try:
                    if update.message.text:
                        await context.bot.send_message(chat_id=target_user_id, text=update.message.text)
                    elif update.message.photo:
                        await context.bot.send_photo(
                            chat_id=target_user_id,
                            photo=update.message.photo[-1].file_id,
                            caption=update.message.caption
                        )
                    elif update.message.video:
                        await context.bot.send_video(
                            chat_id=target_user_id,
                            video=update.message.video.file_id,
                            caption=update.message.caption
                        )
                    elif update.message.document:
                        await context.bot.send_document(
                            chat_id=target_user_id,
                            document=update.message.document.file_id,
                            caption=update.message.caption
                        )
                    elif update.message.sticker:
                        await context.bot.send_sticker(
                            chat_id=target_user_id,
                            sticker=update.message.sticker.file_id
                        )
                    elif update.message.audio:
                        await context.bot.send_audio(
                            chat_id=target_user_id,
                            audio=update.message.audio.file_id,
                            caption=update.message.caption
                        )
                    elif update.message.voice:
                        await context.bot.send_voice(
                            chat_id=target_user_id,
                            voice=update.message.voice.file_id,
                            caption=update.message.caption
                        )
                    else:
                        await update.message.reply_text("❌ Неподдерживаемый тип")
                        return
                    
                    await update.message.reply_text("✅ Отправлено пользователю")
                    # НЕ удаляем состояние
                except Exception as e:
                    await update.message.reply_text(f"❌ Ошибка: {e}")
                return
            
            # Ответ на сообщение в чате
            elif action == 'reply_in_chat' and update.message:
                chat_id = state['chat_id']
                message_id = state['message_id']
                
                try:
                    if update.message.text:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=update.message.text,
                            reply_to_message_id=message_id
                        )
                    elif update.message.photo:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=update.message.photo[-1].file_id,
                            caption=update.message.caption,
                            reply_to_message_id=message_id
                        )
                    elif update.message.video:
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=update.message.video.file_id,
                            caption=update.message.caption,
                            reply_to_message_id=message_id
                        )
                    elif update.message.document:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=update.message.document.file_id,
                            caption=update.message.caption,
                            reply_to_message_id=message_id
                        )
                    elif update.message.sticker:
                        await context.bot.send_sticker(
                            chat_id=chat_id,
                            sticker=update.message.sticker.file_id,
                            reply_to_message_id=message_id
                        )
                    else:
                        await update.message.reply_text("❌ Неподдерживаемый тип")
                        return
                    
                    await update.message.reply_text("✅ Ответ отправлен")
                    # НЕ удаляем состояние
                except Exception as e:
                    await update.message.reply_text(f"❌ Ошибка: {e}")
                return
        
        # Если нет состояния - показываем меню
        if not update.message or not update.message.text or not update.message.text.startswith('/'):
            await update.message.reply_text(
                "👋 <b>Главное меню</b>\n\nВыберите действие:",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )


async def refresh_all_chats(query, context):
    try:
        deleted = cleanup_old_users(30)
        
        chats = get_user_chats(YOUR_USER_ID)
        users = get_all_users()
        blocked = get_blocked_users()
        
        try:
            updates = await context.bot.get_updates(limit=50)
            added = 0
            for update in updates:
                if update.message and update.message.chat:
                    chat = update.message.chat
                    if chat.type in ["group", "supergroup"]:
                        if add_chat_to_db(YOUR_USER_ID, chat.id, chat.title, chat.type):
                            added += 1
            if added > 0:
                logger.info(f"Добавлено {added} новых чатов")
        except Exception as e:
            logger.error(f"Ошибка сканирования: {e}")
        
        await query.edit_message_text(
            f"✅ <b>Обновлено</b>\n\n"
            f"📋 Чатов: {len(chats)}\n"
            f"👥 Всего пользователей: {len(users)}\n"
            f"🚫 В черном списке: {len(blocked)}\n"
            f"🗑 Удалено старых (незаблокированных): {deleted}\n\n"
            f"<i>Заблокированные пользователи хранятся вечно</i>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка обновления: {e}")
        await query.edit_message_text(
            f"❌ Ошибка: {str(e)}",
            reply_markup=get_main_keyboard()
        )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")


# ===== ЗАПУСК =====
def main():
    try:
        print("=" * 50)
        print("Запуск Telegram бота...")
        print("=" * 50)
        
        if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
            print("❌ ОШИБКА: Замените TOKEN на ваш реальный токен!")
            return
        
        init_db()
        
        application = Application.builder().token(TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(handle_callback))
        application.add_handler(MessageHandler(filters.ALL, handle_all_messages))
        application.add_error_handler(error_handler)
        
        print("✅ Бот успешно запущен!")
        print("=" * 50)
        print("📌 ФУНКЦИИ:")
        print("  ⭐ Закрепление нескольких чатов")
        print("  👁 Отслеживание с пометками")
        print("  👥 Личный чат с пользователями")
        print("  📝 Ответ на сообщение с цитатой")
        print("  🎨 Отправка стикеров")
        print("  🚫 Блокировка пользователей (РАБОТАЕТ)")
        print("  📤 Отправка любых медиа (без выхода из режима)")
        print("  🗑 Автоочистка (только незаблокированных)")
        print("=" * 50)
        print("🔄 Ожидание сообщений...")
        print("❌ Чтобы остановить бота, нажмите Ctrl+C")
        print("=" * 50)
        
        application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}")
        print(f"❌ Критическая ошибка: {e}")

if __name__ == "__main__":
    main()
