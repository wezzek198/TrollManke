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
CACHE_DB = "cache.db"
MAX_CACHE_HOURS = 24

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
user_states = {}  # {user_id: {'action': 'send_to', 'chat_id': int}}


# ===== БАЗА ДАННЫХ =====
def init_db():
    """Инициализация всех баз данных"""
    try:
        # Основная БД с чатами
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_chats (
                user_id INTEGER,
                chat_id INTEGER,
                chat_title TEXT,
                chat_type TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            )
        ''')
        conn.commit()
        conn.close()
        
        # БД для кэша сообщений
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                message_text TEXT,
                message_type TEXT,
                file_id TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

def clear_cache_for_chat(chat_id):
    """Очищает кэш для конкретного чата"""
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM messages_cache WHERE chat_id = ?', (chat_id,))
        conn.commit()
        conn.close()
        logger.info(f"Кэш очищен для чата {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка очистки кэша: {e}")
        return False

def add_message_to_cache(chat_id, user_id, username, first_name, message_text, message_type, file_id=None):
    """Добавляет сообщение в кэш"""
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO messages_cache 
            (chat_id, user_id, username, first_name, message_text, message_type, file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, user_id, username, first_name, message_text, message_type, file_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления в кэш: {e}")
        return False

def get_cached_messages(chat_id, hours=24):
    """Получает сообщения из кэша за последние N часов"""
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT user_id, username, first_name, message_text, message_type, timestamp 
            FROM messages_cache 
            WHERE chat_id = ? AND timestamp > datetime('now', '-? hours')
            ORDER BY timestamp DESC
            LIMIT 100
        ''', (chat_id, hours))
        messages = cursor.fetchall()
        conn.close()
        return messages
    except Exception as e:
        logger.error(f"Ошибка получения кэша: {e}")
        return []

def cleanup_old_cache():
    """Удаляет старые записи из кэша"""
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM messages_cache WHERE timestamp < datetime("now", "-24 hours")')
        conn.commit()
        conn.close()
        logger.info("Старый кэш очищен")
    except Exception as e:
        logger.error(f"Ошибка очистки старого кэша: {e}")


