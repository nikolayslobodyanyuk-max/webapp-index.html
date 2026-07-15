import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# КОНФИГУРАЦИЯ - ЗАМЕНИТЕ ЭТИ ЗНАЧЕНИЯ!
TOKEN = '8753350871:AAGTNJVb9pb93fMP_Oe7cjRYb2g5wqPJ4jo'
WEBAPP_URL = 'https://nikolayslobodyanyuk-max.github.io/botmysoul/webapp/'  # ИЗМЕНИТЕ НА ВАШ URL!

# Хранилище данных (в реальном проекте используйте БД)
class UserStorage:
    def __init__(self):
        self.waiting_users: List[int] = []
        self.active_chats: Dict[int, int] = {}
        self.user_last_action: Dict[int, datetime] = {}
        self.user_data: Dict[int, dict] = {}
    
    def add_to_waiting(self, user_id: int) -> bool:
        if user_id not in self.waiting_users and user_id not in self.active_chats:
            self.waiting_users.append(user_id)
            self.user_last_action[user_id] = datetime.now()
            return True
        return False
    
    def remove_from_waiting(self, user_id: int) -> bool:
        if user_id in self.waiting_users:
            self.waiting_users.remove(user_id)
            return True
        return False
    
    def get_partner(self, user_id: int) -> Optional[int]:
        if not self.waiting_users:
            return None
        for waiting_user in self.waiting_users:
            if waiting_user != user_id:
                return waiting_user
        return None
    
    def create_chat(self, user1: int, user2: int) -> bool:
        self.active_chats[user1] = user2
        self.active_chats[user2] = user1
        self.remove_from_waiting(user1)
        self.remove_from_waiting(user2)
        self.user_last_action[user1] = datetime.now()
        self.user_last_action[user2] = datetime.now()
        return True
    
    def end_chat(self, user_id: int) -> Optional[int]:
        if user_id in self.active_chats:
            partner_id = self.active_chats[user_id]
            del self.active_chats[user_id]
            if partner_id in self.active_chats:
                del self.active_chats[partner_id]
            return partner_id
        return None
    
    def is_in_chat(self, user_id: int) -> bool:
        return user_id in self.active_chats
    
    def is_waiting(self, user_id: int) -> bool:
        return user_id in self.waiting_users
    
    def get_chat_partner(self, user_id: int) -> Optional[int]:
        return self.active_chats.get(user_id)
    
    def cleanup_inactive(self):
        now = datetime.now()
        to_remove = []
        for user_id, last_time in self.user_last_action.items():
            if now - last_time > timedelta(minutes=5):
                to_remove.append(user_id)
        
        for user_id in to_remove:
            if user_id in self.waiting_users:
                self.waiting_users.remove(user_id)
            if user_id in self.active_chats:
                partner = self.active_chats[user_id]
                if partner in self.active_chats:
                    del self.active_chats[partner]
                del self.active_chats[user_id]
            if user_id in self.user_last_action:
                del self.user_last_action[user_id]
            if user_id in self.user_data:
                del self.user_data[user_id]

