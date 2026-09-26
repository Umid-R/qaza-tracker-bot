#####
import sys
import os
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    MenuButtonWebApp,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot.prayer_times import get_by_cor, get_cor_city
from bot.database.qaza_stats import get_prayer_times, get_all_users, get_prayer_message, get_gif
from bot.database.database import (
    insert_user,
    update_user,
    is_user_exist,
    insert_prayer_times,
    update_prayer_times,
    add_qaza,
    add_prayer
)


# ======================
# ENV
# ======================
load_dotenv()
access_token = os.getenv("TELEGRAM_TOKEN")

# ======================
# FSM STATES
# ======================
class UserRegistration(StatesGroup):
    waiting_for_name = State()
    waiting_for_city = State()

# ======================
# DISPATCHER
# ======================
dp = Dispatcher(storage=MemoryStorage())

# ======================
# GLOBALS
# ======================
sent_today = {}  # prevent duplicates
prayer_scheduler_tasks = {}  # per-user prayer scheduler
pre_prayer_scheduler_tasks = {}  # per-user pre-prayer scheduler
last_warned_prayer = {}  # Fixed: Now stores message_id to track which prayer was warned
last_prayer_notification = {}  #Track last prayer time notification message


# ======================
# INLINE BUTTONS (10-MIN WARNING)
# ======================
prayed_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✅", callback_data="prayed_yes"),
            InlineKeyboardButton(text="❌", callback_data="prayed_no"),
        ]
    ]
)

# ======================
# PRAYER SCHEDULER
# ======================
async def prayer_scheduler(bot: Bot, user_id: int):
    while True:
        try:
            prayer_times = get_prayer_times(user_id)
            tz = ZoneInfo(prayer_times["timezone"])
            now = datetime.now(tz).strftime("%H:%M")
            today = datetime.now(tz).date()

            if user_id not in sent_today:
                sent_today[user_id] = {}

            for prayer, time_str in prayer_times.items():
                if prayer == "timezone":
                    continue
                if now == time_str:
                    if sent_today[user_id].get(prayer) == today:
                        continue
                    
                    # DELETE PREVIOUS PRAYER NOTIFICATION
                    if user_id in last_prayer_notification:
                        try:
                            await bot.delete_message(chat_id=user_id, message_id=last_prayer_notification[user_id])
                        except Exception as e:
                            logging.error(f"Failed to delete previous prayer notification: {e}")
                    
                    # SEND NEW NOTIFICATION AND STORE MESSAGE ID
                    sent_message = await bot.send_message(
                        chat_id=user_id,
                        text=f"🕌 Time for {prayer.capitalize()}\n{get_prayer_message(prayer)}\n({time_str})",
                    )
                    last_prayer_notification[user_id] = sent_message.message_id
                    sent_today[user_id][prayer] = today
                        
            await asyncio.sleep(30)
            
        except asyncio.CancelledError:
            # Task was cancelled, exit gracefully
            logging.info(f"Prayer scheduler cancelled for user {user_id}")
            break
        except Exception as e:
            logging.error(f"Prayer scheduler error for user {user_id}: {e}")
            await asyncio.sleep(60)  # Back off on error

def start_prayer_scheduler(bot: Bot, user_id: int):
    # Cancel existing task if any
    if user_id in prayer_scheduler_tasks:
        prayer_scheduler_tasks[user_id].cancel()
    
    task = asyncio.create_task(prayer_scheduler(bot, user_id))
    prayer_scheduler_tasks[user_id] = task


# ======================
# MESSAGE DELETER
# ======================
async def delete_message_after(bot: Bot, chat_id: int, message_id: int, seconds: int):
    """Delete a message after specified seconds"""
    await asyncio.sleep(seconds)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        # Message might already be deleted or user deleted it
        logging.error(f"Failed to delete message {message_id}: {e}")

# ======================
# MARK THE PRAYER AS QAZA AND DELETE THE MESSAGE 
# ======================
async def auto_mark_qaza_and_delete(bot: Bot, user_id: int, prayer_name: str, message_id: int, seconds: int):
    """Wait for timeout, then mark as qaza and delete message if user didn't respond"""
    await asyncio.sleep(seconds)
    
    # Check if user already responded
    prayer_data = last_warned_prayer.get(user_id)
    if prayer_data and prayer_data.get('message_id') == message_id:
        # User didn't respond, mark as qaza
        add_qaza(prayer_name, user_id, reason="Unknown")
        
        # Clean up tracking
        del last_warned_prayer[user_id]
    
    # Delete the message regardless
    try:
        await bot.delete_message(chat_id=user_id, message_id=message_id)
    except Exception as e:
        logging.error(f"Failed to delete message {message_id}: {e}")
             
