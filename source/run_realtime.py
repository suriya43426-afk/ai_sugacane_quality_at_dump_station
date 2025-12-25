import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import logging
import threading
import time
from datetime import datetime
from PIL import Image, ImageTk

# Standard internal imports
from source.database import DatabaseManager
from source.lpr_engine import LPREngine
from source.orchestration.classification_engine import ClassificationEngine
from source.orchestration.dump_processor import DumpProcessor

class ProductionApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AI Sugarcane Quality Detection - Production v1.0")
        self.root.geometry("1024x768")
        
        # Setup Logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.log = logging.getLogger("ProductionApp")
        
        # Setup DB
        db_path = "sugarcane_v2.db"
        self.db = DatabaseManager(db_path, logger=self.log)
        
        # Seed initial dummy config if empty
        self.db.seed_initial_config("MDC", "MDC Factory", "milling-process-01", 8)
        
        # Load Models (Heavy)
        self.log.info("Initializing AI Models...")
        self.lpr_engine = LPREngine(model_path="models/objectdetection.pt", logger=self.log)
        self.cls_engine = ClassificationEngine(model_path="models/classification.pt", logger=self.log)
        
        # Load Active Dumps
        self.dumps = self.db.get_active_dumps()
        self.processors = []
        
        self._build_ui()
        self._start_processors()
        
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Header
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill="x")
        ttk.Label(header, text="DUMP STATION MONITORING", font=("Arial", 18, "bold")).pack(side="left")
        
        self.clock_var = tk.StringVar()
        ttk.Label(header, textvariable=self.clock_var, font=("Arial", 14)).pack(side="right")
        self._update_clock()
        
        # Main Body: Table of Dumps
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True)
        
        columns = ("dump_id", "status", "current_state", "lpr", "last_update")
        self.tree = ttk.Treeview(main_frame, columns=columns, show="headings", height=15)
        
        self.tree.heading("dump_id", text="Dump ID")
        self.tree.heading("status", text="Connection")
        self.tree.heading("current_state", text="Current State")
        self.tree.heading("lpr", text="License Plate")
        self.tree.heading("last_update", text="Last Event")
        
        for col in columns:
            self.tree.column(col, width=150, anchor="center")
            
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)
        
        # Bottom Controls
        footer = ttk.Frame(self.root, padding=10)
        footer.pack(fill="x")
        ttk.Button(footer, text="Refresh DB", command=self._refresh_db).pack(side="left")
        ttk.Label(footer, text="Double-click a row to preview latest merged image").pack(side="right")

    def _update_clock(self):
        self.clock_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.root.after(1000, self._update_clock)
        self._update_table()

    def _update_table(self):
        # Update table with current processor states
        for p in self.processors:
            item_id = p.dump_id
            state = p.sm.state.name
            lpr = p.plate_number if p.plate_number else "-"
            
            if self.tree.exists(item_id):
                self.tree.item(item_id, values=(p.dump_id, "RUNNING", state, lpr, datetime.now().strftime("%H:%M:%S")))
            else:
                self.tree.insert("", "end", iid=item_id, values=(p.dump_id, "RUNNING", state, lpr, "-"))

    def _start_processors(self):
        self.log.info(f"Starting {len(self.dumps)} processors...")
        for d in self.dumps:
            p = DumpProcessor(d['dump_id'], self.db, self.lpr_engine, self.cls_engine, logger=self.log)
            p.start()
            self.processors.append(p)

    def _on_double_click(self, event):
        item = self.tree.selection()[0]
        dump_id = self.tree.item(item, "values")[0]
        
        # Find latest session for this dump
        # Fetch from DB: latest merged_image_path where dump_id = x
        # Mock logic or direct DB call:
        session = self._find_latest_merged(dump_id)
        if session and session['merged_image_path']:
            self._show_preview(session['merged_image_path'])
        else:
            messagebox.showinfo("Report", f"No completed session reports found for {dump_id}")

    def _find_latest_merged(self, dump_id):
        # Implementation in DatabaseManager or direct local check
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM dump_session 
                    WHERE dump_id = ? AND status = 'COMPLETE' 
                    ORDER BY end_time DESC LIMIT 1
                """, (dump_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except: return None

    def _show_preview(self, path):
        if not os.path.exists(path):
            messagebox.showerror("Error", f"File not found: {path}")
            return
            
        top = tk.Toplevel(self.root)
        top.title(f"Report Preview: {os.path.basename(path)}")
        top.geometry("800x600")
        
        img = Image.open(path)
        img.thumbnail((780, 580))
        tk_img = ImageTk.PhotoImage(img)
        
        lbl = ttk.Label(top, image=tk_img)
        lbl.image = tk_img # Keep reference
        lbl.pack(pady=10)

    def _refresh_db(self):
        self.log.info("Refreshing configuration from Database...")
        # In a real app, this would check for new camera URLs etc.
        messagebox.showinfo("Config", "Configuration re-loaded from SQLite.")

    def _on_close(self):
        self.log.info("Shutting down...")
        for p in self.processors:
            p.running = False
        self.root.destroy()
        os._exit(0)

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = ProductionApp()
    app.run()
