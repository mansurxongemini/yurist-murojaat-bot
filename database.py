import os
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from contextlib import contextmanager
from datetime import datetime, date, timezone, timedelta
from typing import Optional, List, Tuple, Any, Dict
import logging
from config import DB_MIN_CONN, DB_MAX_CONN

logger = logging.getLogger(__name__)

# ===================================================================
# 1. PostgreSQL Ulanish (Connection Pool)
# ===================================================================

# Global pool o'zgaruvchisi
db_pool = None

def init_pool():
    """Baza ulanish hovuzini (pool) yaratish"""
    global db_pool
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL kiritilmagan! .env faylni tekshiring.")
    
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    try:
        # Min 1, Max 20 ta ulanishni ushlab turadi
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            DB_MIN_CONN, DB_MAX_CONN,
            dsn=db_url,
            cursor_factory=psycopg2.extras.DictCursor
        )
        logger.info("✅ Database Connection Pool created")
    except Exception as e:
        logger.error(f"❌ Pool yaratishda xatolik: {e}")
        raise

def close_pool():
    """Poolni yopish"""
    global db_pool
    if db_pool:
        db_pool.closeall()
        logger.info("✅ Database Connection Pool closed")

@contextmanager
def get_db_cursor():
    """PostgreSQL context manager with Pool"""
    global db_pool
    if not db_pool:
        init_pool()
    
    conn = db_pool.getconn()
    try:
        cursor = conn.cursor()
        yield cursor, conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database xatosi: {e}")
        raise
    finally:
        cursor.close()
        # Ulanishni yopmaymiz, poolga qaytaramiz!
        db_pool.putconn(conn)

# ===================================================================
# 2. BARCHA JADVALLARNI YARATISH
# ===================================================================
# database.py dagi init_db() funksiyasini TO'LIQ almashtiring:

def init_db():
    """
    ✅ TO'G'RI: Faqat birinchi marta jadvallarni yaratadi, o'chirmaydi!
    """
    with get_db_cursor() as (cursor, conn):
        
        # 1. Sessions jadvali (asosiy jadval!)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                status VARCHAR(50) NOT NULL CHECK(status IN ('collecting', 'submitted')),
                topic TEXT,
                case_id INTEGER,
                group_msg_id INTEGER,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 2. Session messages jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_msgs (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                type VARCHAR(20) NOT NULL CHECK(type IN ('text', 'photo', 'video', 'voice', 'document')),
                text TEXT,
                file_id TEXT,
                file_size INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, seq)
            )
        """)
        
        # 3. Users jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 9. Operators jadvali (Cases dan oldin yaratilishi kerak)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS operators (
                id SERIAL PRIMARY KEY,
                full_name TEXT NOT NULL,
                gender VARCHAR(20) DEFAULT 'male',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Operators jadvaliga telegram_id ustunini qo'shish (mavjud bo'lmasa)
        cursor.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='operators' AND column_name='telegram_id') THEN 
                    ALTER TABLE operators ADD COLUMN telegram_id BIGINT; 
                END IF; 
            END $$;
        """)
        
        # 4. Cases jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                case_id SERIAL PRIMARY KEY,
                case_number INTEGER NOT NULL UNIQUE,
                session_id INTEGER NOT NULL REFERENCES sessions(session_id),
                user_id BIGINT NOT NULL,
                topic TEXT,
                combined_text TEXT NOT NULL,
                group_msg_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected', 'closed')),
                operator_id INTEGER REFERENCES operators(id),
                rating INTEGER,
                replied_at TIMESTAMP
            )
        """)
        
        # 5. Case message map jadvali (admin reply uchun)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS case_message_map (
                msg_id BIGINT PRIMARY KEY,
                case_id INTEGER NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE
            )
        """)
        
        # 6. User stats jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id BIGINT PRIMARY KEY,
                total_cases INTEGER DEFAULT 0,
                pending_cases INTEGER DEFAULT 0,
                accepted_cases INTEGER DEFAULT 0,
                rejected_cases INTEGER DEFAULT 0,
                closed_cases INTEGER DEFAULT 0,
                last_case_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 10. FAQ jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS faq (
                id SERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 11. Settings jadvali (Dinamik sozlamalar uchun)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key VARCHAR(50) PRIMARY KEY,
                value TEXT
            )
        """)

        # 12. Blocked Users jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id BIGINT PRIMARY KEY,
                reason TEXT,
                blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                blocked_by BIGINT
            )
        """)
        
        # 7. Rate limits jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                user_id BIGINT NOT NULL,
                count INTEGER DEFAULT 0,
                last_date DATE NOT NULL,
                PRIMARY KEY (user_id, last_date)
            )
        """)
        
        # 8. Indekslar
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_user ON cases(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_number ON cases(case_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_case_msg_map_case ON case_message_map(case_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_user_date ON rate_limits(user_id, last_date)")
        
        print("✅ All tables created successfully (PostgreSQL)")
# ===================================================================
# 3. ✅ TO'LIQ QO'SHILGAN FUNKSİYA
# ===================================================================
def cleanup_old_sessions(max_hours: int):
    """
    PostgreSQL: Eski sessionlarni tozalash
    max_hours: Necha soatdan keyin tozalash (masalan: 24)
    """
    try:
        with get_db_cursor() as (cursor, conn):
            cursor.execute("""
                DELETE FROM sessions 
                WHERE status = 'collecting' 
                AND last_activity < NOW() - INTERVAL '%s hours'
            """, (max_hours,))
            
            if cursor.rowcount > 0:
                logger.info(f"🗑️ {cursor.rowcount} ta eski session tozalandi")
    except Exception as e:
        logger.error(f"❌ Session tozalashda xato: {e}")

# ===================================================================
# 4. RATE LIMIT (XATOLIK TO'G'RILANDI)
# ===================================================================
def check_rate_limit(user_id: int, limit_per_day: int) -> Tuple[bool, int]:
    """PostgreSQL rate limit (xavfsiz)"""
    today = date.today().isoformat()
    
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            INSERT INTO rate_limits (user_id, count, last_date) 
            VALUES (%s, 1, %s)
            ON CONFLICT (user_id, last_date) DO UPDATE 
            SET count = rate_limits.count + 1
        """, (user_id, today))
        
        cursor.execute("SELECT count FROM rate_limits WHERE user_id = %s AND last_date = %s", (user_id, today))
        result = cursor.fetchone()
        current_count = result['count'] if result else 0
        
        remaining = limit_per_day - current_count
        allowed = remaining >= 0
        
        return allowed, max(remaining, 0)

