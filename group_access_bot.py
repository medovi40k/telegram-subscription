import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import json
from pathlib import Path
import sys
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# cfg import
try:
    from config import (
        BOT_TOKEN,
        ADMIN_IDS,
        CHANNEL_ID,
        CHANNEL_LINK,
        TIME_BUTTONS,
        WARNING_HOURS,
        CHECK_INTERVAL,
        DATA_FILE as CONFIG_DATA_FILE,
        VIP_FILE as CONFIG_VIP_FILE,
        START_MESSAGE,
        USER_START_MESSAGE,
        HELP_MESSAGE,
        KICK_MESSAGE,
        USER_KICK_MESSAGE,
        WARNING_MESSAGE,
        APPROVED_MESSAGE,
        DECLINED_MESSAGE,
        USER_SUBSCRIPTION_GRANTED,
        LOG_LEVEL,
        SHOW_SUBSCRIPTION_INFO,
        SUBSCRIPTION_ACTIVE_MESSAGE,
        SUBSCRIPTION_INACTIVE_MESSAGE,
        SUBSCRIPTION_VIP_MESSAGE,
        SUBSCRIPTION_CONTACT,
    )
except ImportError as e:
    print("❌ ОШИБКА: Файл config.py не найден или содержит ошибки!")
    print(f"Детали: {e}")
    print("Создайте файл config.py с настройками бота.")
    sys.exit(1)

log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    logger.error("❌ Не настроен BOT_TOKEN в config.py!")
    sys.exit(1)

if not ADMIN_IDS:
    logger.error("❌ Не настроены ADMIN_IDS в config.py!")
    sys.exit(1)

if CHANNEL_ID == -1001234567890:
    logger.warning("⚠️ Возможно, CHANNEL_ID не настроен в config.py!")

logger.info(f"Загружены настройки: {len(ADMIN_IDS)} админов, {len(TIME_BUTTONS)} кнопок времени")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

DATA_FILE = Path(CONFIG_DATA_FILE)
VIP_FILE = Path(CONFIG_VIP_FILE)



class UserData:
    """Данные о пользователе"""
    def __init__(self, user_id: int, username: str = None):
        self.user_id = user_id
        self.username = username
        self.expires_at: Optional[datetime] = None
        self.warning_sent = False
    
    def to_dict(self):
        return {
            'user_id': self.user_id,
            'username': self.username,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'warning_sent': self.warning_sent
        }
    
    @staticmethod
    def from_dict(data: dict):
        user = UserData(data['user_id'], data.get('username'))
        if data.get('expires_at'):
            user.expires_at = datetime.fromisoformat(data['expires_at'])
        user.warning_sent = data.get('warning_sent', False)
        return user