storage = UserStorage()

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if storage.is_in_chat(user_id):
        await update.message.reply_text("⚠️ Вы уже в чате! Используйте /stop чтобы выйти.")
        return
    
    if storage.is_waiting(user_id):
        storage.remove_from_waiting(user_id)
    
    keyboard = [
        [InlineKeyboardButton("📱 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("🔍 Найти собеседника", callback_data='find')],
        [InlineKeyboardButton("❌ Закончить диалог", callback_data='stop')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "🤝 Бот для анонимных знакомств с Mini App!\n"
        "📱 Нажмите «Открыть приложение» для полного интерфейса.\n\n"
        "Или используйте кнопки ниже для быстрого управления:\n"
        "🔍 Найти собеседника\n"
        "❌ Закончить диалог\n"
        "📊 Статистика",
        reply_markup=reply_markup
    )

# Обработка данных из мини-приложения
async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        data = json.loads(update.message.web_app_data.data)
        action = data.get('action')
        
        logger.info(f"WebApp данные от {user_id}: {action}")
        
        if action == 'find':
            await handle_find_action(user_id, context)
        elif action == 'stop':
            await handle_stop_action(user_id, context)
        elif action == 'message':
            await handle_message_action(user_id, data.get('text'), context)
        elif action == 'next':
            await handle_next_action(user_id, context)
        elif action == 'get_status':
            await handle_status_action(user_id, context)
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
        await update.message.reply_text("❌ Ошибка обработки данных")
    except Exception as e:
        logger.error(f"Ошибка в handle_webapp_data: {e}")
        await update.message.reply_text("❌ Произошла ошибка")

async def handle_find_action(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if storage.is_in_chat(user_id):
        await send_webapp_response(user_id, {'action': 'error', 'text': 'Вы уже в чате'})
        return
    
    partner_id = storage.get_partner(user_id)
    
    if partner_id is None:
        storage.add_to_waiting(user_id)
        await send_webapp_response(user_id, {'action': 'waiting', 'text': 'Ищем собеседника...'})
    else:
        storage.create_chat(user_id, partner_id)
        await send_webapp_response(user_id, {'action': 'chat_started', 'message': 'Собеседник найден! 🎉'})
        await send_webapp_response(partner_id, {'action': 'chat_started', 'message': 'Собеседник найден! 🎉'})

async def handle_stop_action(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if storage.is_waiting(user_id):
        storage.remove_from_waiting(user_id)
        await send_webapp_response(user_id, {'action': 'chat_ended', 'text': 'Поиск отменен'})
        return
    
    partner_id = storage.end_chat(user_id)
    if partner_id:
        await send_webapp_response(partner_id, {'action': 'partner_left', 'text': 'Собеседник завершил диалог'})
    
    await send_webapp_response(user_id, {'action': 'chat_ended', 'text': 'Диалог завершен'})

async def handle_message_action(user_id: int, text: str, context: ContextTypes.DEFAULT_TYPE):
    if not text:
        return
    
    partner_id = storage.get_chat_partner(user_id)
    if partner_id:
        await send_webapp_response(partner_id, {'action': 'new_message', 'text': text})
        await send_webapp_response(user_id, {'action': 'message_sent', 'text': text})
    else:
        await send_webapp_response(user_id, {'action': 'error', 'text': 'Собеседник не найден'})

async def handle_next_action(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    partner_id = storage.end_chat(user_id)
    if partner_id:
        await send_webapp_response(partner_id, {'action': 'partner_left', 'text': 'Собеседник ищет нового'})
    
    new_partner = storage.get_partner(user_id)
    if new_partner is None:
        storage.add_to_waiting(user_id)
        await send_webapp_response(user_id, {'action': 'waiting', 'text': 'Ищем нового собеседника...'})
    else:
        storage.create_chat(user_id, new_partner)
        await send_webapp_response(user_id, {'action': 'chat_started', 'message': 'Новый собеседник найден! 🎉'})
        await send_webapp_response(new_partner, {'action': 'chat_started', 'message': 'Новый собеседник найден! 🎉'})

async def handle_status_action(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    status = {
        'action': 'status',
        'is_waiting': storage.is_waiting(user_id),
        'is_in_chat': storage.is_in_chat(user_id),
        'has_partner': storage.get_chat_partner(user_id) is not None
    }
    await send_webapp_response(user_id, status)

async def send_webapp_response(user_id: int, data: dict):
    try:
        await context.bot.send_message(chat_id=user_id, text=json.dumps(data))
    except Exception as e:
        logger.error(f"Ошибка отправки в WebApp: {e}")

# Обработка кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    storage.user_last_action[user_id] = datetime.now()
    
    if data == 'find':
        await find_partner(query, context)
    elif data == 'stop':
        await stop_chat(query, context)
    elif data == 'next':
        await next_partner(query, context)
    elif data == 'stats':
        await show_stats(query)

async def find_partner(query, context):
    user_id = query.from_user.id
    
    if storage.is_in_chat(user_id):
        await query.edit_message_text("⚠️ Вы уже в чате!", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Закончить", callback_data='stop')]
        ]))
        return
    
    if storage.is_waiting(user_id):
        await query.edit_message_text("⏳ Вы уже в очереди поиска.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Отменить", callback_data='stop')]
        ]))
        return
    
    partner_id = storage.get_partner(user_id)
    
    if partner_id is None:
        storage.add_to_waiting(user_id)
        await query.edit_message_text("🔍 Ищем собеседника...", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Отменить", callback_data='stop')]
        ]))
        return
    
    storage.create_chat(user_id, partner_id)
    await notify_chat_start(user_id, partner_id, context)
    
    await query.edit_message_text("✅ Собеседник найден! 🎉", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Следующий", callback_data='next')],
        [InlineKeyboardButton("❌ Закончить", callback_data='stop')]
    ]))

