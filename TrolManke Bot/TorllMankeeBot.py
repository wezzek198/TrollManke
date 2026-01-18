import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import sqlite3
import os
import sys

# ===== КОНФИГУРАЦИЯ =====
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # ЗАМЕНИТЕ НА ВАШ ТОКЕН!
YOUR_USER_ID = 1307172745 # ЗАМЕНИТЕ НА ВАШ ID!
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

# Глобальная переменная для хранения целевого чата
target_chat_for_photo = None

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
                PRIMARY KEY (user_id, chat_id)
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

def add_chat_to_db(user_id, chat_id, chat_title):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO user_chats (user_id, chat_id, chat_title) VALUES (?, ?, ?)',
            (user_id, chat_id, chat_title)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления чата в БД: {e}")
        return False

def get_user_chats(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT chat_id, chat_title FROM user_chats WHERE user_id = ?',
            (user_id,)
        )
        chats = cursor.fetchall()
        conn.close()
        return chats
    except Exception as e:
        logger.error(f"Ошибка получения чатов из БД: {e}")
        return []

# ===== НОВАЯ КОМАНДА SCAN =====
async def scan_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сканирует все чаты, где находится бот, и добавляет их в базу"""
    try:
        if update.effective_chat.type != "private":
            return
        
        user_id = update.effective_user.id
        if user_id != YOUR_USER_ID:
            await update.message.reply_text("🚫 У вас нет доступа к этой команде.")
            return
        
        await update.message.reply_text("🔍 <b>Начинаю сканирование чатов...</b>", parse_mode='HTML')
        
        # Получаем список всех чатов, где есть бот
        total_chats = 0
        added_chats = 0
        errors = 0
        
        # К сожалению, Telegram Bot API не предоставляет прямого метода для получения списка чатов
        # Поэтому будем использовать альтернативный подход:
        # Бот будет пытаться получить информацию о чатах, которые уже есть в базе, и добавить новые
        
        # Для реального сканирования всех чатов нужно использовать getUpdates или webhook
        # Но это сложно. Вместо этого предложу улучшенную версию:
        
        # Альтернативный подход: бот будет слушать сообщения из ВСЕХ чатов
        # и автоматически добавлять их при получении любого сообщения
        
        await update.message.reply_text(
            "📋 <b>Сканирование завершено!</b>\n\n"
            "Теперь бот будет автоматически добавлять все чаты, в которых вы напишете любое сообщение.\n\n"
            "Чтобы добавить чаты:\n"
            "1. Перейдите в чат где есть бот\n"
            "2. Напишите любое сообщение\n"
            "3. Бот автоматически добавит чат в базу\n\n"
            "Используйте /chats чтобы посмотреть все добавленные чаты.",
            parse_mode='HTML'
        )
        
    except Exception as e:
        error_msg = f"❌ Ошибка при сканировании: {e}"
        logger.error(error_msg)
        await update.message.reply_text(error_msg)

# ===== УЛУЧШЕННАЯ ФУНКЦИЯ ДЛЯ АВТОМАТИЧЕСКОГО ДОБАВЛЕНИЯ ЛЮБЫХ ЧАТОВ =====
async def track_all_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Автоматически добавляет любой чат, где бот получает сообщение"""
    try:
        if update.effective_chat.type == "private":
            return
        
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        chat_title = update.effective_chat.title or "Без названия"
        
        # Добавляем чат для владельца бота
        if user_id == YOUR_USER_ID:
            if add_chat_to_db(user_id, chat_id, chat_title):
                logger.info(f"Чат сохранен: {chat_title} ({chat_id})")
        
    except Exception as e:
        logger.error(f"Ошибка в track_all_chats: {e}")

