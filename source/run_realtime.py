import os
import sys
import time
import threading
import logging
import configparser

import cv2
import numpy as np
from ultralytics import YOLO

# ----------------------------
# Robust paths (important)
# ----------------------------
# ----------------------------
# Robust paths (important)
# ----------------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(BASE_DIR)  # force CWD = project root
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Force TCP for RTSP to prevent packet loss / gray screens
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

# Import modular components
try:
    from source.lpr_engine import LPREngine
    from source.database import DatabaseManager
    from source.config import load_config
except ImportError as e:
    # Fallback if running from source dir (less likely now, but safe)
    sys.path.append(os.path.join(BASE_DIR, "source"))
    from lpr_engine import LPREngine
    from database import DatabaseManager
    from config import load_config
    logging.warning(f"Import fallback triggered: {e}")


CONFIG_PATH = os.path.join(BASE_DIR, "config.txt")
MODEL_PATH = os.path.join(BASE_DIR, "models", "objectdetection.pt")

# Centralized Config Loading
cp, config_dict = load_config(CONFIG_PATH) # config_dict keys are lowercase
# Wrapper to mimic old behavior if needed, or use config_dict directly.
# The code below uses 'config["DEFAULT"].get(...)'. 
# load_config returns (cp, cfg_dict). cp is the parser.
config = cp

# Factory ID (Check both keys)
FACTORY_ID = config["DEFAULT"].get("factory", config["DEFAULT"].get("factory_id", "UNKNOWN"))

_img_cfg = config["DEFAULT"].get("images_path", "")
if _img_cfg and os.path.isabs(_img_cfg):
    IMAGES_DIR = _img_cfg
elif _img_cfg:
    IMAGES_DIR = os.path.join(BASE_DIR, _img_cfg)
else:
    IMAGES_DIR = os.path.join(BASE_DIR, "Images")

