import os
import sys
import cv2
import numpy as np
import logging
import configparser
from datetime import datetime
from PIL import ImageFont, ImageDraw, Image
from ultralytics import YOLO
import threading
import queue
import time
import shutil

# Import Database
try:
    from database import DatabaseManager
except ImportError:
    sys.path.append(os.path.dirname(__file__))
    from database import DatabaseManager

# Setup Logger
log = logging.getLogger("RealtimeWorker")

class RealtimeWorker:
    def __init__(self, config_path, project_root, lpr_engine=None):
        self.config_path = config_path
        self.project_root = project_root
        self.log = log
        
        # Load Config
        self.config = configparser.ConfigParser()
        self.config.read(config_path, encoding="utf-8-sig") # sig for BOM
        
        # Database
        self.db_path = os.path.join(project_root, "sugarcane.db")
        self.db = DatabaseManager(self.db_path, logger=log)
        
        # Paths
        _res_cfg = self.config["DEFAULT"].get("results_path", "Results")
        if os.path.isabs(_res_cfg):
            self.results_dir = _res_cfg
        else:
            self.results_dir = os.path.join(project_root, _res_cfg)
            
        os.makedirs(self.results_dir, exist_ok=True)
        
        # Models
        self.use_gpu = self.config["DEFAULT"].get("lpr_use_gpu", "false").lower() == "true"
        self.cls_model_path = os.path.join(project_root, "models", "classification.pt")
        
        if not os.path.exists(self.cls_model_path):
             self.cls_model_path = os.path.join(project_root, "..", "models", "classification.pt")
        
        self.cls_model = None
        self._load_models()
        
        # LPR Engine (Can be shared or passed in)
        self.lpr_engine = lpr_engine
        
        # Font
        self.font_path = os.path.join(project_root, "source", "font.ttf")
        if not os.path.exists(self.font_path):
             self.font_path = os.path.join(os.path.dirname(__file__), "font.ttf")

        # Constants
        self.YOLO_CLASS = ["burn-clean", "burn-trash", "fresh-clean", "fresh-trash", "other"]
        self.CLASS_TO_THAI = {
            "burn-clean": "อ้อยไฟไหม้-สะอาด",
            "burn-trash": "อ้อยไฟไหม้-สกปรก",
            "fresh-clean": "อ้อยสด-สะอาด",
            "fresh-trash": "อ้อยสด-สกปรก",
            "other": "ไม่สามารถจำแนกได้",
        }
        self.CANE_TYPE_DICT = {
            "fresh-clean": 1, "fresh-trash": 2, "burn-clean": 3, "burn-trash": 4, "other": 5,
        }
        
        # Processing Queue (path_group list)
        self.queue = queue.Queue()
        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()

    # ... [Keep _load_models, enqueue_group, _worker_loop] ...
    
    # Need to keep these methods intact but re-state them if replace_file range requires it.
    # Actually I used StartLine 1 to re-write imports and init.
    # I should be careful not to delete methods.
    
    # Let me use a smaller target block for imports + __init__.

    def _load_models(self):
        try:
            device = 0 if self.use_gpu else "cpu"
            log.info(f"Loading Classification Model: {self.cls_model_path} (Device={device})")
            self.cls_model = YOLO(self.cls_model_path)
            self.model_names = self.cls_model.names
        except Exception as e:
            log.error(f"Failed to load Classification Model: {e}")

    def enqueue_group(self, factory, lane, images_dict):
        """
        images_dict: { '101': 'path/to/img.jpg', ... }
        """
        self.queue.put({
            "factory": factory,
            "lane": lane,
            "images": images_dict,
            "timestamp": time.time()
        })
        log.info(f"Enqueued group for Lane {lane} ({len(images_dict)} images)")

    def _worker_loop(self):
        log.info("RealtimeWorker loop started.")
        while self.running:
            try:
                task = self.queue.get(timeout=1)
                self._process_task(task)
            except queue.Empty:
                continue
            except Exception as e:
                log.error(f"Worker Loop Error: {e}")

    def _process_task(self, task):
        try:
            factory = task["factory"]
            lane = task["lane"]
            images = task["images"] # Dict {chan: path}
            
            # ... [Identify Candidates logic] ...
            sorted_cams = sorted(images.keys())
            if not sorted_cams: return

            # LPR Cam is now ODD index (e.g. 101), Sugar Cam is EVEN index (e.g. 201)
            lpr_cam = None
            cls_cam = None
            for ch in images.keys():
                # channel is like '101', '201'
                prefix = int(ch) // 100
                if prefix % 2 != 0: # Odd prefix (1, 3, 5...) -> LPR
                    lpr_cam = ch
                else: # Even prefix (2, 4, 6...) -> Sugarcane
                    cls_cam = ch
            
            # If not found by logic, fallback to sorted
            if not lpr_cam or not cls_cam:
                sorted_cams = sorted(images.keys())
                lpr_cam = sorted_cams[0] if sorted_cams else None
                cls_cam = sorted_cams[-1] if sorted_cams else None

            # LPR
            plate_text = "NONE"
            if self.lpr_engine and lpr_cam in images:
                 frame = cv2.imread(images[lpr_cam])
                 if frame is not None:
                     res = self.lpr_engine.detect(frame)
                     if res and res.text:
                         plate_text = res.text
            
            if plate_text in ["00-0000", "", "Cannot Detected"]:
                plate_text = "NONE"

            # Classification
            cls_name = "other"
            if cls_cam in images:
                frame = cv2.imread(images[cls_cam])
                if frame is not None:
                    crop = self._center_crop(frame)
                    cls_name, _ = self._classify(crop)
            
            cls_name_th = self.CLASS_TO_THAI.get(cls_name, cls_name)

            # Merge
            dt_now = datetime.now()
            dt_str = dt_now.strftime("%Y%m%d-%H%M%S")
            
            # _create_merged_image now handles saving and returns (abs_path, day_str)
            final_path, day_str = self._create_merged_image(images, dt_str, factory, lane, plate_text, cls_name_th)
            
            log.info(f"Saved Result: {final_path}")
            
            # DB LOG WITH CLASSIFICATION
            # Use Raw Image for UI Display (Matches Aspect Ratio) if listed, else Final Path
            ui_image_path = images.get(lpr_cam)
            if ui_image_path and not os.path.exists(ui_image_path):
                 ui_image_path = final_path # Fallback
            if not ui_image_path:
                 ui_image_path = final_path

            # Ensure Absolute Path for DB
            if not os.path.isabs(ui_image_path):
                 ui_image_path = os.path.abspath(ui_image_path)
            
            self.db.log_processing_result(
                factory_code=factory,
                lane=lane,
                image_path=ui_image_path, # DB might want to store the Snap or the Merged? 
                                        # UI prefers Snap for tiles.
                                        # But Agent might want Merged?
                                        # Actually Agent creates Base64 from "Path" in CSV.
                                        # Let's save `final_path` to CSV.
                plate_number=plate_text,
                confidence=0.0,
                classification=cls_name_th
            )
            
            # CSV Logging (Agent uses this, OR DB in future)
            self._append_to_csv(day_str, os.path.basename(final_path), final_path, cls_name_th, plate_text, dt_now, lane, cls_name)

        except Exception as e:
            log.error(f"Task Failed: {e}")

    # ... [_classify and _center_crop kept same] ...
    
    def _classify(self, image):
        if not self.cls_model:
            return "other", {}
        device = 0 if self.use_gpu else "cpu"
        results = self.cls_model(image, verbose=False, device=device)
        r = results[0]
        model_idx = int(r.probs.top1)
        raw_name = r.names[model_idx]
        name = raw_name if raw_name in self.YOLO_CLASS else "other"
        return name, {}

    def _center_crop(self, image):
        h, w = image.shape[:2]
        size = min(h, w)
        x = (w - size) // 2
        y = (h - size) // 2
        return image[y:y+size, x:x+size]

    def _create_merged_image(self, images_dict, dt_str, factory, lane, plate, cls_th):
        # ... [merged logic] ...
        sorted_keys = sorted(images_dict.keys())
        while len(sorted_keys) < 4:
            sorted_keys.append(None)
            
        base_w, base_h = 1280, 720
        loaded_imgs = []
        
        # We expect 2 images: Sugarcane (cls_cam) and LPR (lpr_cam)
        # Let's just take all available in order
        for k in sorted_keys:
            if k and k in images_dict:
                img = cv2.imread(images_dict[k])
                if img is not None:
                    loaded_imgs.append(cv2.resize(img, (base_w, base_h)))
        
        # Ensure we have at least 2 for layout, even if dummy
        while len(loaded_imgs) < 2:
            loaded_imgs.append(np.zeros((base_h, base_w, 3), dtype=np.uint8))

        # Horizontal stack for 1x2 grid
        grid = np.hstack((loaded_imgs[0], loaded_imgs[1]))
        
        # Header
        header_h = 160
        header = np.zeros((header_h, grid.shape[1], 3), dtype=np.uint8)
        text = f"{dt_str} | {factory}-L{lane} | {plate} | {cls_th}"
        
        pil_img = Image.fromarray(cv2.cvtColor(header, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img) # TYPO FIXED HERE
        
        try:
            font = ImageFont.truetype(self.font_path, 70)
        except:
            font = ImageFont.load_default()
            
        bbox = draw.textbbox((0,0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        
        tx = (header.shape[1] - tw) // 2
        ty = (header_h - th) // 2
        
        draw.text((tx, ty), text, font=font, fill=(255, 255, 255))
        header = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        
        # Save Merged Image
        # OLD: Results/YYYYMMDD HHMM/ai_images/...
        # NEW: Results/YYYYMMDD/ai_images/... (Simplified Structure)
        
        # We need the day string (YYYYMMDD) from dt_str (YYYYMMDD-HHMMSS)
        day_str = dt_str.split("-")[0]
        
        res_dir = self.config["DEFAULT"].get("results_path", "Results")
        if not os.path.isabs(res_dir):
            res_dir = os.path.join(self.project_root, res_dir)
            
        # Per Day Folder
        out_dir = os.path.join(res_dir, day_str, "ai_images")
        os.makedirs(out_dir, exist_ok=True)
        
        out_name = f"{dt_str}_{factory}_L{lane}_{plate}.jpg"
        out_path = os.path.join(out_dir, out_name)
        
        cv2.imwrite(out_path, np.vstack((header, grid)))
        
        # Return Absolute Path and Day String (folder_ts) for CSV
        return out_path, day_str

    def _append_to_csv(self, day_str, name, path, result, plate, dt, lane, eng_cls):
        """Append result to CSV in the Day folder."""
        # path is already Absolute from _create_merged_image
        
        res_dir = self.config["DEFAULT"].get("results_path", "Results")
        if not os.path.isabs(res_dir):
            res_dir = os.path.join(self.project_root, res_dir)
            
        # Folder: Results/YYYYMMDD
        folder_path = os.path.join(res_dir, day_str)
        os.makedirs(folder_path, exist_ok=True)
        
        factory = self.config["DEFAULT"].get("factory", "UNKNOWN")
        csv_name = f"{day_str}_{factory}.csv"
        csv_path = os.path.join(folder_path, csv_name)
        
        is_new = not os.path.exists(csv_path)
        
        try:
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if is_new:
                    writer.writerow(["Date", "Time", "Factory", "Lane", "License plate", "Path", "Cane_type", "Confidence"])
                
                # dt is datetime object
                d_str = dt.strftime("%Y-%m-%d")
                t_str = dt.strftime("%H:%M:%S")
                
                # result is classification EN (e.g. fresh-clean)
                # eng_cls is also available
                
                writer.writerow([d_str, t_str, factory, lane, plate, path, result, "0.0"]) 
                
        except Exception as e:
            self.log.error(f"Failed to append to CSV: {e}")

