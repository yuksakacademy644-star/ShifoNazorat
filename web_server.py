import logging
from fastapi import FastAPI, Request, HTTPException, Depends, Form, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os

import config
from utils import normalize_phone
import database

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebServer")

app = FastAPI(title="ShifoNazorat Web API")

# Enable CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["*"],
)

# Request schemas
class PatientAddPayload(BaseModel):
    bemor_ismi: str
    bemor_telefoni: str
    shifokor_ismi: str
    oxirgi_tashrif_sanasi: str
    tashrif_maqsadi: Optional[str] = ""
    rejalashtirilgan_tekshiruv: Optional[str] = None

class PatientUpdatePayload(BaseModel):
    bemor_ismi: str
    bemor_telefoni: str
    shifokor_ismi: str
    oxirgi_tashrif_sanasi: str
    tashrif_maqsadi: Optional[str] = ""
    rejalashtirilgan_tekshiruv: Optional[str] = None
    status: Optional[str] = None

class RatingPayload(BaseModel):
    patient_id: int
    rating: int

class SettingsPayload(BaseModel):
    auto_messages_enabled: Optional[str] = None
    test_mode: Optional[str] = None

class DoctorUpdateChatIdPayload(BaseModel):
    doctor_id: int
    chat_id: Optional[int] = None

# Ensure static directory exists
os.makedirs("static", exist_ok=True)

# Helper to send alert to admin group
async def send_group_alert(bot, alert_text: str):
    group_id = config.get_admin_group_id()
    if group_id:
        try:
            await bot.send_message(chat_id=group_id, text=alert_text, parse_mode="Markdown")
            logger.info("Sent alert to admin group.")
        except Exception as e:
            logger.error(f"Failed to send alert to admin group: {e}")
    else:
        # Fallback to direct messages for admins
        for admin_id in config.get_admin_ids():
            try:
                await bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to send alert to admin {admin_id}: {e}")

# API Endpoints
@app.get("/api/check-user")
def check_user(chat_id: int, name: str = "Mehmon"):
    admin_ids = config.get_admin_ids()
    
    # If ADMIN_IDS is empty, treat first visitor as admin (for easy initial setup)
    if not admin_ids and chat_id != 0:
        logger.info(f"Setting first visitor {name} ({chat_id}) as temporary admin")
        return {"role": "admin", "name": name, "chat_id": chat_id}
        
    if chat_id in admin_ids:
        return {"role": "admin", "name": name, "chat_id": chat_id}
        
    # Check if this user is a doctor
    doctor = database.get_doctor_by_chat_id(chat_id)
    if doctor:
        return {"role": "doctor", "name": doctor['name'], "chat_id": chat_id, "doctor": doctor}
        
    patient = database.get_patient_by_chat_id(chat_id)
    if patient:
        return {"role": "patient", "name": patient['bemor_ismi'], "chat_id": chat_id, "patient": patient}
        
    return {"role": "guest", "name": name, "chat_id": chat_id}

@app.get("/api/patients")
def get_patients(q: Optional[str] = None, filter: Optional[str] = None):
    return database.get_patients_filtered(limit=100, filter_type=filter, search=q)

@app.post("/api/patients/add")
async def add_patient(payload: PatientAddPayload, request: Request):
    bot = getattr(request.app.state, "bot", None)
    try:
        patient = database.add_or_update_patient(
            name=payload.bemor_ismi,
            phone=payload.bemor_telefoni,
            doctor=payload.shifokor_ismi,
            visit_date=payload.oxirgi_tashrif_sanasi
        )
        # Save extra fields
        if patient:
            database.update_patient(
                patient_id=patient['id'],
                name=patient['bemor_ismi'],
                phone=patient['bemor_telefoni'],
                doctor=patient['shifokor_ismi'],
                visit_date=patient['oxirgi_tashrif_sanasi'],
                visit_purpose=payload.tashrif_maqsadi or '',
                next_checkup=payload.rejalashtirilgan_tekshiruv
            )
        if bot:
            alert_text = f"📢 **Yangi bemor qo'shildi (Web):**\n👤 {payload.bemor_ismi}\n👨‍⚕️ {payload.shifokor_ismi}"
            await send_group_alert(bot, alert_text)
        return {"status": "success", "patient": patient}
    except Exception as e:
        logger.error(f"Error adding patient: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/patients/send-followup/{patient_id}")
