import logging
import asyncio
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    MenuButtonWebApp
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters
)
from telegram.request import HTTPXRequest

import config
from utils import normalize_phone
import database
from web_server import app

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# FSM states for adding a patient (Chat Interface)
CHOOSING_NAME, CHOOSING_PHONE, CHOOSING_DOCTOR, CHOOSING_DATE = range(4)

# Multilingual Strings
STRINGS = {
    'uz': {
        'choose_lang': "Tizim tilini tanlang / Выберите язык системы:",
        'ask_contact': "Tizimga ulanish va shaxsingizni tasdiqlash uchun pastdagi '📱 Telefon raqamni yuborish' tugmasini bosing:",
        'btn_send_contact': "📱 Telefon raqamni yuborish",
        'welcome_registered': "Assalomu alaykum! 'ShifoNazorat' tizimiga ulandingiz. Salomatligingiz biz uchun muhim.\n\nQuyidagi tugmani bosib tizimga kiring:",
        'welcome_new': "Rahmat! Telefon raqamingiz muvaffaqiyatli bog'landi.\n\nQuyidagi tugmani bosib tizimga kiring:",
        'btn_open_app': "👤 Shaxsiy kabinet",
        'error_reg': "Tizimga ulanishda xatolik yuz berdi. Iltimos, klinika ma'muriyati bilan bog'laning."
    },
    'ru': {
        'choose_lang': "Tizim tilini tanlang / Выберите язык системы:",
        'ask_contact': "Для подключения к системе и подтверждения личности нажмите кнопку '📱 Отправить номер телефона' ниже:",
        'btn_send_contact': "📱 Отправить номер телефона",
        'welcome_registered': "Ассалому алейкум! Вы подключены к системе 'ShifoNazorat'. Ваше здоровье важно для нас.\n\nНажмите кнопку ниже для входа:",
        'welcome_new': "Спасибо! Ваш номер телефона успешно привязан.\n\nНажмите кнопку ниже для входа в систему:",
        'btn_open_app': "👤 Личный кабинет",
        'error_reg': "Произошла ошибка при подключении к системе. Пожалуйста, свяжитесь с администрацией клиники."
    }
}

def get_admin_keyboard(webapp_url, chat_id):
    sep = "&" if "?" in webapp_url else "?"
    main_url = f"{webapp_url}{sep}chat_id={chat_id}" if webapp_url else ""

    keyboard = [
        [KeyboardButton(text="🏥 Admin App", web_app=WebAppInfo(url=main_url))]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)

