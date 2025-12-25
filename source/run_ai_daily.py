import os
import sys
import cv2
import configparser
import logging
import shutil
import pandas as pd
import numpy as np
import pytz
from datetime import datetime
from collections import defaultdict
from ultralytics import YOLO
from PIL import ImageFont, ImageDraw, Image

# ================= SETUP LOGGING =================
# Setup logging to file and stdout
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, "run_ai_daily.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

log = logging.getLogger("run_ai_daily")

# Import LPREngine
try:
    from source.lpr_engine import LPREngine
except ImportError:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.append(os.path.join(BASE_DIR, "source"))
    from lpr_engine import LPREngine

# ================= CONFIGURATION =================
CONFIG_PATH = os.path.join(BASE_DIR, "config.txt")
if not os.path.exists(CONFIG_PATH):
    log.error(f"Config file not found: {CONFIG_PATH}")
    sys.exit(1)

config = configparser.ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8")

# Force project root
PROJECT_ROOT = config["DEFAULT"].get("PROJECT_ROOT", BASE_DIR)

# LPR Config
CONF_TH = float(config["DEFAULT"].get("lpr_confidence", "0.7"))
USE_GPU = config["DEFAULT"].get("lpr_use_gpu", "false").lower() == "true"

# Paths
# Configurable paths
_img_cfg = config["DEFAULT"].get("images_path", "")
_res_cfg = config["DEFAULT"].get("results_path", "")

if _img_cfg and os.path.isabs(_img_cfg):
    PATH_IMAGES = _img_cfg
elif _img_cfg:
    PATH_IMAGES = os.path.join(PROJECT_ROOT, _img_cfg)
else:
    PATH_IMAGES = os.path.join(PROJECT_ROOT, "Images")

if _res_cfg and os.path.isabs(_res_cfg):
    PATH_RESULTS = _res_cfg
elif _res_cfg:
    PATH_RESULTS = os.path.join(PROJECT_ROOT, _res_cfg)
else:
    PATH_RESULTS = os.path.join(PROJECT_ROOT, "Results")

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "font.ttf")

os.makedirs(PATH_RESULTS, exist_ok=True)
os.makedirs(PATH_IMAGES, exist_ok=True)

# Suppress YOLO logs
# ================= DATABASE SETUP =================
try:
    from source.database import DatabaseManager
except ImportError:
    sys.path.append(os.path.join(BASE_DIR, "source"))
    from source.database import DatabaseManager

db_path = config["DEFAULT"].get("db_path", "sugarcane.db")
if not os.path.isabs(db_path):
    db_path = os.path.join(PROJECT_ROOT, db_path)

db = DatabaseManager(db_path, logger=log)

# ================= CONSTANTS & MAPPINGS =================
YOLO_CLASS = [
    "burn-clean",
    "burn-trash",
    "fresh-clean",
    "fresh-trash",
    "other",
]

# User Requested 0, 1, 2, 3, 4
CANE_TYPE_DICT = {
    "burn-clean": 0,
    "burn-trash": 1,
    "fresh-clean": 2,
    "fresh-trash": 3,
    "other": 4,
}

CLASS_TO_THAI = {
    "burn-clean": "อ้อยไฟไหม้-สะอาด",
    "burn-trash": "อ้อยไฟไหม้-สกปรก",
    "fresh-clean": "อ้อยสด-สะอาด",
    "fresh-trash": "อ้อยสด-สกปรก",
    "other": "ไม่สามารถจำแนกได้",
}

LANE_CAMERAS = {
    1: [101, 201, 301, 401],
    2: [501, 601, 701, 801],
    3: [901, 1001, 1101, 1201],
    4: [1301, 1401, 1501, 1601],
}

# The 3rd camera in the list (index 2) is used for classification
CLASS_CAM_INDEX = 2 

# Reverse mapping: Camera Code -> Lane
CAM_TO_LANE = {code: lane for lane, codes in LANE_CAMERAS.items() for code in codes}

# Confidence storage
pred_cls_conf = {name: [] for name in YOLO_CLASS}


# ================= LOAD MODEL =================
try:
    MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "classification.pt")
    if not os.path.exists(MODEL_PATH):
         # Try local path relative to script
         MODEL_PATH = os.path.join(BASE_DIR, "models", "classification.pt")
         
    log.info(f"Loading model from: {MODEL_PATH} (GPU={USE_GPU})")
    model_cls = YOLO(MODEL_PATH)
    
    # Load LPR Engine
    # Note: run_ai_daily can use GPU if available and configured
    model_lpr_path = os.path.join(PROJECT_ROOT, "models", "objectdetection.pt")
    log.info(f"Loading LPR Engine from: {model_lpr_path} (GPU={USE_GPU})")
    lpr_engine = LPREngine(model_path=model_lpr_path, conf_th=CONF_TH, logger=log, use_gpu=USE_GPU)
    
    # Map model indices to names
    MODEL_NAMES = model_cls.names
    YOLO_INDEX_TO_NAME = dict(MODEL_NAMES) if isinstance(MODEL_NAMES, dict) else {i: n for i, n in enumerate(MODEL_NAMES)}
    
