import os
import time
import shutil
import logging
import boto3
import cv2
import json
import numpy as np
import configparser
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# CONFIGURATION (DYNAMIC)
# ==============================================================================
AWS_REGION = "ap-southeast-1"
S3_BUCKET = "mitrphol-ai-sugarcane-data-lake"
GLUE_TABLE = "sugarcane_monitoring_log"
BATCH_INTERVAL_SECONDS = 3600  # 1 Hour

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.FileHandler("batch_processor.log"),
        logging.StreamHandler()
    ]
)

def load_config(config_path="config.txt", secrets_path="secrets.ini"):
    # Search up to project root
    curr = os.path.dirname(os.path.abspath(__file__))
    logging.debug(f"Starting config search from: {curr}")
    for i in range(4):
        p_config = os.path.join(curr, config_path)
        p_secrets = os.path.join(curr, secrets_path)
        
        logging.debug(f"Level {i} - Checking: {p_config}")
        if os.path.exists(p_config):
            config = configparser.ConfigParser()
            files_to_read = [p_config]
            logging.info(f"Root config found: {p_config}")
            
            if os.path.exists(p_secrets):
                logging.info(f"Secrets file found: {p_secrets}")
                files_to_read.append(p_secrets)
            else:
                logging.warning(f"Secrets file NOT found at: {p_secrets}")
                
            config.read(files_to_read)
            return config
        curr = os.path.dirname(curr)
    
    logging.error("Could not find config.txt in any search path!")
    return None

def get_s3_client():
    config = load_config()
    aws_access_key = None
    aws_secret_key = None
    region = AWS_REGION

    if config and 'AWS' in config:
        aws_access_key = config['AWS'].get('access_key_id', '').strip()
        aws_secret_key = config['AWS'].get('secret_access_key', '').strip()
        region = config['AWS'].get('region', AWS_REGION).strip()

    if aws_access_key and aws_secret_key:
        return boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key
        )
    
    # Fallback to env vars or profile (standard boto3 behavior)
    return boto3.client('s3', region_name=AWS_REGION)

# ==============================================================================
# FILTERING LOGIC (Reused)
# ==============================================================================
def is_corrupted(image, threshold=0.05):
    """Checks for image corruption (White/Pink/Green blocks)."""
    if image is None: return True
    
    # 1. White
    white_mask = np.all(image > 225, axis=-1)
    if (np.sum(white_mask) / white_mask.size) > threshold: return True
    
    # 2. Pink (High R, High B, Low G)
    pink_mask = (image[:,:,2] > 200) & (image[:,:,0] > 200) & (image[:,:,1] < 100)
    if (np.sum(pink_mask) / pink_mask.size) > threshold: return True
        
    # 3. Green (High G)
    green_mask = (image[:,:,1] > 200) & (image[:,:,2] < 100) & (image[:,:,0] < 100)
    if (np.sum(green_mask) / green_mask.size) > threshold: return True
        
    return False

# ==============================================================================
# CORE LOGIC: SYNCHRONIZATION & UPLOAD
# ==============================================================================
def parse_timestamp(filename):
    """
    Extracts timestamp from filename.
    Format expected: {factory}_{channel}_{YYYYMMDD}_{HHMMSS}.jpg
    Returns: Timestamp string (YYYYMMDD_HHMMSS) or None
    """
    try:
        # Splits by '_' and takes last two parts (Date_Time.jpg)
        parts = filename.replace('.jpg', '').split('_')
        if len(parts) >= 2:
            return f"{parts[-2]}_{parts[-1]}" 
    except Exception:
        pass
    return None

def process_batch(factory, milling_process, source_root):
    logging.info(f"Starting Batch Process for {factory}...")
    
    try:
        s3 = get_s3_client()
    except Exception as e:
        logging.error(f"AWS Failed: {e}")
        return

    # 1. Scan ViewTypes (LPR, TopView)
    if not os.path.exists(source_root): return
    
    view_types = [d for d in os.listdir(source_root) if os.path.isdir(os.path.join(source_root, d))]
    
    total_uploaded = 0
    total_deleted = 0
    
    for view_type in view_types:
        view_path = os.path.join(source_root, view_type)
        
        # 2. Scan Channels (ch101, ch201...)
        channels = [d for d in os.listdir(view_path) if os.path.isdir(os.path.join(view_path, d))]
        
        for ch in channels:
            ch_path = os.path.join(view_path, ch)
            
            # 3. Scan Date Folders
            dates = [d for d in os.listdir(ch_path) if os.path.isdir(os.path.join(ch_path, d))]
            
            for date_folder in dates:
                date_path = os.path.join(ch_path, date_folder)
                files = [f for f in os.listdir(date_path) if f.endswith('.jpg')]
                
                for filename in files:
                    local_path = os.path.join(date_path, filename)
                    
                    # S3 Key: images/{factory}/raw_images/{view_type}/{ch}/{date}/{filename}
                    s3_key = f"images/{factory}/raw_images/{view_type}/{ch}/{date_folder}/{filename}"
                    
                    try:
                        # Quality Check
                        img = cv2.imread(local_path, cv2.IMREAD_REDUCED_COLOR_2)
                        if is_corrupted(img):
                            os.remove(local_path)
                            total_deleted += 1
                            continue
                            
                        # Upload
                        s3.upload_file(local_path, S3_BUCKET, s3_key)
                        os.remove(local_path)
                        total_uploaded += 1
                        
                    except Exception as e:
                        logging.error(f"Upload/Check Failed {filename}: {e}")

    logging.info(f"Batch Complete. Uploaded: {total_uploaded}, Cleaned/Deleted: {total_deleted}")

def main():
    config = load_config()
    factory = config['DEFAULT'].get('factory', 'MDC')
    
    # Locate Source Directory Dynamically
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source_root = os.path.join(root, "images", factory, "raw_images")

    if not os.path.exists(source_root):
        # Fallback Check
        fallback = os.path.join(root, "ai_snap", "image", f"snap_image_{factory}")
        if os.path.exists(fallback):
             source_root = fallback

    logging.info(f"Service Started. Monitoring {source_root}")
    logging.info(f"Sync Logic: Recursive Path Scan. Batch Interval: {BATCH_INTERVAL_SECONDS}s")

    while True:
        try:
            start_time = time.time()
            process_batch(factory, None, source_root)
            
            elapsed = time.time() - start_time
            sleep_time = max(0, BATCH_INTERVAL_SECONDS - elapsed)
            
            logging.info(f"Sleeping for {sleep_time/60:.2f} minutes...")
            time.sleep(sleep_time)
            
        except KeyboardInterrupt:
            logging.info("Stopping Service...")
            break
        except Exception as e:
            logging.error(f"Critical Error: {e}")
            time.sleep(60) # Retry after 1 min on crash

if __name__ == "__main__":
    main()
