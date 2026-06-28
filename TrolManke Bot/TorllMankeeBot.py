import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
import sqlite3
import os
import sys
from datetime import datetime

# ===== КОНФИГУРАЦИЯ =====
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YOUR_USER_ID = 1307172745
DB_NAME = "chat_bot.db"
CACHE_DB = "cache.db"

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
last_selected_chat = None


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
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            )
        ''')
        conn.commit()
        conn.close()
        
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
        logger.info(f"✅ Чат добавлен в БД: {chat_title} ({chat_id})")
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
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM messages_cache WHERE chat_id = ?', (chat_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка очистки кэша: {e}")
        return False

def add_message_to_cache(chat_id, user_id, username, first_name, message_text, message_type, file_id=None):
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
    keyboard = [
        [InlineKeyboardButton("📋 Мои чаты", callback_data="list_chats")],
        [InlineKeyboardButton("📸 Отправить медиа", callback_data="send_media")],
        [InlineKeyboardButton("👁 Отслеживать чат", callback_data="track_chat")],
        [InlineKeyboardButton("🔄 Обновить чаты", callback_data="refresh_chats")]
    ]
    
    if last_selected_chat:
        keyboard.insert(0, [InlineKeyboardButton("⚡ Быстрая отправка", callback_data="quick_send")])
    
    return InlineKeyboardMarkup(keyboard)

def get_quick_send_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Текст", callback_data="quick_text")],
        [InlineKeyboardButton("📷 Фото", callback_data="quick_photo")],
        [InlineKeyboardButton("🎥 Видео", callback_data="quick_video")],
        [InlineKeyboardButton("📄 Документ", callback_data="quick_document")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_chats_keyboard(user_id, page=0, per_page=5):
    chats = get_user_chats(user_id)
    keyboard = []
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(chats))
    
    for chat_id, chat_title, chat_type in chats[start_idx:end_idx]:
        is_selected = (chat_id == last_selected_chat)
        prefix = "⭐ " if is_selected else ""
        keyboard.append([
            InlineKeyboardButton(
                f"{prefix}{chat_title[:30]}", 
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

def get_media_keyboard():
    keyboard = [
        [InlineKeyboardButton("📷 Фото", callback_data="media_photo")],
        [InlineKeyboardButton("🎥 Видео", callback_data="media_video")],
        [InlineKeyboardButton("📄 Документ", callback_data="media_document")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_chat_actions_keyboard(chat_id, is_tracking=False):
    keyboard = []
    
    if is_tracking:
        keyboard.append([InlineKeyboardButton("🛑 Остановить отслеживание", callback_data=f"stop_track_{chat_id}")])
        keyboard.append([InlineKeyboardButton("📜 История (24ч)", callback_data=f"history_{chat_id}")])
        keyboard.append([InlineKeyboardButton("🗑 Очистить историю", callback_data=f"clear_history_{chat_id}")])
    else:
        keyboard.append([InlineKeyboardButton("👁 Начать отслеживание", callback_data=f"start_track_{chat_id}")])
    
    keyboard.append([InlineKeyboardButton("📤 Отправить сообщение", callback_data=f"send_to_{chat_id}")])
    keyboard.append([InlineKeyboardButton("⭐ Выбрать для быстрой отправки", callback_data=f"select_quick_{chat_id}")])
    keyboard.append([InlineKeyboardButton("🗑 Удалить чат", callback_data=f"delete_{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="list_chats")])
    
    return InlineKeyboardMarkup(keyboard)


# ===== ОБРАБОТЧИКИ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != YOUR_USER_ID:
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
        return
    
    await update.message.reply_text(
        "👋 <b>Главное меню</b>\n\nВыберите действие:",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_selected_chat, tracked_chats
    
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
    
    elif data == "quick_send":
        if not last_selected_chat:
            await query.edit_message_text(
                "❌ Нет выбранного чата для быстрой отправки",
                reply_markup=get_main_keyboard()
            )
            return
        
        chat_info = None
        for chat_id, title, ctype in get_user_chats(user_id):
            if chat_id == last_selected_chat:
                chat_info = (title, ctype)
                break
        
        if chat_info:
            text = f"⚡ <b>Быстрая отправка</b>\n\n"
            text += f"📌 Чат: {chat_info[0]}\n"
            text += f"<code>ID: {last_selected_chat}</code>\n\n"
            text += "Выберите что отправить:"
            await query.edit_message_text(
                text,
                parse_mode='HTML',
                reply_markup=get_quick_send_keyboard()
            )
        else:
            last_selected_chat = None
            await query.edit_message_text(
                "❌ Выбранный чат не найден",
                reply_markup=get_main_keyboard()
            )
    
    elif data == "quick_text":
        user_states[user_id] = {'action': 'send_message', 'chat_id': last_selected_chat}
        await query.edit_message_text(
            f"✏️ <b>Введите текст для отправки</b>\n\n"
            f"Чат: <code>{last_selected_chat}</code>",
            parse_mode='HTML'
        )
    
    elif data in ["quick_photo", "quick_video", "quick_document"]:
        media_type = data.split("_")[1]
        user_states[user_id] = {
            'action': 'send_media_file',
            'chat_id': last_selected_chat,
            'media_type': media_type
        }
        
        emoji = {"photo": "📷", "video": "🎥", "document": "📄"}.get(media_type, "📎")
        await query.edit_message_text(
            f"{emoji} <b>Отправьте {media_type}</b>\n\n"
            f"Чат: <code>{last_selected_chat}</code>",
            parse_mode='HTML'
        )
    
    elif data == "list_chats":
        await show_chats(query, user_id, 0)
    
    elif data == "track_chat":
        await show_chats_for_tracking(query, user_id)
    
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        await show_chats(query, user_id, page)
    
    elif data == "send_media":
        await query.edit_message_text(
            "📤 <b>Выберите тип медиа</b>\n\nПосле выбора отправьте файл:",
            parse_mode='HTML',
            reply_markup=get_media_keyboard()
        )
    
    elif data in ["media_photo", "media_video", "media_document"]:
        media_type = data.split("_")[1]
        user_states[user_id] = {'action': 'send_media', 'media_type': media_type}
        await show_chats_for_media(query, user_id, media_type)
    
    elif data == "refresh_chats":
        await query.edit_message_text(
            "🔄 <b>Обновление чатов...</b>",
            parse_mode='HTML'
        )
        await refresh_all_chats(query, context)
    
    elif data.startswith("chat_"):
        chat_id = int(data.split("_")[1])
        await show_chat_actions(query, user_id, chat_id)
    
    elif data.startswith("select_quick_"):
        chat_id = int(data.split("_")[2])
        last_selected_chat = chat_id
        
        await query.edit_message_text(
            f"⭐ <b>Чат выбран для быстрой отправки</b>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    
    elif data.startswith("send_to_"):
        chat_id = int(data.split("_")[2])
        user_states[user_id] = {'action': 'send_message', 'chat_id': chat_id}
        await query.edit_message_text(
            f"✏️ <b>Введите текст для отправки</b>\n\n"
            f"Чат: <code>{chat_id}</code>",
            parse_mode='HTML'
        )
    
    elif data.startswith("start_track_"):
        chat_id = int(data.split("_")[2])
        if chat_id not in tracked_chats:
            tracked_chats.append(chat_id)
        
        await query.edit_message_text(
            f"👁 <b>Отслеживание включено</b>\n\nЧат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_chat_actions_keyboard(chat_id, is_tracking=True)
        )
    
    elif data.startswith("stop_track_"):
        chat_id = int(data.split("_")[2])
        if chat_id in tracked_chats:
            tracked_chats.remove(chat_id)
        
        clear_cache_for_chat(chat_id)
        
        await query.edit_message_text(
            f"🛑 <b>Отслеживание остановлено</b>\n\nЧат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_chat_actions_keyboard(chat_id, is_tracking=False)
        )
    
    elif data.startswith("history_"):
        chat_id = int(data.split("_")[1])
        messages = get_cached_messages(chat_id)
        
        if not messages:
            await query.edit_message_text(
                f"📭 <b>История пуста</b>\n\nЧат: <code>{chat_id}</code>",
                parse_mode='HTML',
                reply_markup=get_chat_actions_keyboard(chat_id, is_tracking=True)
            )
            return
        
        text = f"📜 <b>История чата</b>\n\n"
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
    
    elif data.startswith("clear_history_"):
        chat_id = int(data.split("_")[2])
        clear_cache_for_chat(chat_id)
        await query.edit_message_text(
            f"🗑 <b>История очищена</b>\n\nЧат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_chat_actions_keyboard(chat_id, is_tracking=True)
        )
    
    elif data.startswith("delete_"):
        chat_id = int(data.split("_")[1])
        remove_chat_from_db(user_id, chat_id)
        if last_selected_chat == chat_id:
            last_selected_chat = None
        await query.edit_message_text(
            f"🗑 <b>Чат удален</b>\n\nЧат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )


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
        is_selected = "⭐ " if chat_id == last_selected_chat else ""
        text += f"{is_selected}{emoji} {chat_title}\n<code>{chat_id}</code>\n\n"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=get_chats_keyboard(user_id, page)
    )

async def show_chats_for_tracking(query, user_id):
    chats = get_user_chats(user_id)
    
    if not chats:
        await query.edit_message_text(
            "📭 <b>Нет сохраненных чатов</b>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
        return
    
    keyboard = []
    for chat_id, chat_title, chat_type in chats:
        is_tracking = chat_id in tracked_chats
        status = "🟢" if is_tracking else "⚪️"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {chat_title[:30]}", 
                callback_data=f"chat_{chat_id}"
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])
    
    await query.edit_message_text(
        "👁 <b>Выберите чат для управления отслеживанием</b>\n\n🟢 - отслеживается\n⚪️ - не отслеживается",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_chats_for_media(query, user_id, media_type):
    chats = get_user_chats(user_id)
    
    if not chats:
        await query.edit_message_text(
            "📭 <b>Нет сохраненных чатов</b>",
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
        f"📤 <b>Выберите чат для отправки {media_type}</b>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_chat_actions(query, user_id, chat_id):
    is_tracking = chat_id in tracked_chats
    is_selected = chat_id == last_selected_chat
    
    chats = get_user_chats(user_id)
    chat_info = next((c for c in chats if c[0] == chat_id), None)
    
    if chat_info:
        title = chat_info[1]
        text = f"📌 <b>{title}</b>\n\n<code>ID: {chat_id}</code>\n\n"
    else:
        text = f"📌 <b>Чат</b>\n\n<code>ID: {chat_id}</code>\n\n"
    
    status = "🟢 Отслеживается" if is_tracking else "⚪️ Не отслеживается"
    selected = "⭐ Выбран для быстрой отправки" if is_selected else "⚪️ Не выбран"
    text += f"Статус: {status}\n{selected}"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=get_chat_actions_keyboard(chat_id, is_tracking)
    )


# ===== ГЛАВНЫЙ ОБРАБОТЧИК ВСЕХ СООБЩЕНИЙ =====
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех сообщений - добавляет чаты и обрабатывает команды"""
    user_id = update.effective_user.id
    chat = update.effective_chat
    chat_id = chat.id
    chat_type = chat.type
    
    # Логируем все сообщения для отладки
    logger.info(f"Получено сообщение от {user_id} в чат {chat_id} ({chat_type})")
    
    # ===== АВТОМАТИЧЕСКОЕ ДОБАВЛЕНИЕ ЧАТОВ =====
    # Добавляем чат если это групповой чат и пользователь - владелец
    if chat_type in ["group", "supergroup"]:
        chat_title = chat.title or "Без названия"
        
        # Добавляем чат для владельца
        if user_id == YOUR_USER_ID:
            if add_chat_to_db(YOUR_USER_ID, chat_id, chat_title, chat_type):
                logger.info(f"✅ Чат добавлен: {chat_title}")
                # Отправляем подтверждение в чат
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="✅ Бот активирован в этом чате!"
                )
        else:
            # Если пишет не владелец - уведомляем владельца
            user = update.effective_user
            try:
                await context.bot.send_message(
                    chat_id=YOUR_USER_ID,
                    text=f"⚠️ <b>Сообщение в чате</b>\n\n"
                         f"📌 Чат: {chat.title}\n"
                         f"👤 Пользователь: {user.first_name} (@{user.username or 'Нет'})\n"
                         f"💬 {update.message.text[:100] if update.message.text else 'Медиа'}",
                    parse_mode='HTML'
                )
            except:
                pass
            return  # Не обрабатываем дальше
    
    # Если это приватный чат и не владелец - игнорируем
    if chat_type == "private" and user_id != YOUR_USER_ID:
        return
    
    # ===== ОБРАБОТКА СОСТОЯНИЙ =====
    if user_id in user_states and chat_type == "private":
        state = user_states[user_id]
        
        # Отправка текста
        if state['action'] == 'send_message' and update.message.text:
            chat_id = state['chat_id']
            try:
                await context.bot.send_message(chat_id=chat_id, text=update.message.text)
                await update.message.reply_text(
                    f"✅ Сообщение отправлено",
                    reply_markup=get_main_keyboard()
                )
                del user_states[user_id]
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
            return
        
        # Отправка медиа
        elif state['action'] == 'send_media_file':
            chat_id = state['chat_id']
            media_type = state['media_type']
            
            try:
                if media_type == "photo" and update.message.photo:
                    photo = update.message.photo[-1]
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo.file_id,
                        caption=update.message.caption
                    )
                    await update.message.reply_text(f"✅ Фото отправлено", reply_markup=get_main_keyboard())
                    del user_states[user_id]
                
                elif media_type == "video" and update.message.video:
                    video = update.message.video
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=video.file_id,
                        caption=update.message.caption
                    )
                    await update.message.reply_text(f"✅ Видео отправлено", reply_markup=get_main_keyboard())
                    del user_states[user_id]
                
                elif media_type == "document" and update.message.document:
                    doc = update.message.document
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=doc.file_id,
                        caption=update.message.caption
                    )
                    await update.message.reply_text(f"✅ Документ отправлен", reply_markup=get_main_keyboard())
                    del user_states[user_id]
                
                else:
                    await update.message.reply_text(
                        f"❌ Отправьте {media_type}",
                        reply_markup=get_main_keyboard()
                    )
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
            return
    
    # ===== ПОКАЗЫВАЕМ МЕНЮ В ПРИВАТЕ =====
    if chat_type == "private" and user_id == YOUR_USER_ID:
        # Если это не команда и нет состояния - показываем меню
        if not update.message.text or not update.message.text.startswith('/'):
            await update.message.reply_text(
                "👋 <b>Главное меню</b>\n\nВыберите действие:",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )


async def handle_media_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        user_states[user_id] = {
            'action': 'send_media_file',
            'chat_id': chat_id,
            'media_type': media_type
        }
        
        emoji = {"photo": "📷", "video": "🎥", "document": "📄"}.get(media_type, "📎")
        await query.edit_message_text(
            f"{emoji} <b>Отправьте {media_type}</b>\n\nЧат: <code>{chat_id}</code>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Отмена", callback_data="send_media")]
            ])
        )


async def track_chat_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отслеживание сообщений в чате"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat = update.effective_chat
    
    if chat.type not in ["group", "supergroup"]:
        return
    
    if chat_id not in tracked_chats:
        return
    
    user = update.effective_user
    username = user.username or "Нет"
    first_name = user.first_name or "Нет"
    
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
    
    add_message_to_cache(
        chat_id, user_id, username, first_name, 
        message_text, message_type, file_id
    )
    
    time = datetime.now().strftime("%H:%M:%S")
    user_info = f"@{username}" if username != "Нет" else first_name
    
    notification_text = (
        f"📨 <b>Новое сообщение</b>\n\n"
        f"👤 {user_info} (ID: {user_id})\n"
        f"💬 {message_text}\n"
        f"🕐 {time}"
    )
    
    try:
        if file_id and message_type in ["photo", "video", "document"]:
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
        else:
            await context.bot.send_message(
                chat_id=YOUR_USER_ID,
                text=notification_text,
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")


async def refresh_all_chats(query, context):
    try:
        # Просто показываем сколько чатов в базе
        chats = get_user_chats(YOUR_USER_ID)
        
        await query.edit_message_text(
            f"✅ <b>Чаты обновлены</b>\n\n"
            f"📋 Всего чатов: {len(chats)}\n\n"
            f"<i>Чтобы добавить чат:\n"
            f"1. Добавьте бота в чат\n"
            f"2. Напишите любое сообщение в чате\n"
            f"3. Нажмите 'Обновить чаты' снова</i>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка: {str(e)}",
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
        cleanup_old_cache()
        
        application = Application.builder().token(TOKEN).build()
        
        # Обработчики команд
        application.add_handler(CommandHandler("start", start))
        
        # Callback обработчики
        application.add_handler(CallbackQueryHandler(handle_media_selection, pattern="^media_chat_"))
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        # ГЛАВНЫЙ ОБРАБОТЧИК ВСЕХ СООБЩЕНИЙ (приоритет выше)
        application.add_handler(MessageHandler(
            filters.ALL,
            handle_all_messages
        ))
        
        # Отслеживание чатов
        application.add_handler(MessageHandler(
            filters.ChatType.GROUP | filters.ChatType.SUPERGROUP,
            track_chat_messages
        ))
        
        application.add_error_handler(error_handler)
        
        print("✅ Бот успешно запущен!")
        print("🔄 Ожидание сообщений...")
        print("❌ Чтобы остановить бота, нажмите Ctrl+C")
        print("=" * 50)
        
        application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}")
        print(f"❌ Критическая ошибка: {e}")

if __name__ == "__main__":
    main()