# ===== КЛАВИАТУРЫ =====
def get_main_keyboard():
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("📋 Мои чаты", callback_data="list_chats")],
        [InlineKeyboardButton("📸 Отправить медиа", callback_data="send_media")],
        [InlineKeyboardButton("👁 Отслеживать чат", callback_data="track_chat")],
        [InlineKeyboardButton("🔄 Обновить чаты", callback_data="refresh_chats")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_chats_keyboard(user_id, page=0, per_page=5):
    """Клавиатура со списком чатов"""
    chats = get_user_chats(user_id)
    keyboard = []
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(chats))
    
    for chat_id, chat_title, chat_type in chats[start_idx:end_idx]:
        keyboard.append([
            InlineKeyboardButton(
                f"📌 {chat_title[:30]}", 
                callback_data=f"chat_{chat_id}"
            )
        ])
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"page_{page-1}"))
    if end_idx < len(chats):
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_media_keyboard():
    """Клавиатура выбора типа медиа"""
    keyboard = [
        [InlineKeyboardButton("📷 Фото", callback_data="media_photo")],
        [InlineKeyboardButton("🎥 Видео", callback_data="media_video")],
        [InlineKeyboardButton("📄 Документ", callback_data="media_document")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_chat_actions_keyboard(chat_id, is_tracking=False):
    """Клавиатура действий для чата"""
    keyboard = []
    
    if is_tracking:
        keyboard.append([InlineKeyboardButton("🛑 Остановить отслеживание", callback_data=f"stop_track_{chat_id}")])
        keyboard.append([InlineKeyboardButton("📜 История (24ч)", callback_data=f"history_{chat_id}")])
        keyboard.append([InlineKeyboardButton("🗑 Очистить историю", callback_data=f"clear_history_{chat_id}")])
    else:
        keyboard.append([InlineKeyboardButton("👁 Начать отслеживание", callback_data=f"start_track_{chat_id}")])
    
    keyboard.append([InlineKeyboardButton("📤 Отправить сообщение", callback_data=f"send_to_{chat_id}")])
    keyboard.append([InlineKeyboardButton("🗑 Удалить чат", callback_data=f"delete_{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="list_chats")])
    
    return InlineKeyboardMarkup(keyboard)


# ===== ОБРАБОТЧИКИ КОМАНД =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    # Если это не владелец - просто игнорируем
    if user_id != YOUR_USER_ID:
        # Отправляем уведомление владельцу
        user = update.effective_user
        try:
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=f"⚠️ <b>Попытка использования бота</b>\n\n"
                     f"👤 ID: <code>{user_id}</code>\n"
                     f"📛 Имя: {user.first_name or 'Нет'}\n"
                     f"🔗 Юзернейм: @{user.username or 'Нет'}\n"
                     f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode='HTML'
            )
        except:
            pass
        return  # Ничего не отвечаем пользователю
    
    # Для владельца показываем меню
    await update.message.reply_text(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Выберите действие:",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )


# ===== ОБРАБОТЧИКИ CALLBACK =====
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # Если не владелец - игнорируем
    if user_id != YOUR_USER_ID:
        return
    
    data = query.data
    
    # Главное меню
    if data == "main_menu":
        await query.edit_message_text(
            "👋 <b>Главное меню</b>\n\nВыберите действие:",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    
    # Список чатов
    elif data == "list_chats":
        await show_chats(query, user_id, 0)
    
    # Пагинация
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        await show_chats(query, user_id, page)
    
    # Отправка медиа
    elif data == "send_media":
        await query.edit_message_text(
            "📤 <b>Выберите тип медиа</b>\n\n"
            "После выбора отправьте файл следующим сообщением:",
            parse_mode='HTML',
            reply_markup=get_media_keyboard()
        )
    
    # Выбор типа медиа
    elif data in ["media_photo", "media_video", "media_document"]:
        media_type = data.split("_")[1]
        user_states[user_id] = {'action': 'send_media', 'media_type': media_type}
        
        # Показываем список чатов для выбора
        await show_chats_for_media(query, user_id, media_type)
    
    # Обновить чаты
    elif data == "refresh_chats":
        await query.edit_message_text(
            "🔄 <b>Обновление чатов...</b>\n\n"
            "Бот сканирует все чаты, где он находится.",
            parse_mode='HTML'
        )
        await refresh_all_chats(query, context)
    
    # Действия с чатом
    elif data.startswith("chat_"):
        chat_id = int(data.split("_")[1])
        await show_chat_actions(query, user_id, chat_id)
    
    # Отправить сообщение в чат
    elif data.startswith("send_to_"):
        chat_id = int(data.split("_")[2])
        user_states[user_id] = {'action': 'send_message', 'chat_id': chat_id}
        await query.edit_message_text(
            f"✏️ <b>Введите текст для отправки</b>\n\n"
            f"Чат: <code>{chat_id}</code>\n\n"
            "Просто напишите сообщение в этот чат.",
            parse_mode='HTML'
        )
    
    # Начать отслеживание
    elif data.startswith("start_track_"):
        chat_id = int(data.split("_")[2])
        # Сохраняем состояние отслеживания
        if not hasattr(context.bot_data, 'tracked_chats'):
            context.bot_data['tracked_chats'] = []
        if chat_id not in context.bot_data['tracked_chats']:
            context.bot_data['tracked_chats'].append(chat_id)
        
        await query.edit_message_text(
            f"👁 <b>Отслеживание включено</b>\n\n"
            f"Чат: <code>{chat_id}</code>\n\n"
            "Все сообщения будут пересылаться вам.\n"
            "История хранится 24 часа.",
            parse_mode='HTML',
            reply_markup=get_chat_actions_keyboard(chat_id, is_tracking=True)
        )
        await context.bot.send_message(
            chat_id=YOUR_USER_ID,
            text=f"🟢 Начато отслеживание чата {chat_id}"
        )
    
    # Остановить отслеживание
    elif data.startswith("stop_track_"):
        chat_id = int(data.split("_")[2])
        if 'tracked_chats' in context.bot_data and chat_id in context.bot_data['tracked_chats']:
            context.bot_data['tracked_chats'].remove(chat_id)
        
        # Очищаем кэш
        clear_cache_for_chat(chat_id)
        
        await query.edit_message_text(
            f"🛑 <b>Отслеживание остановлено</b>\n\n"
            f"Чат: <code>{chat_id}</code>\n\n"
            "История сообщений очищена.",
            parse_mode='HTML',
            reply_markup=get_chat_actions_keyboard(chat_id, is_tracking=False)
        )
        await context.bot.send_message(
            chat_id=YOUR_USER_ID,
            text=f"🔴 Отслеживание чата {chat_id} остановлено"
        )
    
    # Показать историю
    elif data.startswith("history_"):
        chat_id = int(data.split("_")[1])
        messages = get_cached_messages(chat_id)
        
        if not messages:
            await query.edit_message_text(
                f"📭 <b>История пуста</b>\n\n"
                f"Чат: <code>{chat_id}</code>\n\n"
                "За последние 24 часа не было сообщений.",
                parse_mode='HTML',
                reply_markup=get_chat_actions_keyboard(chat_id, is_tracking=True)
            )
            return
        
        text = f"📜 <b>История чата {chat_id}</b>\n\n"
        for user_id, username, first_name, msg_text, msg_type, timestamp in messages[:20]:
            user_info = f"@{username}" if username else first_name or f"ID:{user_id}"
            time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S').strftime('%H:%M')
            text += f"• [{time}] {user_info}: {msg_text[:50]}\n"
        
        text += f"\n<i>Показано {min(20, len(messages))} сообщений</i>"
        
        await query.edit_message_text(
            text,
            parse_mode='HTML',
            reply_markup=get_chat_actions_keyboard(chat_id, is_tracking=True)
        )
    
    # Очистить историю
    elif data.startswith("clear_history_"):
        chat_id = int(data.split("_")[2])
        clear_cache_for_chat(chat_id)
        await query.edit_message_text(
            f"🗑 <b>История очищена</b>\n\n"
            f"Чат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_chat_actions_keyboard(chat_id, is_tracking=True)
        )
    
    # Удалить чат
    elif data.startswith("delete_"):
        chat_id = int(data.split("_")[1])
        remove_chat_from_db(user_id, chat_id)
        await query.edit_message_text(
            f"🗑 <b>Чат удален</b>\n\n"
            f"Чат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )


async def show_chats(query, user_id, page):
    """Показывает список чатов"""
    chats = get_user_chats(user_id)
    
    if not chats:
        await query.edit_message_text(
            "📭 <b>Нет сохраненных чатов</b>\n\n"
            "Добавьте бота в чат и нажмите 'Обновить чаты'",
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
        text += f"{emoji} {chat_title}\n<code>{chat_id}</code>\n\n"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=get_chats_keyboard(user_id, page)
    )

async def show_chats_for_media(query, user_id, media_type):
    """Показывает чаты для отправки медиа"""
    chats = get_user_chats(user_id)
    
    if not chats:
        await query.edit_message_text(
            "📭 <b>Нет сохраненных чатов</b>\n\n"
            "Сначала добавьте бота в чат.",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
        return
    
    keyboard = []
    for chat_id, chat_title, chat_type in chats:
        keyboard.append([
            InlineKeyboardButton(
                f"📌 {chat_title[:30]}", 
                callback_data=f"media_chat_{chat_id}_{media_type}"
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="send_media")])
    
    await query.edit_message_text(
        f"📤 <b>Выберите чат для отправки {media_type}</b>\n\n"
        f"После выбора отправьте файл:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_chat_actions(query, user_id, chat_id):
    """Показывает действия для чата"""
    is_tracking = False
    if 'tracked_chats' in query.bot_data:
        is_tracking = chat_id in query.bot_data['tracked_chats']
    
    # Получаем информацию о чате
    chats = get_user_chats(user_id)
    chat_info = next((c for c in chats if c[0] == chat_id), None)
    
    if chat_info:
        title = chat_info[1]
        text = f"📌 <b>{title}</b>\n\n<code>ID: {chat_id}</code>\n\n"
    else:
        text = f"📌 <b>Чат</b>\n\n<code>ID: {chat_id}</code>\n\n"
    
    status = "🟢 Отслеживается" if is_tracking else "⚪️ Не отслеживается"
    text += f"Статус: {status}"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=get_chat_actions_keyboard(chat_id, is_tracking)
    )


# ===== ОБРАБОТЧИКИ СООБЩЕНИЙ =====
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех сообщений"""
    user_id = update.effective_user.id
    chat = update.effective_chat
    chat_id = chat.id
    
    # Если сообщение из чата и владелец - добавляем в кэш
    if chat.type in ["group", "supergroup"] and user_id == YOUR_USER_ID:
        add_chat_to_db(YOUR_USER_ID, chat_id, chat.title, chat.type)
    
    # Если это не владелец - игнорируем и уведомляем
    if user_id != YOUR_USER_ID:
        # Отправляем уведомление владельцу
        user = update.effective_user
        try:
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=f"⚠️ <b>Попытка использования бота</b>\n\n"
                     f"👤 ID: <code>{user_id}</code>\n"
                     f"📛 Имя: {user.first_name or 'Нет'}\n"
                     f"🔗 Юзернейм: @{user.username or 'Нет'}\n"
                     f"📝 Действие: Отправка сообщения\n"
                     f"🕐 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode='HTML'
            )
        except:
            pass
        return  # Ничего не отвечаем пользователю
    
    # Обработка состояния пользователя
    if user_id in user_states:
        state = user_states[user_id]
        
        # Отправка текстового сообщения
        if state['action'] == 'send_message' and update.message.text:
            chat_id = state['chat_id']
            try:
                await context.bot.send_message(chat_id=chat_id, text=update.message.text)
                await update.message.reply_text(
                    f"✅ Сообщение отправлено в чат {chat_id}",
                    reply_markup=get_main_keyboard()
                )
                del user_states[user_id]
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
        
        # Отправка медиа
        elif state['action'] == 'send_media':
            media_type = state['media_type']
            # Ждем выбор чата через callback
            await update.message.reply_text(
                f"⚠️ Сначала выберите чат для отправки {media_type}",
                reply_markup=get_main_keyboard()
            )
        
        return
    
    # Если просто сообщение в приват - показываем меню
    if chat.type == "private":
        await update.message.reply_text(
            "👋 <b>Главное меню</b>\n\nВыберите действие:",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )


async def handle_media_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора чата для медиа"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id != YOUR_USER_ID:
        return
    
    data = query.data
    if data.startswith("media_chat_"):
        parts = data.split("_")
        chat_id = int(parts[2])
        media_type = parts[3]
        
        # Сохраняем состояние
        user_states[user_id] = {
            'action': 'send_media_file',
            'chat_id': chat_id,
            'media_type': media_type
        }
        
        emoji = {"photo": "📷", "video": "🎥", "document": "📄"}.get(media_type, "📎")
        await query.edit_message_text(
            f"{emoji} <b>Отправьте {media_type}</b>\n\n"
            f"Чат: <code>{chat_id}</code>\n\n"
            f"Просто отправьте {media_type} в этот чат.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Отмена", callback_data="send_media")]
            ])
        )


async def handle_media_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик отправки медиа файлов"""
    user_id = update.effective_user.id
    
    if user_id != YOUR_USER_ID:
        return
    
    # Проверяем состояние
    if user_id not in user_states or user_states[user_id]['action'] != 'send_media_file':
        await update.message.reply_text(
            "⚠️ Сначала выберите чат и тип медиа через кнопки",
            reply_markup=get_main_keyboard()
        )
        return
    
    state = user_states[user_id]
    chat_id = state['chat_id']
    media_type = state['media_type']
    
    try:
        # Обработка разных типов медиа
        if media_type == "photo" and update.message.photo:
            photo = update.message.photo[-1]
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo.file_id,
                caption=update.message.caption
            )
            await update.message.reply_text(
                f"✅ Фото отправлено в чат {chat_id}",
                reply_markup=get_main_keyboard()
            )
        
        elif media_type == "video" and update.message.video:
            video = update.message.video
            await context.bot.send_video(
                chat_id=chat_id,
                video=video.file_id,
                caption=update.message.caption
            )
            await update.message.reply_text(
                f"✅ Видео отправлено в чат {chat_id}",
                reply_markup=get_main_keyboard()
            )
        
        elif media_type == "document" and update.message.document:
            doc = update.message.document
            await context.bot.send_document(
                chat_id=chat_id,
                document=doc.file_id,
                caption=update.message.caption
            )
            await update.message.reply_text(
                f"✅ Документ отправлен в чат {chat_id}",
                reply_markup=get_main_keyboard()
            )
        
        else:
            await update.message.reply_text(
                f"❌ Отправьте {media_type}, а не другой тип файла",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Удаляем состояние после успешной отправки
        del user_states[user_id]
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при отправке: {e}")


async def track_chat_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отслеживание сообщений в чате"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat = update.effective_chat
    
    # Только для групповых чатов
    if chat.type not in ["group", "supergroup"]:
        return
    
    # Проверяем, отслеживается ли этот чат
    if 'tracked_chats' not in context.bot_data:
        return
    
    if chat_id not in context.bot_data['tracked_chats']:
        return
    
    # Получаем информацию о пользователе
    user = update.effective_user
    username = user.username or "Нет"
    first_name = user.first_name or "Нет"
    
    # Определяем тип сообщения и текст
    message_text = ""
    message_type = "text"
    file_id = None
    
    if update.message.text:
        message_text = update.message.text
        message_type = "text"
    elif update.message.photo:
        message_text = "📷 Фото"
        message_type = "photo"
        file_id = update.message.photo[-1].file_id
    elif update.message.video:
        message_text = "🎥 Видео"
        message_type = "video"
        file_id = update.message.video.file_id
    elif update.message.document:
        message_text = f"📄 Документ: {update.message.document.file_name or 'без имени'}"
        message_type = "document"
        file_id = update.message.document.file_id
    elif update.message.audio:
        message_text = "🎵 Аудио"
        message_type = "audio"
        file_id = update.message.audio.file_id
    elif update.message.voice:
        message_text = "🎤 Голосовое"
        message_type = "voice"
        file_id = update.message.voice.file_id
    elif update.message.sticker:
        message_text = "🎨 Стикер"
        message_type = "sticker"
        file_id = update.message.sticker.file_id
    else:
        message_text = "📎 Другое сообщение"
        message_type = "other"
    
    # Сохраняем в кэш
    add_message_to_cache(
        chat_id, user_id, username, first_name, 
        message_text, message_type, file_id
    )
    
    # Отправляем уведомление владельцу
    time = datetime.now().strftime("%H:%M:%S")
    user_info = f"@{username}" if username != "Нет" else first_name
    
    notification_text = (
        f"📨 <b>Новое сообщение в чате</b>\n\n"
        f"👤 {user_info} (ID: {user_id})\n"
        f"💬 {message_text}\n"
        f"🕐 {time}"
    )
    
    try:
        # Если это медиа - пересылаем файл
        if file_id and message_type in ["photo", "video", "document", "audio", "voice", "sticker"]:
            if message_type == "photo":
                await context.bot.send_photo(
                    chat_id=YOUR_USER_ID,
                    photo=file_id,
                    caption=notification_text[:1024],
                    parse_mode='HTML'
                )
            elif message_type == "video":
                await context.bot.send_video(
                    chat_id=YOUR_USER_ID,
                    video=file_id,
                    caption=notification_text[:1024],
                    parse_mode='HTML'
                )
            elif message_type == "document":
                await context.bot.send_document(
                    chat_id=YOUR_USER_ID,
                    document=file_id,
                    caption=notification_text[:1024],
                    parse_mode='HTML'
                )
            elif message_type == "audio":
                await context.bot.send_audio(
                    chat_id=YOUR_USER_ID,
                    audio=file_id,
                    caption=notification_text[:1024],
                    parse_mode='HTML'
                )
            elif message_type == "voice":
                await context.bot.send_voice(
                    chat_id=YOUR_USER_ID,
                    voice=file_id,
                    caption=notification_text[:1024],
                    parse_mode='HTML'
                )
            elif message_type == "sticker":
                await context.bot.send_sticker(
                    chat_id=YOUR_USER_ID,
                    sticker=file_id
                )
        else:
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=notification_text,
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")


async def refresh_all_chats(query, context):
    """Обновляет список чатов"""
    try:
        # Получаем все обновления
        updates = await context.bot.get_updates(limit=100)
        added = 0
        
        for update in updates:
            if update.message and update.message.chat:
                chat = update.message.chat
                if chat.type in ["group", "supergroup"]:
                    if add_chat_to_db(YOUR_USER_ID, chat.id, chat.title, chat.type):
                        added += 1
        
        await query.edit_message_text(
            f"✅ <b>Чаты обновлены</b>\n\n"
            f"Добавлено новых чатов: {added}\n"
            f"Всего чатов: {len(get_user_chats(YOUR_USER_ID))}",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка обновления: {e}",
            reply_markup=get_main_keyboard()
        )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")


# ===== ЗАПУСК БОТА =====
def main():
    try:
        print("=" * 50)
        print("Запуск Telegram бота...")
        print("=" * 50)
        
        if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
            print("❌ ОШИБКА: Замените TOKEN на ваш реальный токен!")
            return
        
        init_db()
        
        # Очищаем старый кэш при запуске
        cleanup_old_cache()
        
        application = Application.builder().token(TOKEN).build()
        
        # Инициализация данных
        application.bot_data['tracked_chats'] = []
        
        # Обработчики команд
        application.add_handler(CommandHandler("start", start))
        
        # Callback обработчики - ВАЖНО: сначала общий, потом специфичный
        application.add_handler(CallbackQueryHandler(handle_media_selection, pattern="^media_chat_"))
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        # Обработчики сообщений
        application.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, 
            handle_messages
        ))
        
        # Обработчик для медиа файлов (исправлено)
        application.add_handler(MessageHandler(
            filters.ChatType.PRIVATE & (filters.PHOTO | filters.VIDEO | filters.Document.ALL),
            handle_media_files
        ))
        
        # Обработчик для отслеживания чатов
        application.add_handler(MessageHandler(
            filters.ChatType.GROUP | filters.ChatType.SUPERGROUP,
            track_chat_messages
        ))
        
        application.add_error_handler(error_handler)
        
        print("✅ Бот успешно запущен!")
        print("🔄 Ожидание сообщений...")
        print("❌ Чтобы остановить бота, нажмите Ctrl+C")
        print("=" * 50)
        
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}")
        print(f"❌ Критическая ошибка: {e}")

if __name__ == "__main__":
    main()