# ===================================================================
# 5. BARCHA QOLGAN FUNKSIYALAR (PostgreSQL)
# ===================================================================
def get_active_session(user_id: int) -> Optional[Dict]:
    """Aktiv sessionni olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            "SELECT session_id, status, topic, case_id, group_msg_id FROM sessions WHERE user_id = %s AND status = 'collecting'",
            (user_id,)
        )
        result = cursor.fetchone()
        return dict(result) if result else None


def create_session(user_id: int) -> int:
    """Yangi session yaratish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("INSERT INTO sessions (user_id, status) VALUES (%s, 'collecting') RETURNING session_id", (user_id,))
        return cursor.fetchone()['session_id']


def update_session_topic(session_id: int, topic: str):
    """Sessionga mavzu yozish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("UPDATE sessions SET topic = %s WHERE session_id = %s", (topic, session_id))


def cancel_session(user_id: int) -> bool:
    """Sessionni bekor qilish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("DELETE FROM sessions WHERE user_id = %s AND status = 'collecting'", (user_id,))
        return cursor.rowcount > 0


def add_session_message(session_id: int, msg_type: str, text: Optional[str], 
                       file_id: Optional[str], file_size: Optional[int]) -> int:
    """Xabarni sessionga qo'shish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT COALESCE(MAX(seq), 0) FROM session_msgs WHERE session_id = %s", (session_id,))
        max_seq = cursor.fetchone()[0] or 0
        new_seq = max_seq + 1
        cursor.execute(
            "INSERT INTO session_msgs (session_id, seq, type, text, file_id, file_size) VALUES (%s, %s, %s, %s, %s, %s)",
            (session_id, new_seq, msg_type, text, file_id, file_size)
        )
        return new_seq


def get_session_messages(session_id: int) -> List[Dict]:
    """Session barcha xabarlarini olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT type, text, file_id FROM session_msgs WHERE session_id = %s ORDER BY seq", (session_id,))
        return [dict(row) for row in cursor.fetchall()]


