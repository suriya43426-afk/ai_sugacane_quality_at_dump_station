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

def load_config(config_path="config.txt"):
    # Search up to project root
    curr = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        p = os.path.join(curr, config_path)
        if os.path.exists(p):
            config = configparser.ConfigParser()
            config.read(p)
            return config
        curr = os.path.dirname(curr)
    return None

def get_s3_client():
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
    
    # Identify Pairs: (1,2), (3,4) ... (15,16)
    # Assuming folder names are "ch1", "ch2", etc.
    pairs = []
    for i in range(1, 16, 2):
        pairs.append((f"ch{i}", f"ch{i+1}"))
    
    s3 = get_s3_client()
    
    total_uploaded = 0
    total_deleted = 0

    for ch_a, ch_b in pairs:
        path_a = os.path.join(source_root, ch_a)
        path_b = os.path.join(source_root, ch_b)
        
        # Skip if folders don't exist
        if not os.path.exists(path_a) or not os.path.exists(path_b):
            logging.warning(f"Missing folders for pair {ch_a}-{ch_b}. Skipping.")
            continue
            
        # Get all Date folders in these channels
        dates_a = set(os.listdir(path_a))
        dates_b = set(os.listdir(path_b))
        common_dates = dates_a.intersection(dates_b)
        
        for date_folder in sorted(common_dates):
            dir_a = os.path.join(path_a, date_folder)
            dir_b = os.path.join(path_b, date_folder)
            
            # List files
            files_a = {parse_timestamp(f): f for f in os.listdir(dir_a) if f.endswith('.jpg')}
            files_b = {parse_timestamp(f): f for f in os.listdir(dir_b) if f.endswith('.jpg')}
            
            # Find Intersection of Timestamps
            common_timestamps = set(files_a.keys()).intersection(set(files_b.keys())) - {None}
            
            logging.info(f"[{ch_a}-{ch_b}] Date {date_folder}: Found {len(common_timestamps)} matching pairs.")
            
            # Process Matches
            files_to_upload = []
            files_to_delete = [] # Mismatched or Corrupted
            
            # Add orphans to delete list
            for ts in files_a.keys() - common_timestamps:
                if ts: files_to_delete.append(os.path.join(dir_a, files_a[ts]))
            for ts in files_b.keys() - common_timestamps:
                if ts: files_to_delete.append(os.path.join(dir_b, files_b[ts]))
                
            for ts in common_timestamps:
                file_a = files_a[ts]
                file_b = files_b[ts]
                full_path_a = os.path.join(dir_a, file_a)
                full_path_b = os.path.join(dir_b, file_b)
                
                # Check Image Quality (Filter)
                img_a = cv2.imread(full_path_a, cv2.IMREAD_REDUCED_COLOR_2)
                img_b = cv2.imread(full_path_b, cv2.IMREAD_REDUCED_COLOR_2)
                
                if is_corrupted(img_a) or is_corrupted(img_b):
                    # If EITHER is bad, discard BOTH (Strict Sync)
                    files_to_delete.append(full_path_a)
                    files_to_delete.append(full_path_b)
                else:
                    files_to_upload.append((ch_a, full_path_a, file_a))
                    files_to_upload.append((ch_b, full_path_b, file_b))
            
            # Execute Deletion (Cleanup Bad/Unpaired)
            for f_path in files_to_delete:
                try:
                    os.remove(f_path)
                    total_deleted += 1
                except OSError as e:
                    logging.error(f"Failed to delete {f_path}: {e}")

            # Execute Upload (Batch)
            # S3 Path: {factory}/{milling_process}/{dump_no}/{date}/{filename}
            for ch_name, local_path, filename in files_to_upload:
                dump_no = ch_name.replace('ch', '')
                s3_key = f"images/{factory}/raw_images/{dump_no}/{date_folder}/{filename}"
                
                try:
                    s3.upload_file(local_path, S3_BUCKET, s3_key)
                    # Upload Metadata Log (Optional but recommended)
                    # For now just image
                    
                    # After upload, remove local? Prompt implies "Centralized... send to S3".
                    # Usually "Centralized" means move to cloud. Let's delete after verify upload.
                    os.remove(local_path) 
                    total_uploaded += 1
                except Exception as e:
                    logging.error(f"Failed upload {filename}: {e}")

    logging.info(f"Batch Complete. Uploaded: {total_uploaded}, Cleaned/Deleted: {total_deleted}")

def main():
    config = load_config()
    factory = config['DEFAULT'].get('factory', 'MDC')
    milling_process = config['DEFAULT'].get('milling_process', 'A')
    
    # Locate Source Directory Dynamically
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source_root = os.path.join(root, "ai_snap", "image", f"snap_image_{factory}")
    if not os.path.exists(source_root):
        source_root = os.path.join(root, "image", f"snap_image_{factory}")
    
    if not os.path.exists(source_root):
        logging.error(f"Source directory not found: {source_root}")
        # Try to create it if it doesn't exist? (Optional)
        return

    logging.info(f"Service Started. Monitoring {source_root}")
    logging.info(f"Sync Pairs: (1=2, 3=4...). Batch Interval: {BATCH_INTERVAL_SECONDS}s")

    while True:
        try:
            start_time = time.time()
            process_batch(factory, milling_process, source_root)
            
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