async def send_followup(patient_id: int, request: Request):
    bot = getattr(request.app.state, "bot", None)
    if not bot:
        raise HTTPException(status_code=500, detail="Telegram bot client is not initialized on server.")
        
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
    patient = cursor.fetchone()
    conn.close()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
        
    chat_id = patient['chat_id']
    if not chat_id:
        raise HTTPException(status_code=400, detail="Bemor botdan ro'yxatdan o'tmagan (chat_id yo'q).")
        
    # Helper imported inside due to circular dependency or bot.py layout
    from bot import send_followup_message
    
    success = await send_followup_message(bot, chat_id, patient)
    if success:
        database.mark_followup_sent(patient_id)
        return {"status": "success", "message": "Followup message sent successfully."}
    else:
        raise HTTPException(status_code=500, detail="Failed to send Telegram message to patient.")

@app.get("/api/stats")
def get_stats():
    return database.get_statistics()

@app.get("/api/settings")
def get_settings():
    return {
        "auto_messages_enabled": database.get_setting("auto_messages_enabled", "1"),
        "test_mode": database.get_setting("test_mode", "0")
    }

@app.post("/api/settings")
def update_settings(payload: SettingsPayload):
    if payload.auto_messages_enabled is not None:
        database.set_setting("auto_messages_enabled", payload.auto_messages_enabled)
    if payload.test_mode is not None:
        database.set_setting("test_mode", payload.test_mode)
    return {"status": "success", "settings": get_settings()}

@app.post("/api/patients/submit-rating")
async def submit_patient_rating(payload: RatingPayload, request: Request):
    bot = getattr(request.app.state, "bot", None)
    patient = database.submit_rating(payload.patient_id, payload.rating)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    if payload.rating in (1, 2, 3) and bot:
        alert_text = (
            f"‼️ **DIQQAT: Bemor norozi (Web)!**\n\n"
            f"👤 **Ism:** {patient['bemor_ismi']}\n"
            f"📞 **Tel:** {patient['bemor_telefoni']}\n"
            f"👨‍⚕️ **Shifokor:** {patient['shifokor_ismi']}\n"
            f"⭐ **Baho:** {payload.rating} / 5\n\n"
            f"Iltimos, zudlik bilan bog'laning."
        )
        await send_group_alert(bot, alert_text)
    return {"status": "success", "patient": patient}

@app.put("/api/patients/update/{patient_id}")
async def update_patient_endpoint(patient_id: int, payload: PatientUpdatePayload):
    try:
        patient = database.update_patient(
            patient_id=patient_id,
            name=payload.bemor_ismi,
            phone=payload.bemor_telefoni,
            doctor=payload.shifokor_ismi,
            visit_date=payload.oxirgi_tashrif_sanasi,
            visit_purpose=payload.tashrif_maqsadi or '',
            next_checkup=payload.rejalashtirilgan_tekshiruv,
            status=payload.status
        )
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found.")
        return {"status": "success", "patient": patient}
    except Exception as e:
        logger.error(f"Error updating patient: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/patients/archive/{patient_id}")
