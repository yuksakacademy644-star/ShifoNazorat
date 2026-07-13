import sqlite3
from datetime import datetime, timedelta
from typing import Optional
from utils import normalize_phone

DB_NAME = "shifo_nazorat.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bemor_ismi TEXT NOT NULL,
            bemor_telefoni TEXT NOT NULL,
            bemor_telefoni_norm TEXT NOT NULL,
            oxirgi_tashrif_sanasi TEXT NOT NULL,
            shifokor_ismi TEXT NOT NULL,
            oxirgi_baho INTEGER DEFAULT NULL,
            status TEXT DEFAULT 'Faol',
            chat_id INTEGER DEFAULT NULL,
            added_at TEXT DEFAULT (datetime('now', 'localtime')),
            followup_sent INTEGER DEFAULT 0,
            followup_scheduled_at TEXT NOT NULL,
            tashriflar_soni INTEGER DEFAULT 1
        )
    ''')
    # Migrate: tashriflar_soni
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN tashriflar_soni INTEGER DEFAULT 1")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    # Migrate: tashrif_maqsadi (visit purpose)
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN tashrif_maqsadi TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    # Migrate: rejalashtirilgan_tekshiruv (next scheduled checkup)
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN rejalashtirilgan_tekshiruv TEXT DEFAULT NULL")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    # Migrate: is_archived
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN is_archived INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_langs (
            chat_id INTEGER PRIMARY KEY,
            lang TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocked_users (
            chat_id INTEGER PRIMARY KEY,
            blocked_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS security_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            username TEXT,
            payload TEXT,
            detected_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    
    # 1. Table: doctors
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            specialty TEXT DEFAULT '',
            available_hours TEXT DEFAULT '09:00,10:00,11:00,12:00,14:00,15:00,16:00,17:00',
            price REAL DEFAULT 100000.0
        )
    ''')
    
    try:
        cursor.execute("ALTER TABLE doctors ADD COLUMN price REAL DEFAULT 100000.0")
        conn.commit()
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE doctors ADD COLUMN chat_id INTEGER DEFAULT NULL")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    
    # 2. Table: bookings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            doctor_name TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            booking_time TEXT NOT NULL,
            status TEXT DEFAULT 'Kutilmoqda',
            price REAL DEFAULT 0.0,
            reminder_24h_sent INTEGER DEFAULT 0,
            reminder_2h_sent INTEGER DEFAULT 0,
            noshow_msg_sent INTEGER DEFAULT 0,
            previsit_survey_sent INTEGER DEFAULT 0,
            anamnesis TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        )
    ''')

    try:
        cursor.execute("ALTER TABLE bookings ADD COLUMN previsit_survey_sent INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE bookings ADD COLUMN anamnesis TEXT DEFAULT NULL")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    
    # 3. Table: medical_records
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS medical_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            doctor_name TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            diagnosis TEXT NOT NULL,
            prescription TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        )
    ''')
    
    # 4. Table: lab_results
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lab_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            test_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_at TEXT DEFAULT (datetime('now', 'localtime')),
            sent_to_patient INTEGER DEFAULT 0,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        )
    ''')
    
    # 5. Table: marketing_settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS marketing_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # 6. Table: patient_questions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patient_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            answer_text TEXT DEFAULT NULL,
            asked_at TEXT DEFAULT (datetime('now', 'localtime')),
            answered_at TEXT DEFAULT NULL,
            status TEXT DEFAULT 'Kutilmoqda',
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        )
    ''')

    # Default settings
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_messages_enabled', '1')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('test_mode', '0')")
    
    # Insert default doctors if table is empty
    cursor.execute("SELECT COUNT(*) FROM doctors")
    if cursor.fetchone()[0] == 0:
        default_doctors = [
            ("Dr. Ergashev Z.", "Stomatolog-Terapevt", "09:00,10:00,11:00,12:00,14:00,15:00,16:00,17:00", 150000.0),
            ("Dr. Alimova N.", "Ortodont", "09:30,10:30,11:30,12:30,14:30,15:30,16:30,17:30", 250000.0),
            ("Dr. Yuksel", "Implantolog", "10:00,11:00,12:00,14:00,15:00,16:00,17:00", 300000.0)
        ]
        cursor.executemany("INSERT OR IGNORE INTO doctors (name, specialty, available_hours, price) VALUES (?, ?, ?, ?)", default_doctors)

    # Insert default marketing budget if empty
    cursor.execute("INSERT OR IGNORE INTO marketing_settings (key, value) VALUES ('marketing_budget', '500')")

    # Seed default patients, bookings, EMR records and labs if patients table is empty
    cursor.execute("SELECT COUNT(*) FROM patients")
    if cursor.fetchone()[0] == 0:
        import os
        # 1. Insert Patients
        today = datetime.now()
        day_str = today.strftime("%Y-%m-%d")
        
        patients_data = [
            ("Jasur Halimov", "+998901234567", "998901234567", (today - timedelta(days=2)).strftime("%Y-%m-%d"), "Dr. Ergashev Z.", 5, "Faol", (today + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"), 3, "Implantatsiya va maslahat", (today + timedelta(days=30)).strftime("%Y-%m-%d")),
            ("Malika Karimova", "+998935552233", "998935552233", (today - timedelta(days=12)).strftime("%Y-%m-%d"), "Dr. Alimova N.", 4, "Faol", (today + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"), 2, "Breket tizimini to'g'rilash", (today + timedelta(days=90)).strftime("%Y-%m-%d")),
            ("Diyor Solihov", "+998977778899", "998977778899", (today - timedelta(days=8)).strftime("%Y-%m-%d"), "Dr. Yuksel", 3, "Norozi", (today + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"), 1, "Birlamchi ko'rik, diagnoz qo'yildi", (today + timedelta(days=15)).strftime("%Y-%m-%d")),
            ("Zilola Tursunova", "+998941112233", "998941112233", day_str, "Dr. Ergashev Z.", None, "Faol", (today + timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S"), 1, "Tish tozalash va gigiyena", None)
        ]
        
        cursor.executemany("""
            INSERT INTO patients (
                bemor_ismi, bemor_telefoni, bemor_telefoni_norm, oxirgi_tashrif_sanasi, 
                shifokor_ismi, oxirgi_baho, status, followup_scheduled_at, 
                tashriflar_soni, tashrif_maqsadi, rejalashtirilgan_tekshiruv
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, patients_data)
        
        # 2. Get the generated IDs
        cursor.execute("SELECT id, bemor_ismi FROM patients")
        p_ids = {row['bemor_ismi']: row['id'] for row in cursor.fetchall()}
        
        # 3. Seed bookings
        bookings_data = [
            (p_ids["Jasur Halimov"], "Dr. Ergashev Z.", (today - timedelta(days=30)).strftime("%Y-%m-%d"), "10:00", "Keldi", 150000.0),
            (p_ids["Jasur Halimov"], "Dr. Ergashev Z.", (today - timedelta(days=2)).strftime("%Y-%m-%d"), "14:00", "Keldi", 2000000.0),
            (p_ids["Jasur Halimov"], "Dr. Ergashev Z.", (today + timedelta(days=30)).strftime("%Y-%m-%d"), "11:00", "Kutilmoqda", 200000.0),
            
            (p_ids["Malika Karimova"], "Dr. Alimova N.", (today - timedelta(days=12)).strftime("%Y-%m-%d"), "09:30", "Keldi", 250000.0),
            (p_ids["Malika Karimova"], "Dr. Alimova N.", (today + timedelta(days=90)).strftime("%Y-%m-%d"), "14:30", "Kutilmoqda", 250000.0),
            
            (p_ids["Diyor Solihov"], "Dr. Yuksel", (today - timedelta(days=8)).strftime("%Y-%m-%d"), "12:00", "Keldi", 100000.0),
            
            (p_ids["Zilola Tursunova"], "Dr. Ergashev Z.", day_str, "16:00", "Kutilmoqda", 120000.0)
        ]
        cursor.executemany("""
            INSERT INTO bookings (
                patient_id, doctor_name, booking_date, booking_time, status, price
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, bookings_data)
        
        # 4. Seed medical records (EMR)
        emr_data = [
            (p_ids["Jasur Halimov"], "Dr. Ergashev Z.", (today - timedelta(days=30)).strftime("%Y-%m-%d"), "Kariesni davolash, plomba o'rnatish.", "Kalsiy preparatlari, tish yuvish pastasi.", "Tavsiyaga rioya qilinsin."),
            (p_ids["Jasur Halimov"], "Dr. Ergashev Z.", (today - timedelta(days=2)).strftime("%Y-%m-%d"), "Dental implant o'rnatish muvaffaqiyatli yakunlandi.", "Amoksitsillin 500mg (3 mahal 5 kun), og'iz bo'shlig'ini chayish.", "Implantatsiyadan so'ng 1-nazorat."),
            
            (p_ids["Malika Karimova"], "Dr. Alimova N.", (today - timedelta(days=12)).strftime("%Y-%m-%d"), "Breket tizimi tekshirildi, yoy almashtirildi.", "Tish iplari, maxsus breket cho'tkalari.", "Keyingi kelish 3 oydan so'ng."),
            
            (p_ids["Diyor Solihov"], "Dr. Yuksel", (today - timedelta(days=8)).strftime("%Y-%m-%d"), "Birlamchi ko'rik va tish emalini oqartirish.", "Geksoral spreyi (3 mahal).", "Nazorat uchrashuvi rejalashtirilsin.")
        ]
        cursor.executemany("""
            INSERT INTO medical_records (
                patient_id, doctor_name, visit_date, diagnosis, prescription, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, emr_data)
        
        # 5. Seed lab results
        os.makedirs("static/uploads", exist_ok=True)
        pdf_path = "static/uploads/panoroma.pdf"
        if not os.path.exists(pdf_path):
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [ 3 0 R ] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [ 0 0 595 842 ] /Resources << >> /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length 51 >>\nstream\nBT /F1 12 Tf 70 700 Td (ShifoNazorat 3D Panoroma Rentgen Tahlili) Tj ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000062 00000 n\n0000000125 00000 n\n0000000228 00000 n\ntrailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n329\n%%EOF")
                
        labs_data = [
            (p_ids["Jasur Halimov"], "Jag' rentgen tahlili (Panoroma 3D)", "/static/uploads/panoroma.pdf")
        ]
        cursor.executemany("""
            INSERT INTO lab_results (
                patient_id, test_name, file_path
            ) VALUES (?, ?, ?)
        """, labs_data)

    conn.commit()
    conn.close()


def get_user_lang(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT lang FROM user_langs WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row['lang']
    return 'uz' # Default language

def set_user_lang(chat_id, lang):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO user_langs (chat_id, lang) VALUES (?, ?)", (chat_id, lang))
    conn.commit()
    conn.close()

def get_setting(key, default_value="0"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row['value']
    return default_value

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_patient_by_phone(phone):
    norm = normalize_phone(phone)
    if not norm:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE bemor_telefoni_norm = ? ORDER BY id DESC", (norm,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_patient_by_chat_id(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE chat_id = ? ORDER BY id DESC LIMIT 1", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def register_patient_chat_id(phone, chat_id, name):
    norm = normalize_phone(phone)
    if not norm:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if patient exists
    cursor.execute("SELECT * FROM patients WHERE bemor_telefoni_norm = ?", (norm,))
    patients = cursor.fetchall()
    
    if patients:
        # Update chat_id for all matching phone records
        cursor.execute("UPDATE patients SET chat_id = ? WHERE bemor_telefoni_norm = ?", (chat_id, norm))
        conn.commit()
        # Get the latest one to return
        cursor.execute("SELECT * FROM patients WHERE bemor_telefoni_norm = ? ORDER BY id DESC", (norm,))
        patient = cursor.fetchone()
        conn.close()
        return dict(patient)
    else:
        # Create a stub registration
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT INTO patients (bemor_ismi, bemor_telefoni, bemor_telefoni_norm, oxirgi_tashrif_sanasi, shifokor_ismi, chat_id, followup_sent, followup_scheduled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, phone, norm, '', '', chat_id, 1, now_str))
        conn.commit()
        new_id = cursor.lastrowid
        cursor.execute("SELECT * FROM patients WHERE id = ?", (new_id,))
        patient = cursor.fetchone()
        conn.close()
        return dict(patient)

def add_or_update_patient(name, phone, doctor, visit_date, followup_days=3):
    norm = normalize_phone(phone)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Calculate follow-up time
    cursor.execute("SELECT value FROM settings WHERE key = 'test_mode'")
    test_mode_row = cursor.fetchone()
    test_mode = test_mode_row and test_mode_row['value'] == '1'
    
    if test_mode:
        followup_time = datetime.now() + timedelta(minutes=1)
        followup_scheduled_at = followup_time.strftime("%Y-%m-%d %H:%M:%S")
    else:
        try:
            visit_dt = datetime.strptime(visit_date, "%Y-%m-%d")
            followup_time = visit_dt + timedelta(days=followup_days)
            followup_time = followup_time.replace(hour=12, minute=0, second=0)
            followup_scheduled_at = followup_time.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            followup_time = datetime.now() + timedelta(days=followup_days)
            followup_scheduled_at = followup_time.strftime("%Y-%m-%d %H:%M:%S")
            
    # Check if patient already exists
    cursor.execute("SELECT * FROM patients WHERE bemor_telefoni_norm = ?", (norm,))
    existing = cursor.fetchone()
    
    if existing:
        chat_id = existing['chat_id']
        cursor.execute('''
            UPDATE patients
            SET bemor_ismi = ?, bemor_telefoni = ?, oxirgi_tashrif_sanasi = ?, shifokor_ismi = ?,
                oxirgi_baho = NULL, status = 'Faol', followup_sent = 0, followup_scheduled_at = ?,
                tashriflar_soni = COALESCE(tashriflar_soni, 1) + 1
            WHERE bemor_telefoni_norm = ?
        ''', (name, phone, visit_date, doctor, followup_scheduled_at, norm))
        conn.commit()
        patient_id = existing['id']
    else:
        cursor.execute('''
            INSERT INTO patients (bemor_ismi, bemor_telefoni, bemor_telefoni_norm, oxirgi_tashrif_sanasi, shifokor_ismi, followup_scheduled_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, phone, norm, visit_date, doctor, followup_scheduled_at))
        conn.commit()
        patient_id = cursor.lastrowid
        chat_id = None
        
    cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
    updated_patient = cursor.fetchone()
    conn.close()
    return dict(updated_patient)

def get_pending_followups():
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        SELECT * FROM patients
        WHERE chat_id IS NOT NULL 
          AND followup_sent = 0 
          AND status = 'Faol'
          AND datetime(followup_scheduled_at) <= datetime(?)
    ''', (now_str,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def mark_followup_sent(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE patients SET followup_sent = 1 WHERE id = ?", (patient_id,))
    conn.commit()
    conn.close()

def submit_rating(patient_id, rating):
    conn = get_db_connection()
    cursor = conn.cursor()
    status = "Norozi" if rating in (1, 2, 3) else "Faol"
    cursor.execute('''
        UPDATE patients 
        SET oxirgi_baho = ?, status = ?, followup_sent = 1
        WHERE id = ?
    ''', (rating, status, patient_id))
    conn.commit()
    
    cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
    patient = cursor.fetchone()
    conn.close()
    return dict(patient) if patient else None

def get_statistics():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM patients")
    total_patients = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM patients WHERE status = 'Faol'")
    active_patients = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM patients WHERE status = 'Norozi'")
    norozi_patients = cursor.fetchone()[0]
    
    cursor.execute("SELECT AVG(oxirgi_baho) FROM patients WHERE oxirgi_baho IS NOT NULL")
    avg_rating_row = cursor.fetchone()[0]
    avg_rating = round(avg_rating_row, 2) if avg_rating_row is not None else 0.0
    
    cursor.execute("SELECT COUNT(*) FROM patients WHERE oxirgi_baho IS NOT NULL")
    rated_count = cursor.fetchone()[0]

    # Star breakdown
    cursor.execute("SELECT oxirgi_baho, COUNT(*) FROM patients WHERE oxirgi_baho IS NOT NULL GROUP BY oxirgi_baho")
    star_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for row in cursor.fetchall():
        star_counts[row[0]] = row[1]

    # Repeat patients count (tashriflar_soni > 1)
    cursor.execute("SELECT COUNT(*) FROM patients WHERE tashriflar_soni > 1")
    repeat_count = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total_patients": total_patients,
        "active_patients": active_patients,
        "norozi_patients": norozi_patients,
        "avg_rating": avg_rating,
        "rated_count": rated_count,
        "star_counts": star_counts,
        "repeat_count": repeat_count
    }

def get_all_patients(limit=50):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE is_archived = 0 ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_patient_by_id(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_unique_doctors():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT shifokor_ismi FROM patients WHERE shifokor_ismi != ''")
    patients_docs = [row[0] for row in cursor.fetchall() if row[0]]
    cursor.execute("SELECT DISTINCT name FROM doctors WHERE name != ''")
    table_docs = [row[0] for row in cursor.fetchall() if row[0]]
    all_docs = sorted(list(set(patients_docs + table_docs)))
    conn.close()
    return all_docs

def get_todays_checkups():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM patients
        WHERE rejalashtirilgan_tekshiruv = ?
          AND is_archived = 0
          AND chat_id IS NOT NULL
    """, (today,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_patient_status(patient_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE patients SET status = ? WHERE id = ?", (status, patient_id))
    conn.commit()
    conn.close()

def archive_patient(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE patients SET is_archived = 1 WHERE id = ?", (patient_id,))
    conn.commit()
    conn.close()

def update_patient(patient_id, name, phone, doctor, visit_date, visit_purpose, next_checkup, status=None):
    norm = normalize_phone(phone)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE patients
        SET bemor_ismi = ?, bemor_telefoni = ?, bemor_telefoni_norm = ?,
            shifokor_ismi = ?, oxirgi_tashrif_sanasi = ?,
            tashrif_maqsadi = ?, rejalashtirilgan_tekshiruv = ?
        WHERE id = ?
    """, (name, phone, norm, doctor, visit_date, visit_purpose or '', next_checkup, patient_id))
    if status:
        cursor.execute("UPDATE patients SET status = ? WHERE id = ?", (status, patient_id))
    conn.commit()
    cursor.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
    updated = cursor.fetchone()
    conn.close()
    return dict(updated) if updated else None

def get_patients_filtered(limit=100, filter_type=None, search=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    conditions = ["is_archived = 0"]
    params = []
    if filter_type == "today":
        conditions.append("rejalashtirilgan_tekshiruv = ?")
        params.append(today)
    elif filter_type == "3days":
        three_days = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        conditions.append("rejalashtirilgan_tekshiruv BETWEEN ? AND ?")
        params.extend([today, three_days])
    elif filter_type == "callback":
        conditions.append("status = 'Qayta qo''ng''iroq qilish kerak'")
    if search:
        q_norm = normalize_phone(search)
        conditions.append("(bemor_ismi LIKE ? OR shifokor_ismi LIKE ? OR bemor_telefoni_norm LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{q_norm}%"])
    where = " AND ".join(conditions)
    params.append(limit)
    cursor.execute(f"SELECT * FROM patients WHERE {where} ORDER BY id DESC LIMIT ?", params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ================= NEW FEATURES COMPONENT DEVELOPMENTS =================

# 1. Doctors & Bookings
def get_all_doctors():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_doctor(name, specialty="", available_hours="09:00,10:00,11:00,12:00,14:00,15:00,16:00,17:00", price=100000.0):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO doctors (name, specialty, available_hours, price) VALUES (?, ?, ?, ?)",
            (name, specialty, available_hours, price)
        )
        conn.commit()
        inserted_id = cursor.lastrowid
        cursor.execute("SELECT * FROM doctors WHERE id = ?", (inserted_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except sqlite3.IntegrityError:
        conn.close()
        return None

def get_available_slots(doctor_name, date_str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT available_hours FROM doctors WHERE name = ?", (doctor_name,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return []
    
    hours = [h.strip() for h in row['available_hours'].split(',') if h.strip()]
    
    # Get already booked slots for this doctor and date
    cursor.execute(
        "SELECT booking_time FROM bookings WHERE doctor_name = ? AND booking_date = ? AND status != 'Bekor qilindi'",
        (doctor_name, date_str)
    )
    booked_rows = cursor.fetchall()
    conn.close()
    
    booked_times = {r['booking_time'] for r in booked_rows}
    
    slots = []
    for h in hours:
        slots.append({
            "time": h,
            "available": h not in booked_times
        })
    return slots

def create_booking(patient_id, doctor_name, date_str, time_str, price=100000.0):
    # Prevent double booking
    slots = get_available_slots(doctor_name, date_str)
    slot_info = next((s for s in slots if s['time'] == time_str), None)
    if not slot_info or not slot_info['available']:
        return None  # Slot already booked or invalid
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO bookings (patient_id, doctor_name, booking_date, booking_time, price)
        VALUES (?, ?, ?, ?, ?)
    ''', (patient_id, doctor_name, date_str, time_str, price))
    conn.commit()
    booking_id = cursor.lastrowid
    
    # Fetch patient name & details to update patient's next checkup if needed
    cursor.execute("SELECT bemor_ismi, bemor_telefoni FROM patients WHERE id = ?", (patient_id,))
    pat = cursor.fetchone()
    if pat:
        # Auto-update patient status to Kutilyapti (Waiting) and set their next scheduled visit
        cursor.execute('''
            UPDATE patients
            SET status = 'Kutilyapti', rejalashtirilgan_tekshiruv = ?, shifokor_ismi = ?
            WHERE id = ?
        ''', (date_str, doctor_name, patient_id))
        conn.commit()
        
    cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    booking = cursor.fetchone()
    conn.close()
    return dict(booking) if booking else None

def get_all_bookings(limit=100):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT b.*, p.bemor_ismi, p.bemor_telefoni, p.chat_id
        FROM bookings b
        JOIN patients p ON b.patient_id = p.id
        ORDER BY b.booking_date DESC, b.booking_time DESC
        LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_bookings_for_patient(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE patient_id = ? ORDER BY booking_date DESC, booking_time DESC", (patient_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_booking_status(booking_id, status, price=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if price is not None:
        cursor.execute("UPDATE bookings SET status = ?, price = ? WHERE id = ?", (status, price, booking_id))
    else:
        cursor.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
    conn.commit()
    
    # If completed ('Keldi'), update patient's visits count and last visit date
    if status == 'Keldi':
        cursor.execute("SELECT patient_id, booking_date, doctor_name FROM bookings WHERE id = ?", (booking_id,))
        b = cursor.fetchone()
        if b:
            cursor.execute('''
                UPDATE patients
                SET tashriflar_soni = COALESCE(tashriflar_soni, 1) + 1,
                    oxirgi_tashrif_sanasi = ?,
                    shifokor_ismi = ?,
                    status = 'Faol',
                    followup_sent = 0,
                    followup_scheduled_at = datetime('now', 'localtime', '+3 days')
                WHERE id = ?
            ''', (b['booking_date'], b['doctor_name'], b['patient_id']))
            conn.commit()
            
    cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# 2. Electronic Medical Records (EMR)
def get_patient_medical_records(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medical_records WHERE patient_id = ? ORDER BY visit_date DESC", (patient_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_medical_record(patient_id, doctor_name, visit_date, diagnosis, prescription="", notes=""):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO medical_records (patient_id, doctor_name, visit_date, diagnosis, prescription, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (patient_id, doctor_name, visit_date, diagnosis, prescription, notes))
    conn.commit()
    record_id = cursor.lastrowid
    cursor.execute("SELECT * FROM medical_records WHERE id = ?", (record_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# 3. Lab Results Integration
def add_lab_result(patient_id, test_name, file_path):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO lab_results (patient_id, test_name, file_path)
        VALUES (?, ?, ?)
    ''', (patient_id, test_name, file_path))
    conn.commit()
    lab_id = cursor.lastrowid
    cursor.execute("SELECT * FROM lab_results WHERE id = ?", (lab_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_patient_lab_results(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM lab_results WHERE patient_id = ? ORDER BY uploaded_at DESC", (patient_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_pending_lab_reports():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT lr.*, p.chat_id, p.bemor_ismi
        FROM lab_results lr
        JOIN patients p ON lr.patient_id = p.id
        WHERE lr.sent_to_patient = 0 AND p.chat_id IS NOT NULL
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def mark_lab_report_sent(lab_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE lab_results SET sent_to_patient = 1 WHERE id = ?", (lab_id,))
    conn.commit()
    conn.close()

# 4. Loyalty Marketing settings
def get_marketing_budget():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM marketing_settings WHERE key = 'marketing_budget'")
    row = cursor.fetchone()
    conn.close()
    if row:
        return float(row['value'])
    return 500.0

def set_marketing_budget(amount):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO marketing_settings (key, value) VALUES ('marketing_budget', ?)", (str(amount),))
    conn.commit()
    conn.close()

# 5. Doctor KPI & Financial ROI
def get_doctor_kpis():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all unique doctors
    cursor.execute("SELECT DISTINCT name FROM doctors")
    doc_names = [r['name'] for r in cursor.fetchall()]
    
    # Fallback to unique doctors in patients table if doctors table is empty
    if not doc_names:
        cursor.execute("SELECT DISTINCT shifokor_ismi FROM patients WHERE shifokor_ismi != ''")
        doc_names = [r['shifokor_ismi'] for r in cursor.fetchall()]
        
    kpis = []
    for doc in doc_names:
        # Total patients
        cursor.execute("SELECT COUNT(*) FROM patients WHERE shifokor_ismi = ?", (doc,))
        total_p = cursor.fetchone()[0]
        
        # Repeat patients (visits > 1)
        cursor.execute("SELECT COUNT(*) FROM patients WHERE shifokor_ismi = ? AND tashriflar_soni > 1", (doc,))
        repeat_p = cursor.fetchone()[0]
        
        # Average rating
        cursor.execute("SELECT AVG(oxirgi_baho) FROM patients WHERE shifokor_ismi = ? AND oxirgi_baho IS NOT NULL", (doc,))
        avg_r_row = cursor.fetchone()[0]
        avg_r = round(avg_r_row, 2) if avg_r_row is not None else 0.0
        
        # Revenue generated (Sum of price for 'Keldi' bookings)
        cursor.execute("SELECT SUM(price) FROM bookings WHERE doctor_name = ? AND status = 'Keldi'", (doc,))
        rev_row = cursor.fetchone()[0]
        revenue = float(rev_row) if rev_row is not None else 0.0
        
        kpis.append({
            "doctor_name": doc,
            "total_patients": total_p,
            "repeat_patients": repeat_p,
            "repeat_rate": round((repeat_p / max(total_p, 1)) * 100, 1),
            "avg_rating": avg_r,
            "revenue": revenue
        })
        
    conn.close()
    return kpis

def get_doctor_by_chat_id(chat_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM doctors WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_doctor_chat_id(doctor_id: int, chat_id: Optional[int]):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE doctors SET chat_id = ? WHERE id = ?", (chat_id, doctor_id))
    conn.commit()
    conn.close()
    return True

def get_doctor_today_bookings(doctor_name: str):
    today_str = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT b.*, p.bemor_ismi, p.bemor_telefoni, p.chat_id
        FROM bookings b
        JOIN patients p ON b.patient_id = p.id
        WHERE b.doctor_name = ? AND b.booking_date = ?
        ORDER BY b.booking_time ASC
    ''', (doctor_name, today_str))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_doctor_kpi_single(doctor_name: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Total patients
    cursor.execute("SELECT COUNT(*) FROM patients WHERE shifokor_ismi = ?", (doctor_name,))
    total_p = cursor.fetchone()[0]
    
    # Repeat patients (visits > 1)
    cursor.execute("SELECT COUNT(*) FROM patients WHERE shifokor_ismi = ? AND tashriflar_soni > 1", (doctor_name,))
    repeat_p = cursor.fetchone()[0]
    
    # Average rating
    cursor.execute("SELECT AVG(oxirgi_baho) FROM patients WHERE shifokor_ismi = ? AND oxirgi_baho IS NOT NULL", (doctor_name,))
    avg_r_row = cursor.fetchone()[0]
    avg_r = round(avg_r_row, 2) if avg_r_row is not None else 0.0
    
    # Revenue generated
    cursor.execute("SELECT SUM(price) FROM bookings WHERE doctor_name = ? AND status = 'Keldi'", (doctor_name,))
    rev_row = cursor.fetchone()[0]
    revenue = float(rev_row) if rev_row is not None else 0.0
    
    conn.close()
    return {
        "doctor_name": doctor_name,
        "total_patients": total_p,
        "repeat_patients": repeat_p,
        "repeat_rate": round((repeat_p / max(total_p, 1)) * 100, 1),
        "avg_rating": avg_r,
        "revenue": revenue
    }

def get_roi_analytics():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Total patients count
    cursor.execute("SELECT COUNT(*) FROM patients")
    total_patients = cursor.fetchone()[0]
    
    # Total revenue from bookings
    cursor.execute("SELECT SUM(price) FROM bookings WHERE status = 'Keldi'")
    rev_row = cursor.fetchone()[0]
    total_revenue = float(rev_row) if rev_row is not None else 0.0
    
    conn.close()
    
    budget = get_marketing_budget()
    
    # CAC = budget / total_patients
    cac = round(budget / max(total_patients, 1), 2)
    
    # ROI = ((total_revenue - budget) / budget) * 100
    roi = round(((total_revenue - budget) / max(budget, 1)) * 100, 1)
    
    return {
        "marketing_budget": budget,
        "total_patients": total_patients,
        "total_revenue": total_revenue,
        "net_profit": total_revenue - budget,
        "cac": cac,
        "roi": roi
    }

# 6. "Dozhim" Reminder Loop Helpers
def get_upcoming_bookings_for_reminders():
    # Find active bookings coming up in next 24 hours or 2 hours
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT b.*, p.chat_id, p.bemor_ismi, p.bemor_telefoni
        FROM bookings b
        JOIN patients p ON b.patient_id = p.id
        WHERE b.status IN ('Kutilmoqda', 'Tasdiqlandi')
          AND (b.reminder_24h_sent = 0 OR b.reminder_2h_sent = 0)
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def mark_reminder_sent(booking_id, reminder_type):
    conn = get_db_connection()
    cursor = conn.cursor()
    if reminder_type == "24h":
        cursor.execute("UPDATE bookings SET reminder_24h_sent = 1 WHERE id = ?", (booking_id,))
    elif reminder_type == "2h":
        cursor.execute("UPDATE bookings SET reminder_2h_sent = 1 WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()

def get_no_show_bookings():
    # Find bookings marked 'Kelmadi' where no retention message has been sent yet
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT b.*, p.chat_id, p.bemor_ismi, p.bemor_telefoni
        FROM bookings b
        JOIN patients p ON b.patient_id = p.id
        WHERE b.status = 'Kelmadi' AND b.noshow_msg_sent = 0 AND p.chat_id IS NOT NULL
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def mark_no_show_msg_sent(booking_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE bookings SET noshow_msg_sent = 1 WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()

# 7. Loyalty Marketing Automated Campaign (6 month checkup)
def get_loyalty_candidates():
    # Fetch patients whose last visit was 6 months ago (180 days) and haven't booked next checkup yet
    conn = get_db_connection()
    cursor = conn.cursor()
    # If test_mode is on, we'll check patients whose last visit was 1 minute ago (for testing)
    cursor.execute("SELECT value FROM settings WHERE key = 'test_mode'")
    test_mode_row = cursor.fetchone()
    test_mode = test_mode_row and test_mode_row['value'] == '1'
    
    now = datetime.now()
    candidates = []
    
    cursor.execute('''
        SELECT * FROM patients 
        WHERE chat_id IS NOT NULL 
          AND is_archived = 0 
          AND oxirgi_tashrif_sanasi != '' 
          AND rejalashtirilgan_tekshiruv IS NULL
    ''')
    patients = cursor.fetchall()
    conn.close()
    
    for p in patients:
        try:
            visit_dt = datetime.strptime(p['oxirgi_tashrif_sanasi'], "%Y-%m-%d")
            diff = now - visit_dt
            if test_mode:
                # Trigger loyalty message if registered and 1 minute has passed
                if diff.total_seconds() >= 60:
                    candidates.append(dict(p))
            else:
                # Normal mode: 180 days (6 months)
                if diff.days >= 180:
                    candidates.append(dict(p))
        except Exception:
            continue
    return candidates


# 8. Q&A (Savol-javob) Helpers
def create_patient_question(patient_id, question_text):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO patient_questions (patient_id, question_text) VALUES (?, ?)",
        (patient_id, question_text)
    )
    conn.commit()
    inserted_id = cursor.lastrowid
    cursor.execute("SELECT * FROM patient_questions WHERE id = ?", (inserted_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def answer_patient_question(question_id, answer_text):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE patient_questions SET answer_text = ?, answered_at = ?, status = 'Javob berildi' WHERE id = ?",
        (answer_text, now_str, question_id)
    )
    conn.commit()
    cursor.execute("SELECT * FROM patient_questions WHERE id = ?", (question_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_patient_questions(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patient_questions WHERE patient_id = ? ORDER BY id DESC", (patient_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_pending_questions():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT q.*, p.bemor_ismi, p.bemor_telefoni
        FROM patient_questions q
        JOIN patients p ON q.patient_id = p.id
        ORDER BY q.id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# 9. Family Management Helpers
def get_family_members(chat_id):
    if not chat_id:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM patients WHERE chat_id = ? AND is_archived = 0 ORDER BY id ASC", (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_family_member(chat_id, name, phone, doctor_name="Belgilanmagan"):
    conn = get_db_connection()
    cursor = conn.cursor()
    norm = normalize_phone(phone)
    today = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute("SELECT * FROM patients WHERE bemor_ismi = ? AND bemor_telefoni_norm = ?", (name, norm))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("UPDATE patients SET chat_id = ? WHERE id = ?", (chat_id, existing['id']))
        conn.commit()
        cursor.execute("SELECT * FROM patients WHERE id = ?", (existing['id'],))
        row = cursor.fetchone()
        conn.close()
        return dict(row)
        
    cursor.execute("""
        INSERT INTO patients (
            bemor_ismi, bemor_telefoni, bemor_telefoni_norm, oxirgi_tashrif_sanasi, 
            shifokor_ismi, status, chat_id, followup_scheduled_at
        ) VALUES (?, ?, ?, ?, ?, 'Faol', ?, ?)
    """, (name, phone, norm, today, doctor_name, chat_id, (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    inserted_id = cursor.lastrowid
    cursor.execute("SELECT * FROM patients WHERE id = ?", (inserted_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# 10. Pre-visit Survey Helpers
def get_upcoming_bookings_for_previsit_survey():
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    now_date = now.strftime("%Y-%m-%d")
    
    cursor.execute("""
        SELECT b.*, p.chat_id, p.bemor_ismi, p.bemor_telefoni
        FROM bookings b
        JOIN patients p ON b.patient_id = p.id
        WHERE b.status IN ('Kutilmoqda', 'Tasdiqlandi')
          AND b.previsit_survey_sent = 0
          AND b.booking_date = ?
          AND p.chat_id IS NOT NULL
    """, (now_date,))
    rows = cursor.fetchall()
    
    matching = []
    for r in rows:
        try:
            b_dt = datetime.strptime(f"{r['booking_date']} {r['booking_time']}", "%Y-%m-%d %H:%M")
            diff = b_dt - now
            if 0 < diff.total_seconds() <= 3600:
                matching.append(dict(r))
        except Exception:
            continue
            
    conn.close()
    return matching

def mark_previsit_survey_sent(booking_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE bookings SET previsit_survey_sent = 1 WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()

def save_previsit_anamnesis(chat_id, text):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    now_date = now.strftime("%Y-%m-%d")
    
    cursor.execute("""
        SELECT b.id, b.booking_date, b.booking_time
        FROM bookings b
        JOIN patients p ON b.patient_id = p.id
        WHERE p.chat_id = ?
          AND b.status IN ('Kutilmoqda', 'Tasdiqlandi')
          AND b.booking_date = ?
    """, (chat_id, now_date))
    rows = cursor.fetchall()
    
    closest_booking = None
    min_diff = 7200.0
    
    for r in rows:
        try:
            b_dt = datetime.strptime(f"{r['booking_date']} {r['booking_time']}", "%Y-%m-%d %H:%M")
            diff = abs((b_dt - now).total_seconds())
            if diff < min_diff:
                min_diff = diff
                closest_booking = r['id']
        except Exception:
            continue
            
    if closest_booking:
        cursor.execute("UPDATE bookings SET anamnesis = ? WHERE id = ?", (text, closest_booking))
        conn.commit()
        conn.close()
        return closest_booking
    conn.close()
    return None

# Blocked users management
def block_user(chat_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO blocked_users (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()

def is_user_blocked(chat_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM blocked_users WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return True if row else False

def log_attack(chat_id: int, username: str, payload: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO security_logs (chat_id, username, payload) VALUES (?, ?, ?)",
        (chat_id, username or '', payload)
    )
    conn.commit()
    conn.close()

def get_attack_logs(limit=10):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM security_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_blocked_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.chat_id, b.blocked_at, p.bemor_ismi 
        FROM blocked_users b
        LEFT JOIN patients p ON b.chat_id = p.chat_id
        ORDER BY b.blocked_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def unblock_user(chat_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM blocked_users WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def get_all_active_chat_ids():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT chat_id 
        FROM patients 
        WHERE chat_id IS NOT NULL 
          AND chat_id != 0 
          AND chat_id NOT IN (SELECT chat_id FROM blocked_users)
    """)
    p_ids = [row[0] for row in cursor.fetchall() if row[0]]
    
    cursor.execute("""
        SELECT DISTINCT chat_id 
        FROM user_langs 
        WHERE chat_id NOT IN (SELECT chat_id FROM blocked_users)
    """)
    l_ids = [row[0] for row in cursor.fetchall() if row[0]]
    
    cursor.execute("""
        SELECT DISTINCT chat_id 
        FROM doctors 
        WHERE chat_id IS NOT NULL 
          AND chat_id != 0 
          AND chat_id NOT IN (SELECT chat_id FROM blocked_users)
    """)
    d_ids = [row[0] for row in cursor.fetchall() if row[0]]
    
    all_ids = sorted(list(set(p_ids + l_ids + d_ids)))
    conn.close()
    return all_ids