except Exception as e:
    log.critical(f"Failed to load YOLO model: {e}")
    sys.exit(1)


# ================= HELPER FUNCTIONS =================

def parse_filename(fname):
    """
    Parses filenames like: 20250205-002517_S09_501_80-8624.jpg
    Returns: (dt_str, factory, lane, cam_code, plate) or None
    """
    stem = os.path.splitext(fname)[0]
    parts = stem.split("_")
    if len(parts) < 3:
        return None

    dt_str = parts[0]
    factory = parts[1]
    cam_str = parts[2]
    # plate = parts[3] if len(parts) >= 4 else None 
    # New logic: Plate is NOT in filename anymore
    plate = None

    try:
        cam_code = int(cam_str)
    except ValueError:
        return None

    lane = CAM_TO_LANE.get(cam_code)
    if lane is None:
        return None

    return dt_str, factory, lane, cam_code, plate

def get_center_square_crop(image):
    """
    Crops the center square of the image.
    """
    h, w, _ = image.shape
    new_size = min(h, w)
    
    x1 = (w - new_size) // 2
    y1 = (h - new_size) // 2
    x2 = x1 + new_size
    y2 = y1 + new_size
    
    return image[y1:y2, x1:x2]

def classify_image(image):
    """
    Runs YOLO classification on the image.
    Returns: (top_class_name, confidence_details_dict)
    """
    device = 0 if USE_GPU else "cpu"
    results = model_cls(image, verbose=False, device=device)
    r = results[0]
    
    model_index = int(r.probs.top1)
    raw_name = YOLO_INDEX_TO_NAME.get(model_index, "other")
    
    # Normalize class name
    top_name = raw_name if raw_name in YOLO_CLASS else "other"
    
    # Extract scores
    scores = r.probs.data.tolist()
    detail = {name: 0.0 for name in YOLO_CLASS}
    
    for i, score in enumerate(scores):
        n = YOLO_INDEX_TO_NAME.get(i, "other")
        if n not in YOLO_CLASS: 
            n = "other"
        detail[n] = max(detail[n], float(score))
        
    return top_name, detail

def create_merged_image(group_key, recs, expected_cams, map_cam_path, dt_str, factory, lane, plate, cls_name):
    """
    Creates a 2x2 grid of images with a header text.
    Returns the merged image (numpy array).
    """
    # Load 4 images
    imgs = []
    base_w, base_h = 1280, 720
    
    for cam_code in expected_cams:
        if cam_code in map_cam_path and os.path.exists(map_cam_path[cam_code]):
            img = cv2.imread(map_cam_path[cam_code])
            if img is not None:
                imgs.append(cv2.resize(img, (base_w, base_h)))
            else:
                # Black placeholder
                imgs.append(np.zeros((base_h, base_w, 3), dtype=np.uint8))
        else:
            # Black placeholder
            imgs.append(np.zeros((base_h, base_w, 3), dtype=np.uint8))

    row1 = np.hstack((imgs[0], imgs[1]))
    row2 = np.hstack((imgs[2], imgs[3]))
    merged = np.vstack((row1, row2))

    # Add Header
    text = f"{dt_str} | {factory}-L{lane} | {plate} | {cls_name}"
    text_height = 160
    font_size = 70

    header = np.zeros((text_height, merged.shape[1], 3), dtype=np.uint8)
    pil_image = Image.fromarray(cv2.cvtColor(header, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_image)

    try:
        font = ImageFont.truetype(FONT_PATH, font_size)
    except:
        font = ImageFont.load_default()

    # Center text
    try:
         text_bbox = draw.textbbox((0, 0), text, font=font)
         text_w = text_bbox[2] - text_bbox[0]
         text_h = text_bbox[3] - text_bbox[1]
    except AttributeError:
         # Fallback for older PIL
         text_w, text_h = draw.textsize(text, font=font)
         
    text_x = (header.shape[1] - text_w) // 2
    text_y = (text_height - text_h) // 2

    draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255))
    header_with_text = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    
    return np.vstack((header_with_text, merged))