# ======================
# PRE-PRAYER REMINDER (10 MIN)
# ======================
async def pre_prayer_scheduler(bot: Bot, user_id: int):
    sent_pre = {}  # Fixed: Changed to dict to store dates for cleanup
    
    while True:
        try:
            prayer_times = get_prayer_times(user_id)
            tz = ZoneInfo(prayer_times["timezone"])
            now = datetime.now(tz)

            prayers = []
            for prayer, time_str in prayer_times.items():
                if prayer == "timezone": 
                    continue
                dt = datetime.strptime(time_str, "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day, tzinfo=tz
                )
                prayers.append((prayer, dt))
            prayers.sort(key=lambda x: x[1])

            # Sunrise is the deadline for Fajr
            # Asr is the deadline for Dhuhr
            # Maghrib is the deadline for Asr
            deadline_to_prayer = {
                "sunrise": "fajr",
                "dhuhr": None,
                "asr": "dhuhr",
                "maghrib": "asr",
                "isha": "maghrib",
            }

            for prayer, dt in prayers:
                target_prayer = deadline_to_prayer.get(prayer)

                if target_prayer is None:
                    continue

                reminder_dt = dt - timedelta(minutes=10)
                key = (target_prayer, reminder_dt.date())

                if reminder_dt <= now < reminder_dt + timedelta(minutes=1):
                    if key not in sent_pre:
                        # Send the reminder
                        sent_message = await bot.send_animation(
                            chat_id=user_id,
                            animation=get_gif(type='judging'),
                            caption=f"⚠️ {target_prayer.capitalize()} prayer will be MISSED in 10 minutes.\nHave you prayed it already?",
                            reply_markup=prayed_keyboard
                        )
                        sent_pre[key] = True
                        
                        # Fixed: Store both prayer name and message_id to track which prayer this reminder is for
                        last_warned_prayer[user_id] = {
                            'prayer': target_prayer,
                            'message_id': sent_message.message_id
                        }
                        
                        # Auto-timeout after 2 hours (7200 seconds)
                        asyncio.create_task(
                            auto_mark_qaza_and_delete(bot, user_id, target_prayer, sent_message.message_id, 7200)
                        )

            # SPECIAL HANDLING FOR ISHA AT 22:00
            isha_reminder_time = datetime.strptime("22:00", "%H:%M").replace(
                year=now.year, month=now.month, day=now.day, tzinfo=tz
            )
            isha_key = ("isha_daily", isha_reminder_time.date())

            if isha_reminder_time <= now < isha_reminder_time + timedelta(minutes=1):
                if isha_key not in sent_pre:
                    # Send Isha reminder at 22:00
                    sent_message = await bot.send_animation(
                        chat_id=user_id,
                        animation=get_gif(type='judging'),
                        caption=f"⚠️ Isha prayer will be MISSED soon.\nHave you prayed it already?",
                        reply_markup=prayed_keyboard
                    )
                    sent_pre[isha_key] = True
                    
                    last_warned_prayer[user_id] = {
                        'prayer': 'isha',
                        'message_id': sent_message.message_id
                    }
                    
                    # Auto-timeout after 2 hours (7200 seconds)
                    asyncio.create_task(
                        auto_mark_qaza_and_delete(bot, user_id, 'isha', sent_message.message_id, 7200)
                    )

            # Fixed: Clean up old dates from sent_pre to prevent memory leak
            today = now.date()
            sent_pre = {k: v for k, v in sent_pre.items() 
                       if k[1] >= today - timedelta(days=1)}

            await asyncio.sleep(20)
            
        except asyncio.CancelledError:
            # Task was cancelled, exit gracefully
            logging.info(f"Pre-prayer scheduler cancelled for user {user_id}")
            break
        except Exception as e:
            logging.error(f"Pre-prayer scheduler error for user {user_id}: {e}")
            await asyncio.sleep(60)  # Back off on error

def start_pre_prayer_scheduler(bot: Bot, user_id: int):
    # Cancel existing task if any
    if user_id in pre_prayer_scheduler_tasks:
        pre_prayer_scheduler_tasks[user_id].cancel()
    
    task = asyncio.create_task(pre_prayer_scheduler(bot, user_id))
    pre_prayer_scheduler_tasks[user_id] = task


        
        
