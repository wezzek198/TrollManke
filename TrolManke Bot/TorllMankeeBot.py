import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
import sqlite3
import os
import sys
import asyncio
from datetime import datetime

# ===== КОНФИГУРАЦИЯ =====
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YOUR_USER_ID = 1307172745
DB_NAME = "chat_bot.db"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,  # Меняем на DEBUG для детального лога
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
                is_blocked INTEGER DEFAULT 0,
                last_message_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Базы данных инициализированы")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False

def is_user_blocked(user_id):
    """Проверка блокировки с логированием"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT is_blocked FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            blocked = result[0] == 1
            logger.info(f"🔍 Проверка блокировки {user_id}: {'ЗАБЛОКИРОВАН' if blocked else 'НЕ ЗАБЛОКИРОВАН'}")
            return blocked
        logger.info(f"🔍 Пользователь {user_id} не найден в БД")
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки блокировки: {e}")
        return False

def block_user(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Сначала проверяем есть ли пользователь
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute('UPDATE users SET is_blocked = 1 WHERE user_id = ?', (user_id,))
        else:
            cursor.execute('INSERT INTO users (user_id, is_blocked) VALUES (?, 1)', (user_id,))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Пользователь {user_id} ЗАБЛОКИРОВАН")
        
        # Проверяем что блокировка применилась
        if is_user_blocked(user_id):
            logger.info(f"✅ Блокировка {user_id} ПОДТВЕРЖДЕНА")
            return True
        else:
            logger.error(f"❌ Блокировка {user_id} НЕ ПОДТВЕРДИЛАСЬ")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка блокировки: {e}")
        return False

def unblock_user(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_blocked = 0 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        logger.info(f"✅ Пользователь {user_id} РАЗБЛОКИРОВАН")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки: {e}")
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
        logger.error(f"❌ Ошибка добавления пользователя: {e}")
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
        logger.error(f"❌ Ошибка получения пользователя: {e}")
        return None

def get_all_users():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, last_name, is_blocked, last_message_time FROM users ORDER BY is_blocked DESC, last_message_time DESC')
        users = cursor.fetchall()
        conn.close()
        
        # Логируем состояние
        for u in users:
            logger.info(f"👤 Пользователь {u[0]}: {'ЗАБЛОКИРОВАН' if u[4] else 'АКТИВЕН'}")
        return users
    except Exception as e:
        logger.error(f"❌ Ошибка получения пользователей: {e}")
        return []

def get_blocked_users():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, last_name, last_message_time FROM users WHERE is_blocked = 1 ORDER BY last_message_time DESC')
        users = cursor.fetchall()
        conn.close()
        return users
    except Exception as e:
        logger.error(f"❌ Ошибка получения заблокированных: {e}")
        return []

def chat_exists(user_id, chat_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM user_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    except Exception as e:
        logger.error(f"❌ Ошибка проверки чата: {e}")
        return False

def add_chat_to_db(user_id, chat_id, chat_title, chat_type):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO user_chats (user_id, chat_id, chat_title, chat_type) VALUES (?, ?, ?, ?)',
                      (user_id, chat_id, chat_title, chat_type))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка добавления чата: {e}")
        return False

def get_user_chats(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT chat_id, chat_title, chat_type FROM user_chats WHERE user_id = ? ORDER BY chat_title', (user_id,))
        chats = cursor.fetchall()
        conn.close()
        return chats
    except Exception as e:
        logger.error(f"❌ Ошибка получения чатов: {e}")
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
        logger.error(f"❌ Ошибка удаления чата: {e}")
        return False


# ===== КЛАВИАТУРЫ (сокращенно) =====
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

def get_back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в меню", callback_data="exit_mode")]])

def get_reply_keyboard(chat_id, message_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton("📝 Ответить", callback_data=f"reply_msg_{chat_id}_{message_id}")]])

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
        keyboard.append([InlineKeyboardButton(f"{is_fixed}{is_tracking}{chat_title[:25]}", callback_data=f"chat_{chat_id}")])
    
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
    keyboard.append([InlineKeyboardButton("🗑 Удалить чат", callback_data=f"delete_{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="list_chats")])
    
    return InlineKeyboardMarkup(keyboard)

def get_tracking_keyboard():
    chats = get_user_chats(YOUR_USER_ID)
    keyboard = []
    for chat_id, chat_title, chat_type in chats:
        is_tracking = "🟢" if chat_id in tracked_chats else "⚪️"
        keyboard.append([InlineKeyboardButton(f"{is_tracking} {chat_title[:30]}", callback_data=f"chat_{chat_id}")])
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
        keyboard.append([InlineKeyboardButton(f"{status} {name} (@{username or 'нет'})", callback_data=f"user_{user_id}")])
    
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
        keyboard.append([InlineKeyboardButton(f"🚫 {name} (@{username or 'нет'})", callback_data=f"user_{user_id}")])
    
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


# ===== КОМАНДЫ БЛОКИРОВКИ =====
async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /block [user_id] - блокирует пользователя"""
    user_id = update.effective_user.id
    
    if user_id != YOUR_USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ <b>Использование:</b>\n"
            "<code>/block [user_id]</code>\n\n"
            "Пример: <code>/block 123456789</code>",
            parse_mode='HTML'
        )
        return
    
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом!")
        return
    
    if target_id == YOUR_USER_ID:
        await update.message.reply_text("❌ Нельзя заблокировать себя!")
        return
    
    if block_user(target_id):
        await update.message.reply_text(
            f"✅ <b>Пользователь ЗАБЛОКИРОВАН</b>\n\n"
            f"🆔 ID: <code>{target_id}</code>\n"
            f"Теперь его сообщения игнорируются.",
            parse_mode='HTML'
        )
        logger.info(f"✅ Блокировка через команду: {target_id}")
    else:
        await update.message.reply_text("❌ Ошибка блокировки")