def archive_patient_endpoint(patient_id: int):
    try:
        database.archive_patient(patient_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/doctors")
def get_doctors():
    return database.get_unique_doctors()

@app.get("/api/patients/get/{patient_id}")
def get_patient(patient_id: int):
    patient = database.get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient

# ================= NEW FEATURES APIS =================

class BookingCreatePayload(BaseModel):
    patient_id: int
    doctor_name: str
    booking_date: str
    booking_time: str
    price: Optional[float] = 100000.0

class BookingStatusPayload(BaseModel):
    booking_id: int
    status: str
    price: Optional[float] = None

class MedicalRecordPayload(BaseModel):
    doctor_name: str
    visit_date: str
    diagnosis: str
    prescription: Optional[str] = ""
    notes: Optional[str] = ""

class BudgetPayload(BaseModel):
    amount: float

# 1. Doctors & Booking Engine
@app.get("/api/doctors/all")
def get_all_doctors():
    return database.get_all_doctors()

@app.get("/api/bookings/available-slots")
def get_available_slots(doctor_name: str, date: str):
    return database.get_available_slots(doctor_name, date)

@app.post("/api/bookings/create")
async def create_booking_api(payload: BookingCreatePayload, request: Request):
    bot = getattr(request.app.state, "bot", None)
    booking = database.create_booking(
        patient_id=payload.patient_id,
        doctor_name=payload.doctor_name,
        date_str=payload.booking_date,
        time_str=payload.booking_time,
        price=payload.price
    )
    if not booking:
        raise HTTPException(status_code=400, detail="Ushbu vaqt band yoki xato ma'lumot kiritildi.")
        
    # Notify Admin group/channel about new booking
    if bot:
        patient = database.get_patient_by_id(payload.patient_id)
        pat_name = patient['bemor_ismi'] if patient else "Noma'lum"
        alert_text = (
            f"📅 **Yangi qabul yozildi!**\n\n"
            f"👤 **Bemor:** {pat_name}\n"
            f"👨‍⚕️ **Shifokor:** {payload.doctor_name}\n"
            f"🕒 **Vaqt:** {payload.booking_date} kuni soat {payload.booking_time}"
        )
        await send_group_alert(bot, alert_text)
        
    return {"status": "success", "booking": booking}

@app.get("/api/bookings/list")
def get_all_bookings_api():
    return database.get_all_bookings()

@app.get("/api/bookings/patient/{patient_id}")
def get_bookings_for_patient_api(patient_id: int):
    return database.get_bookings_for_patient(patient_id)

@app.post("/api/bookings/update-status")
async def update_booking_status_api(payload: BookingStatusPayload, request: Request):
    bot = getattr(request.app.state, "bot", None)
    booking = database.update_booking_status(
        booking_id=payload.booking_id,
        status=payload.status,
        price=payload.price
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
        
    # If updated to NoShow ('Kelmadi'), send automatic reminder notification via Telegram immediately or background
    if payload.status == 'Kelmadi' and bot:
        patient = database.get_patient_by_id(booking['patient_id'])
        if patient and patient.get('chat_id'):
            # Trigger immediate No-Show Dozhim/Retention
            try:
                retention_msg = (
                    f"Assalomu alaykum, *{patient['bemor_ismi']}*! 👋\n\n"
                    f"«ShifoNazorat» klinikasidan bezovta qilyapmiz.\n"
                    f"Siz bugun shifokor qabuliga yozilgan edingiz, lekin kela olmadingiz. "
                    f"Sizda hammasi yaxshimi?\n\n"
                    f"Agar qabul vaqtini o'zgartirmoqchi bo'lsangiz, botimiz orqali boshqa qulay vaqtni band qilishingiz mumkin. "
                    f"Biz sizni kutib qolamiz! 😊"
                )
                await bot.send_message(chat_id=patient['chat_id'], text=retention_msg, parse_mode="Markdown")
                database.mark_no_show_msg_sent(booking['id'])
            except Exception as e:
                logger.error(f"Failed to send no-show retention: {e}")
                
    return {"status": "success", "booking": booking}

# 2. Medical Records (EMR)
@app.get("/api/patients/{patient_id}/records")
def get_patient_records(patient_id: int):
    return database.get_patient_medical_records(patient_id)

@app.post("/api/patients/{patient_id}/records")
async def add_patient_record(
    patient_id: int,
    request: Request,
    doctor_name: str = Form(...),
    visit_date: str = Form(...),
    diagnosis: str = Form(...),
    prescription: str = Form(""),
    notes: str = Form(""),
    file: Optional[UploadFile] = File(None)
):
    import shutil
    bot = getattr(request.app.state, "bot", None)
    
    # 1. Save medical record
    record = database.add_medical_record(
        patient_id=patient_id,
        doctor_name=doctor_name,
        visit_date=visit_date,
        diagnosis=diagnosis,
        prescription=prescription,
        notes=notes
    )
    if not record:
        raise HTTPException(status_code=500, detail="Failed to create medical record.")
        
    # 2. Save file if uploaded
    lab_result = None
    if file and file.filename:
        os.makedirs("static/uploads", exist_ok=True)
        timestamp = int(datetime.now().timestamp())
        filename_clean = file.filename.replace(" ", "_")
        relative_path = f"static/uploads/{patient_id}_{timestamp}_{filename_clean}"
        
        with open(relative_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        test_name = "Tahlil natijasi (Tavsiyaga ilova)"
        lab_result = database.add_lab_result(patient_id, test_name, "/" + relative_path)
        
    # 3. Send Telegram Push Notification & optional PDF report
    if bot:
        patient = database.get_patient_by_id(patient_id)
        if patient and patient.get('chat_id'):
            chat_id = patient['chat_id']
            try:
                push_text = (
                    f"🔔 **Yangi tibbiy xulosa!**\n\n"
                    f"Sizga yangi shifokor tavsiyalari keldi. "
                    f"Shaxsiy kabinetingizni tekshiring. 🏥\n\n"
                    f"👨‍⚕️ Shifokor: *{doctor_name}*\n"
                    f"📋 Tashxis: *{diagnosis}*\n"
                    f"💊 Tavsiyalar: {prescription if prescription else '-'}"
                )
                await bot.send_message(chat_id=chat_id, text=push_text, parse_mode="Markdown")
                
                # Send the PDF document if uploaded
                if file and file.filename:
                    caption = (
                        f"📄 **Ilova qilingan tahlil natijasi:**\n"
                        f"🧪 {file.filename}"
                    )
                    with open(relative_path, "rb") as pdf_file:
                        await bot.send_document(
                            chat_id=chat_id,
                            document=pdf_file,
                            filename=file.filename,
                            caption=caption,
                            parse_mode="Markdown"
                        )
                        if lab_result:
                            database.mark_lab_report_sent(lab_result['id'])
            except Exception as e:
                logger.error(f"Failed to send EMR Telegram notification to patient: {e}")
                
    return {"status": "success", "record": record, "lab": lab_result}

@app.get("/api/patients/{patient_id}/bookings")
def get_patient_bookings_api(patient_id: int):
    return database.get_bookings_for_patient(patient_id)

# 3. Lab Results Integration & Upload
@app.post("/api/lab-results/upload")
async def upload_lab_result_api(
    request: Request,
    patient_id: int = Form(...),
    test_name: str = Form(...),
    file: UploadFile = File(...)
):
    import shutil
    # Ensure upload directory exists
    os.makedirs("static/uploads", exist_ok=True)
    # Save the file
    timestamp = int(datetime.now().timestamp())
    filename_clean = file.filename.replace(" ", "_")
    relative_path = f"static/uploads/{patient_id}_{timestamp}_{filename_clean}"
    
    with open(relative_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    lab = database.add_lab_result(patient_id, test_name, "/" + relative_path)
    
    # Auto-send PDF report immediately to patient via DM
    bot = getattr(request.app.state, "bot", None)
    if bot:
        patient = database.get_patient_by_id(patient_id)
        if patient and patient.get('chat_id'):
            try:
                caption = (
                    f"📄 **Tahlil natijalari tayyor!**\n\n"
                    f"👤 Bemor: {patient['bemor_ismi']}\n"
                    f"🧪 Tahlil nomi: *{test_name}*\n\n"
                    f"Natijalar PDF shaklida ilova qilindi. Salomat bo'ling! ❤️"
                )
                with open(relative_path, "rb") as pdf_file:
                    await bot.send_document(
                        chat_id=patient['chat_id'],
                        document=pdf_file,
                        filename=file.filename,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                database.mark_lab_report_sent(lab['id'])
            except Exception as e:
                logger.error(f"Failed to send uploaded PDF via Telegram: {e}")
                
    return {"status": "success", "lab_result": lab}

@app.get("/api/patients/{patient_id}/labs")
def get_patient_labs(patient_id: int):
    return database.get_patient_lab_results(patient_id)

# 4. Analytics: KPI & ROI
@app.get("/api/analytics/kpis")
def get_analytics_kpis():
    return database.get_doctor_kpis()

class PatientQuestionPayload(BaseModel):
    patient_id: int
    question_text: str

class AnswerQuestionPayload(BaseModel):
    question_id: int
    answer_text: str

class FamilyAddPayload(BaseModel):
    chat_id: int
    bemor_ismi: str
    bemor_telefoni: str

@app.get("/api/analytics/roi")
def get_analytics_roi():
    return database.get_roi_analytics()

@app.post("/api/analytics/marketing-budget")
def update_marketing_budget(payload: BudgetPayload):
    database.set_marketing_budget(payload.amount)
    return {"status": "success", "roi": database.get_roi_analytics()}

# 5. Q&A Endpoints
@app.get("/api/qa/patient/{patient_id}")
def get_patient_qa_api(patient_id: int):
    return database.get_patient_questions(patient_id)

@app.get("/api/qa/pending")
def get_pending_qa_api():
    return database.get_all_pending_questions()

@app.post("/api/qa/ask")
async def ask_question_api(payload: PatientQuestionPayload, request: Request):
    bot = getattr(request.app.state, "bot", None)
    question = database.create_patient_question(payload.patient_id, payload.question_text)
    if not question:
        raise HTTPException(status_code=500, detail="Savolni yozishda xatolik yuz berdi.")
        
    if bot:
        patient = database.get_patient_by_id(payload.patient_id)
        pat_name = patient['bemor_ismi'] if patient else "Noma'lum"
        alert_text = (
            f"❓ **Yangi savol keldi!**\n\n"
            f"👤 **Bemor:** {pat_name}\n"
            f"💬 **Savol:** {payload.question_text}\n\n"
            f"Javob berish uchun Admin panelga kiring."
        )
        await send_group_alert(bot, alert_text)
        
    return {"status": "success", "question": question}

@app.post("/api/qa/answer")
async def answer_question_api(payload: AnswerQuestionPayload, request: Request):
    bot = getattr(request.app.state, "bot", None)
    question = database.answer_patient_question(payload.question_id, payload.answer_text)
    if not question:
        raise HTTPException(status_code=404, detail="Savol topilmadi.")
        
    if bot:
        patient = database.get_patient_by_id(question['patient_id'])
        if patient and patient.get('chat_id'):
            try:
                push_text = (
                    f"💬 **Shifokordan javob keldi!**\n\n"
                    f"❓ **Sizning savolingiz:**\n_{question['question_text']}_\n\n"
                    f"👨‍⚕️ **Shifokor javobi:**\n{payload.answer_text}"
                )
                await bot.send_message(chat_id=patient['chat_id'], text=push_text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to send answer notification: {e}")
                
    return {"status": "success", "question": question}

# 6. Family Profile Endpoints
@app.get("/api/patients/family/{chat_id}")
def get_family_members_api(chat_id: int):
    return database.get_family_members(chat_id)

@app.post("/api/patients/family/add")
def add_family_member_api(payload: FamilyAddPayload):
    member = database.add_family_member(payload.chat_id, payload.bemor_ismi, payload.bemor_telefoni)
    if not member:
        raise HTTPException(status_code=500, detail="Oila a'zosini qo'shishda xatolik yuz berdi.")
    return {"status": "success", "member": member}

# 7. Doctor Cabinet / Dashboard Endpoints
@app.post("/api/doctors/update-chat-id")
def update_doctor_chat_id_api(payload: DoctorUpdateChatIdPayload):
    database.update_doctor_chat_id(payload.doctor_id, payload.chat_id)
    return {"status": "success"}

@app.get("/api/doctor/bookings")
def get_doctor_bookings_api(chat_id: int):
    doctor = database.get_doctor_by_chat_id(chat_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Shifokor profili topilmadi.")
    return database.get_doctor_today_bookings(doctor['name'])

@app.get("/api/doctor/kpis")
def get_doctor_kpis_api(chat_id: int):
    doctor = database.get_doctor_by_chat_id(chat_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Shifokor profili topilmadi.")
    return database.get_doctor_kpi_single(doctor['name'])

@app.post("/api/doctor/accept-patient")
async def doctor_accept_patient(
    request: Request,
    booking_id: int = Form(...),
    diagnosis: str = Form(...),
    prescription: str = Form(""),
    notes: str = Form(""),
    file: Optional[UploadFile] = File(None)
):
    import shutil
    bot = getattr(request.app.state, "bot", None)
    
    # 1. Fetch booking
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    booking = cursor.fetchone()
    conn.close()
    if not booking:
        raise HTTPException(status_code=404, detail="Qabul topilmadi.")
        
    booking = dict(booking)
    patient_id = booking['patient_id']
    doctor_name = booking['doctor_name']
    visit_date = booking['booking_date']
    
    # 2. Update booking status to 'Keldi'
    updated_booking = database.update_booking_status(booking_id, 'Keldi')
    if not updated_booking:
        raise HTTPException(status_code=500, detail="Qabul holatini yangilab bo'lmadi.")
        
    # 3. Create medical record
    record = database.add_medical_record(
        patient_id=patient_id,
        doctor_name=doctor_name,
        visit_date=visit_date,
        diagnosis=diagnosis,
        prescription=prescription,
        notes=notes
    )
    if not record:
        raise HTTPException(status_code=500, detail="Tibbiy xulosani yaratib bo'lmadi.")
        
    # 4. Save file if uploaded
    lab_result = None
    if file and file.filename:
        os.makedirs("static/uploads", exist_ok=True)
        timestamp = int(datetime.now().timestamp())
        filename_clean = file.filename.replace(" ", "_")
        relative_path = f"static/uploads/{patient_id}_{timestamp}_{filename_clean}"
        
        with open(relative_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        test_name = "Tahlil natijasi (Tavsiyaga ilova)"
        lab_result = database.add_lab_result(patient_id, test_name, "/" + relative_path)
        
    # 5. Send Telegram Push Notification to patient
    if bot:
        patient = database.get_patient_by_id(patient_id)
        if patient and patient.get('chat_id'):
            chat_id = patient['chat_id']
            try:
                push_text = (
                    f"🔔 **Tibbiy qabul yakunlandi!**\n\n"
                    f"Sizga shifokor *{doctor_name}* tomonidan yangi tavsiyalar va tashxis kiritildi. "
                    f"Tizimga kirib batafsil tanishishingiz mumkin. 🏥\n\n"
                    f"📋 Tashxis: *{diagnosis}*\n"
                    f"💊 Tavsiyalar: {prescription if prescription else '-'}"
                )
                await bot.send_message(chat_id=chat_id, text=push_text, parse_mode="Markdown")
                
                # Send the PDF/Image document if uploaded
                if file and file.filename:
                    caption = (
                        f"📄 **Ilova qilingan tahlil natijasi:**\n"
                        f"🧪 {file.filename}"
                    )
                    with open(relative_path, "rb") as doc_file:
                        await bot.send_document(
                            chat_id=chat_id,
                            document=doc_file,
                            filename=file.filename,
                            caption=caption,
                            parse_mode="Markdown"
                        )
                        if lab_result:
                            database.mark_lab_report_sent(lab_result['id'])
            except Exception as e:
                logger.error(f"Failed to send Doctor EMR Telegram notification to patient: {e}")
                
    return {"status": "success", "record": record, "lab": lab_result, "booking": updated_booking}

# Health check endpoint (Render uses this)
@app.head("/")
@app.get("/health")
def health_check():
    return {"status": "ok"}

# Serve index.html at root
@app.get("/")
def read_root():
    return FileResponse("static/index.html")

# Mount static folder LAST (catch-all)
app.mount("/static", StaticFiles(directory="static"), name="static")