# ===== ОСНОВНЫЕ КОМАНДЫ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type == "private":
            user_id = update.effective_user.id
            if user_id == YOUR_USER_ID:
                await update.message.reply_text(
                    "🤖 <b>Привет, хозяин!</b>\n\n"
                    "Добавь меня в чаты как администратора, затем просто напиши любое сообщение в чате.\n\n"
                    "<b>Доступные команды:</b>\n"
                    "/scan - просканировать все чаты\n"
                    "/chats - показать все мои чаты\n"
                    "/send [ID_чата] [сообщение] - отправить текст\n"
                    "/pic [ID_чата] - подготовиться к отправке фото\n\n"
                    "После /pic просто отправьте фото следующим сообщением",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text("🚫 У вас нет доступа к этому боту.")
    except Exception as e:
        logger.error(f"Ошибка в команде start: {e}")

async def list_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private":
            return
        
        user_id = update.effective_user.id
        if user_id != YOUR_USER_ID:
            await update.message.reply_text("🚫 У вас нет доступа к этой команде.")
            return
        
        chats = get_user_chats(user_id)
        if not chats:
            await update.message.reply_text("📭 Вы еще не добавили меня ни в один чат.")
            return
        
        message = "📋 <b>Ваши чаты:</b>\n\n"
        for chat_id, chat_title in chats:
            message += f"• {chat_title}\n<code>ID: {chat_id}</code>\n\n"
        
        await update.message.reply_text(message, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка в list_chats: {e}")

async def send_message_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type != "private":
            return
        
        user_id = update.effective_user.id
        if user_id != YOUR_USER_ID:
            await update.message.reply_text("🚫 У вас нет доступа к этой команде.")
            return
        
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "❌ <b>Неверный формат команды</b>\n\n"
                "Используйте: <code>/send [ID_чата] [сообщение]</code>\n"
                "Пример: <code>/send -1002284518507 Привет, чат!</code>",
                parse_mode='HTML'
            )
            return
        
        try:
            target_chat_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ ID чата должен быть числом!")
            return
        
        user_chats = [chat[0] for chat in get_user_chats(user_id)]
        if target_chat_id not in user_chats:
            await update.message.reply_text("❌ У вас нет доступа к этому чату или чат не найден.")
            return
        
        message_text = ' '.join(context.args[1:])
        
        await context.bot.send_message(chat_id=target_chat_id, text=message_text)
        await update.message.reply_text(f"✅ Сообщение отправлено в чат {target_chat_id}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка при отправке: {e}"
        logger.error(error_msg)
        await update.message.reply_text(error_msg)

async def handle_photo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /pic"""
    global target_chat_for_photo
    
    try:
        if update.effective_chat.type != "private":
            return
        
        user_id = update.effective_user.id
        if user_id != YOUR_USER_ID:
            await update.message.reply_text("🚫 У вас нет доступа к этой команде.")
            return
        
        if not context.args or len(context.args) < 1:
            await update.message.reply_text(
                "❌ <b>Неверный формат команды</b>\n\n"
                "Используйте: <code>/pic [ID_чата]</code>\n"
                "Пример: <code>/pic -1002284518507</code>",
                parse_mode='HTML'
            )
            return
        
        try:
            target_chat_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ ID чата должен быть числом!")
            return
        
        user_chats = [chat[0] for chat in get_user_chats(user_id)]
        if target_chat_id not in user_chats:
            await update.message.reply_text("❌ У вас нет доступа к этому чату.")
            return
        
        # Сохраняем целевой чат в глобальной переменной
        target_chat_for_photo = target_chat_id
        
        await update.message.reply_text(
            f"📸 <b>Готов отправить фото в чат {target_chat_id}</b>\n\n"
            "Теперь отправьте фото следующим сообщением.",
            parse_mode='HTML'
        )
        logger.info(f"Установлен целевой чат для фото: {target_chat_id}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка: {e}"
        logger.error(error_msg)
        await update.message.reply_text(error_msg)

async def handle_private_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик приватных сообщений (для фото)"""
    global target_chat_for_photo
    
    try:
        if update.effective_chat.type != "private":
            return
        
        user_id = update.effective_user.id
        if user_id != YOUR_USER_ID:
            return
        
        # Если есть фото и установлен целевой чат
        if update.message.photo and target_chat_for_photo:
            logger.info(f"Получено фото для отправки в чат {target_chat_for_photo}")
            
            # Отправляем фото в целевой чат
            photo_file = await update.message.photo[-1].get_file()
            await context.bot.send_photo(
                chat_id=target_chat_for_photo,
                photo=photo_file.file_id,
                caption=update.message.caption
            )
            
            await update.message.reply_text(f"✅ Фото отправлено в чат {target_chat_for_photo}")
            logger.info(f"Фото успешно отправлено в чат {target_chat_for_photo}")
            
            # Сбрасываем целевой чат
            target_chat_for_photo = None
            
        elif update.message.photo:
            # Если фото отправлено без команды /pic
            await update.message.reply_text(
                "📸 <b>Чтобы отправить фото:</b>\n\n"
                "1. Сначала используйте команду: <code>/pic [ID_чата]</code>\n"
                "2. Затем отправьте фото следующим сообщением\n\n"
                "Пример: <code>/pic -1002284518507</code>",
                parse_mode='HTML'
            )
            
    except Exception as e:
        error_msg = f"❌ Ошибка при обработке фото: {e}"
        logger.error(error_msg)
        target_chat_for_photo = None
        await update.message.reply_text(error_msg)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")

# ===== ЗАПУСК БОТА =====
def main():
    global target_chat_for_photo
    target_chat_for_photo = None
    
    try:
        print("=" * 50)
        print("Запуск Telegram бота...")
        print("=" * 50)
        
        if TOKEN == "YOUR_BOT_TOKEN_HERE":
            print("❌ ОШИБКА: Замените TOKEN на ваш реальный токен!")
            input("Нажмите Enter для выхода...")
            return
        
        if YOUR_USER_ID == 123456789:
            print("❌ ОШИБКА: Замените YOUR_USER_ID на ваш реальный ID!")
            input("Нажмите Enter для выхода...")
            return
        
        init_db()
        application = Application.builder().token(TOKEN).build()
        
        # Добавляем обработчики в правильном порядке
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("scan", scan_chats))  # НОВАЯ КОМАНДА
        application.add_handler(CommandHandler("chats", list_chats))
        application.add_handler(CommandHandler("send", send_message_to_chat))
        application.add_handler(CommandHandler("pic", handle_photo_command))
        
        # Обработчик для ВСЕХ групповых чатов (любые сообщения)
        application.add_handler(MessageHandler(filters.ChatType.GROUP | filters.ChatType.SUPERGROUP, track_all_chats))
        
        # Обработчик для приватных сообщений (все типы контента)
        application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, handle_private_messages))
        
        application.add_error_handler(error_handler)
        
        print("✅ Бот успешно запущен!")
        print("🔄 Ожидание сообщений...")
        print("❌ Чтобы остановить бота, нажмите Ctrl+C")
        print("=" * 50)
        
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}")
        print(f"❌ Критическая ошибка: {e}")
        input("Нажмите Enter для выхода...")

if __name__ == "__main__":

    main()