async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /unblock [user_id] - разблокирует пользователя"""
    user_id = update.effective_user.id
    
    if user_id != YOUR_USER_ID:
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ <b>Использование:</b>\n"
            "<code>/unblock [user_id]</code>\n\n"
            "Пример: <code>/unblock 123456789</code>",
            parse_mode='HTML'
        )
        return
    
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом!")
        return
    
    if unblock_user(target_id):
        await update.message.reply_text(
            f"✅ <b>Пользователь РАЗБЛОКИРОВАН</b>\n\n"
            f"🆔 ID: <code>{target_id}</code>",
            parse_mode='HTML'
        )
        logger.info(f"✅ Разблокировка через команду: {target_id}")
    else:
        await update.message.reply_text("❌ Ошибка разблокировки")

async def blocked_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /blocked - показывает список заблокированных"""
    user_id = update.effective_user.id
    
    if user_id != YOUR_USER_ID:
        return
    
    blocked = get_blocked_users()
    if not blocked:
        await update.message.reply_text("🚫 <b>Черный список пуст</b>", parse_mode='HTML')
        return
    
    text = "🚫 <b>Заблокированные пользователи:</b>\n\n"
    for user in blocked:
        user_id, username, first_name, last_name, last_time = user
        name = first_name or "Без имени"
        text += f"🆔 <code>{user_id}</code> - {name} (@{username or 'нет'})\n"
    
    await update.message.reply_text(text, parse_mode='HTML')