def create_case(session_id: int, user_id: int, topic: Optional[str], 
                combined_text: str) -> Tuple[int, int, int]:
    """Case yaratish (atomic)"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT COALESCE(MAX(case_number), 0) + 1 FROM cases")
        case_number = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO cases (case_number, session_id, user_id, topic, combined_text, group_msg_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            RETURNING case_id
        """, (case_number, session_id, user_id, topic, combined_text, None))
        
        case_id = cursor.fetchone()['case_id']
        
        cursor.execute("UPDATE sessions SET case_id = %s, status = 'submitted' WHERE session_id = %s", (case_id, session_id))
        
        # User stats yangilash
        cursor.execute("""
            INSERT INTO user_stats (user_id, total_cases, pending_cases, last_case_at)
            VALUES (%s, 1, 1, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                total_cases = user_stats.total_cases + 1,
                pending_cases = user_stats.pending_cases + 1,
                last_case_at = CURRENT_TIMESTAMP
        """, (user_id,))
        
        logger.info(f"✅ Case #{case_number} created for user {user_id}")
        return case_id, case_number, session_id


def get_case_by_message_id(msg_id: int) -> Optional[Dict]:
    """Xabar ID bo'yicha case ni topish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT c.case_id, c.user_id, c.session_id, c.topic, c.case_number, c.created_at
            FROM case_message_map m 
            JOIN cases c ON m.case_id = c.case_id 
            WHERE m.msg_id = %s
        """, (msg_id,))
        
        result = cursor.fetchone()
        if result:
            return dict(result)
        
        cursor.execute("SELECT case_id, user_id, session_id, topic, case_number, created_at FROM cases WHERE group_msg_id = %s", (msg_id,))
        result = cursor.fetchone()
        return dict(result) if result else None


def get_user_cases(user_id: int, limit: int = 10, offset: int = 0) -> List[Dict]:
    """Foydalanuvchining murojaatlarini olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT case_number, topic, created_at, status 
            FROM cases 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s OFFSET %s
        """, (user_id, limit, offset))
        return [dict(row) for row in cursor.fetchall()]

def count_user_cases(user_id: int) -> int:
    """Foydalanuvchining jami murojaatlari sonini olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT COUNT(*) FROM cases WHERE user_id = %s", (user_id,))
        return cursor.fetchone()[0]


def get_user_stats(user_id: int) -> Dict:
    """Foydalanuvchi statistikasini olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT 
                COUNT(*) as total_cases,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_cases,
                SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as accepted_cases,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected_cases,
                SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed_cases,
                MAX(created_at) as last_case_at
            FROM cases 
            WHERE user_id = %s
        """, (user_id,))
        
        result = cursor.fetchone()
        if result and result['total_cases']:
            return dict(result)
        
        return {
            'total_cases': 0, 'pending_cases': 0, 'accepted_cases': 0,
            'rejected_cases': 0, 'closed_cases': 0, 'last_case_at': None
        }


def update_case_status(case_id: int, status: str):
    """Case holatini yangilash"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("UPDATE cases SET status = %s WHERE case_id = %s", (status, case_id))
        
        # Postgres uchun soddalashtirilgan update
        cursor.execute("SELECT user_id FROM cases WHERE case_id = %s", (case_id,))
        user_id = cursor.fetchone()['user_id']
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as accepted,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed
            FROM cases WHERE user_id = %s
        """, (user_id,))
        stats = cursor.fetchone()

        cursor.execute("""
            INSERT INTO user_stats (user_id, total_cases, pending_cases, accepted_cases, rejected_cases, closed_cases, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                total_cases = EXCLUDED.total_cases,
                pending_cases = EXCLUDED.pending_cases,
                accepted_cases = EXCLUDED.accepted_cases,
                rejected_cases = EXCLUDED.rejected_cases,
                closed_cases = EXCLUDED.closed_cases,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, stats['total'], stats['pending'], stats['accepted'], stats['rejected'], stats['closed']))