# ----------------------------
# Logging (show + file)
# ----------------------------
LOGFILE = os.path.join(BASE_DIR, "run_realtime.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOGFILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger("ultralytics").setLevel(logging.CRITICAL)

log = logging.getLogger("run_realtime")

# Database Init
DB_PATH = os.path.join(BASE_DIR, "sugarcane.db")
db = DatabaseManager(DB_PATH, logger=log)

# ----------------------------
# Load config
# ----------------------------
config = configparser.ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8-sig")

import torch

FACTORY = config["DEFAULT"].get("factory", "UNKNOWN")
TOTAL_LANES = int(config["DEFAULT"].get("total_lanes", "1"))
CONF_TH = float(config["DEFAULT"].get("lpr_confidence", "0.7"))

# GPU Auto-Detection Logic
# 1. Config can be 'true', 'false', 'auto', or missing
# 2. If 'true' -> force True
# 3. If 'false' -> force False
# 4. If 'auto' or missing -> detect torch.cuda
raw_gpu_cfg = config["DEFAULT"].get("lpr_use_gpu", "auto").lower()

if raw_gpu_cfg == "true":
    USE_GPU = True
    gpu_source = "Config (Forced)"
elif raw_gpu_cfg == "false":
    USE_GPU = False
    gpu_source = "Config (Disabled)"
else:
    # Auto-detect
    USE_GPU = torch.cuda.is_available()
    gpu_source = f"Auto-Detect ({'Found' if USE_GPU else 'Not Found'})"

log.info("GPU Configuration: %s | Result: %s", raw_gpu_cfg, "ENABLED" if USE_GPU else "DISABLED")

from urllib.parse import quote

CAMERA_IP = config["NVR1"].get("camera_ip", "")
CAMERA_USERNAME = config["NVR1"].get("camera_username", "")
CAMERA_PASSWORD = config["NVR1"].get("camera_password", "")

# URL Encode credentials to handle special characters (e.g. #, @, :)
safe_user = quote(CAMERA_USERNAME, safe="")
safe_pass = quote(CAMERA_PASSWORD, safe="")

camera_path = f"rtsp://{safe_user}:{safe_pass}@{CAMERA_IP}/Streaming/channels/"
log.info(f"Camera Configuration Loaded: IP={CAMERA_IP}, User={CAMERA_USERNAME}, URL_Base={camera_path.replace(safe_pass, '****')}")

# ----------------------------
# Load Engines
# ----------------------------
if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(
        f"Model not found: {MODEL_PATH}\n"
        f"Please place unencrypted YOLO model file at models/objectdetection.pt"
    )

log.info("Initializing LPR Engine (Conf > %.2f, YOLO Only, GPU=%s)...", CONF_TH, USE_GPU)
# Use LPREngine with GPU config
lpr_engine = LPREngine(model_path=MODEL_PATH, conf_th=CONF_TH, logger=log, ocr_lang="en", use_gpu=USE_GPU)

# ----------------------------
# Globals & Worker
# ----------------------------
LOCALPATH = IMAGES_DIR
os.makedirs(LOCALPATH, exist_ok=True)

# Import and Init Realtime Worker
try:
    from source.realtime_worker import RealtimeWorker
except ImportError:
    sys.path.append(os.path.join(BASE_DIR, "source"))
    from realtime_worker import RealtimeWorker

# Share LPREngine to save memory
rt_worker = RealtimeWorker(CONFIG_PATH, BASE_DIR, lpr_engine=lpr_engine)

# Group Collector Logic
class GroupCollector:
    def __init__(self, lane_id, worker):
        self.lane_id = lane_id
        self.worker = worker
        self.lock = threading.Lock()
        self.active_groups = {} # { timestamp_key: {count: 0, images: {}} }

    def add_image(self, timestamp_key, channel, image_path):
        with self.lock:
            if timestamp_key not in self.active_groups:
                self.active_groups[timestamp_key] = {"count": 0, "images": {}, "created": time.time()}
            
            group = self.active_groups[timestamp_key]
            group["images"][channel] = image_path
            group["count"] += 1
            
            # Check completeness (expect 2 images for Dump Station: Sugarcane + LPR)
            if group["count"] >= 2:
                # Dispatch!
                log.info(f"Group {timestamp_key} (Dump {self.lane_id}) Complete. Enqueuing for Classification.")
                self.worker.enqueue_group(FACTORY, self.lane_id, group["images"])
                del self.active_groups[timestamp_key]
            else:
                 # Check timeout (e.g. if one camera failed)
                 # We can run a separate cleanup or just check here
                 pass

# Initialize collectors per lane
collectors = [GroupCollector(i+1, rt_worker) for i in range(TOTAL_LANES)]

position_tracker = [{} for _ in range(TOTAL_LANES)]
exit_tracker = [{} for _ in range(TOTAL_LANES)]
licenseplate_tracker = [[] for _ in range(TOTAL_LANES)]
check = [False for _ in range(TOTAL_LANES)]
display_text_duration = 3
show_text = [False for _ in range(TOTAL_LANES)]
start_time_show_text = [time.time() for _ in range(TOTAL_LANES)]

camera_status = ["Disconnected" for _ in range(TOTAL_LANES)]
last_snap_time = {}  # Key: slot_index (int), Value: timestamp (float)

# ----------------------------
# LINE notify
# ----------------------------
def send_line_notify(token, message):
    import requests
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"message": message}
    try:
        r = requests.post(url, headers=headers, data=payload, timeout=20)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


def monitor_thread():
    global camera_status
    line_notify_token = config["DEFAULT"].get("line_token", "")
    LOG_FILE = os.path.join(BASE_DIR, "CameraStatusLog.txt")

    while True:
        try:
            current_time = time.time()
            if int(current_time) % 3600 == 0:
                text = time.strftime("%d/%m/%Y - %H:%M:%S\n", time.localtime(current_time))
                for cam_id, status in enumerate(camera_status):
                    text += f"Camera{cam_id + 1} has {status}\n"

                if line_notify_token:
                    send_line_notify(line_notify_token, text)

                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(text)

                # Log to DB
                db.log_system_event("INFO", "CameraMonitor", f"Status Update: {camera_status}")

            time.sleep(1)
        except Exception as e:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"Error in monitor_thread: {e}\n")
            log.exception("monitor_thread error: %s", e)


