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
tracked_chats = []  # Список отслеживаемых чатов
fixed_chat = None  # Закрепленный чат для быстрой отправки


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
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
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


# ===== КЛАВИАТУРЫ =====
def get_main_keyboard():
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("📋 Список чатов", callback_data="list_chats")],
        [InlineKeyboardButton("👁 Отслеживание", callback_data="tracking_menu")],
        [InlineKeyboardButton("🔄 Обновить чаты", callback_data="refresh_chats")]
    ]
    
    if fixed_chat:
        chat_title = "Чат"
        for cid, title, ctype in get_user_chats(YOUR_USER_ID):
            if cid == fixed_chat:
                chat_title = title[:20]
                break
        keyboard.insert(0, [InlineKeyboardButton(f"⚡ Быстрая отправка в {chat_title}", callback_data="quick_send")])
    
    return InlineKeyboardMarkup(keyboard)

def get_quick_send_keyboard():
    """Клавиатура быстрой отправки"""
    keyboard = [
        [InlineKeyboardButton("📝 Текст", callback_data="quick_text")],
        [InlineKeyboardButton("📷 Фото", callback_data="quick_photo")],
        [InlineKeyboardButton("🎥 Видео", callback_data="quick_video")],
        [InlineKeyboardButton("📄 Документ", callback_data="quick_document")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_chats_keyboard(user_id, page=0, per_page=5):
    """Клавиатура со списком чатов"""
    chats = get_user_chats(user_id)
    keyboard = []
    
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(chats))
    
    for chat_id, chat_title, chat_type in chats[start_idx:end_idx]:
        is_fixed = "⭐ " if chat_id == fixed_chat else ""
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
    """Клавиатура действий с чатом"""
    is_tracking = chat_id in tracked_chats
    is_fixed = chat_id == fixed_chat
    
    keyboard = []
    
    # Отслеживание
    if is_tracking:
        keyboard.append([InlineKeyboardButton("🛑 Остановить отслеживание", callback_data=f"stop_track_{chat_id}")])
    else:
        keyboard.append([InlineKeyboardButton("👁 Начать отслеживание", callback_data=f"start_track_{chat_id}")])
    
    # Закрепление для быстрой отправки
    if is_fixed:
        keyboard.append([InlineKeyboardButton("⭐ Открепить", callback_data=f"unfix_chat")])
    else:
        keyboard.append([InlineKeyboardButton("⭐ Закрепить для быстрой отправки", callback_data=f"fix_chat_{chat_id}")])
    
    # Отправка
    keyboard.append([InlineKeyboardButton("📤 Отправить сообщение", callback_data=f"send_to_{chat_id}")])
    keyboard.append([InlineKeyboardButton("🗑 Удалить чат", callback_data=f"delete_{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="list_chats")])
    
    return InlineKeyboardMarkup(keyboard)

def get_tracking_keyboard():
    """Клавиатура меню отслеживания"""
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
        "👋 <b>Главное меню</b>\n\n"
        "Выберите действие:",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global fixed_chat, tracked_chats
    
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
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
    
    # Меню отслеживания
    elif data == "tracking_menu":
        await query.edit_message_text(
            "👁 <b>Управление отслеживанием</b>\n\n"
            "🟢 - отслеживается\n"
            "⚪️ - не отслеживается\n\n"
            "Выберите чат:",
            parse_mode='HTML',
            reply_markup=get_tracking_keyboard()
        )
    
    # Быстрая отправка
    elif data == "quick_send":
        if not fixed_chat:
            await query.edit_message_text(
                "❌ Нет закрепленного чата",
                reply_markup=get_main_keyboard()
            )
            return
        
        chat_title = "Чат"
        for cid, title, ctype in get_user_chats(user_id):
            if cid == fixed_chat:
                chat_title = title
                break
        
        await query.edit_message_text(
            f"⚡ <b>Быстрая отправка</b>\n\n"
            f"📌 Чат: {chat_title}\n"
            f"<code>ID: {fixed_chat}</code>\n\n"
            f"Выберите что отправить:",
            parse_mode='HTML',
            reply_markup=get_quick_send_keyboard()
        )
    
    # Быстрая отправка текста
    elif data == "quick_text":
        user_states[user_id] = {'action': 'send_message', 'chat_id': fixed_chat}
        await query.edit_message_text(
            f"✏️ <b>Введите текст</b>\n\n"
            f"Чат: <code>{fixed_chat}</code>",
            parse_mode='HTML'
        )
    
    # Быстрая отправка медиа
    elif data in ["quick_photo", "quick_video", "quick_document"]:
        media_type = data.split("_")[1]
        user_states[user_id] = {
            'action': 'send_media',
            'chat_id': fixed_chat,
            'media_type': media_type
        }
        
        emoji = {"photo": "📷", "video": "🎥", "document": "📄"}.get(media_type, "📎")
        await query.edit_message_text(
            f"{emoji} <b>Отправьте {media_type}</b>\n\n"
            f"Чат: <code>{fixed_chat}</code>",
            parse_mode='HTML'
        )
    
    # Список чатов
    elif data == "list_chats":
        await show_chats(query, user_id, 0)
    
    # Пагинация
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        await show_chats(query, user_id, page)
    
    # Действия с чатом
    elif data.startswith("chat_"):
        chat_id = int(data.split("_")[1])
        await show_chat_actions(query, user_id, chat_id)
    
    # Закрепить чат
    elif data.startswith("fix_chat_"):
        chat_id = int(data.split("_")[2])
        fixed_chat = chat_id
        
        await query.edit_message_text(
            f"⭐ <b>Чат закреплен</b>\n\n"
            f"Теперь в главном меню есть кнопка быстрой отправки",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    
    # Открепить чат
    elif data == "unfix_chat":
        fixed_chat = None
        await query.edit_message_text(
            f"⭐ <b>Чат откреплен</b>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    
    # Начать отслеживание
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
    
    # Остановить отслеживание
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
    
    # Отправить сообщение
    elif data.startswith("send_to_"):
        chat_id = int(data.split("_")[2])
        user_states[user_id] = {'action': 'send_message', 'chat_id': chat_id}
        await query.edit_message_text(
            f"✏️ <b>Введите текст</b>\n\n"
            f"Чат: <code>{chat_id}</code>",
            parse_mode='HTML'
        )
    
    # Удалить чат
    elif data.startswith("delete_"):
        chat_id = int(data.split("_")[1])
        remove_chat_from_db(user_id, chat_id)
        if fixed_chat == chat_id:
            fixed_chat = None
        if chat_id in tracked_chats:
            tracked_chats.remove(chat_id)
        
        await query.edit_message_text(
            f"🗑 <b>Чат удален</b>",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
    
    # Обновить чаты
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
        is_fixed = "⭐ " if chat_id == fixed_chat else ""
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
    is_fixed = chat_id == fixed_chat
    
    status = "🟢 Отслеживается" if is_tracking else "⚪️ Не отслеживается"
    fixed = "⭐ Закреплен" if is_fixed else "⚪️ Не закреплен"
    text += f"{status}\n{fixed}"
    
    await query.edit_message_text(
        text,
        parse_mode='HTML',
        reply_markup=get_chat_actions_keyboard(chat_id)
    )


# ===== ОБРАБОТЧИКИ СООБЩЕНИЙ =====
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главный обработчик всех сообщений"""
    user_id = update.effective_user.id
    chat = update.effective_chat
    chat_id = chat.id
    chat_type = chat.type
    
    logger.info(f"Сообщение от {user_id} в {chat_id} ({chat_type})")
    
    # ===== АВТОМАТИЧЕСКОЕ ДОБАВЛЕНИЕ ЧАТОВ =====
    if chat_type in ["group", "supergroup"]:
        chat_title = chat.title or "Без названия"
        
        if user_id == YOUR_USER_ID:
            if add_chat_to_db(YOUR_USER_ID, chat_id, chat_title, chat_type):
                await context.bot.send_message(
                    chat_id=YOUR_USER_ID,
                    text=f"✅ Чат добавлен: {chat_title}\nID: <code>{chat_id}</code>",
                    parse_mode='HTML'
                )
        else:
            # Уведомление о сообщении от другого пользователя
            user = update.effective_user
            try:
                await context.bot.send_message(
                    chat_id=YOUR_USER_ID,
                    text=f"📨 <b>Сообщение в чате</b>\n\n"
                         f"📌 {chat.title}\n"
                         f"👤 {user.first_name} (@{user.username or 'Нет'})\n"
                         f"💬 {update.message.text[:100] if update.message.text else 'Медиа'}",
                    parse_mode='HTML'
                )
            except:
                pass
            return
    
    # ===== ОТСЛЕЖИВАНИЕ ЧАТОВ =====
    if chat_type in ["group", "supergroup"] and chat_id in tracked_chats:
        user = update.effective_user
        username = user.username or "Нет"
        first_name = user.first_name or "Нет"
        
        message_text = ""
        if update.message.text:
            message_text = update.message.text
        elif update.message.photo:
            message_text = "📷 Фото"
        elif update.message.video:
            message_text = "🎥 Видео"
        elif update.message.document:
            message_text = f"📄 {update.message.document.file_name or 'Документ'}"
        elif update.message.audio:
            message_text = "🎵 Аудио"
        elif update.message.voice:
            message_text = "🎤 Голосовое"
        elif update.message.sticker:
            message_text = "🎨 Стикер"
        else:
            message_text = "📎 Другое"
        
        time = datetime.now().strftime("%H:%M:%S")
        user_info = f"@{username}" if username != "Нет" else first_name
        
        notification = (
            f"📨 <b>Отслеживание</b>\n\n"
            f"📌 {chat.title}\n"
            f"👤 {user_info} (ID: {user_id})\n"
            f"💬 {message_text}\n"
            f"🕐 {time}"
        )
        
        try:
            # Пересылаем медиа если есть
            if update.message.photo:
                await context.bot.send_photo(
                    chat_id=YOUR_USER_ID,
                    photo=update.message.photo[-1].file_id,
                    caption=notification[:1024],
                    parse_mode='HTML'
                )
            elif update.message.video:
                await context.bot.send_video(
                    chat_id=YOUR_USER_ID,
                    video=update.message.video.file_id,
                    caption=notification[:1024],
                    parse_mode='HTML'
                )
            elif update.message.document:
                await context.bot.send_document(
                    chat_id=YOUR_USER_ID,
                    document=update.message.document.file_id,
                    caption=notification[:1024],
                    parse_mode='HTML'
                )
            else:
                await context.bot.send_message(
                    chat_id=YOUR_USER_ID,
                    text=notification,
                    parse_mode='HTML'
                )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")
        
        return  # Не обрабатываем дальше
    
    # ===== ПРИВАТНЫЙ ЧАТ =====
    if chat_type == "private":
        # Если не владелец - игнорируем
        if user_id != YOUR_USER_ID:
            return
        
        # Обработка состояний
        if user_id in user_states:
            state = user_states[user_id]
            
            # Отправка текста
            if state['action'] == 'send_message' and update.message.text:
                chat_id = state['chat_id']
                try:
                    await context.bot.send_message(chat_id=chat_id, text=update.message.text)
                    await update.message.reply_text(
                        f"✅ Отправлено",
                        reply_markup=get_main_keyboard()
                    )
                    del user_states[user_id]
                except Exception as e:
                    await update.message.reply_text(f"❌ Ошибка: {e}")
                return
            
            # Отправка медиа
            elif state['action'] == 'send_media':
                chat_id = state['chat_id']
                media_type = state['media_type']
                
                try:
                    if media_type == "photo" and update.message.photo:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=update.message.photo[-1].file_id,
                            caption=update.message.caption
                        )
                        await update.message.reply_text(f"✅ Фото отправлено", reply_markup=get_main_keyboard())
                        del user_states[user_id]
                    
                    elif media_type == "video" and update.message.video:
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=update.message.video.file_id,
                            caption=update.message.caption
                        )
                        await update.message.reply_text(f"✅ Видео отправлено", reply_markup=get_main_keyboard())
                        del user_states[user_id]
                    
                    elif media_type == "document" and update.message.document:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=update.message.document.file_id,
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
        
        # Показываем меню
        if not update.message.text or not update.message.text.startswith('/'):
            await update.message.reply_text(
                "👋 <b>Главное меню</b>\n\nВыберите действие:",
                parse_mode='HTML',
                reply_markup=get_main_keyboard()
            )


async def refresh_all_chats(query, context):
    try:
        chats = get_user_chats(YOUR_USER_ID)
        
        await query.edit_message_text(
            f"✅ <b>Чаты обновлены</b>\n\n"
            f"📋 Всего чатов: {len(chats)}\n\n"
            f"<i>Чтобы добавить чат:\n"
            f"1. Добавьте бота в чат\n"
            f"2. Напишите любое сообщение в чате</i>",
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
        
        application = Application.builder().token(TOKEN).build()
        
        # Обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(handle_callback))
        application.add_handler(MessageHandler(filters.ALL, handle_all_messages))
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