def add_media_message_map(msg_id: int, case_id: int):
    """Media xabarlarni case bilan bog'lash"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            "INSERT INTO case_message_map (msg_id, case_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (msg_id, case_id)
        )


def update_session_activity(session_id: int):
    """
    Sessionning last_activity vaqtini yangilash.
    Har bir xabardan keyin chaqiriladi.
    """
    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            "UPDATE sessions SET last_activity = CURRENT_TIMESTAMP WHERE session_id = %s",
            (session_id,)
        )
        
        # Qadir ma'lumotlar oʻzgarayotganini tekshirish
        if cursor.rowcount == 0:
            logger.warning(f"Session {session_id} topilmadi, activity yangilanmadi")


# database.py oxiriga qo'shing:

def get_case_status(case_number: int, user_id: int) -> Optional[Dict]:
    """
    Ma'lum murojaatning holatini olish (user uchun)
    Returns: {'case_number': ..., 'topic': ..., 'status': ..., 'created_at': ...}
    """
    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            "SELECT case_number, topic, status, created_at FROM cases WHERE case_number = %s AND user_id = %s",
            (case_number, user_id)
        )
        result = cursor.fetchone()
        return dict(result) if result else None


def get_all_users() -> List[int]:
    """
    Barcha foydalanuvchilar IDlarini olish (broadcast uchun)
    """
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT DISTINCT user_id FROM cases")
        return [row['user_id'] for row in cursor.fetchall()]
    
def update_case_group_msg_id(case_id: int, group_msg_id: int):
    """
    Case ning group_msg_id ni yangilash (admin javob yuborganda)
    """
    with get_db_cursor() as (cursor, conn):
        cursor.execute(
            "UPDATE cases SET group_msg_id = %s WHERE case_id = %s",
            (group_msg_id, case_id)
        )


def search_user_cases(user_id: int, query: str, limit: int = 10) -> List[Dict]:
    """
    Foydalanuvchining murojaatlari ichida qidirish (topic yoki matn bo'yicha)
    """
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT case_number, topic, created_at, status 
            FROM cases 
            WHERE user_id = %s 
              AND (topic ILIKE %s OR combined_text ILIKE %s)
            ORDER BY created_at DESC 
            LIMIT %s
        """, (user_id, f"%{query}%", f"%{query}%", limit))
        return [dict(row) for row in cursor.fetchall()]

# ===================================================================
# OPERATORLAR BILAN ISHLASH
# ===================================================================
def add_operator(full_name: str, gender: str = 'male', telegram_id: int = None) -> int:
    """Yangi operator qo'shish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("INSERT INTO operators (full_name, gender, telegram_id) VALUES (%s, %s, %s) RETURNING id", (full_name, gender, telegram_id))
        return cursor.fetchone()['id']

def get_active_operators() -> List[Dict]:
    """Aktiv operatorlarni olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT id, full_name FROM operators WHERE is_active = 1 ORDER BY full_name")
        return [dict(row) for row in cursor.fetchall()]

def delete_operator(operator_id: int):
    """Operatorni o'chirish (soft delete)"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("UPDATE operators SET is_active = FALSE WHERE id = %s", (operator_id,))

def update_operator_name(operator_id: int, new_name: str):
    """Operator ismini yangilash"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("UPDATE operators SET full_name = %s WHERE id = %s", (new_name, operator_id))

def assign_case_operator(case_id: int, operator_id: int):
    """Murojaatga operator biriktirish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("UPDATE cases SET operator_id = %s WHERE case_id = %s", (operator_id, case_id))

def get_operator_name(operator_id: int) -> Optional[str]:
    """Operator ismini olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT full_name FROM operators WHERE id = %s", (operator_id,))
        res = cursor.fetchone()
        return res['full_name'] if res else None

def get_operator_telegram_id(operator_id: int) -> Optional[int]:
    """Operatorning Telegram ID sini olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT telegram_id FROM operators WHERE id = %s", (operator_id,))
        res = cursor.fetchone()
        return res['telegram_id'] if res else None

def get_case_by_number_admin(case_number: int) -> Optional[Dict]:
    """Case raqami bo'yicha olish (admin uchun)"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT * FROM cases WHERE case_number = %s", (case_number,))
        result = cursor.fetchone()
        return dict(result) if result else None

def update_case_reply_info(case_id: int):
    """Javob berilgan vaqtni yangilash"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("UPDATE cases SET replied_at = CURRENT_TIMESTAMP WHERE case_id = %s", (case_id,))

def update_case_rating(case_id: int, rating: int):
    """Bahoni saqlash"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("UPDATE cases SET rating = %s WHERE case_id = %s", (rating, case_id))

