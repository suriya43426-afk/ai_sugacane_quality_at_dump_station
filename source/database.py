import sqlite3
import os
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

class DatabaseManager:
    def __init__(self, db_path: str, logger: Optional[logging.Logger] = None):
        self.db_path = db_path
        self.logger = logger or logging.getLogger("DatabaseManager")
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize the production database schema (8 Tables)."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 1. factory_master
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS factory_master (
                        factory_id TEXT PRIMARY KEY,
                        factory_name TEXT,
                        milling_process TEXT,
                        location TEXT,
                        updated_at DATETIME
                    )
                """)
                
                # 2. dump_master
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dump_master (
                        dump_id TEXT PRIMARY KEY,
                        dump_name TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        updated_at DATETIME
                    )
                """)
                
                # 3. camera_master
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS camera_master (
                        camera_id TEXT PRIMARY KEY,
                        camera_name TEXT,
                        rtsp_url TEXT,
                        view_type TEXT, -- 'FRONT' or 'TOP'
                        updated_at DATETIME
                    )
                """)
                
                # 4. dump_camera_map
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dump_camera_map (
                        dump_id TEXT,
                        camera_id TEXT,
                        channel_type TEXT, -- 'CH101' (Front) or 'CH201' (Top)
                        PRIMARY KEY (dump_id, camera_id),
                        FOREIGN KEY (dump_id) REFERENCES dump_master(dump_id),
                        FOREIGN KEY (camera_id) REFERENCES camera_master(camera_id)
                    )
                """)
                
                # 5. dump_session
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dump_session (
                        session_uuid TEXT PRIMARY KEY,
                        dump_id TEXT,
                        start_time DATETIME,
                        end_time DATETIME,
                        plate_number TEXT,
                        merged_image_path TEXT,
                        status TEXT, -- 'INCOMPLETE', 'COMPLETE'
                        FOREIGN KEY (dump_id) REFERENCES dump_master(dump_id)
                    )
                """)
                
                # 6. dump_images
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dump_images (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_uuid TEXT,
                        image_type TEXT, -- 'IMAGE_1', 'IMAGE_2', 'IMAGE_3', 'IMAGE_4'
                        image_path TEXT,
                        captured_at DATETIME,
                        FOREIGN KEY (session_uuid) REFERENCES dump_session(session_uuid)
                    )
                """)
                
                # 7. dump_state_log
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dump_state_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_uuid TEXT,
                        state_from TEXT,
                        state_to TEXT,
                        changed_at DATETIME,
                        FOREIGN KEY (session_uuid) REFERENCES dump_session(session_uuid)
                    )
                """)
                
                # 8. system_config
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS system_config (
                        config_key TEXT PRIMARY KEY,
                        config_value TEXT,
                        description TEXT
                    )
                """)
                
                conn.commit()
                self.logger.info(f"Production Database initialized at {self.db_path}")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")

    # --- Config & Master Data ---

    def get_system_config(self, key: str, default: Any = None) -> Any:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT config_value FROM system_config WHERE config_key = ?", (key,))
                row = cursor.fetchone()
                return row['config_value'] if row else default
        except:
            return default

    def get_active_dumps(self) -> List[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM dump_master WHERE is_active = 1")
                return [dict(row) for row in cursor.fetchall()]
        except:
            return []

    def get_cameras_for_dump(self, dump_id: str) -> Dict[str, str]:
        """Returns {'CH101': rtsp_url, 'CH201': rtsp_url} for a dump."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT m.channel_type, c.rtsp_url 
                    FROM dump_camera_map m
                    JOIN camera_master c ON m.camera_id = c.camera_id
                    WHERE m.dump_id = ?
                """, (dump_id,))
                rows = cursor.fetchall()
                return {row['channel_type']: row['rtsp_url'] for row in rows}
        except:
            return {}

    # --- Session Management ---

    def create_session(self, dump_id: str) -> str:
        session_uuid = str(uuid.uuid4())
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO dump_session (session_uuid, dump_id, start_time, status)
                    VALUES (?, ?, ?, ?)
                """, (session_uuid, dump_id, datetime.now(), 'INCOMPLETE'))
                conn.commit()
            return session_uuid
        except Exception as e:
            self.logger.error(f"Failed to create session: {e}")
            return ""

    def update_session(self, session_uuid: str, **kwargs):
        if not kwargs: return
        try:
            cols = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            vals = list(kwargs.values()) + [session_uuid]
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"UPDATE dump_session SET {cols} WHERE session_uuid = ?", vals)
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to update session {session_uuid}: {e}")

    def log_state_transition(self, session_uuid: str, state_from: str, state_to: str):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO dump_state_log (session_uuid, state_from, state_to, changed_at)
                    VALUES (?, ?, ?, ?)
                """, (session_uuid, state_from, state_to, datetime.now()))
                conn.commit()
        except:
            pass

    def log_image(self, session_uuid: str, image_type: str, image_path: str):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO dump_images (session_uuid, image_type, image_path, captured_at)
                    VALUES (?, ?, ?, ?)
                """, (session_uuid, image_type, image_path, datetime.now()))
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to log image: {e}")

    def log_system_event(self, level, module, message):
        # We can keep a simplified system log if needed, or reuse state_log for major events
        pass

    def get_factory_info(self) -> Dict[str, Any]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM factory_master LIMIT 1")
                row = cursor.fetchone()
                return dict(row) if row else {}
        except:
            return {}
            
    # --- Helper for Initialization ---
    def seed_initial_config(self, factory_id, factory_name, milling_process, total_dumps, 
                            nvr_ip=None, nvr_user=None, nvr_pass=None):
        """Seed initial data for first-time run."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Seed Factory
                cursor.execute("""
                    INSERT INTO factory_master (factory_id, factory_name, milling_process, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(factory_id) DO UPDATE SET 
                        factory_name=excluded.factory_name,
                        milling_process=excluded.milling_process,
                        updated_at=excluded.updated_at
                """, (factory_id, factory_name, milling_process, datetime.now()))
                
                # Seed Dumps & Cameras if empty
                cursor.execute("SELECT COUNT(*) FROM dump_master")
                if cursor.fetchone()[0] == 0:
                    for i in range(1, total_dumps + 1):
                        d_id = f"dump-{i:02d}"
                        cursor.execute("INSERT INTO dump_master (dump_id, dump_name, updated_at) VALUES (?, ?, ?)",
                                     (d_id, f"Dump Station {i}", datetime.now()))
                        
                        # RTSP URL Template (Hikvision style: rtsp://user:pass@ip:554/Streaming/Channels/CH01)
                        # Front Camera: (2i-1)
                        # Top Camera: (2i)
                        
                        def build_url(idx):
                            if nvr_ip and nvr_user and nvr_pass:
                                return f"rtsp://{nvr_user}:{nvr_pass}@{nvr_ip}:554/Streaming/Channels/{idx}01"
                            return f"CH{idx}01" # Placeholder if no NVR info

                        # Front Camera
                        c1_id = f"cam-{d_id}-front"
                        ch_front = (2*i-1)
                        url_front = build_url(ch_front)
                        cursor.execute("INSERT INTO camera_master (camera_id, camera_name, rtsp_url, view_type, updated_at) VALUES (?, ?, ?, ?, ?)",
                                     (c1_id, f"Front {i}", url_front, "FRONT", datetime.now()))
                        cursor.execute("INSERT INTO dump_camera_map (dump_id, camera_id, channel_type) VALUES (?, ?, ?)",
                                     (d_id, c1_id, "CH101"))
                        
                        # Top Camera
                        c2_id = f"cam-{d_id}-top"
                        ch_top = (2*i)
                        url_top = build_url(ch_top)
                        cursor.execute("INSERT INTO camera_master (camera_id, camera_name, rtsp_url, view_type, updated_at) VALUES (?, ?, ?, ?, ?)",
                                     (c2_id, f"Top {i}", url_top, "TOP", datetime.now()))
                        cursor.execute("INSERT INTO dump_camera_map (dump_id, camera_id, channel_type) VALUES (?, ?, ?)",
                                     (d_id, c2_id, "CH201"))
                
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to seed config: {e}")