# ======================
# DAILY PRAYER TIMES UPDATER
# ======================
async def daily_prayer_times_updater():
    while True:
        try:
            users = get_all_users()
            for user in users:
                try:
                    prayer_times = get_by_cor(user["lat"], user["lon"])
                    update_prayer_times(
                        user["id"],
                        prayer_times["Fajr"],
                        prayer_times["Sunrise"],
                        prayer_times["Dhuhr"],
                        prayer_times["Asr"],
                        prayer_times["Maghrib"],
                        prayer_times["Isha"],
                    )
                except Exception as e:
                    logging.error(f"Failed to update prayer times for user {user['id']}: {e}")
                    
            await asyncio.sleep(86400)  # 24 hours
            
        except Exception as e:
            logging.error(f"Daily prayer times updater error: {e}")
            await asyncio.sleep(3600)  # Retry in 1 hour on error

# ======================
# COMMAND /START
# ======================
@dp.message(CommandStart())
async def command_start(message: Message, state: FSMContext):
    await state.set_state(UserRegistration.waiting_for_name)
    await message.answer(
        f"Hello, {html.bold(message.from_user.full_name)} 👋\nWhat is your name?"
    )

# ======================
# ENTER CITY MANUALLY CLICK
# ======================
@dp.message(F.text == "🏙️ Enter City Manually")
async def manual_city(message: Message, state: FSMContext):
    await state.set_state(UserRegistration.waiting_for_city)
    await message.answer(
        "Okay! Please type your city name (e.g., Seoul, Busan, Osh):",
        reply_markup=ReplyKeyboardRemove()
    )

# ======================
# HANDLE LOCATION
# ======================
@dp.message(F.location)
async def handle_location(message: Message, state: FSMContext):
    data = await state.get_data()
    user_name = data.get("user_name")
    user_id = message.from_user.id
    
    lat = message.location.latitude
    lon = message.location.longitude
    prayer_times = get_by_cor(lat=lat, lon=lon)

    if not is_user_exist(user_id) and user_name:
        insert_user(id=user_id, name=user_name, lat=lat, lon=lon)
        insert_prayer_times(
            user_id,
            prayer_times["Fajr"],
            prayer_times["Sunrise"],
            prayer_times["Dhuhr"],
            prayer_times["Asr"],
            prayer_times["Maghrib"],
            prayer_times["Isha"],
        )
    else:
        update_user(id=user_id, name=user_name, lat=lat, lon=lon)
        update_prayer_times(
            user_id,
            prayer_times["Fajr"],
            prayer_times["Sunrise"],
            prayer_times["Dhuhr"],
            prayer_times["Asr"],
            prayer_times["Maghrib"],
            prayer_times["Isha"],
        )

    await message.answer(
        f"Here are the prayer times for your location 🕌\n"
        f"Fajr:{prayer_times['Fajr']}\n"
        f"Sunrise:{prayer_times['Sunrise']}\n"
        f"Dhuhr:{prayer_times['Dhuhr']}\n"
        f"Asr:{prayer_times['Asr']}\n"
        f"Maghrib:{prayer_times['Maghrib']}\n"
        f"Isha:{prayer_times['Isha']}",
        reply_markup=ReplyKeyboardRemove()
    )

    # Fixed: Cancel old tasks before starting new ones
    start_prayer_scheduler(message.bot, user_id)
    start_pre_prayer_scheduler(message.bot, user_id)
    
    await state.clear()