def get_case_operator_info(case_id: int) -> Optional[Dict]:
    """Case ga biriktirilgan operator ma'lumotlarini olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT o.full_name, o.gender 
            FROM cases c 
            JOIN operators o ON c.operator_id = o.id 
            WHERE c.case_id = %s
        """, (case_id,))
        result = cursor.fetchone()
        return dict(result) if result else None

def get_all_stats_for_export() -> List[Dict]:
    """Excel uchun barcha statistika"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT c.case_number, c.replied_at, c.rating, o.full_name 

            FROM cases c 
            LEFT JOIN operators o ON c.operator_id = o.id 
            WHERE c.status IN ('closed', 'accepted') AND c.replied_at IS NOT NULL
            ORDER BY c.replied_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

def get_case_by_number_and_user(case_number: int, user_id: int) -> Optional[Dict]:
    """Case raqami va user_id bo'yicha olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT * FROM cases WHERE case_number = %s AND user_id = %s", (case_number, user_id))
        result = cursor.fetchone()
        return dict(result) if result else None

# ===================================================================
# FAQ FUNCTIONS
# ===================================================================
def get_faqs() -> List[Dict]:
    """Barcha FAQ larni olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT * FROM faq ORDER BY id")
        return [dict(row) for row in cursor.fetchall()]

def get_faq(faq_id: int) -> Optional[Dict]:
    """ID bo'yicha FAQ olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT * FROM faq WHERE id = %s", (faq_id,))
        result = cursor.fetchone()
        return dict(result) if result else None

def add_faq(question: str, answer: str):
    """Yangi FAQ qo'shish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("INSERT INTO faq (question, answer) VALUES (%s, %s)", (question, answer))

def delete_faq(faq_id: int):
    """FAQ ni o'chirish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("DELETE FROM faq WHERE id = %s", (faq_id,))

# ===================================================================
# SETTINGS FUNCTIONS
# ===================================================================
def get_setting(key: str) -> Optional[str]:
    """Sozlamani olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT value FROM settings WHERE key = %s", (key,))
        res = cursor.fetchone()
        return res['value'] if res else None

def set_setting(key: str, value: str):
    """Sozlamani saqlash"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            INSERT INTO settings (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (key, value))

# ===================================================================
# BLOCK/BAN FUNCTIONS
# ===================================================================
def block_user(user_id: int, reason: str = None, admin_id: int = None):
    """Foydalanuvchini bloklash"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            INSERT INTO blocked_users (user_id, reason, blocked_by)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                reason = EXCLUDED.reason,
                blocked_at = CURRENT_TIMESTAMP,
                blocked_by = EXCLUDED.blocked_by
        """, (user_id, reason, admin_id))

def unblock_user(user_id: int):
    """Foydalanuvchini blokdan chiqarish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("DELETE FROM blocked_users WHERE user_id = %s", (user_id,))

def is_user_blocked(user_id: int) -> bool:
    """Foydalanuvchi bloklanganligini tekshirish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT 1 FROM blocked_users WHERE user_id = %s", (user_id,))
        return cursor.fetchone() is not None

def get_blocked_users_list() -> List[Dict]:
    """Bloklangan foydalanuvchilar ro'yxati"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT * FROM blocked_users ORDER BY blocked_at DESC")
        return [dict(row) for row in cursor.fetchall()]

def get_operator_statistics() -> List[Dict]:
    """Operatorlar statistikasini olish"""
    with get_db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT o.full_name,
                   COUNT(c.case_id) as total_assigned,
                   SUM(CASE WHEN c.status = 'closed' THEN 1 ELSE 0 END) as closed_cases,
                   SUM(CASE WHEN c.status = 'accepted' THEN 1 ELSE 0 END) as accepted_cases,
                   SUM(CASE WHEN c.status = 'pending' THEN 1 ELSE 0 END) as pending_cases
            FROM operators o
            LEFT JOIN cases c ON o.id = c.operator_id
            WHERE o.is_active = TRUE
            GROUP BY o.id, o.full_name
            ORDER BY closed_cases DESC
        """)
        return [dict(row) for row in cursor.fetchall()]
