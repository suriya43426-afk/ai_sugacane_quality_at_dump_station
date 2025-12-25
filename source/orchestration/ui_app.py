import os
import sys
import subprocess
import time
import queue
import threading
import cv2
import numpy as np
import logging
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

# Robust import for LPR Engine
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# Add both Source and Root to path to handle "import database" and "from source.database"
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from lpr_engine import LPREngine
    HAS_LPR = True
except ImportError:
    HAS_LPR = False

from source.config import build_paths, load_config, get_total_lanes, clamp_lanes, get_rtsp_base
from .logging_setup import setup_logger
from .camera import CameraManager, letterbox_to_fit
from .orchestrator import Orchestrator
from source.database import DatabaseManager

# Force TCP for RTSP to prevent packet loss / gray screens
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
# Suppress FFMPEG and OpenCV Error Logs (spammy h264 errors)
os.environ["OPENCV_LOG_LEVEL"] = "OFF"
try:
    if hasattr(cv2, 'utils') and hasattr(cv2.utils, 'logging'):
         cv2.utils.logging.setLogLevel(0) # 0 = OFF (Silent)
except:
    pass



CAM_FPS_UI = 1

def get_git_id():
    try:
        # Get short hash
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], stderr=subprocess.DEVNULL).decode('ascii').strip()
    except:
        return "Dev"