def get_patient_keyboard(webapp_url, chat_id, lang='uz'):
    sep = "&" if "?" in webapp_url else "?"
    patient_url = f"{webapp_url}{sep}chat_id={chat_id}" if webapp_url else ""
    btn_text = STRINGS[lang]['btn_open_app']
    keyboard = [
        [KeyboardButton(text=btn_text, web_app=WebAppInfo(url=patient_url))]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Prompt for language selection
    keyboard = [
        [
            InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"),
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Tizim tilini tanlang / Выберите язык системы:", reply_markup=reply_markup)
    
    logger.info(f"User started bot: {user.full_name} (ID: {chat_id})")
    
    # Inform user if no admins are set up
    admin_ids = config.get_admin_ids()
    if not admin_ids:
        await update.message.reply_text(
            f"⚠️ Diqqat: Tizimda adminlar sozlanmagan.\n"
            f"Sizning Telegram ID'ingiz: `{chat_id}`\n\n"
            f"Ushbu ID'ni loyiha papkasidagi `.env` fayliga `ADMIN_IDS={chat_id}` deb qo'shing va botni qayta ishга tushiring.",
            parse_mode="Markdown"
        )

# Contact Sharing Registration Handler
async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    contact = update.message.contact
    chat_id = update.effective_chat.id
    phone = contact.phone_number
    name = f"{contact.first_name} {contact.last_name or ''}".strip()
    
    lang = database.get_user_lang(chat_id)
    
    logger.info(f"Contact received: {name}, Phone: {phone}, Chat ID: {chat_id}")
    patient = database.register_patient_chat_id(phone, chat_id, name)
    
    if patient:
        try:
            pat_url = config.get_webapp_url()
            sep = "&" if "?" in pat_url else "?"
            await context.bot.set_chat_menu_button(
                chat_id=chat_id,
                menu_button=MenuButtonWebApp(text=STRINGS[lang]['btn_open_app'], web_app=WebAppInfo(url=f"{pat_url}{sep}chat_id={chat_id}"))
            )
            logger.info(f"Set patient menu button for {chat_id} via contact sharing")
        except Exception as me:
            logger.error(f"Failed to set patient specific menu button: {me}")

        text = STRINGS[lang]['welcome_new']
        await update.message.reply_text(text, reply_markup=get_patient_keyboard(config.get_webapp_url(), chat_id, lang=lang))
    else:
        text = STRINGS[lang]['error_reg']
        await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())

# Normal text messages handler
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    lang = database.get_user_lang(chat_id)
    admin_ids = config.get_admin_ids()
    
    if chat_id in admin_ids:
        await update.message.reply_text(
            "Boshqaruv paneli tugmasidan foydalaning:",
            reply_markup=get_admin_keyboard(config.get_webapp_url(), chat_id)
        )
    else:
        # Check if registered patient
        patients = database.get_family_members(chat_id)
        if patients:
            closest_booking_id = database.save_previsit_anamnesis(chat_id, text)
            if closest_booking_id:
                patient_name = patients[0]['bemor_ismi']
                msg_to_admin = (
                    f"📝 **Tashrifdan oldingi anamnez (so'rovnoma)!**\n\n"
                    f"👤 **Bemor:** {patient_name}\n"
                    f"💬 **Holati/Alomatlar:** {text}\n\n"
                    f"Tashrif tafsilotlarini ko'rish uchun admin panelga kiring."
                )
                await send_group_alert(context.bot, msg_to_admin)
                
                await update.message.reply_text(
                    "Tashrifdan oldingi so'rovnoma uchun javobingiz qabul qilindi. "
                    "Salomatligingiz haqidagi ma'lumotlar shifokorga uzatildi. Rahmat! 🩺",
                    reply_markup=get_patient_keyboard(config.get_webapp_url(), chat_id, lang=lang)
                )
                return
            else:
                # Check if unregistered patient typed phone number (e.g. adding a family member or registering)
                norm = normalize_phone(text)
                if len(norm) >= 9 and norm.isdigit():
                    user = update.effective_user
                    name = user.full_name
                    patient = database.register_patient_chat_id(text, chat_id, name)
                    if patient:
                        try:
                            pat_url = config.get_webapp_url()
                            sep = "&" if "?" in pat_url else "?"
                            await context.bot.set_chat_menu_button(
                                chat_id=chat_id,
                                menu_button=MenuButtonWebApp(text=STRINGS[lang]['btn_open_app'], web_app=WebAppInfo(url=f"{pat_url}{sep}chat_id={chat_id}"))
                            )
                            logger.info(f"Set patient menu button for {chat_id} via phone number text")
                        except Exception as me:
                            logger.error(f"Failed to set patient specific menu button: {me}")
                        await update.message.reply_text(
                            STRINGS[lang]['welcome_new'],
                            reply_markup=get_patient_keyboard(config.get_webapp_url(), chat_id, lang=lang)
                        )
                        return
                
                # General message response for registered patient
                await update.message.reply_text(
                    "Xabaringiz uchun rahmat! Shaxsiy kabinetingiz orqali shifokorga bevosita savol yuborishingiz yoki qabulga yozilishingiz mumkin. 😊",
                    reply_markup=get_patient_keyboard(config.get_webapp_url(), chat_id, lang=lang)
                )
                return
        else:
            # Check if unregistered patient typed phone number
            norm = normalize_phone(text)
            if len(norm) >= 9 and norm.isdigit():
                user = update.effective_user
                name = user.full_name
                patient = database.register_patient_chat_id(text, chat_id, name)
                if patient:
                    try:
                        pat_url = config.get_webapp_url()
                        sep = "&" if "?" in pat_url else "?"
                        await context.bot.set_chat_menu_button(
                            chat_id=chat_id,
                            menu_button=MenuButtonWebApp(text=STRINGS[lang]['btn_open_app'], web_app=WebAppInfo(url=f"{pat_url}{sep}chat_id={chat_id}"))
                        )
                        logger.info(f"Set patient menu button for {chat_id} via phone number text")
                    except Exception as me:
                        logger.error(f"Failed to set patient specific menu button: {me}")
    
                    await update.message.reply_text(
                        STRINGS[lang]['welcome_new'],
                        reply_markup=get_patient_keyboard(config.get_webapp_url(), chat_id, lang=lang)
                    )
                    return
            
            await update.message.reply_text(
                "Iltimos, pastdagi tugmani bosing yoki ro'yxatdan o'tish uchun telefon raqamingizni yuboring:",
                reply_markup=get_patient_keyboard(config.get_webapp_url(), chat_id, lang=lang)
            )


# FSM: Add Patient start
async def add_patient_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    if chat_id not in config.get_admin_ids():
        return ConversationHandler.END
        
    await update.message.reply_text(
        "Bemorning ismini kiriting:",
        reply_markup=get_cancel_keyboard()
    )
    return CHOOSING_NAME

async def add_patient_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['temp_patient_name'] = update.message.text.strip()
    await update.message.reply_text(
        "Telefon raqamini kiriting (masalan, +998901234567):",
        reply_markup=get_cancel_keyboard()
    )
    return CHOOSING_PHONE

async def add_patient_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone_input = update.message.text.strip()
    norm = normalize_phone(phone_input)
    
    if len(norm) < 9:
        await update.message.reply_text(
            "⚠️ Telefon raqami formati noto'g'ri. Iltimos, qayta kiriting:",
            reply_markup=get_cancel_keyboard()
        )
        return CHOOSING_PHONE
        
    context.user_data['temp_patient_phone'] = phone_input
    await update.message.reply_text(
        "Qaysi shifokorda bo'ldi?",
        reply_markup=get_cancel_keyboard()
    )
    return CHOOSING_DOCTOR

async def add_patient_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['temp_patient_doctor'] = update.message.text.strip()
    date_kb = ReplyKeyboardMarkup([["Bugun"], ["❌ Bekor qilish"]], resize_keyboard=True)
    await update.message.reply_text(
        "Tashrif sanasini kiriting (YYYY-MM-DD):",
        reply_markup=date_kb
    )
    return CHOOSING_DATE

async def add_patient_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_input = update.message.text.strip()
    if date_input.lower() == "bugun":
        visit_date = datetime.now().strftime("%Y-%m-%d")
    else:
        try:
            datetime.strptime(date_input, "%Y-%m-%d")
            visit_date = date_input
        except ValueError:
            await update.message.reply_text(
                "⚠️ Sana formati noto'g'ri (YYYY-MM-DD):",
                reply_markup=ReplyKeyboardMarkup([["Bugun"], ["❌ Bekor qilish"]], resize_keyboard=True)
            )
            return CHOOSING_DATE
            
    name = context.user_data['temp_patient_name']
    phone = context.user_data['temp_patient_phone']
    doctor = context.user_data['temp_patient_doctor']
    
    patient = database.add_or_update_patient(name, phone, doctor, visit_date)
    
    test_mode = database.get_setting("test_mode", "0") == "1"
    delay_str = "1 daqiqa" if test_mode else "3 kun"
    
    await update.message.reply_text(
        f"✅ Ma'lumotlar saqlandi.\nBemor: {name}\nEslatma [{delay_str}] dan so'ng yuboriladi.",
        reply_markup=get_admin_keyboard(config.get_webapp_url(), chat_id)
    )
    
    # Notify Admin Group
    group_id = config.get_admin_group_id()
    if group_id:
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text=f"📢 Yangi bemor qo'shildi: {name}, Shifokor: {doctor}"
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    context.user_data.clear()
    await update.message.reply_text(
        "Amal bekor qilindi.",
        reply_markup=get_admin_keyboard(config.get_webapp_url(), chat_id)
    )
    return ConversationHandler.END

# Admin Actions
async def list_patients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    patients = database.get_all_patients(20)
    if not patients:
        await update.message.reply_text("Baza bo'sh.")
        return
        
    text = "📋 **Oxirgi 20 ta bemor ro'yxati:**\n\n"
    keyboard_buttons = []
    
    for p in patients:
        baho_emoji = f"{p['oxirgi_baho']} ⭐" if p['oxirgi_baho'] else "Baholanmagan ⏳"
        status_emoji = "🟢 Faol" if p['status'] == "Faol" else "🔴 Norozi"
        link_status = "🔗 Ulangan" if p['chat_id'] else "❌ Ulanmagan"
        tashrif = p['oxirgi_tashrif_sanasi'] if p['oxirgi_tashrif_sanasi'] else "Noma'lum"
        
        text += (
            f"👤 **{p['bemor_ismi']}** ({p['bemor_telefoni']})\n"
            f"👨‍⚕️ Shifokor: {p['shifokor_ismi'] or 'Belgilanmagan'}\n"
            f"📅 Tashrif: {tashrif}\n"
            f"📊 Baho: {baho_emoji} | Status: {status_emoji} ({link_status})\n"
            f"----------------------------------------\n"
        )
        
        if p['chat_id'] and not p['oxirgi_baho']:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"✉️ Eslatma yuborish: {p['bemor_ismi']}",
                    callback_data=f"send_now_{p['id']}"
                )
            ])
            
    keyboard_buttons.append([InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_list")])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard_buttons), parse_mode="Markdown")

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    stats = database.get_statistics()
    text = (
        f"📊 **TIZIM STATISTIKASI**\n"
        f"------------------------------------\n"
        f"👥 Umumiy bemorlar soni: {stats['total_patients']}\n"
        f"🟢 Faol statusdagi bemorlar: {stats['active_patients']}\n"
        f"🔴 Norozi statusdagi bemorlar: {stats['norozi_patients']}\n"
        f"⭐ Xizmatlarning o'rtacha bahosi: {stats['avg_rating']} / 5.00\n"
        f"💬 Fikr bildirgan bemorlar: {stats['rated_count']}\n"
        f"------------------------------------\n"
    )
    await update.message.reply_text(text, reply_markup=get_admin_keyboard(config.get_webapp_url(), chat_id), parse_mode="Markdown")

def get_settings_markup():
    auto_enabled = database.get_setting("auto_messages_enabled", "1") == "1"
    test_mode = database.get_setting("test_mode", "0") == "1"
    auto_text = "🟢 YOQILGAN" if auto_enabled else "🔴 O'CHIRILGAN"
    test_text = "🟢 YOQILGAN (1 daq. kutish)" if test_mode else "🔴 O'CHIRILGAN (3 kun kutish)"
    
    keyboard = [
        [InlineKeyboardButton(f"Avtomatik xabarlar: {auto_text}", callback_data="toggle_auto")],
        [InlineKeyboardButton(f"Test rejimi: {test_text}", callback_data="toggle_test")],
        [InlineKeyboardButton("🔄 Yangilash", callback_data="refresh_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    group_id = config.get_admin_group_id()
    group_status = f"`{group_id}`" if group_id else "❌ *Sozlanmagan*"
    text = (
        f"⚙️ **TIZIM SOZLAMALARI**\n\n"
        f"📣 Guruh ID'si: {group_status}\n\n"
        f"Fikr-mulohaza xabarlarini yoqish/o'chirish:"
    )
    await update.message.reply_text(text, reply_markup=get_settings_markup(), parse_mode="Markdown")

# Callback Handlers
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Language callback selection
    if data.startswith("lang_"):
        lang = 'uz' if data == 'lang_uz' else 'ru'
        database.set_user_lang(chat_id, lang)
        
        admin_ids = config.get_admin_ids()
        # If admin list is empty, make this user admin
        if not admin_ids:
            config.ADMIN_IDS.append(chat_id)
            admin_ids = [chat_id]
            
        if chat_id in admin_ids:
            try:
                admin_url = config.get_webapp_url()
                sep = "&" if "?" in admin_url else "?"
                await context.bot.set_chat_menu_button(
                    chat_id=chat_id,
                    menu_button=MenuButtonWebApp(text="🏥 Admin App", web_app=WebAppInfo(url=f"{admin_url}{sep}chat_id={chat_id}"))
                )
                logger.info(f"Set admin menu button for {chat_id}")
            except Exception as me:
                logger.error(f"Failed to set admin specific menu button: {me}")

            await query.message.reply_text(
                f"Xush kelibsiz, Administrator {user.first_name}!\n\n"
                f"Siz bot boshqaruv menyusidasiz. Quyidagi Web App tugmasini bosib sayt shaklidagi boshqaruv panelini ochishingiz mumkin:",
                reply_markup=get_admin_keyboard(config.get_webapp_url(), chat_id)
            )
        else:
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM patients WHERE chat_id = ? LIMIT 1", (chat_id,))
            linked = cursor.fetchone()
            conn.close()
            
            if linked:
                try:
                    pat_url = config.get_webapp_url()
                    sep = "&" if "?" in pat_url else "?"
                    await context.bot.set_chat_menu_button(
                        chat_id=chat_id,
                        menu_button=MenuButtonWebApp(text=STRINGS[lang]['btn_open_app'], web_app=WebAppInfo(url=f"{pat_url}{sep}chat_id={chat_id}"))
                    )
                    logger.info(f"Set patient menu button for {chat_id}")
                except Exception as me:
                    logger.error(f"Failed to set patient specific menu button: {me}")

                await query.message.reply_text(
                    STRINGS[lang]['welcome_registered'],
                    reply_markup=get_patient_keyboard(config.get_webapp_url(), chat_id, lang=lang)
                )
            else:
                keyboard = [
                    [KeyboardButton(text=STRINGS[lang]['btn_send_contact'], request_contact=True)]
                ]
                await query.message.reply_text(
                    STRINGS[lang]['ask_contact'],
                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                )
        return

    # Settings toggle callbacks
    if data == "toggle_auto":
        current = database.get_setting("auto_messages_enabled", "1")
        new_val = "0" if current == "1" else "1"
        database.set_setting("auto_messages_enabled", new_val)
        await query.edit_message_reply_markup(reply_markup=get_settings_markup())
    elif data == "toggle_test":
        current = database.get_setting("test_mode", "0")
        new_val = "0" if current == "1" else "1"
        database.set_setting("test_mode", new_val)
        await query.edit_message_reply_markup(reply_markup=get_settings_markup())
    elif data == "refresh_settings":
        await query.edit_message_reply_markup(reply_markup=get_settings_markup())
    elif data == "refresh_list":
        patients = database.get_all_patients(20)
        if not patients:
            await query.edit_message_text("Baza bo'sh.")
            return
            
        text = "📋 **Oxirgi 20 ta bemor ro'yxati:**\n\n"
        keyboard_buttons = []
        
        for p in patients:
            baho_emoji = f"{p['oxirgi_baho']} ⭐" if p['oxirgi_baho'] else "Baholanmagan ⏳"
            status_emoji = "🟢 Faol" if p['status'] == "Faol" else "🔴 Norozi"
            link_status = "🔗 Ulangan" if p['chat_id'] else "❌ Ulanmagan"
            tashrif = p['oxirgi_tashrif_sanasi'] if p['oxirgi_tashrif_sanasi'] else "Noma'lum"
            
            text += (
                f"👤 **{p['bemor_ismi']}** ({p['bemor_telefoni']})\n"
                f"👨‍⚕️ Shifokor: {p['shifokor_ismi'] or 'Belgilanmagan'}\n"
                f"📅 Tashrif: {tashrif}\n"
                f"📊 Baho: {baho_emoji} | Status: {status_emoji} ({link_status})\n"
                f"----------------------------------------\n"
            )
            
            if p['chat_id'] and not p['oxirgi_baho']:
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text=f"✉️ Eslatma yuborish: {p['bemor_ismi']}",
                        callback_data=f"send_now_{p['id']}"
                    )
                ])
                
        keyboard_buttons.append([InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_list")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard_buttons), parse_mode="Markdown")

    # Send followup manual callback
    elif data.startswith("send_now_"):
        patient_id = int(data.split("_")[2])
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
        patient = cursor.fetchone()
        conn.close()
        
        if not patient:
            await query.message.reply_text("Bemor topilmadi.")
            return
            
        p_chat_id = patient['chat_id']
        if not p_chat_id:
            await query.message.reply_text("Bemor botdan ro'yxatdan o'tmagan.")
            return
            
        success = await send_followup_message(context.bot, p_chat_id, patient)
        if success:
            database.mark_followup_sent(patient_id)
            await query.message.reply_text(f"✅ {patient['bemor_ismi']} bemoriga eslatma yuborildi!")
        else:
            await query.message.reply_text("Eslatmani yuborishda xatolik yuz berdi.")

    # Rating query callback
    elif data.startswith("rate_"):
        parts = data.split("_")
        if len(parts) == 3:
            patient_id = int(parts[1])
            score = int(parts[2])
            
            patient = database.submit_rating(patient_id, score)
            if not patient:
                await query.edit_message_text("Xatolik yuz berdi.")
                return
                
            if score in (1, 2, 3):
                await query.edit_message_text(f"Siz {score} ball berdingiz.\n\nRahmat, fikringiz qabul qilindi. Ma'muriyatimiz tez orada siz bilan bog'lanadi.")
                
                # Send alert to Admin Group
                group_id = config.get_admin_group_id()
                alert_text = (
                    f"‼️ **DIQQAT: Bemor norozi!**\n\n"
                    f"👤 **Ism:** {patient['bemor_ismi']}\n"
                    f"📞 **Tel:** {patient['bemor_telefoni']}\n"
                    f"👨‍⚕️ **Shifokor:** {patient['shifokor_ismi']}\n"
                    f"⭐ **Baho:** {score} / 5\n\n"
                    f"Iltimos, zudlik bilan bog'laning."
                )
                
                if group_id:
                    try:
                        await context.bot.send_message(chat_id=group_id, text=alert_text, parse_mode="Markdown")
                    except Exception as e:
                        logger.error(f"Failed to send alert to group: {e}")
                else:
                    for admin_id in config.get_admin_ids():
                        try:
                            await context.bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="Markdown")
                        except Exception as e:
                            logger.error(f"Failed to send alert: {e}")
            else:
                await query.edit_message_text(f"Siz {score} ball berdingiz.\n\nKatta rahmat! Sizning bahoyingiz biz uchun muhim. Kelgusi tashrifingiz uchun sizga 5% chegirma taqdim etamiz! Promokod: SHIFO5")

    # Recare callbacks
    elif data.startswith("recare_accept_"):
        patient_id = int(data.split("_")[2])
        database.update_patient_status(patient_id, "Kelgan")
        await query.edit_message_text(
            "✅ Ajoyib! Shifokorimiz siz bilan tez orada bog'lanadi. Sog'lom bo'ling! 😊"
        )

    elif data.startswith("recare_later_"):
        patient_id = int(data.split("_")[2])
        database.update_patient_status(patient_id, "Qayta qo'ng'iroq qilish kerak")
        await query.edit_message_text(
            "Tushundik! Ma'muriyatimiz siz bilan qayta bog'lanadi. 🙏"
        )
        patient = database.get_patient_by_id(patient_id)
        if patient:
            alert_text = (
                f"📞 **Bemorga qayta qo'ng'iroq kerak!**\n\n"
                f"👤 **Ism:** {patient['bemor_ismi']}\n"
                f"📞 **Tel:** {patient['bemor_telefoni']}\n"
                f"👨‍⚕️ **Shifokor:** {patient['shifokor_ismi']}\n\n"
                f"Bemor «Boshqa vaqtda kelaman» dedi."
            )
            group_id = config.get_admin_group_id()
            if group_id:
                try:
                    await context.bot.send_message(chat_id=group_id, text=alert_text, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Recare alert error: {e}")
            else:
                for admin_id in config.get_admin_ids():
                    try:
                        await context.bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="Markdown")
                    except Exception:
                        pass

# Send follow-up message function
async def send_followup_message(bot, chat_id, patient):
    try:
        patient_id = patient['id']
        name = patient['bemor_ismi']
        
        text = (
            f"Assalomu alaykum, {name}! Klinikamizga tashrifingiz uchun rahmat.\n"
            f"Hammasi joyidami? O'zingizni qanday his qilyapsiz?\n"
            f"Iltimos, xizmat ko'rsatish sifatini 1 dan 5 gacha baholang, bu bizga yaxshilanishga yordam beradi:"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("1️⃣ Juda yomon", callback_data=f"rate_{patient_id}_1"),
                InlineKeyboardButton("2️⃣ Yomon", callback_data=f"rate_{patient_id}_2"),
            ],
            [
                InlineKeyboardButton("3️⃣ O'rta", callback_data=f"rate_{patient_id}_3"),
                InlineKeyboardButton("4️⃣ Yaxshi", callback_data=f"rate_{patient_id}_4"),
            ],
            [
                InlineKeyboardButton("5️⃣ A'lo", callback_data=f"rate_{patient_id}_5")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return False

# Asynchronous Background loop
async def auto_followup_loop(bot_app: Application):
    logger.info("Auto follow-up background checker started.")
    while True:
        try:
            auto_enabled = database.get_setting("auto_messages_enabled", "1") == "1"
            if auto_enabled:
                pending = database.get_pending_followups()
                for patient in pending:
                    chat_id = patient['chat_id']
                    patient_id = patient['id']
                    name = patient['bemor_ismi']
                    
                    success = await send_followup_message(bot_app.bot, chat_id, patient)
                    if success:
                        database.mark_followup_sent(patient_id)
                        logger.info(f"Auto follow-up sent to patient {name} (ID: {patient_id})")
        except Exception as e:
            logger.error(f"Error in auto_followup_loop: {e}")
        await asyncio.sleep(10)

async def reminders_and_loyalty_loop(bot_app: Application):
    logger.info("Reminders and loyalty background task started.")
    await asyncio.sleep(5)  # initial delay
    while True:
        try:
            from datetime import datetime, timedelta
            # 1. Booking Reminders (24h and 2h)
            upcoming = database.get_upcoming_bookings_for_reminders()
            now = datetime.now()
            for b in upcoming:
                chat_id = b['chat_id']
                if not chat_id:
                    continue
                try:
                    booking_dt = datetime.strptime(f"{b['booking_date']} {b['booking_time']}", "%Y-%m-%d %H:%M")
                    diff = booking_dt - now
                    diff_seconds = diff.total_seconds()
                    
                    # 24h reminder (within 24 hours but more than 2 hours)
                    if 0 < diff_seconds <= 24 * 3600 and b['reminder_24h_sent'] == 0:
                        msg = (
                            f"⏰ **Tashrif eslatmasi (24 soat)!**\n\n"
                            f"Assalomu alaykum, *{b['bemor_ismi']}*! 👋\n"
                            f"Ertaga soat *{b['booking_time']}* da shifokor *{b['doctor_name']}* qabuliga yozilgansiz. "
                            f"Kutib qolamiz! 😊"
                        )
                        await bot_app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                        database.mark_reminder_sent(b['id'], "24h")
                        logger.info(f"24h reminder sent for booking {b['id']} to patient {b['bemor_ismi']}")
                        
                    # 2h reminder (within 2 hours)
                    if 0 < diff_seconds <= 2 * 3600 and b['reminder_2h_sent'] == 0:
                        msg = (
                            f"⏰ **Tashrif eslatmasi (2 soat)!**\n\n"
                            f"Hurmatli *{b['bemor_ismi']}*! 👋\n"
                            f"Bugun soat *{b['booking_time']}* da (tez orada) shifokor *{b['doctor_name']}* qabuliga yozilgansiz. "
                            f"Klinikamizga kelishingizni eslatib o'tamiz. Kutamiz! 😊"
                        )
                        await bot_app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                        database.mark_reminder_sent(b['id'], "2h")
                        logger.info(f"2h reminder sent for booking {b['id']} to patient {b['bemor_ismi']}")
                except Exception as ex:
                    logger.error(f"Error checking reminder for booking {b['id']}: {ex}")
            
            # 1.5. Pre-visit Surveys (1h before booking)
            previsit_bookings = database.get_upcoming_bookings_for_previsit_survey()
            for pb in previsit_bookings:
                chat_id = pb['chat_id']
                if not chat_id:
                    continue
                try:
                    survey_msg = (
                        f"📋 **Tashrifdan oldingi so'rovnoma!**\n\n"
                        f"Hurmatli *{pb['bemor_ismi']}*! 👋\n"
                        f"Bugun soat *{pb['booking_time']}* da shifokor *{pb['doctor_name']}* qabuliga kelasiz.\n\n"
                        f"Qabul tez va samarali o'tishi uchun, iltimos, o'zingizni qanday his qilayotganingiz va sizni qaysi alomatlar bezovta qilayotganini **shu xabarga javob sifatida yozib yuboring**. 🩺\n"
                        f"Shifokor kelishingizdan oldin bu ma'lumotlar bilan tanishib chiqadi."
                    )
                    await bot_app.bot.send_message(chat_id=chat_id, text=survey_msg, parse_mode="Markdown")
                    database.mark_previsit_survey_sent(pb['id'])
                    logger.info(f"Pre-visit survey sent for booking {pb['id']} to patient {pb['bemor_ismi']}")
                except Exception as ex:
                    logger.error(f"Error sending pre-visit survey for booking {pb['id']}: {ex}")
            
            # 2. Loyalty campaign (6 months)
            loyalty_candidates = database.get_loyalty_candidates()
            for p in loyalty_candidates:
                chat_id = p['chat_id']
                if not chat_id:
                    continue
                try:
                    msg = (
                        f"🎁 **Sog'lig'ingiz haqida qayg'uramiz!** 👋\n\n"
                        f"Assalomu alaykum, *{p['bemor_ismi']}*! Oxirgi marta klinikamizga *{p['oxirgi_tashrif_sanasi']}* kuni tashrif buyurgan edingiz. "
                        f"Sog'lom tishlar va samimiy tabassum uchun muntazam ravishda shifokor ko'rigidan o'tib turishni tavsiya etamiz.\n\n"
                        f"Kelgusi ko'rigingiz uchun sizga maxsus **10% chegirma** taqdim etamiz! Promokod: *SOGLIK10*\n\n"
                        f"Quyidagi Web App orqali o'zingizga qulay shifokor va vaqtni tanlab yozilishingiz mumkin!"
                    )
                    await bot_app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                    
                    # Update patient next checkup status to prevent duplicate sending
                    database.update_patient(
                        patient_id=p['id'],
                        name=p['bemor_ismi'],
                        phone=p['bemor_telefoni'],
                        doctor=p['shifokor_ismi'],
                        visit_date=p['oxirgi_tashrif_sanasi'],
                        visit_purpose=p.get('tashrif_maqsadi', ''),
                        next_checkup='Loyalty chegirmasi yuborildi'
                    )
                    logger.info(f"Loyalty marketing message sent to patient {p['bemor_ismi']} (ID: {p['id']})")
                except Exception as ex:
                    logger.error(f"Error checking loyalty for patient {p['id']}: {ex}")
                    
        except Exception as e:
            logger.error(f"Error in reminders_and_loyalty_loop: {e}")
        await asyncio.sleep(20)  # check reminders and loyalty candidates every 20 seconds

# ===== RECARE: Send scheduled checkup reminder =====
async def send_recare_message(bot, patient):
    try:
        chat_id = patient['chat_id']
        patient_id = patient['id']
        name = patient['bemor_ismi']
        last_visit = patient.get('oxirgi_tashrif_sanasi', '')
        try:
            from datetime import datetime as dt
            visit_dt = dt.strptime(last_visit, "%Y-%m-%d")
            days = (dt.now() - visit_dt).days
            if days >= 365:
                period = f"{days // 365} yil"
            elif days >= 30:
                period = f"{days // 30} oy"
            else:
                period = f"{days} kun"
        except Exception:
            period = "bir muddat"
        text = (
            f"Assalomu alaykum, *{name}*! 👋\n\n"
            f"«ShifoNazorat» klinikasidan eslatma:\n\n"
            f"*{last_visit}* dagi kelishuvingizdan so'ng *{period}* o'tdi. "
            f"Salomatligingizni nazorat qilish uchun shifokor ko'rigiga yozilish vaqti keldi.\n\n"
            f"📞 Qulay vaqtni tanlash uchun qo'ng'iroq qiling: *+998 71 123 45 67*"
        )
        keyboard = [[
            InlineKeyboardButton("✅ Yozilaman", callback_data=f"recare_accept_{patient_id}"),
            InlineKeyboardButton("🕐 Boshqa vaqtda", callback_data=f"recare_later_{patient_id}")
        ]]
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        logger.info(f"Recare message sent to {name} (chat_id={chat_id})")
        return True
    except Exception as e:
        logger.error(f"Failed to send recare message: {e}")
        return False

# Daily cron job: checks at 09:00 every day for scheduled checkups
async def daily_checkup_loop(bot_app: Application):
    logger.info("Daily checkup cron loop started.")
    while True:
        try:
            now = datetime.now()
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_secs = (target - now).total_seconds()
            logger.info(f"Next recare check in {wait_secs/3600:.1f} hours.")
            await asyncio.sleep(wait_secs)
            # Run checkup
            patients = database.get_todays_checkups()
            logger.info(f"Daily checkup: found {len(patients)} patients to remind.")
            for patient in patients:
                await send_recare_message(bot_app.bot, patient)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in daily_checkup_loop: {e}")
            await asyncio.sleep(60)

# Prewarm the tunnel so first user requests are fast (not cold-start slow)
async def _prewarm_tunnel(tunnel_url: str):
    """Make several background requests to warm up the SSH tunnel connection."""
    import httpx
    await asyncio.sleep(3)  # Give tunnel a moment to stabilize
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.get(f"{tunnel_url}/api/check-user?chat_id=0")
                logger.info(f"Tunnel prewarm ping {attempt+1}: HTTP {resp.status_code}")
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Tunnel prewarm ping {attempt+1} failed: {e}")

# Automatic SSH tunneling
tunnel_process = None

async def start_auto_tunnel(bot_app=None):
    """Keeps the SSH tunnel alive. Auto-reconnects if serveo.net drops the connection."""
    global tunnel_process
    import re

    url = config.get_webapp_url()
    is_loopback = "localhost" in url or "127.0.0.1" in url or "t.me" in url or not url
    if not is_loopback:
        logger.info(f"WEBAPP_URL is already set to a public URL: {url}. No tunnel needed.")
        return

    # Wait for Uvicorn to start
    await asyncio.sleep(2)

    attempt = 0
    while True:
        attempt += 1
        logger.info(f"SSH tunnel attempt #{attempt} via serveo.net...")
        try:
            cmd = [
                "ssh", "-T",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-o", "ExitOnForwardFailure=yes",
                "-R", "80:127.0.0.1:8000",
                "serveo.net"
            ]
            tunnel_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            tunnel_url = None
            # Read lines looking for the tunnel URL
            async def read_output():
                nonlocal tunnel_url
                async for line_bytes in tunnel_process.stdout:
                    line = line_bytes.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    match = re.search(r'https://[a-zA-Z0-9.-]+\.serveousercontent\.com', line)
                    if not match:
                        match = re.search(r'https://[a-zA-Z0-9.-]+\.serveo\.net', line)
                    if match and not tunnel_url:
                        tunnel_url = match.group(0)
                        config.DYNAMIC_WEBAPP_URL = tunnel_url
                        logger.info(f"TUNNEL ACTIVE (attempt #{attempt}): {tunnel_url}")
                        print(f"\n{'='*70}")
                        print(f"  TUNNEL: {tunnel_url}")
                        print(f"{'='*70}\n")
                        # Update Telegram menu button
                        if bot_app:
                            try:
                                await bot_app.bot.set_chat_menu_button(
                                    menu_button=MenuButtonWebApp(
                                        text="🏥 ShifoNazorat",
                                        web_app=WebAppInfo(url=tunnel_url)
                                    )
                                )
                                logger.info("Menu button updated with new tunnel URL")
                            except Exception as me:
                                logger.error(f"Menu button update failed: {me}")
                        # Prewarm in background
                        asyncio.create_task(_prewarm_tunnel(tunnel_url))

            # Run reader until process exits
            try:
                await asyncio.wait_for(read_output(), timeout=None)
            except Exception as read_err:
                logger.warning(f"Tunnel stdout reader error: {read_err}")

            # Wait for process to fully exit
            await tunnel_process.wait()
            rc = tunnel_process.returncode
            logger.warning(f"SSH tunnel process exited (code {rc}). Reconnecting in 5s...")

        except asyncio.CancelledError:
            logger.info("Tunnel task cancelled. Stopping.")
            if tunnel_process:
                try:
                    tunnel_process.terminate()
                except Exception:
                    pass
            return
        except Exception as e:
            logger.error(f"Tunnel error: {e}")

        # Reset URL so users see the loading state during reconnect
        config.DYNAMIC_WEBAPP_URL = None
        await asyncio.sleep(5)


# Lifespan manager for FastAPI to run Telegram Bot concurrently
@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Initialize SQLite tables
    database.init_db()
    
    # Build Telegram Bot application with custom timeouts and optional proxy settings
    import os
    proxy_url = os.getenv("PROXY_URL")
    if proxy_url:
        logger.info(f"Using proxy URL: {proxy_url}")
        request_obj = HTTPXRequest(proxy_url=proxy_url, connect_timeout=30.0, read_timeout=30.0)
    else:
        logger.info("Initializing bot with custom HTTPXRequest (timeout: 30s)")
        request_obj = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
        
    bot_app = Application.builder().token(config.BOT_TOKEN).request(request_obj).build()
    
    # Start automatic SSH tunnel asynchronously in the background
    asyncio.create_task(start_auto_tunnel(bot_app))
    
    # FSM Conversation Handler for adding patient
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Bemor qo'shish$"), add_patient_start)],
        states={
            CHOOSING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_patient_name)],
            CHOOSING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_patient_phone)],
            CHOOSING_DOCTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_patient_doctor)],
            CHOOSING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_patient_date)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_action),
            MessageHandler(filters.Regex("^(❌ Bekor qilish|cancel)$"), cancel_action)
        ]
    )
    
    # Register Bot Handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(conv_handler)
    bot_app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    bot_app.add_handler(CallbackQueryHandler(handle_callbacks))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    
    # Store bot instance in FastAPI app state for web API access
    fastapi_app.state.bot = bot_app.bot
    
    # Start bot updater and polling
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    logger.info("Telegram Bot starts polling.")
    
    # Start the follow-up background checker loop
    bg_task = asyncio.create_task(auto_followup_loop(bot_app))
    # Start the daily 09:00 recare checkup loop
    daily_task = asyncio.create_task(daily_checkup_loop(bot_app))
    # Start the reminders and loyalty background loop
    reminders_task = asyncio.create_task(reminders_and_loyalty_loop(bot_app))
    
    yield
    
    # Graceful shutdown
    bg_task.cancel()
    daily_task.cancel()
    reminders_task.cancel()
    if tunnel_process:
        try:
            tunnel_process.terminate()
            await tunnel_process.wait()
            logger.info("Automatic SSH tunnel terminated.")
        except Exception as e:
            logger.error(f"Error terminating SSH tunnel: {e}")

    try:
        await bg_task
        await reminders_task
    except asyncio.CancelledError:
        pass
        
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()
    logger.info("Telegram Bot shut down.")

# Attach Lifespan context to FastAPI Router
app.router.lifespan_context = lifespan

# Main launch point
def main() -> None:
    import os
    # Read PORT from environment variable (required by Render)
    port = int(os.environ.get("PORT", 8000))
    # Run Uvicorn server which runs uvicorn loop and coordinates lifespan
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