class DataManager:
    def __init__(self):
        self.users: Dict[int, UserData] = {}
        self.load_data()
    
    def load_data(self):
        if DATA_FILE.exists():
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.users = {
                        int(uid): UserData.from_dict(udata) 
                        for uid, udata in data.items()
                    }
                logger.info(f"Загружено {len(self.users)} пользователей")
            except Exception as e:
                logger.error(f"Ошибка загрузки данных: {e}")
    
    def save_data(self):
        try:
            data = {str(uid): user.to_dict() for uid, user in self.users.items()}
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Данные сохранены")
        except Exception as e:
            logger.error(f"Ошибка сохранения данных: {e}")
    
    def get_user(self, user_id: int) -> Optional[UserData]:
        return self.users.get(user_id)
    
    def add_or_update_user(self, user_id: int, username: str = None, 
                          hours: float = None) -> UserData:
        if user_id not in self.users:
            self.users[user_id] = UserData(user_id, username)
        
        user = self.users[user_id]
        if username:
            user.username = username
        
        if hours is not None:
            if user.expires_at and user.expires_at > datetime.now():
                user.expires_at += timedelta(hours=hours)
            else:
                user.expires_at = datetime.now() + timedelta(hours=hours)
            user.warning_sent = False
        
        self.save_data()
        return user
    
    def remove_user(self, user_id: int):
        if user_id in self.users:
            del self.users[user_id]
            self.save_data()
    
    def get_all_users(self):
        return list(self.users.values())
    
    def has_valid_access(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        if not user or not user.expires_at:
            return False
        return user.expires_at > datetime.now()


class VIPManager:
    def __init__(self):
        self.vip_users: List[int] = []
        self.load_data()
    
    def load_data(self):
        if VIP_FILE.exists():
            try:
                with open(VIP_FILE, 'r', encoding='utf-8') as f:
                    self.vip_users = json.load(f)
                logger.info(f"Загружено {len(self.vip_users)} VIP пользователей")
            except Exception as e:
                logger.error(f"Ошибка загрузки VIP: {e}")
    
    def save_data(self):
        try:
            with open(VIP_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.vip_users, f, indent=2)
            logger.info("VIP данные сохранены")
        except Exception as e:
            logger.error(f"Ошибка сохранения VIP: {e}")
    
    def add_vip(self, user_id: int):
        """Добавить VIP пользователя"""
        if user_id not in self.vip_users:
            self.vip_users.append(user_id)
            self.save_data()
    
    def remove_vip(self, user_id: int):
        """Удалить VIP пользователя"""
        if user_id in self.vip_users:
            self.vip_users.remove(user_id)
            self.save_data()
    
    def is_vip(self, user_id: int) -> bool:
        """Проверить, является ли пользователь VIP"""
        return user_id in self.vip_users
    
    def get_all_vips(self) -> List[int]:
        """Получить всех VIP"""
        return self.vip_users.copy()


data_manager = DataManager()
vip_manager = VIPManager()



class UserManagement(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_custom_hours = State()
    waiting_for_vip_id = State()



def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом"""
    return user_id in ADMIN_IDS


def is_special_user(user_id: int) -> bool:
    """Проверка, является ли пользователь VIP"""
    return vip_manager.is_vip(user_id)


def format_time_remaining(expires_at: datetime) -> str:
    """Форматирование оставшегося времени"""
    now = datetime.now()
    if expires_at <= now:
        return "⏰ Истекло"
    
    delta = expires_at - now
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    
    parts = []
    if days > 0:
        parts.append(f"{days}д")
    if hours > 0:
        parts.append(f"{hours}ч")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes}м")
    
    return " ".join(parts) if parts else "< 1м"


async def resolve_user_identifier(identifier: str) -> tuple[Optional[int], Optional[str]]:
    """
    Определить user_id и username из введенных данных
    Возвращает (user_id, username)
    """
    identifier = identifier.strip()
    
    if identifier.isdigit():
        user_id = int(identifier)
        return user_id, None
    
    return None, None


async def notify_user_subscription(user_id: int, user: UserData):
    """Отправить пользователю уведомление о предоставлении доступа"""
    try:
        time_left = format_time_remaining(user.expires_at)
        expires_date = user.expires_at.strftime('%d.%m.%Y %H:%M')
        
        notification = USER_SUBSCRIPTION_GRANTED.format(
            expires_date=expires_date,
            time_left=time_left,
            channel_link=CHANNEL_LINK
        )
        
        await bot.send_message(user_id, notification, parse_mode="HTML")
        logger.info(f"✅ Уведомление отправлено пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")


def create_time_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Создание клавиатуры с кнопками времени"""
    buttons = []
    
    # Кнопки времени по 2 в ряд
    for i in range(0, len(TIME_BUTTONS), 2):
        row = []
        for j in range(2):
            if i + j < len(TIME_BUTTONS):
                label, hours = TIME_BUTTONS[i + j]
                row.append(InlineKeyboardButton(
                    text=f"➕ {label}",
                    callback_data=f"add_time:{user_id}:{hours}"
                ))
        buttons.append(row)
    
    # Кнопка для ввода своего времени
    buttons.append([InlineKeyboardButton(
        text="⏱ Свое время",
        callback_data=f"custom_time:{user_id}"
    )])
    
    # Кнопка для удаления пользователя
    buttons.append([InlineKeyboardButton(
        text="🗑 Удалить",
        callback_data=f"remove_user:{user_id}"
    )])
    
    # Кнопка назад
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="back_to_list"
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def kick_user(user_id: int):
    try:
        user = data_manager.get_user(user_id)
        username = user.username if user and user.username else str(user_id)
        
        kick_msg = KICK_MESSAGE.format(username=username, user_id=user_id)
        await bot.ban_chat_member(CHANNEL_ID, user_id)
        await bot.unban_chat_member(CHANNEL_ID, user_id)
        
        
        logger.info(f"Пользователь {user_id} удален из канала")
        
        try:
            user_msg = USER_KICK_MESSAGE.format(contact=SUBSCRIPTION_CONTACT)
            await bot.send_message(user_id, user_msg)
        except Exception:
            pass  # Игнорируем, если не можем отправить ЛС
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"✅ Пользователь @{username} (ID: {user_id}) удален из канала.\n"
                    f"Время доступа истекло."
                )
            except Exception:
                pass
        
        data_manager.remove_user(user_id)
        
    except Exception as e:
        logger.error(f"Ошибка при удалении пользователя {user_id}: {e}")


async def send_warning(user_id: int):
    """Отправить предупреждение о скором истечении"""
    try:
        user = data_manager.get_user(user_id)
        if not user or not user.expires_at:
            return
        
        time_left = format_time_remaining(user.expires_at)
        
        try:
            warning_text = WARNING_MESSAGE.format(
                time_left=time_left,
                contact=SUBSCRIPTION_CONTACT
            )
            await bot.send_message(user_id, warning_text, parse_mode="HTML")
        except Exception:
            pass
        
        username = user.username if user.username else str(user_id)
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"⚠️ Скоро истечет доступ:\n"
                    f"👤 @{username} (ID: {user_id})\n"
                    f"⏰ Осталось: {time_left}",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        
        user.warning_sent = True
        data_manager.save_data()
        
        logger.info(f"Предупреждение отправлено пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке предупреждения {user_id}: {e}")


@dp.chat_join_request()
async def handle_join_request(join_request: ChatJoinRequest):
    user_id = join_request.from_user.id
    username = join_request.from_user.username or str(user_id)
    
    logger.info(f"Получена заявка от пользователя {user_id} (@{username})")
    
    if is_special_user(user_id):
        try:
            await join_request.approve()
            
            logger.info(f"✅ VIP пользователь {user_id} одобрен автоматически")
            
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"✅ <b>VIP одобрен автоматически</b>\n\n"
                        f"👤 @{username} (ID: {user_id})\n"
                        f"👑 VIP статус",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            
            return
        except Exception as e:
            logger.error(f"Ошибка при одобрении VIP: {e}")
            return
    
    if data_manager.has_valid_access(user_id):
        try:
            await join_request.approve()
            
            user = data_manager.get_user(user_id)
            time_left = format_time_remaining(user.expires_at)
            expires_date = user.expires_at.strftime('%d.%m.%Y %H:%M')
            
            logger.info(f"✅ Пользователь {user_id} одобрен (доступ до {expires_date})")
            
            for admin_id in ADMIN_IDS:
                try:
                    approval_msg = APPROVED_MESSAGE.format(
                        username=f"@{username}",
                        expires_date=expires_date,
                        time_left=time_left
                    )
                    await bot.send_message(admin_id, approval_msg, parse_mode="HTML")
                except Exception:
                    pass
            
        except Exception as e:
            logger.error(f"Ошибка при одобрении заявки: {e}")
    else:
        logger.info(f"❌ Заявка от {user_id} не одобрена - нет доступа")
        
        for admin_id in ADMIN_IDS:
            try:
                decline_msg = DECLINED_MESSAGE.format(username=f"@{username}")
                decline_msg += f"\n\nℹ️ Заявка висит. Добавьте доступ командой:\n/add {user_id}"
                await bot.send_message(admin_id, decline_msg, parse_mode="HTML")
            except Exception:
                pass


# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start"""
    if is_admin(message.from_user.id):
        await message.answer(START_MESSAGE, parse_mode="HTML")
    else:
        await message.answer(USER_START_MESSAGE, parse_mode="HTML")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Команда /help"""
    if not is_admin(message.from_user.id):
        return
    
    help_text = HELP_MESSAGE.format(warning_hours=WARNING_HOURS)
    await message.answer(help_text, parse_mode="HTML")


@dp.message(Command("info", "status"))
async def cmd_info(message: Message):
    """Команда /info или /status - показать информацию о подписке"""
    if not SHOW_SUBSCRIPTION_INFO:
        return
    
    user_id = message.from_user.id
    
    if is_special_user(user_id):
        await message.answer(SUBSCRIPTION_VIP_MESSAGE, parse_mode="HTML")
        return
    
    user = data_manager.get_user(user_id)
    print(user)
    if user and user.expires_at:
        if user.expires_at > datetime.now():
            time_left = format_time_remaining(user.expires_at)
            expires_date = user.expires_at.strftime('%d.%m.%Y %H:%M')
            
            info_text = SUBSCRIPTION_ACTIVE_MESSAGE.format(
                expires_date=expires_date,
                time_left=time_left,
                contact=SUBSCRIPTION_CONTACT
            )
            await message.answer(info_text, parse_mode="HTML")
        else:
            info_text = SUBSCRIPTION_INACTIVE_MESSAGE.format(contact=SUBSCRIPTION_CONTACT)
            await message.answer(info_text, parse_mode="HTML")
    else:
        info_text = SUBSCRIPTION_INACTIVE_MESSAGE.format(contact=SUBSCRIPTION_CONTACT)
        await message.answer(info_text, parse_mode="HTML")


@dp.message(Command("vip"))
async def cmd_vip(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    vip_users = vip_manager.get_all_vips()
    
    text = "<b>👑 VIP пользователи (бессрочный доступ):</b>\n\n"
    
    if vip_users:
        for user_id in vip_users:
            # trying to get username
            user = data_manager.get_user(user_id)
            if user and user.username:
                text += f"• @{user.username} (ID: {user_id})\n"
            else:
                text += f"• ID: {user_id}\n"
    else:
        text += "Нет VIP пользователей\n"
    
    text += f"\n<b>Всего:</b> {len(vip_users)}"
    
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить VIP", callback_data="add_vip")],
        [InlineKeyboardButton(text="➖ Удалить VIP", callback_data="remove_vip")],
    ]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@dp.message(Command("users"))
async def cmd_users(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    users = data_manager.get_all_users()
    
    if not users:
        await message.answer("📭 Нет пользователей с ограниченным доступом.")
        return
    
    # Сортируем по времени истечения
    active_users = [u for u in users if u.expires_at and u.expires_at > datetime.now()]
    expired_users = [u for u in users if u.expires_at and u.expires_at <= datetime.now()]
    
    text = "<b>👥 Пользователи с доступом:</b>\n\n"
    
    if active_users:
        text += "<b>✅ Активные:</b>\n"
        for user in sorted(active_users, key=lambda x: x.expires_at):
            username = f"@{user.username}" if user.username else f"ID: {user.user_id}"
            time_left = format_time_remaining(user.expires_at)
            text += f"• {username}\n  ⏰ Осталось: {time_left}\n\n"
    
    if expired_users:
        text += "<b>⏰ Истекшие:</b>\n"
        for user in expired_users:
            username = f"@{user.username}" if user.username else f"ID: {user.user_id}"
            text += f"• {username}\n  ❌ Доступ истек\n\n"
    
    text += f"\n<b>👑 VIP пользователей:</b> {len(vip_manager.get_all_vips())}"
    buttons = []
    for user in active_users + expired_users:
        username = user.username if user.username else str(user.user_id)
        buttons.append([InlineKeyboardButton(
            text=f"👤 {username}",
            callback_data=f"user_info:{user.user_id}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text="➕ Добавить пользователя",
        callback_data="add_new_user"
    )])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    await message.answer(
        "👤 Отправьте ID пользователя:\n\n"
        "Примеры:\n"
        "• 123456789 (ID)\n"
        "ℹ️ Пользователь получит уведомление со ссылкой на канал!\n\n"
        "Отмена: /cancel"
    )
    await state.set_state(UserManagement.waiting_for_user_id)


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущей операции"""
    await state.clear()
    await message.answer("❌ Операция отменена.")


@dp.message(UserManagement.waiting_for_user_id)
async def process_user_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    try:
        user_id, username = await resolve_user_identifier(message.text)
        
        if not user_id and not username:
            await message.answer(
                "❌ Неверный формат. Отправьте:\n"
                "• ID (например: 123456789)\n"
                "• Username (например: @username)\n\n"
                "Попробуйте снова или /cancel"
            )
            return
        
        if is_special_user(user_id):
            await message.answer(
                "⚠️ Этот пользователь является VIP и имеет бессрочный доступ."
            )
            await state.clear()
            return
        
        user = data_manager.add_or_update_user(user_id, username)
        
        username_display = f"@{username}" if username else f"ID: {user_id}"
        
        await message.answer(
            f"✅ Пользователь {username_display} добавлен!\n\n"
            "Выберите время доступа:",
            reply_markup=create_time_keyboard(user_id)
        )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при добавлении пользователя: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте снова.")
        await state.clear()


@dp.message(UserManagement.waiting_for_custom_hours)
async def process_custom_hours(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    try:
        hours = float(message.text.strip())
        
        if hours <= 0:
            await message.answer("❌ Время должно быть положительным числом.")
            return
        
        data = await state.get_data()
        user_id = data.get('user_id')
        
        if not user_id:
            await message.answer("❌ Ошибка. Попробуйте снова.")
            await state.clear()
            return
        
        user = data_manager.add_or_update_user(user_id, hours=hours)
        
        await notify_user_subscription(user_id, user)
        
        username = user.username if user.username else str(user_id)
        username_display = f"@{username}" if username else f"ID: {user_id}"
        time_left = format_time_remaining(user.expires_at)
        expires_date = user.expires_at.strftime('%d.%m.%Y %H:%M')
        
        await message.answer(
            f"✅ <b>Доступ предоставлен!</b>\n\n"
            f"👤 {username_display}\n"
            f"⏰ Доступ до: {expires_date}\n"
            f"⏱ Срок: {time_left}\n\n"
            f"📨 Пользователю отправлено уведомление со ссылкой на канал!",
            parse_mode="HTML"
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число часов (можно с дробной частью).")
    except Exception as e:
        logger.error(f"Ошибка при установке времени: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте снова.")
        await state.clear()


@dp.message(UserManagement.waiting_for_vip_id)
async def process_vip_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    try:
        data = await state.get_data()
        action = data.get('action')
        
        user_id, username = await resolve_user_identifier(message.text)
        
        if not user_id:
            await message.answer("❌ Не удалось определить пользователя. Попробуйте снова или /cancel")
            return
        
        if action == 'add':
            vip_manager.add_vip(user_id)
            username_display = f"@{username}" if username else f"ID: {user_id}"
            await message.answer(f"✅ Пользователь {username_display} добавлен в VIP!")
        elif action == 'remove':
            vip_manager.remove_vip(user_id)
            username_display = f"@{username}" if username else f"ID: {user_id}"
            await message.answer(f"✅ Пользователь {username_display} удален из VIP!")
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при VIP операции: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте снова.")
        await state.clear()



@dp.callback_query(F.data == "add_vip")
async def callback_add_vip(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа!")
        return
    
    await callback.message.answer(
        "👑 Отправьте ID пользователя для добавления в VIP:\n\n"
        "Отмена: /cancel"
    )
    await state.update_data(action='add')
    await state.set_state(UserManagement.waiting_for_vip_id)
    await callback.answer()


@dp.callback_query(F.data == "remove_vip")
async def callback_remove_vip(callback: CallbackQuery, state: FSMContext):
    """Удалить VIP пользователя"""
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа!")
        return
    
    await callback.message.answer(
        "👑 Отправьте ID пользователя для удаления из VIP:\n\n"
        "Отмена: /cancel"
    )
    await state.update_data(action='remove')
    await state.set_state(UserManagement.waiting_for_vip_id)
    await callback.answer()


@dp.callback_query(F.data == "add_new_user")
async def callback_add_new_user(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа!")
        return
    
    await callback.message.answer(
        "👤 Отправьте ID или @username пользователя:\n\n"
        "Примеры:\n"
        "• 123456789 (ID)\n"
        "ℹ️ Пользователь получит уведомление со ссылкой на канал!\n\n"
        "Отмена: /cancel"
    )
    await state.set_state(UserManagement.waiting_for_user_id)
    await callback.answer()


@dp.callback_query(F.data.startswith("user_info:"))
async def callback_user_info(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа!")
        return
    
    user_id = int(callback.data.split(":")[1])
    user = data_manager.get_user(user_id)
    
    if not user:
        await callback.answer("Пользователь не найден!", show_alert=True)
        return
    
    username = f"@{user.username}" if user.username else f"ID: {user.user_id}"
    
    text = f"<b>👤 Пользователь: {username}</b>\n\n"
    
    if user.expires_at:
        time_left = format_time_remaining(user.expires_at)
        text += f"⏰ Доступ до: {user.expires_at.strftime('%d.%m.%Y %H:%M')}\n"
        text += f"⏱ Осталось: {time_left}\n\n"
        
        if user.expires_at <= datetime.now():
            text += "❌ <b>Доступ истек!</b>\n\n"
    else:
        text += "⏰ Время не установлено\n\n"
    
    text += "Выберите действие:"
    
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=create_time_keyboard(user_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("add_time:"))
async def callback_add_time(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа!")
        return
    
    parts = callback.data.split(":")
    user_id = int(parts[1])
    hours = float(parts[2])
    
    # Обновляем время пользователя
    user = data_manager.add_or_update_user(user_id, hours=hours)
    
    # Отправляем уведомление пользователю
    await notify_user_subscription(user_id, user)
    
    username = user.username if user.username else str(user_id)
    username_display = f"@{username}" if username else f"ID: {user_id}"
    time_left = format_time_remaining(user.expires_at)
    
    await callback.message.edit_text(
        f"✅ <b>Время обновлено!</b>\n\n"
        f"👤 {username_display}\n"
        f"➕ Добавлено: {hours} ч\n"
        f"⏰ Доступ до: {user.expires_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"⏱ Осталось: {time_left}\n\n"
        f"📨 Пользователю отправлено уведомление!",
        parse_mode="HTML",
        reply_markup=create_time_keyboard(user_id)
    )
    
    await callback.answer(f"✅ Добавлено {hours} ч")


@dp.callback_query(F.data.startswith("custom_time:"))
async def callback_custom_time(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа!")
        return
    
    user_id = int(callback.data.split(":")[1])
    
    await state.update_data(user_id=user_id)
    await state.set_state(UserManagement.waiting_for_custom_hours)
    
    await callback.message.answer(
        "⏱ Введите количество часов (можно с дробной частью):\n\n"
        "Например: 1.5 (полтора часа)\n\n"
        "Отмена: /cancel"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("remove_user:"))
async def callback_remove_user(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа!")
        return
    
    user_id = int(callback.data.split(":")[1])
    user = data_manager.get_user(user_id)
    
    if user:
        username = user.username if user.username else str(user_id)
        
        try:
            
            await bot.ban_chat_member(CHANNEL_ID, user_id)
            await bot.unban_chat_member(CHANNEL_ID, user_id)
            logger.info(f"Пользователь {user_id} удален из канала")
        except Exception as e:
            logger.error(f"Ошибка при удалении из канала: {e}")
        
        data_manager.remove_user(user_id)
        
        await callback.message.edit_text(
            f"✅ Пользователь @{username} удален из базы и канала.\n\n"
            "Используйте /users для просмотра списка."
        )
        await callback.answer("Удалено!")
    else:
        await callback.answer("Пользователь не найден!", show_alert=True)


@dp.callback_query(F.data == "back_to_list")
async def callback_back_to_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа!")
        return
    
    users = data_manager.get_all_users()
    
    if not users:
        await callback.message.edit_text("📭 Нет пользователей с ограниченным доступом.")
        await callback.answer()
        return
    
    active_users = [u for u in users if u.expires_at and u.expires_at > datetime.now()]
    expired_users = [u for u in users if u.expires_at and u.expires_at <= datetime.now()]
    
    text = "<b>👥 Пользователи с доступом:</b>\n\n"
    
    if active_users:
        text += "<b>✅ Активные:</b>\n"
        for user in sorted(active_users, key=lambda x: x.expires_at):
            username = f"@{user.username}" if user.username else f"ID: {user.user_id}"
            time_left = format_time_remaining(user.expires_at)
            text += f"• {username}\n  ⏰ Осталось: {time_left}\n\n"
    
    if expired_users:
        text += "<b>⏰ Истекшие:</b>\n"
        for user in expired_users:
            username = f"@{user.username}" if user.username else f"ID: {user.user_id}"
            text += f"• {username}\n  ❌ Доступ истек\n\n"
    
    text += f"\n<b>👑 VIP пользователей:</b> {len(vip_manager.get_all_vips())}"
    
    buttons = []
    for user in active_users + expired_users:
        username = user.username if user.username else str(user.user_id)
        buttons.append([InlineKeyboardButton(
            text=f"👤 {username}",
            callback_data=f"user_info:{user.user_id}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text="➕ Добавить пользователя",
        callback_data="add_new_user"
    )])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()



async def check_users_task():
    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL)
            
            now = datetime.now()
            users = data_manager.get_all_users()
            
            for user in users:
                if not user.expires_at:
                    continue
                
                if user.expires_at <= now:
                    logger.info(f"Время истекло для пользователя {user.user_id}")
                    await kick_user(user.user_id)
                    continue
                
                time_until_expire = (user.expires_at - now).total_seconds() / 3600
                
                if (time_until_expire <= WARNING_HOURS and 
                    not user.warning_sent and
                    not is_special_user(user.user_id)):
                    logger.info(f"Отправка предупреждения пользователю {user.user_id}")
                    await send_warning(user.user_id)
            
        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче: {e}")



async def main():

    asyncio.create_task(check_users_task())
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("✅ Бот успешно запущен и готов к работе!")
    logger.info("📝 Ожидание заявок на вступление...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
