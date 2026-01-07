import os
import logging
import configparser
from source.database import DatabaseManager
from source.orchestration.lpr_engine import LPREngine
from source.orchestration.classification_engine import ClassificationEngine
from source.orchestration.dump_processor import DumpProcessor

class SugarcaneSystem:
    def __init__(self):
        # Setup Logging
        self.log = logging.getLogger("SugarcaneSystem")
        
        # Load Config
        self.config = configparser.ConfigParser()
        
        # --- DEBUG CONFIG LOADING ---
        cwd = os.getcwd()
        self.log.info(f"DEBUG: Current CWD: {cwd}")
        if os.path.exists("config.txt"):
            self.log.info("DEBUG: Found config.txt in CWD.")
        else:
            self.log.warning("DEBUG: config.txt NOT FOUND in CWD!")
            
        read_files = self.config.read("config.txt", encoding="utf-8")
        self.log.info(f"DEBUG: ConfigParser read: {read_files}")
        
        t_val = self.config.get("DEFAULT", "testing", fallback="NOT_SET")
        self.log.info(f"DEBUG: RAW 'testing' value: {t_val}")
        # ----------------------------
        
        self.factory = self.config.get("DEFAULT", "factory", fallback="MDC")
        self.total_dumps = self.config.getint("DEFAULT", "total_dumps", fallback=8)
        
        nvr_ip = self.config.get("NVR", "ip", fallback=None)
        nvr_user = self.config.get("NVR", "username", fallback=None)
        nvr_pass = self.config.get("NVR", "password", fallback=None)
        
        # Setup DB
        db_path = self.config.get("DATABASE", "path", fallback="sugarcane_v2.db")
        self.log.info(f"Initializing Database at {db_path}...")
        self.db = DatabaseManager(db_path, logger=self.log)
        
        # Seed initial config if empty
        self.db.seed_initial_config(
            self.factory, 
            f"{self.factory} Factory", 
            "milling-process-01", 
            self.total_dumps,
            nvr_ip=nvr_ip, 
            nvr_user=nvr_user, 
            nvr_pass=nvr_pass
        )
        
        import threading
        self.ai_lock = threading.Lock()
        
        # Load Models
        self.log.info("Initializing AI Models...")
        self.lpr_engine = LPREngine(model_path="models/classification.pt", logger=self.log, global_lock=self.ai_lock)
        self.cls_engine = ClassificationEngine(model_path="models/objectdetection.pt", logger=self.log, global_lock=self.ai_lock)
        
        self.processors = []
        self.dumps = []

    def get_system_info(self):
        """Returns factory_name and milling_process."""
        info = self.db.get_factory_info()
        return {
            'factory': info.get('factory_name', 'Unknown Factory'),
            'milling': info.get('milling_process', 'Unknown Process')
        }

    def start_processors(self):
        testing_mode = self.config.getboolean('DEFAULT', 'testing', fallback=False)
        self.dumps = self.db.get_active_dumps()
        self.log.info(f"Starting {len(self.dumps)} processors... (Testing Mode: {testing_mode})")
        for d in self.dumps:
            p = DumpProcessor(d['dump_id'], self.db, self.lpr_engine, self.cls_engine, logger=self.log, testing_mode=testing_mode)
            p.start()
            self.processors.append(p)

    def stop_processors(self):
        self.log.info("Stopping all processors...")
        for p in self.processors:
            p.running = False

    def set_ai_enabled(self, enabled: bool):
        self.log.info(f"System AI Enabled: {enabled}")
        for p in self.processors:
            p.ai_enabled = enabled

    def get_processor_states(self):
        """Returns a list of state dictionaries for the UI with real AI data."""
        states = []
        from datetime import datetime
        for p in self.processors:
            states.append({
                'dump_id': p.dump_id,
                'status': 'RUNNING' if p.is_alive() else 'STOPPED',
                'state': p.sm.state.name,
                'lpr': p.plate_number if p.plate_number else "-",
                'trash_pct': p.latest_cls_res.get('cane_percentage', 0), # Real AI value
                'transaction_id': p.session_uuid[-8:] if p.session_uuid else "-",
                'timestamp': datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            })
        return states

    def get_latest_frames(self, dump_id):
        """Returns the latest frames for a specific dump processor."""
        p = next((p for p in self.processors if p.dump_id == dump_id), None)
        if p:
            return p.latest_frames
        return {}
    
    def refresh_db(self):
        self.log.info("Refreshing configuration from Database...")
        # Placeholder for deeper refresh logic

    # --- UI Helpers (Delegates to DB) ---
    def get_recent_transactions(self, limit=50):
        return self.db.get_recent_transactions(limit)

    def get_dashboard_charts_data(self):
        return self.db.get_dashboard_charts_data()

    def get_daily_report(self, date_str):
        return self.db.get_daily_report(date_str)