APP_VERSION = f"1.01.{get_git_id()}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.paths = build_paths()
        self.logger = setup_logger("ai_orchestration", self.paths.log_file)

        # Init Database
        db_path = os.path.join(self.paths.project_root, "sugarcane.db")
        self.db = DatabaseManager(db_path, logger=self.logger)
        
        # Seed/Update from CSV
        csv_path = os.path.join(self.paths.project_root, "factory_code_list.csv")
        self.db.seed_factories_from_csv(csv_path)

        self.cp, self.cfg = load_config(self.paths.config_file)

        self.factory = self.cfg.get("factory", "Sxx")

        lanes_raw = get_total_lanes(self.cp, fallback=1)
        self.total_lanes = clamp_lanes(lanes_raw, 1, 8)
        
        self.display_channels = []
        for i in range(self.total_lanes):
            base = 101 + (i * 200) # Jump 2 channels per lane
            self.display_channels.extend([base, base + 100])

        self.logger.info(
            "Config parsed: factory=%s total_lanes=%s display_channels=%s",
            self.factory,
            self.total_lanes,
            self.display_channels,
        )

        self.title(f"AI Orchestration - {self.factory} | Ver: {APP_VERSION}")
        self.geometry("1280x760")
        self.minsize(1100, 650)
        
        # Auto-Maximize
        try:
            self.state("zoomed")
        except:
            pass

        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        
        # --- Taskbar Icon & ID ---
        try:
            import ctypes
            myappid = f'ai.sugarcane.installer.{APP_VERSION}' 
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
            
        try:
            logo_path = os.path.join(self.paths.project_root, "logo.png")
            if os.path.exists(logo_path):
                icon_img = tk.PhotoImage(file=logo_path)
                self.iconphoto(True, icon_img)
        except Exception:
            pass
        # -------------------------
        
        # Init Flag early
        self.shutting_down = False

        # queues
        # ... (services)
        
        # GPU detection early
        raw_gpu = self.cfg.get("lpr_use_gpu", "auto").lower()
        use_gpu = False
        if raw_gpu == "true":
            use_gpu = True
        elif raw_gpu == "false":
            use_gpu = False
        else:
            try:
                import torch
                use_gpu = torch.cuda.is_available()
            except ImportError:
                use_gpu = False

        # --- Data / Networking ---
        self.cam_mgr = None
        self.orch = Orchestrator(
            self.paths, 
            factory_id=self.factory, 
            total_lanes=self.total_lanes,
            logger=self.logger,
            ui_callbacks={"update_status": self.update_orch_status, "append_log": self.append_log}
        )
        self.ui_cam_q = queue.Queue()
        
        self.cam_running = False
        self.close_attempts = 0
        
        # Monitor Toggle (Cv2 Window)
        self.show_monitor = tk.BooleanVar(value=False)
        
        # LPR Engine (Restored for Monitor, but lightweight)
        self.lpr_engine = None
        self.lpr_lock = threading.Lock() # Thread safety
        self.last_detect_map = {} # map channel -> timestamp
        
        if HAS_LPR:
            model_path = os.path.join(self.paths.project_root, "models", "objectdetection.pt")
            if os.path.exists(model_path):
                try:
                    # Fix: Use lower confidence (0.40) to make sure we see plates even if blurry
                    conf = 0.40
                    # Re-use global GPU config detected earlier
                    self.logger.info(f"Loading LPREngine for UI (Conf={conf}, GPU={use_gpu}): {model_path}")
                    self.lpr_engine = LPREngine(model_path=model_path, conf_th=conf, logger=self.logger, use_gpu=use_gpu)
                except Exception as e:
                    self.logger.error(f"Failed to load LPREngine: {e}")
        
        # Last Snap Cache
        self.latest_snap_paths = {} # ch -> path
        
        # Fallback Live Preview Timestamp (ch -> float)
        self.last_fallback_ts = {} 

        # Auto-Sync Scheduler (Disabled per Offline Mode Request)
        # self.sync_stop_event = threading.Event()
        # self.sync_thread = threading.Thread(target=self._auto_sync_loop, daemon=True)
        # self.sync_thread.start()

        # Test Flag
        self.do_test_snapshot = False

        # System Start Time for Uptime
        self.system_start_time = time.time()
        
        # System Status State (GREEN, YELLOW, RED)
        self.status_state = "GREEN" 
        self.status_msg = "System Normal"

        self._build_ui()

        
        # Start Status Update Loop
        self._update_status_loop()

        self.after(50, self._camera_ui_pump)
        # Schedule Last Snap Update (every 2 seconds)
        self.after(2000, self._update_last_snaps)
        
        # Finally start orchestration
        self._start_all()
        
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Auto-Restart Scheduler (at 05:00 AM daily)
        self._schedule_daily_restart()

    def _auto_sync_loop(self):
        """
        Background loop to run Data Sync every hour.
        """
        self.logger.info("Auto-Sync Scheduler Started (Interval: 1 Hour)")
        
        # Initial wait (45 sec after startup to capture first snapshot)
        if self.sync_stop_event.wait(45):
            return

        while not self.sync_stop_event.is_set():
            try:
                msg = "Triggering Hourly Data Sync..."
                self.logger.info(msg)
                self.append_log("INFO", msg)
                
                script_path = os.path.join(self.paths.project_root, "source", "run_data_sync.py")
                
                # Run sync script and capture output
                res = subprocess.run(
                    [sys.executable, script_path], 
                    capture_output=True, 
                    text=True
                )
                
                # Log Output to UI
                if res.stdout and len(res.stdout.strip()) > 0:
                    self.append_log("INFO", f"[DataSync] {res.stdout.strip()}")
                
                if res.returncode != 0:
                    self.append_log("ERROR", f"[DataSync] Failed (RC={res.returncode})")
                    if res.stderr:
                         self.append_log("ERROR", f"[DataSync] Error: {res.stderr.strip()}")
                else:
                    self.append_log("INFO", "[DataSync] Sync Completed Successfully.")
                
            except Exception as e:
                err_msg = f"Auto-Sync Exception: {e}"
                self.logger.error(err_msg)
                self.append_log("ERROR", err_msg)
            
            # Wait 1 hour (3600s)
            if self.sync_stop_event.wait(3600):
                break

    def _schedule_daily_restart(self):
        now = datetime.now()
        target = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        
        ms_until = int((target - now).total_seconds() * 1000)
        self.logger.info(f"Auto-restart scheduled in {ms_until/1000/60:.1f} minutes ({target})")
        
        self.after(ms_until, self._auto_restart_trigger)

    def _auto_restart_trigger(self):
        self.logger.info("Triggering Auto-Restart for Updates...")
        self._stop_all()
        # Exit with code 100 to tell batch script to restart
        os._exit(100)

    def _update_last_snaps(self):
        """Periodically check DB for new truck images and update UI tiles."""
        try:
            # 1. Update Lane Headers (Plate Number / Empty)
            if hasattr(self, 'lane_status_vars'):
                for lane_num, var in self.lane_status_vars.items():
                    # Unpack 3 values (Updated DB method)
                    plate, ts, cls_res = self.db.get_latest_lane_info(lane_num)
                    
                    status_text = "Waiting"
                    ts_str = ""
                    
                    if plate and ts:
                        # Check freshness (e.g. within 60 seconds)
                        now = datetime.now()
                        delta = (now - ts).total_seconds()
                        
                        ts_str = ts.strftime("%H:%M:%S")
                        
                        if delta < 60:
                            # Show Processing + Class (if available)
                            status_text = f"Processing: {plate}"
                            if cls_res and cls_res != "None":
                                status_text += f" | {cls_res}"
                        else:
                            status_text = "Waiting"
                    
                    # Update Left Panel Variable
                    # Format: LANE_1 : Waiting (Time: 12:00:00)
                    display_text = f"LANE_{lane_num} : {status_text}"
                    if ts_str:
                         display_text += f" ({ts_str})"
                         
                    var.set(display_text)

            # 2. Update Tile Images
            if not self.show_monitor.get():
                BUFFER_DIR = os.path.join(self.paths.project_root, "buffer_images")
                
                for idx, ch in enumerate(self.display_channels):
                   # Calculate Lane
                   lane_num = ((ch - 101) // 400) + 1
                   
                   # PRIORITY 1: Live View (Heartbeat Image)
                   # This satisfies "Update every 10s" requirement
                   live_path = os.path.join(BUFFER_DIR, f"live_view_{ch}.jpg")
                   target_path = None
                   
                   if os.path.exists(live_path):
                       # Check if modified recently to avoid stale images?
                       # Logic: Just display it.
                       target_path = live_path
                   else:
                       # PRIORITY 2: Fallback to DB "Last Truck"
                       if str(ch).endswith("01"):
                           base_path = self.db.get_latest_lane_image(lane_num)
                           if base_path and os.path.exists(base_path):
                               # deduce logic
                               # If 101, valid.
                               # If 201, must deduce 201 path.
                               
                               base_name, ext = os.path.splitext(base_path)
                               parts = base_name.split('_')
                               # e.g. ..._101
                               
                               candidate_path = None
                               if parts and len(parts[-1]) in [3, 4] and parts[-1].isdigit():
                                   suffix = parts[-1]
                                   if suffix == str(ch):
                                       candidate_path = base_path
                                   else:
                                       new_base = "_".join(parts[:-1]) + f"_{ch}"
                                       candidate_path = new_base + ext
                               else:
                                   if str(ch) in base_path: # Weak check
                                       candidate_path = base_path
                               
                               if candidate_path and os.path.exists(candidate_path):
                                   target_path = candidate_path
                   
                   if target_path and os.path.exists(target_path):
                       # Basic optimization: Don't re-read if same path AND not modified?
                       # Live view path is constant, so we MUST check mtime or just re-read.
                       # Re-reading 4 small jpgs every 2s is fine.
                       try:
                           bgr = cv2.imread(target_path)
                           if bgr is not None:
                               self._render_tile_image(ch, bgr)
                       except Exception:
                           pass

            # 3. Update Camera Status (JSON Sync)
            # We stick this here to run every loop
            try:
                BUFFER_DIR = os.path.join(self.paths.project_root, "buffer_images")
                for ch in self.display_channels:
                     status_file = os.path.join(BUFFER_DIR, f"status_{ch}.json")
                     if os.path.exists(status_file):
                         # Read status
                         try:
                             import json
                             with open(status_file, "r") as f:
                                 st = json.load(f)
                                 # st["ts"] check? If > 15s ago, consider disconnected?
                                 if time.time() - st.get("ts", 0) < 15:
                                     self.cam_status[ch] = "Connected"
                                 else:
                                     self.cam_status[ch] = "Disconnected (Stale)"
                         except:
                             self.cam_status[ch] = "Error Read"
                     else:
                         self.cam_status[ch] = "Connecting..."
            except Exception:
                pass

        except Exception as e:
            self.logger.error(f"Error in last snap update: {e}")
        
        self.after(2000, self._update_last_snaps)



    def _get_thai_factory_name(self):
        """Reads factory_code_list.csv and returns Thai name for self.factory"""
        return self.db.get_thai_factory_name(self.factory)

    def _rtsp_base(self) -> str:
        return get_rtsp_base(self.cfg)


        
    def _detection_callback(self, frame_bgr, channel):
        """
        Restored & Optimized Detection:
        - Max 5 FPS per channel
        - Draw Red Box ONLY (No text / No confidence) to be minimal
        - Added [LPR] indicator to show system is scanning
        """
        if self.lpr_engine is None:
            return

        # Rate Limit: 5 FPS (0.2s)
        now = time.time()
        last_ts = self.last_detect_map.get(channel, 0.0)
        if now - last_ts < 0.2:
            return
        self.last_detect_map[channel] = now

        try:
            # Draw visual indicator (Green text)
            cv2.putText(frame_bgr, "[LPR RUNNING]", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Locking essential for thread safety if multiple cams call this
            with self.lpr_lock:
                 # Detect
                 res = self.lpr_engine.detect(frame_bgr, skip_ocr=True) # Skip OCR for speed
            
            if res:
                x1, y1, x2, y2 = res.bbox
                # Draw RED Box (BGR = 0, 0, 255)
                # Thickness = 3
                cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (0, 0, 255), 3)
                self.do_test_snapshot = False
                # NO TEXT as requested
        except Exception:
            pass

    def _build_ui(self):
        root = self
        root.title(f"AI Sugarcane Installer - v{APP_VERSION}")
        root.geometry("1024x768")
        
        
        # Set Window Icon
        # Windows Taskbar strongly prefers .ico via iconbitmap().
        # If we only have .png, try to convert it to a temp .ico for best results.
        logo_path_png = os.path.join(self.paths.project_root, "logo.png")
        logo_path_ico = os.path.join(self.paths.project_root, "logo.ico")
        
        try:
            # 1. Try to generate .ico if missing
            if not os.path.exists(logo_path_ico) and os.path.exists(logo_path_png):
                try:
                    img = Image.open(logo_path_png)
                    img.save(logo_path_ico, format='ICO', sizes=[(256, 256)])
                    self.logger.info("Generated logo.ico from logo.png for Taskbar support")
                except Exception as gen_err:
                     self.logger.warning(f"Could not generate .ico: {gen_err}")

            # 2. Apply .ico (Primary)
            if os.path.exists(logo_path_ico):
                root.iconbitmap(logo_path_ico)
            
            # 3. Apply .png (Secondary/Linux/Fallback)
            if os.path.exists(logo_path_png):
                icon_img = ImageTk.PhotoImage(file=logo_path_png)
                root.iconphoto(True, icon_img)
                
        except Exception as e:
            self.logger.error(f"Failed to set window icon: {e}")
        
        # --- Layout ---
        # Top: Header / Status
        # Middle: Split (Left Control/Log | Right Camera Grid)
        
        main_cont = ttk.Frame(root)
        main_cont.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Left Panel (Controls & Logs)
        # Width ~35%
        left = ttk.Frame(main_cont, width=350)
        left.pack(side="left", fill="y", padx=(0, 10))
        
        # Right Panel (Camera Grid)
        right = ttk.Frame(main_cont)
        right.pack(side="right", fill="both", expand=True)
        
        # --- LEFT SIDE ---
        
        # Logo (Optional)
        logo_path = os.path.join(self.paths.project_root, "logo.png")
        if os.path.exists(logo_path):
            try:
                pil_img = Image.open(logo_path)
                # Resize to reasonable header size (e.g. 100px height)
                base_height = 100
                w_percent = (base_height / float(pil_img.size[1]))
                w_size = int((float(pil_img.size[0]) * float(w_percent)))
                pil_img = pil_img.resize((w_size, base_height), Image.Resampling.LANCZOS)
                
                self.logo_tk = ImageTk.PhotoImage(pil_img)
                lbl_logo = ttk.Label(left, image=self.logo_tk, anchor="center")
                lbl_logo.pack(fill="x", pady=(0, 10))
            except Exception as e:
                self.logger.error(f"Failed to load logo: {e}")

        # Factory Name Header (Thai)
        thai_name = self._get_thai_factory_name()
        display_name = f"{self.factory} : {thai_name}" if thai_name else self.factory
        
        lbl_thai = ttk.Label(left, text=display_name, font=("Segoe UI", 12, "bold"), foreground="#2b5797", justify="center", anchor="center")
        lbl_thai.pack(fill="x", pady=(0, 4))

        header = ttk.Frame(left)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="System Status", font=("Segoe UI", 14, "bold")).pack(side="left")
        
        # CPU/GPU Mode Indicator
        raw_gpu = self.cfg.get("lpr_use_gpu", "auto").lower()
        use_gpu = False
        
        if raw_gpu == "true":
            use_gpu = True
        elif raw_gpu == "false":
            use_gpu = False
        else:
            # Auto-detect using torch if available, safely
            try:
                import torch
                use_gpu = torch.cuda.is_available()
                self.logger.info(f"GPU Auto-Detect: {use_gpu} (torch available)")
            except Exception as e:
                self.logger.warning(f"GPU Auto-Detect Failed: {e}")
                use_gpu = False

        mode_text = "GPU Mode" if use_gpu else "CPU Mode"
        mode_color = "#009900" if use_gpu else "#555"
        
        # Right side of header: Version | Mode
        h_right = ttk.Frame(header)
        h_right.pack(side="right", anchor="s")
        
        ttk.Label(h_right, text=mode_text, foreground=mode_color, font=("Segoe UI", 9, "bold")).pack(side="right", padx=(10, 0))
        ttk.Label(h_right, text=f"v{APP_VERSION}", foreground="#555").pack(side="right")

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(0, 8))

        # STATUS INDICATOR (Replaces Stop Button)
        # We use a Label with background color
        self.lbl_status = tk.Label(btns, text="System Normal", bg="#4CAF50", fg="white", font=("Segoe UI", 10, "bold"), height=2)
        self.lbl_status.pack(side="left", fill="x", expand=True)

        # AI Process Button (Disabled)
        self.btn_daily = ttk.Button(btns, text="Sync Cloud (OFF)", state="disabled")
        self.btn_daily.pack(side="left", padx=(6, 0))
        
        # Test Upload Button (New)
        self.btn_test_upload = ttk.Button(btns, text="Test Upload", command=self._on_click_test_upload)
        self.btn_test_upload.pack(side="left", padx=(6, 0))
        
        # Update Button
        self.btn_update = ttk.Button(btns, text="Update System", command=self._on_click_update)
        self.btn_update.pack(side="right", padx=0)
        
        # Test E2E Button (New)
        self.btn_test = ttk.Button(btns, text="Test E2E", command=self._on_click_test_e2e)
        self.btn_test.pack(side="right", padx=6)
        
        # Options Frame
        opts = ttk.Frame(left)
        opts.pack(fill="x", pady=(0, 8))
        # Monitor Toggle
        ttk.Checkbutton(opts, text="Show Monitor (External Window)", variable=self.show_monitor, command=self._on_click_monitor).pack(anchor="w")

        st1 = ttk.LabelFrame(left, text="System Status", padding=10)
        st1.pack(fill="x", pady=(0, 10))

        self.var_rt = tk.StringVar(value="run_realtime: (external / manual)")
        self.var_daily = tk.StringVar(value="run_ai_daily: -")
        self.var_agent = tk.StringVar(value="agent: -")

        ttk.Label(st1, textvariable=self.var_rt).pack(anchor="w")
        ttk.Label(st1, textvariable=self.var_daily).pack(anchor="w", pady=(6, 0))
        ttk.Label(st1, textvariable=self.var_agent).pack(anchor="w", pady=(6, 0))

        # Lane Status Section (New)
        st_lanes = ttk.LabelFrame(left, text="Lane Status", padding=10)
        st_lanes.pack(fill="x", pady=(0, 10))
        
        self.lane_status_vars = {}
        for i in range(self.total_lanes):
            lane_num = i + 1
            v = tk.StringVar(value=f"LANE_{lane_num}: Waiting")
            self.lane_status_vars[lane_num] = v
            ttk.Label(st_lanes, textvariable=v, font=("Segoe UI", 9)).pack(anchor="w", pady=2)

        logf = ttk.LabelFrame(left, text="Logs", padding=8)
        logf.pack(fill="both", expand=True, pady=(10, 0))

        # ... [Logs section same] ...

        self.txt = tk.Text(logf, wrap="none", height=12, font=("Consolas", 9))
        self.txt.pack(fill="both", expand=True, side="left")
        
        # ...

        yscroll = ttk.Scrollbar(logf, command=self.txt.yview)
        yscroll.pack(side="right", fill="y")
        self.txt.configure(yscrollcommand=yscroll.set)

        self.txt.tag_configure("INFO", foreground="black")
        self.txt.tag_configure("WARNING", foreground="#d98400")
        self.txt.tag_configure("ERROR", foreground="#c00000")

        # ---- Right panel (cameras) ----
        cam_box = ttk.LabelFrame(right, text="Last Truck Snap", padding=8)
        cam_box.pack(fill="both", expand=True)

        self.cam_tiles = {}
        self.lane_frames = {} 
        idx = 0
        
        for lane_idx in range(self.total_lanes):
            lane_num = lane_idx + 1
            
            # Create Lane Group (Fixed Title)
            lane_frame = ttk.LabelFrame(cam_box, text=f"LANE_{lane_num}", padding=5)
            lane_frame.pack(fill="x", expand=True, padx=5, pady=5, anchor="n") 
            # Force Equal Height for Lanes? User said "Right UI height equal".
            # pack(expand=True) makes them share vertical space.
            self.lane_frames[lane_num] = lane_frame
            
            # Configure Grid for Lane Frame (1 row, 4 cols)
            lane_frame.rowconfigure(0, weight=1) # Ensure row expands
            for c in range(4):
                lane_frame.columnconfigure(c, weight=1, uniform="lanecols")
                
                if idx < len(self.display_channels):
                    ch = self.display_channels[idx]
                    idx += 1
                    
                    # Create Tile
                    tile = ttk.Frame(lane_frame, relief="solid", borderwidth=1)
                    tile.grid(row=0, column=c, sticky="nsew", padx=4, pady=4)
                    
                    # Force tile to have some minimum height/aspect?
                    # The image render will push layout.
                    tile.rowconfigure(0, weight=1)
                    tile.columnconfigure(0, weight=1)
                    
                    # Content
                    lbl = ttk.Label(tile)
                    lbl.grid(row=0, column=0, sticky="nsew")
                    lbl.configure(anchor="center")
                    
                    # Caption Logic (Simplified)
                    # "Status 901 : Connected (age 0.0s)"
                    
                    # Initial Text
                    cap = ttk.Label(tile, text=f"Status {ch} : -", font=("Segoe UI", 8))
                    cap.grid(row=1, column=0, sticky="w", padx=4, pady=(2, 0))
                    
                    # Store
                    self.cam_tiles[ch] = {"label": lbl, "caption": cap, "img": None}
                else:
                    # Placeholder (Should not happen if display_channels matches logic)
                    pass

    def _start_all(self):
        self.append_log("INFO", f"Starting UI. Factory={self.factory} total_lanes={self.total_lanes}")
        self.orch.start()
        self.orch.start_realtime()

        if self.cam_mgr is None:
            # RTSP CONFLICT FIX: UI does NOT open cameras.
            # self.cam_mgr = CameraManager(self._rtsp_base(), self.display_channels, self.ui_cam_q, detector=self._detection_callback)
            pass
        
        # self.cam_mgr.start()
        self.cam_running = True
        # self.btn_toggle.configure(text="Stop Orchestration") # Removed as stop button is gone

    def _stop_all(self):
        self.append_log("INFO", "Stopping Orchestration...")
        try:
            self.orch.stop()
            self.orch.stop_realtime()
        except Exception:
            pass
        try:
            if self.cam_mgr:
                self.cam_mgr.stop()
        except Exception:
            pass
        self.cam_running = False
        # self.btn_toggle.configure(text="Start Orchestration") # Removed as stop button is gone
        
        # Cleanup any open CV windows
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

    # def _on_toggle(self): ... REMOVED

    def _update_status_loop(self):
        """Update uptime, memory, CPU."""
        if not self.cam_running:
             # If stopped, just loop slowly
             self.after(1000, self._update_status_loop)
             return

        # ... (Rest of status loop is same, omitted for brevity if no changes)
        # Actually I need to replace the grid logic which is in __init__.
        # Wait, the previous tool call modified __init__ lines 70-160.
        # The grid setup is around line 520.
        pass

    def _camera_grid(self):
        """
        Return (rows, col)
        New Logic: Rows = Total Lanes, Cols = 2 (LPR + Sugarcane)
        """
        return self.total_lanes, 2


        """Update system status indicator (Uptime/Color)."""
        if self.shutting_down:
            return

        # Calculate Uptime
        uptime_sec = int(time.time() - self.system_start_time)
        uptime_str = str(timedelta(seconds=uptime_sec))
        
        # Color Logic
        bg_color = "#4CAF50" # Green (Normal)
        if self.status_state == "YELLOW":
            bg_color = "#FFC107" # Amber
        elif self.status_state == "RED":
            bg_color = "#F44336" # Red
            
        # Text Logic
        if self.status_state == "GREEN":
            msg = f"System OK | Uptime: {uptime_str}"
        else:
            msg = self.status_msg # Show specific message for Yellow/Red
            
        # Update UI
        try:
            self.lbl_status.config(text=msg, bg=bg_color)
        except:
            pass
            
        # Schedule next update (1s)
        self.after(1000, self._update_status_loop)

    def set_system_error(self, msg):
        """Set system to RED state with error message."""
        self.status_state = "RED"
        self.status_msg = f"Error: {msg}"
        self.logger.error(f"System Error State: {msg}")

    def _on_click_update(self):
        """Trigger background update check."""
        if self.status_state == "YELLOW":
             return # Already updating
             
        if messagebox.askyesno("Update System", "Check for updates now? \n(System will restart automatically if found)"):
            self.status_state = "YELLOW"
            self.status_msg = "Checking for updates..."
            self.append_log("INFO", "Starting Background Update Check...")
            
            # Run in thread
            threading.Thread(target=self._check_git_update).start()

    def _check_git_update(self):
        """Run git pull in background."""
        try:
            # 1. Fetch
            subprocess.run(["git", "fetch", "origin"], cwd=self.paths.project_root, check=True, capture_output=True)
            
            # 2. Check status
            # git status -uno
            res = subprocess.run(["git", "status", "-uno"], cwd=self.paths.project_root, capture_output=True, text=True)
            
            if "behind" in res.stdout:
                self.status_msg = "Update Found! Downloading..."
                self.append_log("INFO", "New version found. Pulling changes...")
                
                # 3. Pull
                pull_res = subprocess.run(["git", "pull"], cwd=self.paths.project_root, capture_output=True, text=True)
                
                if pull_res.returncode == 0:
                    self.status_msg = "Update Applied! Restarting..."
                    self.append_log("INFO", "Update Successful! Restarting in 3 seconds...")
                    time.sleep(3)
                    self._restart_application()
                else:
                     self.set_system_error(f"Git Pull Failed: {pull_res.stderr}")
            else:
                self.status_state = "GREEN"
                self.status_msg = "System Normal"
                self.append_log("INFO", "System is already up to date.")
                
        except Exception as e:
            self.set_system_error(f"Update Check Failed: {e}")

    def _restart_application(self):
        """Restart the app via exit code 100 (monitor handles restart)."""
        self.shutting_down = True

        self.logger.info("Restarting Application (Exit Code 100)...")
        # And ensure the exit code is passed to the batch script
        os._exit(100)

    def _on_click_monitor(self):
        """Toggle monitor flag for run_realtime.py to pick up."""
        flag_path = os.path.join(self.paths.project_root, "monitor_active.txt")
        if self.show_monitor.get():
            # Create flag
            try:
                with open(flag_path, "w") as f:
                    f.write("active")
            except Exception as e:
                self.logger.error(f"Failed to set monitor flag: {e}")
        else:
            # Remove flag
            if os.path.exists(flag_path):
                try:
                    os.remove(flag_path)
                except Exception as e:
                    self.logger.error(f"Failed to remove monitor flag: {e}")

    def _on_trigger_cloud_sync(self):
        if not self.orch: return
        self.orch.trigger_agent_now()



    def _on_click_test_upload(self):
        """Manually trigger Data Sync (Upload to GDrive)."""
        # Removed confirmation dialog as requested
        try:
            self.append_log("INFO", "Manually Triggering Data Sync... (Please Wait)")
            
            # Run in thread to not block UI
            def _run_sync():
                try:
                    script_path = os.path.join(self.paths.project_root, "source", "run_data_sync.py")
                    # Run sync script in TEST MODE (Force Upload)
                    res = subprocess.run([sys.executable, script_path, "--test"], capture_output=True, text=True)
                    
                    # Log STDOUT (for debug info)
                    if res.stdout:
                        self.append_log("INFO", f"Sync Log: {res.stdout.strip()}")

                    if res.returncode == 0:
                        self.append_log("INFO", "Upload Process Finished.")
                    else:
                        self.append_log("ERROR", f"Upload Failed! (Code {res.returncode})")
                        self.append_log("ERROR", f"Details: {res.stderr}")
                except Exception as e:
                    self.append_log("ERROR", f"Manual Sync Error: {e}")
            
            threading.Thread(target=_run_sync).start()
            
        except Exception as e:
            self.append_log("ERROR", f"Failed to modify upload trigger: {e}") 

    def update_orch_status(self, st: dict):
        def fmt_dt(d):
            return "-" if not d else d.strftime("%Y-%m-%d %H:%M:%S")

        if st.get("realtime_running", False):
            pid = st.get("realtime_pid", "?")
            self.var_rt.set(f"run_realtime: Running (PID {pid})")
        else:
            self.var_rt.set("run_realtime: Stopped")

        if st["daily_is_running"]:
            self.var_daily.set("run_ai_daily: Running...")
        else:
            self.var_daily.set(
                f"run_ai_daily: Last={fmt_dt(st['daily_last_run'])} rc={st['daily_last_rc'] if st['daily_last_rc'] is not None else '-'} next={fmt_dt(st['daily_next_run'])}"
            )

        if st["agent_is_running"]:
            self.var_agent.set("agent: Running...")
        else:
            self.var_agent.set(
                f"agent: Last={fmt_dt(st['agent_last_run'])} rc={st['agent_last_rc'] if st['agent_last_rc'] is not None else '-'}"
            )

    def _camera_ui_pump(self):
        # Fix UI Freeze: Process max N events per tick
        MAX_EVENTS = 20
        count = 0
        
        try:
            while count < MAX_EVENTS:
                try:
                    msg = self.ui_cam_q.get_nowait()
                except queue.Empty:
                    break
                
                count += 1
                kind = msg[0]

                if kind == "STATUS":
                    _, ch, _, _ = msg # Extract ch from msg
                    if self.cam_mgr:
                        status, age = self.cam_mgr.get_status(ch)
                        # Update Tile Caption directly (Right Panel)
                        if ch in self.cam_tiles:
                            meta = self.cam_tiles[ch]
                            # Format: Status 901 : Connected (age 0.0s)
                            new_text = f"Status {ch} : {status} (age {age:.1f}s)"
                            
                            try:
                                # Only configure if changed to reduce flicker (though tk handles this effectively)
                                current_text = meta["caption"].cget("text")
                                if current_text != new_text:
                                    meta["caption"].configure(text=new_text)
                            except Exception as e:
                                self.logger.error(f"Failed to update caption for {ch}: {e}")

                elif kind == "FRAME":
                    _, ch, frame_bgr, _ts = msg
                    
                    # Intercept for Test E2E
                    if self.do_test_snapshot:
                        self.do_test_snapshot = False
                        # Process in a thread to avoid blocking UI pump
                        threading.Thread(target=self._perform_test_e2e_logic, args=(ch, frame_bgr.copy())).start()
                    
                    if self.show_monitor.get():
                        # External Window Mode
                        win_name = f"Camera {ch}"
                        
                        # Resize to 480p fixed height
                        h, w = frame_bgr.shape[:2]
                        if h > 0 and w > 0:
                            try:
                                scale = 480.0 / float(h)
                                new_w = int(w * scale)
                                if new_w > 0:
                                    resized = cv2.resize(frame_bgr, (new_w, 480))
                                    cv2.imshow(win_name, resized)
                                else:
                                    cv2.imshow(win_name, frame_bgr)
                            except Exception:
                                # Fallback if resize fails
                                cv2.imshow(win_name, frame_bgr)
                        else:
                             cv2.imshow(win_name, frame_bgr)
                             
                        cv2.waitKey(1)
                        
                        # Set static status text on UI tile
                        if ch in self.cam_tiles:
                             lbl = self.cam_tiles[ch]["label"]
                             lbl.configure(image="", text="[ External Monitor Active ]")
                             self.cam_tiles[ch]["img"] = None
                    else:
                        # Close individual window if open
                        try:
                            cv2.destroyWindow(f"Camera {ch}")
                        except Exception:
                            pass
                        
                        # If we have a cached last snap, do NOT overwrite with text placeholder continuously
                        if ch not in self.latest_snap_paths:
                            # Fallback Logic: Update 1 frame per minute
                            now = time.time()
                            last = self.last_fallback_ts.get(ch, 0.0)
                            
                            # If never shown (0.0) or elapsed > 20s
                            if now - last >= 20.0:
                                self.last_fallback_ts[ch] = now
                                # Render this frame as fallback
                                if ch in self.cam_tiles:
                                    # Ensure 480p resize for consistency logic (though render_tile handles fit)
                                    # Just utilize _render_tile_image directly
                                    # NOTE: _render_tile_image calls letterbox, so it fits nicely.
                                    # We just need to update the text to say "Live Preview"
                                    
                                    try:
                                        self._render_tile_image(ch, frame_bgr)
                                        lbl = self.cam_tiles[ch]["label"]
                                        # Overlay text? Or render tile image clears text.
                                        # Let's set the text to empty to show image, 
                                        # but maybe we want a caption?
                                        # The caption label is separate (CAM_101).
                                        # Let's just show the image. User requirement: "default pull image 1 min/frame 480p"
                                        pass
                                    except Exception:
                                        pass
                            
                            # If we still have NO image (startup and haven't hit trigger), show placeholder
                            if ch in self.cam_tiles and self.cam_tiles[ch]["img"] is None:
                                 lbl = self.cam_tiles[ch]["label"]
                                 lbl.configure(image="", text="[ Waiting for Truck... ]")

        except Exception as e:
            self.set_system_error(f"Camera UI Error: {e}")
            self.append_log("ERROR", f"Camera pump error: {e}")

        # Schedule next pump
        # 30ms delay (~33FPS) is much safer for Tkinter/Windows loop than 1ms
        self.after(30, self._camera_ui_pump)

    def _resize_aspect_fill(self, image, target_w, target_h):
        """Resize image to fill target area (Aspect Fill / Center Crop)."""
        if image is None: return None
        h, w = image.shape[:2]
        if w == 0 or h == 0: return None
        
        # Calculate scale to cover the target
        scale_w = target_w / w
        scale_h = target_h / h
        scale = max(scale_w, scale_h)
        
        new_w = int(w * scale)
        new_h = int(h * scale)
        
        # Resize
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        # Center Crop
        x = (new_w - target_w) // 2
        y = (new_h - target_h) // 2
        
        # Ensure bounds
        x = max(0, x)
        y = max(0, y)
        
        cropped = resized[y : y + target_h, x : x + target_w]
        
        # Convert to RGB
        return cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)

    def _render_tile_image(self, ch: int, frame_bgr):
        """Helper to actally render an BGR image to the tile (replaces old _render_frame)"""
        tile = self.cam_tiles.get(ch)
        if not tile:
            return

        lbl = tile["label"]
        w = max(320, lbl.winfo_width())
        # Force 16:9 Aspect Ratio
        h = int(w * 9 / 16)

        # Use Aspect Fill instead of Letterbox
        rgb = self._resize_aspect_fill(frame_bgr, w, h)
        if rgb is None:
            return

        img = Image.fromarray(rgb)
        tk_img = ImageTk.PhotoImage(img)
        tile["img"] = tk_img  # keep ref
        lbl.configure(image=tk_img, text="") # clear text



    def append_log(self, level: str, msg: str):
        def _append():
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"{ts} | {level:<7} | {msg}\n"
            self.txt.insert("end", line, (level,))
            self.txt.see("end")

        try:
            self.after(0, _append)
        except Exception:
            pass

    def _on_click_test_e2e(self):
        """Enable flag to capture next frame for E2E testing."""
        self.logger.info("Manual E2E Test Initiated. Waiting for camera frame...")
        self.do_test_snapshot = True
        self.append_log("INFO", "Test E2E Started... Waiting for camera frame.")

    def _perform_test_e2e_logic(self, ch, frame):
        """
        Delegates to SystemTester.
        """
        try:
            from .tester import SystemTester
            tester = SystemTester(self.paths, self.cfg, self.logger, self.factory, self.total_lanes)
            
            # Run Test (Blocking call, run in thread preferably, but for test it's ok)
            success, logs = tester.run_e2e_test(ch, frame)
            
            # Output Logs to UI
            for line in logs:
                level = "INFO"
                if "ERROR" in line: level = "ERROR"
                elif "WARNING" in line: level = "WARNING"
                self.append_log(level, line)

        except Exception as e:
            self.logger.error(f"Test E2E Failed: {e}")
            self.append_log("ERROR", f"Test E2E Failed: {e}")

    def on_close(self):
        self.close_attempts += 1
        remain = 3 - self.close_attempts
        if remain > 0:
            messagebox.showwarning(
                "Confirm Exit",
                f"ระบบกำลังทำงานอยู่\nกรุณากดปิดอีก {remain} ครั้งเพื่อยืนยันการปิดโปรแกรม",
            )
            return

        try:
            self._stop_all()
            time.sleep(0.2)
        except Exception:
            pass
        os._exit(0)


def main():
    # Fix Taskbar Icon Grouping (Must run before Tk init)
    try:
        import ctypes
        myappid = 'ocs.ai_sugarcane_installer.v1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