# ===== ОБРАБОТЧИКИ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_USERNAME
    
    user_id = update.effective_user.id
    
    if not BOT_USERNAME:
        bot_info = await context.bot.get_me()
        BOT_USERNAME = bot_info.username
    
    # === НЕ ВЛАДЕЛЕЦ ===
    if user_id != YOUR_USER_ID:
        user = update.effective_user
        add_user_to_db(user_id, user.username, user.first_name, user.last_name)
        
        # ===== ПРОВЕРКА БЛОКИРОВКИ =====
        if is_user_blocked(user_id):
            logger.info(f"🔒 ЗАБЛОКИРОВАННЫЙ {user_id} - ИГНОР")
            return
        
        # Отправляем уведомление владельцу
        try:
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=f"👤 <b>Новый пользователь</b>\n\n"
                     f"🆔 ID: <code>{user_id}</code>\n"
                     f"📛 Имя: {user.first_name or 'Нет'}\n"
                     f"🔗 Юзернейм: @{user.username or 'Нет'}\n"
                     f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                     f"<i>Чтобы заблокировать: /block {user_id}</i>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📤 Ответить", callback_data=f"reply_user_{user_id}")],
                    [InlineKeyboardButton("🚫 Заблокировать", callback_data=f"block_user_{user_id}")]
                ])
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления: {e}")
        return
    
    # === ВЛАДЕЛЕЦ ===
    await update.message.reply_text(
        "👋 <b>Главное меню</b>\n\n"
        "Команды:\n"
        "/block [id] - заблокировать пользователя\n"
        "/unblock [id] - разблокировать\n"
        "/blocked - список заблокированных",
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
    
    # === ВЫХОД ===
    if data == "exit_mode":
        if user_id in user_states:
            del user_states[user_id]
        await query.edit_message_text(
            "✅ <b>Режим отправки отключен</b>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
        return
    
    if data == "main_menu":
        if user_id in user_states:
            del user_states[user_id]
        await query.edit_message_text(
            "👋 <b>Главное меню</b>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
        return
    
    # === ПОЛЬЗОВАТЕЛИ ===
    if data == "users_menu":
        users = get_all_users()
        if not users:
            await query.edit_message_text(
                "👥 <b>Нет пользователей</b>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
            )
            return
        await query.edit_message_text(
            f"👥 <b>Пользователи</b> ({len(users)})",
            parse_mode='HTML',
            reply_markup=get_users_keyboard()
        )
        return
    
    if data.startswith("users_page_"):
        page = int(data.split("_")[2])
        await query.edit_message_text(
            "👥 <b>Пользователи</b>",
            parse_mode='HTML',
            reply_markup=get_users_keyboard(page)
        )
        return
    
    if data == "blocked_menu":
        blocked = get_blocked_users()
        if not blocked:
            await query.edit_message_text(
                "🚫 <b>Черный список пуст</b>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
            )
            return
        await query.edit_message_text(
            f"🚫 <b>Черный список</b> ({len(blocked)})",
            parse_mode='HTML',
            reply_markup=get_blocked_keyboard()
        )
        return
    
    if data.startswith("blocked_page_"):
        page = int(data.split("_")[2])
        await query.edit_message_text(
            "🚫 <b>Черный список</b>",
            parse_mode='HTML',
            reply_markup=get_blocked_keyboard(page)
        )
        return
    
    if data.startswith("user_"):
        user_id = int(data.split("_")[1])
        user = get_user(user_id)
        if not user:
            await query.edit_message_text("❌ Пользователь не найден", reply_markup=get_main_keyboard())
            return
        
        user_id, username, first_name, last_name, is_blocked = user
        text = f"👤 <b>Информация</b>\n\n🆔 ID: <code>{user_id}</code>\n📛 {first_name or 'Нет'}\n🔗 @{username or 'Нет'}\n📊 {'🚫 ЗАБЛОКИРОВАН' if is_blocked else '✅ Активен'}"
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_user_actions_keyboard(user_id))
        return
    
    # === БЛОКИРОВКА ===
    if data.startswith("block_user_"):
        user_id = int(data.split("_")[2])
        if block_user(user_id):
            if user_id in user_states:
                del user_states[user_id]
            await query.edit_message_text(
                f"🚫 <b>Пользователь ЗАБЛОКИРОВАН</b>\n\nID: <code>{user_id}</code>",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )
        else:
            await query.edit_message_text("❌ Ошибка", reply_markup=get_main_keyboard())
        return
    
    if data.startswith("unblock_user_"):
        user_id = int(data.split("_")[2])
        if unblock_user(user_id):
            await query.edit_message_text(
                f"✅ <b>Пользователь РАЗБЛОКИРОВАН</b>\n\nID: <code>{user_id}</code>",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )
        else:
            await query.edit_message_text("❌ Ошибка", reply_markup=get_main_keyboard())
        return
    
    # === ОТВЕТ ПОЛЬЗОВАТЕЛЮ ===
    if data.startswith("reply_user_"):
        user_id = int(data.split("_")[2])
        if is_user_blocked(user_id):
            await query.edit_message_text(
                f"🚫 <b>Пользователь ЗАБЛОКИРОВАН</b>\n\nID: <code>{user_id}</code>",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )
            return
        user_states[YOUR_USER_ID] = {'action': 'reply_to_user', 'user_id': user_id}
        await query.edit_message_text(
            f"✏️ <b>Ответ пользователю</b>\n\nID: <code>{user_id}</code>",
            parse_mode='HTML',
            reply_markup=get_back_keyboard()
        )
        return
    
    # === ОТСЛЕЖИВАНИЕ ===
    if data == "tracking_menu":
        await query.edit_message_text(
            "👁 <b>Управление отслеживанием</b>\n\n🟢 - отслеживается\n⚪️ - нет",
            parse_mode='HTML',
            reply_markup=get_tracking_keyboard()
        )
        return
    
    if data.startswith("start_track_"):
        chat_id = int(data.split("_")[2])
        if chat_id not in tracked_chats:
            tracked_chats.append(chat_id)
            logger.info(f"Начато отслеживание чата {chat_id}")
            await context.bot.send_message(chat_id=YOUR_USER_ID, text=f"🟢 Начато отслеживание чата {chat_id}")
        await show_chat_actions(query, user_id, chat_id)
        return
    
    if data.startswith("stop_track_"):
        chat_id = int(data.split("_")[2])
        if chat_id in tracked_chats:
            tracked_chats.remove(chat_id)
            logger.info(f"Остановлено отслеживание чата {chat_id}")
            await context.bot.send_message(chat_id=YOUR_USER_ID, text=f"🔴 Остановлено отслеживание чата {chat_id}")
        await show_chat_actions(query, user_id, chat_id)
        return
    
    # === ЧАТЫ ===
    if data == "list_chats":
        await show_chats(query, user_id, 0)
        return
    
    if data.startswith("page_"):
        page = int(data.split("_")[1])
        await show_chats(query, user_id, page)
        return
    
    if data.startswith("chat_"):
        chat_id = int(data.split("_")[1])
        await show_chat_actions(query, user_id, chat_id)
        return
    
    # === ЗАКРЕПЛЕНИЕ ===
    if data.startswith("fix_chat_"):
        chat_id = int(data.split("_")[2])
        if chat_id not in fixed_chats:
            fixed_chats.append(chat_id)
        await query.edit_message_text(f"⭐ <b>Чат закреплен</b>", parse_mode='HTML', reply_markup=get_main_keyboard())
        return
    
    if data.startswith("unfix_chat_"):
        chat_id = int(data.split("_")[2])
        if chat_id in fixed_chats:
            fixed_chats.remove(chat_id)
        await query.edit_message_text(f"⭐ <b>Чат откреплен</b>", parse_mode='HTML', reply_markup=get_main_keyboard())
        return
    
    # === ОТПРАВКА ===
    if data.startswith("quick_send_"):
        chat_id = int(data.split("_")[2])
        chat_title = "Чат"
        for cid, title, ctype in get_user_chats(user_id):
            if cid == chat_id:
                chat_title = title
                break
        await query.edit_message_text(
            f"⚡ <b>Быстрая отправка</b>\n\n📌 {chat_title}\n<code>ID: {chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_quick_send_keyboard(chat_id)
        )
        return
    
    if data.startswith("quick_text_"):
        chat_id = int(data.split("_")[2])
        user_states[user_id] = {'action': 'send_message', 'chat_id': chat_id}
        await query.edit_message_text(
            f"✏️ <b>Режим текста</b>\n\nЧат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_back_keyboard()
        )
        return
    
    if data.startswith("quick_media_"):
        parts = data.split("_")
        chat_id = int(parts[2])
        media_type = parts[3]
        user_states[user_id] = {'action': 'send_media', 'chat_id': chat_id, 'media_type': media_type}
        emoji = {"photo": "📷", "video": "🎥", "document": "📄", "sticker": "🎨"}.get(media_type, "📎")
        await query.edit_message_text(
            f"{emoji} <b>Режим отправки {media_type}</b>\n\nЧат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_back_keyboard()
        )
        return
    
    if data.startswith("send_to_"):
        chat_id = int(data.split("_")[2])
        user_states[user_id] = {'action': 'send_any', 'chat_id': chat_id}
        await query.edit_message_text(
            f"📤 <b>Режим отправки</b>\n\nЧат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_back_keyboard()
        )
        return
    
    # === ОТВЕТ НА СООБЩЕНИЕ ===
    if data.startswith("reply_msg_"):
        parts = data.split("_")
        chat_id = int(parts[2])
        message_id = int(parts[3])
        user_states[YOUR_USER_ID] = {'action': 'reply_in_chat', 'chat_id': chat_id, 'message_id': message_id}
        await query.edit_message_text(
            f"✏️ <b>Напишите ответ</b>\n\nЧат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_back_keyboard()
        )
        return
    
    if data.startswith("delete_"):
        chat_id = int(data.split("_")[1])
        remove_chat_from_db(user_id, chat_id)
        if chat_id in fixed_chats:
            fixed_chats.remove(chat_id)
        if chat_id in tracked_chats:
            tracked_chats.remove(chat_id)
        await query.edit_message_text(f"🗑 <b>Чат удален</b>", parse_mode='HTML', reply_markup=get_main_keyboard())
        return
    
    if data == "refresh_chats":
        await query.edit_message_text("🔄 <b>Обновление...</b>", parse_mode='HTML')
        await refresh_all_chats(query, context)
        return


async def show_chats(query, user_id, page):
    chats = get_user_chats(user_id)
    if not chats:
        await query.edit_message_text("📭 <b>Нет чатов</b>", parse_mode='HTML', reply_markup=get_main_keyboard())
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
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_chats_keyboard(user_id, page))


async def show_chat_actions(query, user_id, chat_id):
    chats = get_user_chats(user_id)
    chat_info = next((c for c in chats if c[0] == chat_id), None)
    title = chat_info[1] if chat_info else "Чат"
    
    is_tracking = chat_id in tracked_chats
    is_fixed = chat_id in fixed_chats
    
    text = f"📌 <b>{title}</b>\n\n<code>ID: {chat_id}</code>\n\n"
    text += f"{'🟢 Отслеживается' if is_tracking else '⚪️ Не отслеживается'}\n"
    text += f"{'⭐ Закреплен' if is_fixed else '⚪️ Не закреплен'}"
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=get_chat_actions_keyboard(chat_id))


