import sqlite3
import os
import csv
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

class DatabaseManager:
    def __init__(self, db_path: str, logger: Optional[logging.Logger] = None):
        self.db_path = db_path
        self.logger = logger or logging.getLogger("DatabaseManager")
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Initialize the database schema if it doesn't exist."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Table: factories
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS factories (
                        code TEXT PRIMARY KEY,
                        thai_name TEXT,
                        updated_at DATETIME
                    )
                """)
                
                # Table: processing_logs
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processing_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME,
                        factory_code TEXT,
                        lane_number INTEGER,
                        image_path TEXT,
                        plate_number TEXT,
                        confidence REAL,
                        is_uploaded BOOLEAN DEFAULT 0
                    )
                """)
                
                # Table: system_logs
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS system_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME,
                        level TEXT,
                        module TEXT,
                        message TEXT
                    )
                """)
                
                try:
                    cursor.execute("ALTER TABLE processing_logs ADD COLUMN classification TEXT")
                except sqlite3.OperationalError:
                    pass 

                try:
                    cursor.execute("ALTER TABLE processing_logs ADD COLUMN uploaded_at DATETIME")
                except sqlite3.OperationalError:
                    pass

                conn.commit()
                self.logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
            # raise # Don't raise, just log error so app can try to continue or fail gracefully
            # Actually, without DB app is useless. But raising here might crash importing.
            pass

    def get_pending_uploads(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch records where uploaded_at IS NULL."""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM processing_logs 
                    WHERE uploaded_at IS NULL 
                    ORDER BY timestamp ASC 
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Failed to fetch pending uploads: {e}")
            return []

    def mark_as_uploaded(self, log_ids: List[int]):
        """Mark records as uploaded with current timestamp."""
        if not log_ids:
            return
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now()
                placeholders = ','.join('?' for _ in log_ids)
                query = f"UPDATE processing_logs SET uploaded_at = ? WHERE id IN ({placeholders})"
                cursor.execute(query, [now] + log_ids)
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to mark logs as uploaded: {e}")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
            raise

    def seed_factories_from_csv(self, csv_path: str):
        """Reads the legacy factory_code_list.csv and upserts into factories table."""
        if not os.path.exists(csv_path):
            self.logger.warning(f"CSV path does not exist: {csv_path}")
            return

        try:
            count = 0
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    now = datetime.now()
                    
                    for row in reader:
                        code = row.get("factory", "").strip()
                        thai_name = row.get("thai_name", "").strip()
                        
                        if code and thai_name:
                            cursor.execute("""
                                INSERT INTO factories (code, thai_name, updated_at)
                                VALUES (?, ?, ?)
                                ON CONFLICT(code) DO UPDATE SET
                                    thai_name = excluded.thai_name,
                                    updated_at = excluded.updated_at
                            """, (code, thai_name, now))
                            count += 1
                    
                    conn.commit()
            self.logger.info(f"Seeded/Updated {count} factories from CSV.")
        except Exception as e:
            self.logger.error(f"Failed to seed factories from CSV: {e}")

    def update_ai_result(self, old_path_keyword, new_path, plate, classification):
        """Update the log entry based on a partial path match (files might move)."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Find ID by partial path match (since filename contains timestamp which is unique enough per lane)
                # old_path_keyword is e.g. "20251217-224400_Factory"
                # But safer to check if image_path LIKE %keyword%
                
                cursor.execute("""
                    UPDATE processing_logs 
                    SET image_path = ?, plate_number = ?, classification = ?
                    WHERE image_path LIKE ? AND uploaded_at IS NULL
                """, (new_path, plate, str(classification), f"%{old_path_keyword}%"))
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to update AI result: {e}")

    def get_latest_lane_image(self, lane: int) -> Optional[str]:
        """Get the latest image path for a specific lane."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT image_path FROM processing_logs 
                    WHERE lane_number = ? 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                """, (lane,))
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def get_thai_factory_name(self, factory_code: str) -> str:
        """Retrieve Thai name for a given factory code."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT thai_name FROM factories WHERE code = ?", (factory_code,))
                row = cursor.fetchone()
                if row:
                    return row[0]
        except Exception as e:
            self.logger.error(f"Error fetching factory name for {factory_code}: {e}")
        return ""

    def log_processing_result(self, factory_code, lane, image_path, plate_number=None, confidence=None):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO processing_logs (timestamp, factory_code, lane_number, image_path, plate_number, confidence, classification)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (datetime.now(), factory_code, lane, image_path, plate_number, confidence, "PENDING"))
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Failed to log result: {e}")
            return None

    def log_system_event(self, level, module, message):
        try:
             with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO system_logs (timestamp, level, module, message)
                    VALUES (?, ?, ?, ?)
                """, (datetime.now(), level, module, message))
                conn.commit()
        except:
             pass

    def get_latest_lane_info(self, lane: int) -> tuple[Optional[str], Optional[datetime], Optional[str]]:
        """Get (plate_number, timestamp, classification) of latest event for a lane."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Ensure we select classification if it exists (it should now)
                cursor.execute("""
                    SELECT plate_number, timestamp, classification FROM processing_logs 
                    WHERE lane_number = ? 
                    ORDER BY id DESC LIMIT 1
                """, (lane,))
                row = cursor.fetchone()
                if row:
                    ts = row[1]
                    if isinstance(ts, str):
                        try:
                            ts = datetime.fromisoformat(ts)
                        except:
                            pass
                    # row[2] is classification
                    return row[0], ts, row[2] 
        except Exception as e:
            self.logger.error(f"Error fetching latest info for lane {lane}: {e}")
        return None, None, None