# ----------------------------
# Main camera worker per lane
# ----------------------------
def Live_process(slot: str):
    def live():
        POSITION_TOLERANCE = 15
        EXIT_TOLERANCE = 15
        SAVE_DURATION = 5

        def is_position_similar(bbox1, bbox2, tolerance=POSITION_TOLERANCE):
            x1_1, y1_1, x2_1, y2_1 = bbox1
            x1_2, y1_2, x2_2, y2_2 = bbox2
            return (
                abs(x1_1 - x1_2) <= tolerance
                and abs(y1_1 - y1_2) <= tolerance
                and abs(x2_1 - x2_2) <= tolerance
                and abs(y2_1 - y2_2) <= tolerance
            )

        def force_resize(frame, width=1920, height=1080):
            """Resize frame to standard 1080p to save storage/bandwidth."""
            if frame is None: return None
            # Only resize if larger/different to save CPU? 
            # Actually, user wants to Force 1080p (even if 4K).
            # If smaller (e.g. 720p), maybe upscale? Or keep?
            # User requirement implies "Standardization". Let's force it.
            try:
                if frame.shape[1] != width or frame.shape[0] != height:
                    return cv2.resize(frame, (width, height))
            except:
                pass
            return frame

        def detect_wrapper(image):
            """Returns (bbox, text) where text is always None here"""
            res = lpr_engine.detect(image, skip_ocr=True)
            if res:
                return res.bbox, None
            return None, None

        # Get Collector for this lane
        lane_idx_int = int(slot) - 1
        my_collector = collectors[lane_idx_int] if 0 <= lane_idx_int < TOTAL_LANES else None

        def capture_image(channel, snap_key=None):
            def capture():
                # channel e.g. "101", "201"
                cap_test = cv2.VideoCapture(camera_path + channel)
                
                # Check frames
                frames_read = 0
                while cap_test.isOpened():
                    ret, frame = cap_test.read()
                    if not ret or frame is None:
                        break
                    frames_read += 1
                    
                    if frames_read < 5:
                        continue
                        
                    # --- OPTIMIZATION: FORCE 1080p ---
                    frame = force_resize(frame)
                    # ---------------------------------

                    # Try detection
                    bbox, plate_text = None, None
                    # Only try to detect on specific cameras to name the file
                    # or if we want to confirm plate
                    is_lpr_cam = (len(channel) == 3 and channel.endswith("01")) # e.g. 101, 201...
                    
                    if is_lpr_cam:
                        bbox, plate_text = detect_wrapper(frame)
                        if bbox is None:
                            # Try crop center if full frame failed (legacy logic)
                            h, w, _ = frame.shape
                            crop = frame[h//10 : h - h//10, w//10 : w - w//10]
                            crop = cv2.resize(crop, (w, h))
                            bbox, plate_text = detect_wrapper(crop)

                    # Use snap_key (filename) passed from trigger
                    safe_fn = snap_key if snap_key else filename # fallback to global filename
                    
                    # Save WITHOUT plate text (Plate text added by helper/worker if needed)
                    # Format: YYYYMMDD-HHMMSS_FACTORY_S01_101.jpg
                    full_path = os.path.join(LOCALPATH, f"{safe_fn}_{channel}.jpg")
                    cv2.imwrite(full_path, frame)
                    
                    # Notify Collector
                    if my_collector and snap_key:
                        my_collector.add_image(snap_key, channel, full_path)

                    break
                
                cap_test.release()
            
            threading.Thread(target=capture, daemon=True).start()
        
        # ---------------------------
        # Buffer Snapshot Logic (Hourly)
        # ---------------------------
        factory_val = FACTORY_ID
        BUFFER_DIR = os.path.join(BASE_DIR, "buffer_images")
        os.makedirs(BUFFER_DIR, exist_ok=True)
            
        def capture_buffer_snapshot(channel):
            # User Requirement: "One image per Lane" -> Filter for x01 cam only
            if not channel.endswith("01"):
                return

            def _snap():
                # State Persistence: Prevent double capture in same hour (even after restart)
                state_file = os.path.join(BUFFER_DIR, f"state_buffer_last_{channel}.txt")
                current_ts_day = time.strftime("%Y%m%d")
                current_ts_hr = time.strftime("%H")
                current_hour_key = f"{current_ts_day}_{current_ts_hr}"
                
                # Check Last Capture
                if os.path.exists(state_file):
                    try:
                        with open(state_file, "r") as f:
                            last_key = f.read().strip()
                        if last_key == current_hour_key:
                            # Already captured this hour
                            return
                    except:
                        pass # proceed if read error

                # Proceed to Capture
                cap_buf = cv2.VideoCapture(camera_path + channel)
                frames_read = 0
                while cap_buf.isOpened():
                    ret, frame = cap_buf.read()
                    if not ret: break
                    frames_read += 1
                    # Skip a few frames
                    if frames_read < 10: continue

                    # --- FORCE 1080p ---
                    frame = force_resize(frame)
                    # -------------------
                    
                    try:
                        lane_id = int(channel) // 100
                    except:
                        lane_id = "X"
                    
                    # Filename: {day}_{hr}_{factory_id}_{lend}_{cam}.png
                    # Example: 20251217_13_S60_L1_101.png
                    fn = f"{current_hour_key}_{factory_val}_L{lane_id}_{channel}.png"
                    
                    target_path = os.path.join(BUFFER_DIR, fn)
                    cv2.imwrite(target_path, frame)
                    
                    # Update State
                    try:
                        with open(state_file, "w") as f:
                            f.write(current_hour_key)
                    except Exception as e:
                        logging.error(f"Failed to update buffer state: {e}")
                    
                    break
                
                cap_buf.release()
                    

            
            threading.Thread(target=_snap, daemon=True).start()
            
        # Hook for hourly snapshot
        # dBufferSnap will store the channels that need a snapshot
        dBufferSnap = {}
        channels_for_slot = []
        for i in range(4):
            cam_idx = (int(slot) - 1) * 4 + (i + 1)
            camera_channel = f"{cam_idx}01"
            channels_for_slot.append(camera_channel)
            # dBufferSnap[camera_channel] = capture_buffer_snapshot # This was the old way
        
        # Capture images per dump (Sugarcane + LPR)
        dProcess = {}
        # User requested swap:
        # Odd (101, 301, ...) : LPR
        # Even (201, 401, ...) : Sugarcane (AI detection)
        
        dump_id = int(slot)
        ch_lpr = f"{(2 * dump_id - 1)}01"
        ch_sugarcane = f"{(2 * dump_id)}01"
        
        channels_for_slot = [ch_lpr, ch_sugarcane]
        
        for ch in channels_for_slot:
            dProcess[ch] = capture_image
            log.info("Dump: %s | CHANNEL: %s", slot, ch)

        def process_video(camera_path2, slot):
            global camera_status, filename

            slot_index = int(slot) - 1
            if slot_index < 0 or slot_index >= len(position_tracker):
                log.error("Invalid slot: %s", slot)
                return

            def open_camera():
                cap = cv2.VideoCapture(camera_path2)
                while not cap.isOpened():
                    camera_status[slot_index] = "Disconnected"
                    # REDACT PASSWORD for safety if needed, or just log full for debug
                    # Assuming internal factory environment, full logging is helpful.
                    safe_url = camera_path2.replace(CAMERA_PASSWORD, "****") if CAMERA_PASSWORD else camera_path2
                    log.warning("Failed to open camera %s (URL: %s), retrying...", slot, safe_url)
                    time.sleep(5)
                    cap = cv2.VideoCapture(camera_path2)
                return cap

            cap = open_camera()
            log.info("Connected: %s", camera_path2)

            # Timer for 1 FPS loop
            last_process_time = 0.0
            
            # Timer for cooldown after save (replaces wait_time usage)
            last_save_time = 0.0
            
            # --- Hourly Buffer Snapshot State ---
            # Trigger immediately on startup (0) so we have data for the first sync
            last_buffer_snap_time = 0
            BUFFER_INTERVAL = 3600
            
            last_live_view_time = 0
            last_status_update = 0

            # ---------------------------
            # Secondary Camera Poller (Background)
            # ---------------------------
            # Purpose: Fetch Live View for the NON-MAIN cameras (e.g. 201, 301, 401) every 10s
            # The Main Camera (101) is handled by the main loop.
            def _secondary_poller():
                while True:
                    try:
                        time.sleep(10) # 10s interval
                        
                        # Identify Main Channel
                        # camera_path2 ends with "101" usually.
                        main_ch_suffix = camera_path2[-3:] # "101"
                        
                        BUFFER_DIR = os.path.join(BASE_DIR, "buffer_images")
                        
                        for ch in dProcess.keys():
                            if str(ch) == main_ch_suffix:
                                continue # Skip Main (Already Handled)
                                
                            # Fetch Snapshot
                            try:
                                # Use global camera_path
                                # RTSP URL construction
                                sub_url = f"{camera_path}{ch}" 
                                
                                # Quick Snap
                                sub_cap = cv2.VideoCapture(sub_url)
                                if sub_cap.isOpened():
                                    ret_sub, frame_sub = sub_cap.read()
                                    if ret_sub and frame_sub is not None:
                                        # Resize 640x360
                                        lv = cv2.resize(frame_sub, (640, 360))
                                        path = os.path.join(BUFFER_DIR, f"live_view_{ch}.jpg")
                                        cv2.imwrite(path, lv)
                                        
                                        # Also write status
                                        st_file = os.path.join(BUFFER_DIR, f"status_{ch}.json")
                                        with open(st_file, "w") as f:
                                            import json
                                            json.dump({"status": "Connected", "ts": time.time()}, f)
                                    else:
                                        # Write Error Status if open but no frame?
                                        pass
                                    sub_cap.release()
                                else:
                                    # Status Error
                                    pass
                            except Exception as e:
                                log.error(f"Poller Error {ch}: {e}")
                                
                    except Exception as e:
                         log.error(f"Poller Crash: {e}")
                         time.sleep(5)

            threading.Thread(target=_secondary_poller, daemon=True).start()

            while cap.isOpened():
                current_time = time.time()
                ret, frame = cap.read()
                
                # -----------------------
                # UI Live View & Status Sync (Heartbeat)
                # -----------------------
                # Write "Connected" status every 5s
                if current_time - last_status_update > 5.0:
                    last_status_update = current_time
                    try:
                        # Use file per channel to be safe: status_{channel}.json
                        # Main camera channel for this slot: (slot-1)*4 + 1 -> e.g. 101
                        # Wait, we need the CURRENT channel status. 
                        # This 'cap' is confusingly 'camera_path2' which is the main cam.
                        # We can just write for the main channel known as 'video_url' passed to process_video?
                        # No, we have 'channels_for_slot'. We should mark THEM as connected?
                        # Actually, this loop ONLY reads the MAIN camera (e.g. 101).
                        # So we only assert status for the main camera.
                         
                         main_cam_ch = f"{((int(slot)-1)*4 + 1)}01" # e.g. 101, 501
                         st_file = os.path.join(BUFFER_DIR, f"status_{main_cam_ch}.json")
                         
                         import json
                         with open(st_file, "w") as f:
                            json.dump({"status": "Connected", "ts": current_time}, f)
                    except Exception:
                        pass
                
                # Save Live View Image every 10s (for UI tiles)
                if current_time - last_live_view_time > 10.0:
                     last_live_view_time = current_time
                     try:
                         # Resize to small for UI (e.g. 640x360)
                         lv_frame = cv2.resize(frame, (640, 360))
                         dump_id = int(slot)
                         main_cam_ch = f"{(2 * dump_id - 1)}01"
                         lv_path = os.path.join(BUFFER_DIR, f"live_view_{main_cam_ch}.jpg")
                         cv2.imwrite(lv_path, lv_frame)
                     except Exception:
                         pass

                # --- Check Hourly Snapshot ---
                # --- Check Hourly Snapshot ---
                if current_time - last_buffer_snap_time > BUFFER_INTERVAL:
                    last_buffer_snap_time = current_time
                    log.info("Triggering Buffer Snapshot for Slot %s...", slot)
                    try:
                        for ch_code in channels_for_slot:
                            capture_buffer_snapshot(ch_code)
                    except Exception as e:
                        log.error(f"Buffer Snap Error: {e}")
                if not ret or frame is None:
                    camera_status[slot_index] = "Error"
                    cap = open_camera()
                    continue

                camera_status[slot_index] = "Connected"
                # frame_number = int(cap.get(cv2.CAP_PROP_POS_FRAMES))

                # Reduce CPU usage
                time.sleep(0.01)
                
                # -----------------------
                # Smart Detection Trigger
                # -----------------------
                monitor_flag_path = os.path.join(BASE_DIR, "monitor_active.txt")
                is_monitor_active = os.path.exists(monitor_flag_path)
                
                # Check if it's time for the 1FPS logic
                is_logic_time = (current_time - last_process_time >= 0.95)
                
                bbox = None
                plate_text = None
                
                # Only run heavy LPR if necessary
                if is_monitor_active or is_logic_time:
                    bbox, plate_text = detect_wrapper(frame)
                    
                    if bbox:
                        # Draw Red Box (BGR: 0, 0, 255)
                        x1, y1, x2, y2 = bbox
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)

                # -----------------------
                # UI Monitor Logic (Proxy)
                # -----------------------
                if is_monitor_active:
                     try:
                         # Resize for display (480p)
                         h, w = frame.shape[:2]
                         scale = 480 / h
                         disp_w = int(w * scale)
                         disp = cv2.resize(frame, (disp_w, 480))
                         
                         win_name = f"Monitor Lane {slot}"
                         cv2.imshow(win_name, disp)
                         cv2.waitKey(1)
                     except:
                         pass
                else:
                     try:
                         # Use strict error handling to avoid clutter
                         import cv2 as cv2_cleanup
                         cv2_cleanup.destroyWindow(f"Monitor Lane {slot}")
                     except:
                         pass

                # -----------------------
                # Optimization: 1 FPS Limit
                # -----------------------
                if not is_logic_time:
                    continue
                
                last_process_time = current_time
                
                # Check cooldown (60s after save) if needed, otherwise detect
                if current_time - last_save_time < 60 and last_save_time > 0:
                    continue
                
                # Detect (Moved UP)
                # bbox, plate_text = detect_wrapper(frame)  <-- REMOVED

                # Show status (Overlay logic)
                if show_text[slot_index] and time.time() - start_time_show_text[slot_index] > display_text_duration:
                    show_text[slot_index] = False

                if bbox:
                    x1, y1, x2, y2 = bbox
                    key = (x1, y1, x2, y2)
                    matched_key = None

                    # Find existing object in tracker
                    for previous_key in list(position_tracker[slot_index].keys()):
                        if is_position_similar(previous_key, key):
                            matched_key = previous_key
                            break
                    
                    if matched_key:
                        # Update key to latest position (optional, but keeping old key prevents drift)
                        # We keep old key for stability
                        # Fix: access "ts" from the dict
                        tracker_entry = position_tracker[slot_index][matched_key]
                        # Handle legacy float if hot-swapping or robust check
                        if isinstance(tracker_entry, dict):
                            start_time = tracker_entry["ts"]
                        else:
                             # Should not happen in new code, but safe fallback
                            start_time = tracker_entry
                        
                        # Check if stable enough to snap
                        if current_time - start_time >= SAVE_DURATION:
                            # Check if already processed (snapped)
                            is_processed = False
                            if isinstance(tracker_entry, dict):
                                is_processed = tracker_entry.get("processed", False)
                            
                            if not is_processed:
                                # Debounce Check: Prevent re-snap within 120s (global lane cooldown)
                                last_snap = last_snap_time.get(slot_index, 0)
                                if current_time - last_snap < 120:
                                    log.info(f"Slot {slot}: Ignored snap (Global Cooldown active)")
                                else:
                                    # SNAP!
                                    log.info(f"Slot {slot}: Stable object verified. Snapping...")
                                    
                                    filename = time.strftime(f"%Y%m%d-%H%M%S_{FACTORY}", time.localtime(current_time))
                                    start_time_show_text[slot_index] = time.time()
                                    show_text[slot_index] = True
                                    
                                    last_snap_time[slot_index] = current_time
                                    last_save_time = current_time

                                    # Trigger capture threads
                                    for ch, fc in dProcess.items():
                                        # Pass filename as snap_key for grouping
                                        threading.Thread(target=fc, args=(str(ch), filename), daemon=True).start()

                                    # Log to DB
                                    # We don't have the plate text or confidence from the main stream detection 
                                    # readily available here unless we dig into matched_key or re-detect.
                                    # For now, we log the snap event.
                                    full_image_path = os.path.join(LOCALPATH, f"{filename}.jpg")
                                    # Note: processing_logs requires: factory_code, lane, image_path...
                                    # We'll use the "Main" filename base.
                                    db.log_processing_result(
                                        factory_code=FACTORY,
                                        lane=slot,
                                        image_path=full_image_path,
                                        plate_number=None, # Filled by LPR later if async
                                        confidence=None
                                    )

                                # MARK AS PROCESSED (Prevent repetitive snaps)
                                position_tracker[slot_index][matched_key]["processed"] = True
                        
                        # Reset exit tracker since object is seen
                        if matched_key in exit_tracker[slot_index]:
                            del exit_tracker[slot_index][matched_key]

                    else:
                        # New Object
                        # Store dict with timestamp and processed flag
                        position_tracker[slot_index][key] = {"ts": current_time, "processed": False}
                        # exit_tracker[slot_index][key] = 0 # Not needed until it's missing

                else:
                    # Logic to clear tracker if object lost for X frames
                    # Iterate over a copy of keys since we might delete
                    for key in list(position_tracker[slot_index].keys()):
                        # Increment exit counter
                        cnt = exit_tracker[slot_index].get(key, 0) + 1
                        exit_tracker[slot_index][key] = cnt
                        
                        if cnt >= EXIT_TOLERANCE:
                            log.info(f"Slot {slot}: Object lost/removed. clearing tracker.")
                            del position_tracker[slot_index][key]
                            del exit_tracker[slot_index][key]

            cap.release()

        # Start monitoring the "LPR" camera for this dump (now ODD channels)
        dump_id = int(slot)
        lpr_cam_idx = 2 * dump_id - 1
        video_url = f"{camera_path}{lpr_cam_idx}01"
        process_video(video_url, slot)

    threading.Thread(target=live, daemon=True).start()


# ----------------------------
# Start all lanes
# ----------------------------
for lane in range(TOTAL_LANES):
    Live_process(str(lane + 1))

threading.Thread(target=monitor_thread, daemon=True).start()

# keep main alive
while True:
    time.sleep(5)