async def notify_chat_start(user_id, partner_id, context):
    try:
        for uid in [user_id, partner_id]:
            await context.bot.send_message(
                chat_id=uid,
                text="✅ Собеседник найден! 🎉\nМожете начинать общение.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➡️ Следующий", callback_data='next')],
                    [InlineKeyboardButton("❌ Закончить", callback_data='stop')]
                ])
            )
    except Exception as e:
        logger.error(f"Ошибка уведомления: {e}")

async def stop_chat(query, context):
    user_id = query.from_user.id
    
    if storage.is_waiting(user_id):
        storage.remove_from_waiting(user_id)
        await query.edit_message_text("❌ Поиск отменен.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Найти", callback_data='find')]
        ]))
        return
    
    if storage.is_in_chat(user_id):
        partner_id = storage.end_chat(user_id)
        if partner_id:
            try:
                await context.bot.send_message(chat_id=partner_id, text="👋 Собеседник завершил диалог.")
            except Exception:
                pass
        
        await query.edit_message_text("✅ Диалог завершен.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Найти", callback_data='find')]
        ]))
        return
    
    await query.edit_message_text("ℹ️ Вы не в диалоге.", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Найти", callback_data='find')]
    ]))

async def next_partner(query, context):
    user_id = query.from_user.id
    
    if storage.is_in_chat(user_id):
        partner_id = storage.end_chat(user_id)
        if partner_id:
            try:
                await context.bot.send_message(chat_id=partner_id, text="👋 Собеседник ищет нового.")
            except Exception:
                pass
    
    storage.remove_from_waiting(user_id)
    partner_id = storage.get_partner(user_id)
    
    if partner_id is None:
        storage.add_to_waiting(user_id)
        await query.edit_message_text("🔍 Ищем нового собеседника...", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Отменить", callback_data='stop')]
        ]))
        return
    
    storage.create_chat(user_id, partner_id)
    await notify_chat_start(user_id, partner_id, context)
    
    await query.edit_message_text("✅ Новый собеседник найден! 🎉", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Следующий", callback_data='next')],
        [InlineKeyboardButton("❌ Закончить", callback_data='stop')]
    ]))

async def show_stats(query):
    stats_text = (
        "📊 Статистика:\n\n"
        f"👥 В очереди: {len(storage.waiting_users)}\n"
        f"💬 Активных чатов: {len(storage.active_chats) // 2}\n"
        f"👤 Всего пользователей: {len(storage.user_last_action)}\n"
    )
    await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Назад", callback_data='find')]
    ]))

# Обработка текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    storage.user_last_action[user_id] = datetime.now()
    
    if storage.is_in_chat(user_id):
        partner_id = storage.get_chat_partner(user_id)
        if partner_id:
            try:
                await context.bot.send_message(chat_id=partner_id, text=f"💬 {message_text}")
                await update.message.reply_text("✅ Отправлено")
            except Exception as e:
                logger.error(f"Ошибка отправки: {e}")
                await update.message.reply_text("❌ Не удалось отправить")
        else:
            await update.message.reply_text("⚠️ Партнер не найден")
    else:
        await update.message.reply_text("ℹ️ Вы не в чате. Используйте /start")

# Команды
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if storage.is_waiting(user_id):
        storage.remove_from_waiting(user_id)
        await update.message.reply_text("❌ Поиск отменен")
        return
    
    if storage.is_in_chat(user_id):
        partner_id = storage.end_chat(user_id)
        if partner_id:
            try:
                await context.bot.send_message(chat_id=partner_id, text="👋 Собеседник завершил диалог.")
            except Exception:
                pass
        await update.message.reply_text("✅ Диалог завершен")
        return
    
    await update.message.reply_text("ℹ️ Вы не в диалоге")

async def next_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    class FakeQuery:
        def __init__(self, user, message):
            self.from_user = user
            self.message = message
        async def edit_message_text(self, text, reply_markup=None):
            await self.message.reply_text(text, reply_markup=reply_markup)
        async def answer(self):
            pass
    
    fake_query = FakeQuery(update.effective_user, update.message)
    await next_partner(fake_query, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 Помощь:\n\n"
        "/start - Главное меню\n"
        "/stop - Завершить диалог\n"
        "/next - Найти нового собеседника\n"
        "/help - Эта справка\n\n"
        "📱 Используйте мини-приложение для лучшего опыта!"
    )
    await update.message.reply_text(help_text)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

def main():
    application = Application.builder().token(TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("next", next_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Обработчики
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    print("🤖 Бот для знакомств с Mini App запущен!")
    print(f"🌐 WebApp URL: {WEBAPP_URL}")
    print("📱 Найдите бота в Telegram и нажмите START")
    print("🛑 Нажмите Ctrl+C для остановки")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()