# ======================
# HANDLE TEXT (NAME OR CITY)
# ======================
@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    current_state = await state.get_state()
    
    if message.text == "🏙️ Enter City Manually":
        return

    # STEP 1: Get name
    if current_state == UserRegistration.waiting_for_name:
        user_name = message.text.strip()
        await state.update_data(user_name=user_name)
        
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📍 Send Location", request_location=True)],
                [KeyboardButton(text="🏙️ Enter City Manually")],
            ],
            resize_keyboard=True,
        )
        await message.answer(
            f"Nice to meet you, {user_name} 😊\nChoose an option:",
            reply_markup=keyboard
        )
        return

    # STEP 2: Handle manual city input
    if current_state == UserRegistration.waiting_for_city:
        data = await state.get_data()
        user_name = data.get("user_name")
        user_id = message.from_user.id
        
        city = message.text.strip()
        cors = get_cor_city(city.capitalize())
        if cors is None:
            await message.answer("Oops — city not found. Try again 😊")
            return

        prayer_times = get_by_cor(float(cors[0]), float(cors[1]))

        if not is_user_exist(user_id) and user_name:
            insert_user(id=user_id, name=user_name, lat=float(cors[0]), lon=float(cors[1]))
            insert_prayer_times(
                user_id,
                prayer_times["Fajr"],
                prayer_times["Sunrise"],
                prayer_times["Dhuhr"],
                prayer_times["Asr"],
                prayer_times["Maghrib"],
                prayer_times["Isha"],
            )
        else:
            update_user(id=user_id, name=user_name, lat=float(cors[0]), lon=float(cors[1]))
            update_prayer_times(
                user_id,
                prayer_times["Fajr"],
                prayer_times["Sunrise"],
                prayer_times["Dhuhr"],
                prayer_times["Asr"],
                prayer_times["Maghrib"],
                prayer_times["Isha"],
            )

        await message.answer(
            f"Here are the prayer times for your location 🕌\n"
            f"Fajr:{prayer_times['Fajr']}\n"
            f"Sunrise:{prayer_times['Sunrise']}\n"
            f"Dhuhr:{prayer_times['Dhuhr']}\n"
            f"Asr:{prayer_times['Asr']}\n"
            f"Maghrib:{prayer_times['Maghrib']}\n"
            f"Isha:{prayer_times['Isha']}",
            reply_markup=ReplyKeyboardRemove()
        )

        # Fixed: Cancel old tasks before starting new ones
        start_prayer_scheduler(message.bot, user_id)
        start_pre_prayer_scheduler(message.bot, user_id)
        
        await state.clear()
        return


# ======================
# CALLBACK HANDLERS
# ======================

@dp.callback_query(F.data == "prayed_yes")
async def handle_prayed_yes(query: CallbackQuery):
    user_id = query.from_user.id
    
    # Fixed: Get prayer name from stored data
    prayer_data = last_warned_prayer.get(user_id)
    
    if prayer_data and isinstance(prayer_data, dict):
        prayer_name = prayer_data.get('prayer', 'unknown')
    else:
        prayer_name = 'unknown'
    
    if prayer_name != "unknown":
        add_prayer(prayer_name, user_id)
    
    # Clean up
    if user_id in last_warned_prayer:
        del last_warned_prayer[user_id]
    
    # DELETE THE ORIGINAL WARNING MESSAGE IMMEDIATELY
    try:
        await query.message.delete()
    except Exception as e:
        logging.error(f"Failed to delete warning message: {e}")
    
    sent_message = await query.bot.send_animation(
        chat_id=user_id,       
        animation=get_gif(type='yes')       
    )
    await query.answer() 
    
    asyncio.create_task(
        delete_message_after(query.bot, user_id, sent_message.message_id, 10)
    )           

@dp.callback_query(F.data == "prayed_no")
async def handle_prayed_no(query: CallbackQuery):
    user_id = query.from_user.id
    
    # Fixed: Get prayer name from stored data
    prayer_data = last_warned_prayer.get(user_id)
    
    if prayer_data and isinstance(prayer_data, dict):
        prayer_name = prayer_data.get('prayer', 'unknown')
    else:
        prayer_name = 'unknown'
    
    if prayer_name != "unknown":
        add_qaza(prayer_name, user_id)
    
    # Clean up
    if user_id in last_warned_prayer:
        del last_warned_prayer[user_id]
    
    # DELETE THE ORIGINAL WARNING MESSAGE IMMEDIATELY
    try:
        await query.message.delete()
    except Exception as e:
        logging.error(f"Failed to delete warning message: {e}")
    
    sent_message = await query.bot.send_animation(
        chat_id=user_id,
        animation=get_gif(type='no')
    )
    await query.answer()
    
    asyncio.create_task(
        delete_message_after(query.bot, user_id, sent_message.message_id, 10)
    )

# ======================
# MAIN
# ======================
async def main():
    bot = Bot(token=access_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="🕌 Qaza Tracker",
            web_app=WebAppInfo(url="https://jsur.vercel.app")
        )
    )
    asyncio.create_task(daily_prayer_times_updater())
    
    users = get_all_users()
    for user in users:
        start_prayer_scheduler(bot, user["id"])
        start_pre_prayer_scheduler(bot, user["id"])
        
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())