import sys
import base64
import math
import os
import time
import asyncio
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from typing import List, Dict, Optional
from dotenv import load_dotenv
import mimetypes
from datetime import datetime
import logging
import configparser
import pytz

# ------------------ SETUP LOGGING ------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, "agent.log")

# Ensure Project Root is in sys.path for "source" package imports
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

try:
    from source.database import DatabaseManager
    from source.config import load_config
except ImportError as e:
    # If run from source dir directly
    sys.path.append(os.path.join(BASE_DIR, "source"))
    from database import DatabaseManager
    from config import load_config
    # logging.warning(f"Fallback import in agent.py: {e}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("agent")

# ------------------ CONFIG LOADING ------------------
load_dotenv(override=True)
MAX_RETRIES = 3
TIMEOUT_SECONDS = 300

CONFIG_PATH = os.path.join(BASE_DIR, "config.txt")

try:
    cp, config_dict = load_config(CONFIG_PATH)
    config = cp
except Exception as e:
    log.error(f"Config loading failed: {e}")
    sys.exit(1)

PROJECT_ROOT = config["DEFAULT"].get("PROJECT_ROOT", BASE_DIR)


class BatchProcessor:
    def __init__(self, url_batch: str, url_key: str, api_key: str):
        self.url_batch = url_batch
        self.url_key = url_key
        self.api_key = api_key
        self.timeout = ClientTimeout(total=TIMEOUT_SECONDS)

    @staticmethod
    def image_to_base64(image_path: str) -> Optional[str]:
        if not os.path.exists(image_path):
            log.warning(f"Image not found: {image_path}")
            return None
            
        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        try:
            with open(image_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            return f"data:{mime_type};base64,{encoded}"
        except Exception as e:
            log.error(f"Failed to encode image {image_path}: {e}")
            return None

    async def send_batch_to_api(self, batch_payload: List[Dict], batch_number: int) -> Dict[str, str]:
        request_number = f"REQ_{batch_number}_{datetime.now().isoformat()}"
        factory_code = config['DEFAULT'].get('factory', 'UNKNOWN')

        data = {
            "request_number": request_number,
            "factory_code": factory_code,
            "payload": batch_payload,
        }

        for attempt in range(MAX_RETRIES):
            try:
                connector = TCPConnector(ssl=False)
                async with ClientSession(timeout=self.timeout, connector=connector) as session:
                    async with session.post(
                        self.url_batch,
                        headers={
                            "Content-Type": "application/json",
                            "x-api-key": self.api_key,
                        },
                        json=data,
                    ) as response:

                        response_data = await response.json()
                        if response.status == 200:
                            log.info(f"Batch {batch_number}: Success")
                            return {
                                "status": "Success",
                                "message": response_data.get("message", ""),
                                "request_number": response_data.get("request_number", request_number),
                            }
                        
                        log.warning(f"Batch {batch_number} Attempt {attempt+1} Failed: HTTP {response.status} - {response_data}")

                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(2 ** attempt)

            except Exception as e:
                log.error(f"Batch {batch_number} Attempt {attempt+1} Error: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)

        return {
            "status": "Failed",
            "message": f"Batch {batch_number} could not be sent after {MAX_RETRIES} retries.",
        }

    async def process_db_batch(self, rows: List[Dict], batch_number: int) -> Dict:
        """Convert DB rows to payload and send."""
        thailand = pytz.timezone('Asia/Bangkok')
        # DB timestamp is often string in SQLite? "YYYY-MM-DD HH:MM:SS"
        # We need "YYYY-MM-DDTHH:MM:SS+07:00"
        
        tz_offset = datetime.now(thailand).strftime('%z')
        tz_offset = f"{tz_offset[:3]}:{tz_offset[3:]}"
        
        batch_payload = []
        ids_to_mark = []
        
        for row in rows:
            img_path = row["image_path"]
            if img_path and not os.path.isabs(img_path):
                 img_path = os.path.join(PROJECT_ROOT, img_path)
                 
            img64 = self.image_to_base64(img_path)
            
            # Format timestamp from DB
            # row['timestamp'] might be datetime object or string depending on sqlite adapter
            ts_val = row["timestamp"]
            if isinstance(ts_val, str):
                # Attempt parse if needed, but usually ISO format "YYYY-MM-DD HH:MM:SS.ssss"
                # Ideally we just replace space with T
                data_at = ts_val.replace(" ", "T") + tz_offset
            else:
                data_at = ts_val.strftime("%Y-%m-%dT%H:%M:%S") + tz_offset

            # Mapping AI Class (0-4) to Quality Score (1-5) per User Request
            # 0(BurnClean)->3, 1(BurnDirty)->4, 2(FreshClean)->1, 3(FreshDirty)->2, 4(Other)->5
            raw_cls = row["classification"]
            quality_score = "5" # Default to 'Unable to Score'
            
            try:
                # raw_cls might be "1" (str) or 1 (int) or "Fresh-Clean" (if legacy)
                # Assuming new system sends string/int of 0-4
                if raw_cls is not None:
                     v = int(raw_cls)
                     if v == 0: quality_score = "3"
                     elif v == 1: quality_score = "4"
                     elif v == 2: quality_score = "1"
                     elif v == 3: quality_score = "2"
                     elif v == 4: quality_score = "5"
                     else: quality_score = "5" # Out of range
            except:
                # Fallback if text format
                quality_score = "5"

            entry = {
                "factory_lane": str(row["lane_number"]),
                "truck": {"plate": str(row["plate_number"]), "province": "Unknown"},
                "cane": {"quantity_score": quality_score, "image_base64": img64},
                "data_at": data_at,
            }
            batch_payload.append(entry)
            ids_to_mark.append(row["id"])
            
        result = await self.send_batch_to_api(batch_payload, batch_number)
        
        if result["status"] == "Success":
            return {
                "success": True, 
                "ids": ids_to_mark, 
                "msg": result["message"], 
                "request_number": result.get("request_number"),
                "payload": batch_payload
            }
        else:
            return {"success": False, "ids": [], "msg": result["message"]}


async def main():
    log.info("Agent started (DB Mode).")
    
    # 1. Setup DB
    db_path = config["DEFAULT"].get("db_path", "sugarcane.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(PROJECT_ROOT, db_path)
        
    db = DatabaseManager(db_path, logger=log)
    
    # 2. Setup API
    api_config_path = os.path.join(BASE_DIR, "api_config.json")
    api_data = {}
    if os.path.exists(api_config_path):
        import json
        try:
            with open(api_config_path, 'r', encoding='utf-8') as f:
                api_data = json.load(f)
        except Exception:
            pass

    try:
        url_batch = api_data.get('cqc_endpoint') or config['DEFAULT'].get('cqc_endpoint')
        url_key   = api_data.get('hq_endpoint') or config['DEFAULT'].get('hq_endpoint')
        api_key   = api_data.get('x_api_key') or config['DEFAULT'].get('x_api_key')
        
        if not all([url_batch, url_key, api_key]):
            raise KeyError("Missing API keys")
    except Exception as e:
        log.error(f"Config Error: {e}")
        return

    processor = BatchProcessor(url_batch, url_key, api_key)
    
    # 3. Processing Loop
    batch_count = 0
    total_processed = 0
    
    # Audit Log Setup
    import csv
    log_dir = os.path.join(PROJECT_ROOT, "sync_logs")
    os.makedirs(log_dir, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    audit_path = os.path.join(log_dir, f"upload_log_{today_str}.csv")
    
    # Initialize CSV header if new
    if not os.path.exists(audit_path):
        try:
            with open(audit_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "BatchID", "Items", "Status", "RequestNumber", "Message"])
        except Exception:
            pass

    while True:
        rows = db.get_pending_uploads(limit=10)
        
        if not rows:
            log.info("No pending uploads found.")
            break
            
        batch_count += 1
        log.info(f"Processing Batch {batch_count} ({len(rows)} items)...")
        
        res = await processor.process_db_batch(rows, batch_count)
        
        # Audit Logging
        try:
            with open(audit_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                req_num = res.get("request_number") if res["success"] else "N/A" # request_number might be in res msg struct
                # Wait, process_db_batch returns success/ids/msg. It loses request_number unless passed through.
                # Let's check process_db_batch again.
                # It returns {"success": T/F, "ids": [], "msg": ...}
                # So we don't have request_number here easily unless we parse msg or update return.
                # Simplified log:
                writer.writerow([ts, batch_count, len(rows), "SUCCESS" if res["success"] else "FAILED", "N/A", res["msg"]])
        except Exception as e:
            log.error(f"Failed to write audit log: {e}")

        if res["success"]:
            # -----------------------------------------------
            # User Requirement: batchlog_no_{datetime}.csv in Results
            # -----------------------------------------------
            try:
                # Results dir might vary, check config or default
                res_path_cfg = config["DEFAULT"].get("results_path", "Results")
                if os.path.isabs(res_path_cfg):
                    RESULTS_DIR = res_path_cfg
                else:
                    RESULTS_DIR = os.path.join(PROJECT_ROOT, res_path_cfg)
                os.makedirs(RESULTS_DIR, exist_ok=True)
                
                # Filename
                now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                req_num = res.get("request_number", "Unknown")
                
                # Maybe user meant the request number IN the filename? 
                # "batchlog_no_{datetime}" -> "batchlog_no_2025..."
                # Or "batchlog_{no}_{datetime}"?
                # "batchlog_no_{datetime}.csv" seems to imply "batchlog number X" or just "batchlog_no_..." prefix.
                # using the requested format literally.
                
                csv_name = f"batchlog_no_{now_str}.csv"
                log_full_path = os.path.join(RESULTS_DIR, csv_name)
                
                payload = res.get("payload", [])
                
                with open(log_full_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    # Header
                    writer.writerow(["Timestamp", "RequestNumber", "FactoryLane", "Plate", "Class", "DataAt"])
                    
                    # Rows
                    for item in payload:
                         # Extract data safely
                         lane = item.get("factory_lane", "")
                         plate = item.get("truck", {}).get("plate", "")
                         cls_val = item.get("cane", {}).get("quantity_score", "")
                         data_at = item.get("data_at", "")
                         
                         writer.writerow([now_str, req_num, lane, plate, cls_val, data_at])
                         
            except Exception as e:
                log.error(f"Failed to write detailed batch log: {e}")

            db.mark_as_uploaded(res["ids"])
            total_processed += len(rows)
            log.info(f"Batch {batch_count} Uploaded & Marked in DB.")
        else:
            log.error(f"Batch {batch_count} Failed: {res['msg']}")
            break
            
        await asyncio.sleep(0.5)

    log.info(f"Agent finished. Total processed: {total_processed}")
    time.sleep(2)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log.exception(f"Unhandled exception in main: {e}")