# ================= MAIN LOGIC =================
def main():
    log.info("Started Daily AI Processing...")
    
    # --- Step 1: Scan Images ---
    files = [f for f in os.listdir(PATH_IMAGES) if os.path.isfile(os.path.join(PATH_IMAGES, f))]
    records = []
    
    for fname in files:
        parsed = parse_filename(fname)
        if parsed is None:
            continue
            
        dt_str, factory, lane, cam_code, plate = parsed
        records.append({
            "full_path": os.path.join(PATH_IMAGES, fname),
            "filename": fname,
            "dt_str": dt_str,
            "factory": factory,
            "lane": lane,
            "cam_code": cam_code,
            "plate": plate
        })
        
    if not records:
        log.info("No valid images found to process.")
        sys.exit(0)
        
    log.info(f"Found {len(records)} images.")
    
    # --- Step 2: Grouping ---
    groups = defaultdict(list)
    for rec in records:
        key = (rec["dt_str"], rec["factory"], rec["lane"])
        groups[key].append(rec)
        
    sorted_keys = sorted(groups.keys())
    log.info(f"Processing {len(sorted_keys)} truck groups...")
    
    # --- Step 3: Prepare Results Dir ---
    current_time = datetime.now(pytz.timezone("Asia/Bangkok"))
    folder_timestamp = current_time.strftime("%Y%m%d %H%M")
    
    # Make subfolders
    res_dir = os.path.join(PATH_RESULTS, folder_timestamp)
    for sub in ["ai_images", "raw_images", "incomplete", "classification"]:
        os.makedirs(os.path.join(res_dir, sub), exist_ok=True)
        
    # --- Step 4: Process Groups ---
    # DataFrame lists
    data_out = {
        "Name": [], "Path": [], "AI result": [], "License plate": [],
        "Date": [], "Time": [], "Lane": [], "Cane_type": [], "pred_cls": []
    }
    
    cnt_success = 0
    cnt_incomplete = 0
    
    for i, key in enumerate(sorted_keys, 1):
        dt_str, factory, lane = key
        recs = groups[key]
        
        # Check completeness
        cam_map = {r["cam_code"]: r for r in recs}
        valid_cam_paths = {code: r["full_path"] for code, r in cam_map.items()}
        expected_cams = LANE_CAMERAS.get(lane, [])
        
        # Determine Plate
        plate = next((r["plate"] for r in recs if r["plate"]), "Cannot Detected")
        
        # Identify Missing Cams
        missing = [c for c in expected_cams if c not in cam_map]
        
        if missing:
             log.warning(f"Group {key} Missing cams {missing}. Moving to incomplete.")
             for r in recs:
                 shutil.move(r["full_path"], os.path.join(res_dir, "incomplete", r["filename"]))
             cnt_incomplete += 1
             continue
             
        try:
            # Classification
            class_cam_code = expected_cams[CLASS_CAM_INDEX]
            # Fallback if specific class cam logic fails (though we checked missing)
            if class_cam_code not in cam_map:
                raise ValueError(f"Classification camera {class_cam_code} missing")

            class_img_path = cam_map[class_cam_code]["full_path"]
            img_cls = cv2.imread(class_img_path)
            
            if img_cls is None:
                raise ValueError(f"Cannot read classification image: {class_img_path}")
            
            # Crop & Classify
            crop_img = get_center_square_crop(img_cls)
            
            # --- NEW LPR LOGIC ---
            # Try to find a plate from the LPR camera (ending in 01, e.g. 101, 501...)
            # We must find which camera in the expected_cams list is the LPR one.
            # Usually it's the first one? Let's check logic:
            # Lane 1: [101, 201, 301, 401]. 101 is usually LPR. 
            # Lane 2: [501, 601, 701, 801]. 501 is LPR.
            # Pattern: ends with 01.
            
            plate_text = "Cannot Detected"
            lpr_cam_code = None
            
            # Find candidate LPR cam
            for code in expected_cams:
                if str(code).endswith("01"):
                    lpr_cam_code = code
                    break
            
            if lpr_cam_code and lpr_cam_code in cam_map:
                lpr_img_path = cam_map[lpr_cam_code]["full_path"]
                lpr_img_bgr = cv2.imread(lpr_img_path)
                if lpr_img_bgr is not None:
                     res = lpr_engine.detect(lpr_img_bgr)
                     if res and res.text:
                         plate_text = res.text
                         log.info(f"LPR Detected: {plate_text} from {lpr_cam_code}")

            plate = plate_text
            
            # Normalize LPR Output per user request
            # "00-0000", "Cannot Detect" -> "NONE"
            if plate in ["Cannot Detected", "Cannot Detect", "00-0000", "000000", ""]:
                plate = "NONE"
            # ---------------------
            
            # Save Debug Crop
            
            # Save Debug Crop
            debug_crop_name = f"{dt_str}_{factory}_L{lane}_CAM{class_cam_code}.jpg"
            cv2.imwrite(os.path.join(res_dir, "classification", debug_crop_name), crop_img)
            
            # AI Inference
            cls_name, conf_map = classify_image(crop_img)
            cls_name_th = CLASS_TO_THAI.get(cls_name, cls_name)
            
            # Save confidence
            pred_cls_conf[cls_name].append(conf_map.get(cls_name, 0.0))
            for k, v in conf_map.items():
                if k != cls_name:
                    pred_cls_conf[k].append(v)

            # Metadata formatting
            try:
                # 20250205-002517
                ts_obj = datetime.strptime(dt_str, "%Y%m%d-%H%M%S")
                date_disp = ts_obj.strftime("%d/%m/%Y")
                time_disp = ts_obj.strftime("%H:%M")
            except:
                date_disp = dt_str
                time_disp = "00:00"

            # Merge Images
            # Use Thai name for display
            merged_img = create_merged_image(key, recs, expected_cams, valid_cam_paths, dt_str, factory, lane, plate, cls_name_th)
            
            basename = f"{dt_str}_{factory}_L{lane}"
            # Filename keeps English class for safety? Or Thai? 
            # Usually filenames are better in English to avoid filesystem issues.
            # Let's keep English in filename, but Thai in CSV/Image Text.
            final_img_name = f"{basename}_{plate}_{cls_name}.jpg"
            final_img_path = os.path.join(res_dir, "ai_images", final_img_name)
            
            # Ensure absolute path for CSV
            abs_final_path = os.path.abspath(final_img_path)
            cv2.imwrite(abs_final_path, merged_img)
            
            # Determine Integer Class
            cane_type_int = CANE_TYPE_DICT.get(cls_name, 4) # Default to 4 (Other) if unknown
            
            # --- UPDATE DB ---
            # run_realtime saved file as "YYYYMMDD-HHMMSS_{FACTORY}.jpg"
            # Our key "dt_str" is "YYYYMMDD-HHMMSS".
            # So "basename" keyword matches the run_realtime file.
            db.update_ai_result(
                old_path_keyword=basename, 
                new_path=abs_final_path, 
                plate=plate, 
                classification=cane_type_int
            )
            # -----------------

            # Collect Data
            data_out["Name"].append(basename)
            data_out["Path"].append(abs_final_path)
            data_out["AI result"].append(cls_name_th)
            data_out["License plate"].append(plate)
            data_out["Date"].append(date_disp)
            data_out["Time"].append(time_disp)
            data_out["Lane"].append(lane)
            data_out["Cane_type"].append(cane_type_int)
            data_out["pred_cls"].append(cls_name)
            
            # Move RAW images
            for r in recs:
                target_raw = os.path.join(res_dir, "raw_images", r["filename"])
                if os.path.exists(r["full_path"]):
                    shutil.move(r["full_path"], target_raw)
            
            cnt_success += 1
            log.info(f"Processed Group {key} -> {cls_name}")
            
        except Exception as e:
            log.error(f"Error processing group {key}: {e}")
            # Move to incomplete if failed
            for r in recs:
                if os.path.exists(r["full_path"]):
                    shutil.move(r["full_path"], os.path.join(res_dir, "incomplete", r["filename"]))
            cnt_incomplete += 1

    # --- Step 5: Save CSV ---
    if cnt_success > 0:
        df = pd.DataFrame(data_out)
        
        # Create Full DF with conf
        # Fill missing conf entries to match length
        max_len = len(df)
        for k in pred_cls_conf:
             # If list is shorter (due to skipped groups), pad with 0? 
             # Actually we only appended to pred_cls_conf on success. 
             # So lengths should match cnt_success.
             pass

        # Since we might have issue syncing list lengths if logic drifted, 
        # let's rebuild conf_dict strictly aligned with rows.
        # Ideally, we should have stored conf in data_out per row.
        # But to respect existing structure, let's just save Main CSV first.
        
        csv_name = f"{folder_timestamp.split(' ')[0]}-{folder_timestamp.split(' ')[1]}.csv"
        csv_path = os.path.join(res_dir, csv_name)
        df.to_csv(csv_path, index=False)
        
        log.info(f"Saved CSV: {csv_path}")
    else:
        log.warning("No successful groups processed. No CSV generated.")

    log.info(f"Summary: Success={cnt_success}, Incomplete/Failed={cnt_incomplete}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception(f"Critical Failure: {e}")
        sys.exit(1)