async def send_tracking_notification(context, chat, user, message_text, message_id, file_id=None, file_type=None, is_reply_to_bot=False):
    """Отправляет уведомление с кнопкой ответа"""
    username = user.username or "Нет"
    first_name = user.first_name or "Нет"
    user_id = user.id
    time = datetime.now().strftime("%H:%M:%S")
    user_info = f"@{username}" if username != "Нет" else first_name
    
    label = "🤖 ОТВЕТ БОТУ" if is_reply_to_bot else "💬 ОБЫЧНОЕ СООБЩЕНИЕ"
    
    notification = (
        f"📨 <b>Отслеживание</b>\n"
        f"{label}\n\n"
        f"📌 {chat.title}\n"
        f"👤 {user_info} (ID: {user_id})\n"
        f"💬 {message_text}\n"
        f"🕐 {time}\n\n"
        f"<i>Чтобы заблокировать: /block {user_id}</i>"
    )
    
    try:
        if file_type == "photo":
            await context.bot.send_photo(
                chat_id=YOUR_USER_ID,
                photo=file_id,
                caption=notification[:1024],
                parse_mode='HTML',
                reply_markup=get_reply_keyboard(chat.id, message_id)
            )
        elif file_type == "video":
            await context.bot.send_video(
                chat_id=YOUR_USER_ID,
                video=file_id,
                caption=notification[:1024],
                parse_mode='HTML',
                reply_markup=get_reply_keyboard(chat.id, message_id)
            )
        elif file_type == "document":
            await context.bot.send_document(
                chat_id=YOUR_USER_ID,
                document=file_id,
                caption=notification[:1024],
                parse_mode='HTML',
                reply_markup=get_reply_keyboard(chat.id, message_id)
            )
        elif file_type == "audio":
            await context.bot.send_audio(
                chat_id=YOUR_USER_ID,
                audio=file_id,
                caption=notification[:1024],
                parse_mode='HTML',
                reply_markup=get_reply_keyboard(chat.id, message_id)
            )
        elif file_type == "voice":
            await context.bot.send_voice(
                chat_id=YOUR_USER_ID,
                voice=file_id,
                caption=notification[:1024],
                parse_mode='HTML',
                reply_markup=get_reply_keyboard(chat.id, message_id)
            )
        elif file_type == "sticker":
            await context.bot.send_sticker(chat_id=YOUR_USER_ID, sticker=file_id)
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=notification,
                parse_mode='HTML',
                reply_markup=get_reply_keyboard(chat.id, message_id)
            )
        else:
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=notification,
                parse_mode='HTML',
                reply_markup=get_reply_keyboard(chat.id, message_id)
            )
        await asyncio.sleep(0.2)
    except Exception as e:
        logger.error(f"Ошибка уведомления: {e}")


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
    
    # === ЛИЧНЫЙ ЧАТ С БОТОМ (НЕ ВЛАДЕЛЕЦ) ===
    if chat_type == "private" and user_id != YOUR_USER_ID:
        user = update.effective_user
        add_user_to_db(user_id, user.username, user.first_name, user.last_name)
        
        # ===== ГЛАВНАЯ ПРОВЕРКА БЛОКИРОВКИ =====
        if is_user_blocked(user_id):
            logger.info(f"🔒 ЗАБЛОКИРОВАННЫЙ {user_id} - ИГНОР")
            return  # МОЛЧА ИГНОРИРУЕМ
        
        # Отправляем уведомление владельцу
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
                f"👤 <b>Сообщение</b>\n\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"📛 {user.first_name or 'Нет'}\n"
                f"🔗 @{user.username or 'Нет'}\n"
                f"💬 {message_text}\n"
                f"🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
                f"<i>Чтобы заблокировать: /block {user_id}</i>"
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
                await context.bot.send_sticker(chat_id=YOUR_USER_ID, sticker=file_id)
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
            logger.error(f"Ошибка: {e}")
        return
    
    # === ГРУППОВЫЕ ЧАТЫ ===
    if chat_type in ["group", "supergroup"]:
        chat_title = chat.title or "Без названия"
        
        # Добавляем чат
        if user_id == YOUR_USER_ID:
            if not chat_exists(YOUR_USER_ID, chat_id):
                if add_chat_to_db(YOUR_USER_ID, chat_id, chat_title, chat_type):
                    await context.bot.send_message(
                        chat_id=YOUR_USER_ID,
                        text=f"✅ Чат добавлен: {chat_title}\nID: <code>{chat_id}</code>",
                        parse_mode='HTML'
                    )
            else:
                add_chat_to_db(YOUR_USER_ID, chat_id, chat_title, chat_type)
        
        # ===== ОТСЛЕЖИВАНИЕ - ВСЕ СООБЩЕНИЯ =====
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
                    message_text = "📎 Другое"
                
                await send_tracking_notification(
                    context, chat, user, message_text, 
                    update.message.message_id,
                    file_id, file_type, is_reply_to_bot
                )
        return
    
    # === ПРИВАТНЫЙ ЧАТ С ВЛАДЕЛЬЦЕМ ===
    if chat_type == "private" and user_id == YOUR_USER_ID:
        # Обработка состояний
        if user_id in user_states:
            state = user_states[user_id]
            action = state['action']
            
            # Проверка блокировки для ответа пользователю
            if action == 'reply_to_user':
                target_user_id = state['user_id']
                if is_user_blocked(target_user_id):
                    await update.message.reply_text(
                        f"🚫 <b>Пользователь ЗАБЛОКИРОВАН</b>\n\n"
                        f"ID: <code>{target_user_id}</code>\n"
                        f"Используйте /unblock {target_user_id} для разблокировки",
                        parse_mode='HTML',
                        reply_markup=get_main_keyboard()
                    )
                    if user_id in user_states:
                        del user_states[user_id]
                    return
            
            # Отправка текста
            if action == 'send_message' and update.message and update.message.text:
                chat_id = state['chat_id']
                try:
                    await context.bot.send_message(chat_id=chat_id, text=update.message.text)
                    await update.message.reply_text("✅ Отправлено", reply_markup=get_back_keyboard())
                except Exception as e:
                    await update.message.reply_text(f"❌ {e}")
                return
            
            # Отправка чего угодно
            if action == 'send_any' and update.message:
                chat_id = state['chat_id']
                try:
                    if update.message.text:
                        await context.bot.send_message(chat_id=chat_id, text=update.message.text)
                    elif update.message.photo:
                        await context.bot.send_photo(chat_id=chat_id, photo=update.message.photo[-1].file_id, caption=update.message.caption)
                    elif update.message.video:
                        await context.bot.send_video(chat_id=chat_id, video=update.message.video.file_id, caption=update.message.caption)
                    elif update.message.document:
                        await context.bot.send_document(chat_id=chat_id, document=update.message.document.file_id, caption=update.message.caption)
                    elif update.message.sticker:
                        await context.bot.send_sticker(chat_id=chat_id, sticker=update.message.sticker.file_id)
                    elif update.message.audio:
                        await context.bot.send_audio(chat_id=chat_id, audio=update.message.audio.file_id, caption=update.message.caption)
                    elif update.message.voice:
                        await context.bot.send_voice(chat_id=chat_id, voice=update.message.voice.file_id, caption=update.message.caption)
                    else:
                        await update.message.reply_text("❌ Неподдерживаемый тип")
                        return
                    await update.message.reply_text("✅ Отправлено", reply_markup=get_back_keyboard())
                except Exception as e:
                    await update.message.reply_text(f"❌ {e}")
                return
            
            # Отправка медиа
            if action == 'send_media' and update.message:
                chat_id = state['chat_id']
                media_type = state['media_type']
                try:
                    if media_type == "photo" and update.message.photo:
                        await context.bot.send_photo(chat_id=chat_id, photo=update.message.photo[-1].file_id, caption=update.message.caption)
                    elif media_type == "video" and update.message.video:
                        await context.bot.send_video(chat_id=chat_id, video=update.message.video.file_id, caption=update.message.caption)
                    elif media_type == "document" and update.message.document:
                        await context.bot.send_document(chat_id=chat_id, document=update.message.document.file_id, caption=update.message.caption)
                    elif media_type == "sticker" and update.message.sticker:
                        await context.bot.send_sticker(chat_id=chat_id, sticker=update.message.sticker.file_id)
                    else:
                        await update.message.reply_text(f"❌ Отправьте {media_type}")
                        return
                    await update.message.reply_text(f"✅ {media_type.capitalize()} отправлен", reply_markup=get_back_keyboard())
                except Exception as e:
                    await update.message.reply_text(f"❌ {e}")
                return
            
            # Ответ пользователю
            if action == 'reply_to_user' and update.message:
                target_user_id = state['user_id']
                try:
                    if update.message.text:
                        await context.bot.send_message(chat_id=target_user_id, text=update.message.text)
                    elif update.message.photo:
                        await context.bot.send_photo(chat_id=target_user_id, photo=update.message.photo[-1].file_id, caption=update.message.caption)
                    elif update.message.video:
                        await context.bot.send_video(chat_id=target_user_id, video=update.message.video.file_id, caption=update.message.caption)
                    elif update.message.document:
                        await context.bot.send_document(chat_id=target_user_id, document=update.message.document.file_id, caption=update.message.caption)
                    elif update.message.sticker:
                        await context.bot.send_sticker(chat_id=target_user_id, sticker=update.message.sticker.file_id)
                    elif update.message.audio:
                        await context.bot.send_audio(chat_id=target_user_id, audio=update.message.audio.file_id, caption=update.message.caption)
                    elif update.message.voice:
                        await context.bot.send_voice(chat_id=target_user_id, voice=update.message.voice.file_id, caption=update.message.caption)
                    else:
                        await update.message.reply_text("❌ Неподдерживаемый тип")
                        return
                    await update.message.reply_text("✅ Отправлено пользователю", reply_markup=get_back_keyboard())
                except Exception as e:
                    await update.message.reply_text(f"❌ {e}")
                return
            
            # Ответ в чате
            if action == 'reply_in_chat' and update.message:
                chat_id = state['chat_id']
                message_id = state['message_id']
                try:
                    if update.message.text:
                        await context.bot.send_message(chat_id=chat_id, text=update.message.text, reply_to_message_id=message_id)
                    elif update.message.photo:
                        await context.bot.send_photo(chat_id=chat_id, photo=update.message.photo[-1].file_id, caption=update.message.caption, reply_to_message_id=message_id)
                    elif update.message.video:
                        await context.bot.send_video(chat_id=chat_id, video=update.message.video.file_id, caption=update.message.caption, reply_to_message_id=message_id)
                    elif update.message.document:
                        await context.bot.send_document(chat_id=chat_id, document=update.message.document.file_id, caption=update.message.caption, reply_to_message_id=message_id)
                    elif update.message.sticker:
                        await context.bot.send_sticker(chat_id=chat_id, sticker=update.message.sticker.file_id, reply_to_message_id=message_id)
                    else:
                        await update.message.reply_text("❌ Неподдерживаемый тип")
                        return
                    await update.message.reply_text("✅ Ответ отправлен", reply_markup=get_back_keyboard())
                except Exception as e:
                    await update.message.reply_text(f"❌ {e}")
                return
        
        # Показываем меню
        if not update.message or not update.message.text or not update.message.text.startswith('/'):
            await update.message.reply_text(
                "👋 <b>Главное меню</b>\n\n"
                "Команды:\n"
                "/block [id] - заблокировать пользователя\n"
                "/unblock [id] - разблокировать\n"
                "/blocked - список заблокированных",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )


async def refresh_all_chats(query, context):
    try:
        chats = get_user_chats(YOUR_USER_ID)
        await query.edit_message_text(
            f"✅ <b>Обновлено</b>\n\n📋 Чатов: {len(chats)}",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        await query.edit_message_text(f"❌ {e}", reply_markup=get_main_keyboard())


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")


# ===== ЗАПУСК =====
def main():
    try:
        print("=" * 50)
        print("Запуск бота...")
        print("=" * 50)
        
        if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
            print("❌ ОШИБКА: Замените TOKEN!")
            return
        
        if not init_db():
            print("❌ Ошибка БД!")
            return
        
        application = Application.builder().token(TOKEN).build()
        
        # Команды
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("block", block_command))
        application.add_handler(CommandHandler("unblock", unblock_command))
        application.add_handler(CommandHandler("blocked", blocked_list_command))
        
        # Callback
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        # Сообщения
        application.add_handler(MessageHandler(filters.ALL, handle_all_messages))
        application.add_error_handler(error_handler)
        
        print("✅ Бот запущен!")
        print("=" * 50)
        print("📌 КОМАНДЫ:")
        print("  /block [id] - заблокировать пользователя")
        print("  /unblock [id] - разблокировать")
        print("  /blocked - список заблокированных")
        print("=" * 50)
        print("📌 Логирование включено (смотрите bot.log)")
        print("=" * 50)
        
        application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        print(f"❌ {e}")

if __name__ == "__main__":
    main()
