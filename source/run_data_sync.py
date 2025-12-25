# -*- coding: utf-8 -*-
"""
run_data_sync.py
- Scheduled task (e.g., hourly) to select diverse image samples and upload to GDrive.
- Also checks for model updates.
"""

import os
import sys
import time
import shutil
import sqlite3
import random
import logging
import argparse
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.transport.requests import Request

# Paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Logging Setup ---
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logger = logging.getLogger("data_sync")
logger.setLevel(logging.INFO)
# Console Handler
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

# File Handler
fh = logging.FileHandler(os.path.join(LOG_DIR, "data_sync.log"))
fh.setFormatter(formatter)
logger.addHandler(fh)

# Configuration Loading
def load_app_config():
    """
    Load configuration from config.txt in PROJECT_ROOT.
    Returns:
        factory_id (str): Default "Sxx"
        folder_id (str): Google Drive Folder ID
        total_lanes (int): Default 4
    """
    config_path = os.path.join(PROJECT_ROOT, "..", "config.txt") # Adjusted path to be consistent with original
    factory_id = "Sxx"
    folder_id = None
    total_lanes = 4 # Default
    
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip().lower()
                    val = val.strip()
                    
                    if key == "factory":
                        factory_id = val
                    elif key == "gdrive_folder_id":
                        folder_id = val
                    elif key == "total_lanes":
                        try:
                            total_lanes = int(val)
                        except ValueError: # Catch specific error for int conversion
                            logger.warning(f"Invalid value for total_lanes: {val}. Using default {total_lanes}.")
                            pass
                            
    return factory_id, folder_id, total_lanes

# Global Config
FACTORY_ID, GDRIVE_FOLDER_ID, TOTAL_LANES = load_app_config()

# Note: Database is in the project root, one level up from source/
DB_PATH = os.path.join(PROJECT_ROOT, "..", "sugarcane.db")
IMG_DIR = os.path.join(PROJECT_ROOT, "..", "images")


def get_db_connection():
    return sqlite3.connect(DB_PATH)

def select_samples(hours_lookback=1):
    """
    Select samples from each configured lane to ensure coverage.
    Strategy: For each lane (1..TOTAL_LANES), select up to 6 images (3 Pos, 3 Neg).
    """
    logger.info(f"Selecting samples from last {hours_lookback} hours for {TOTAL_LANES} lanes...")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Calculate cutoff
    cutoff = datetime.now() - timedelta(hours=hours_lookback)
    cutoff_ts = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    
    final_samples = []
    
    for lane in range(1, TOTAL_LANES + 1):
        # 1. Select Negatives (00-0000) for this lane
        cursor.execute("""
            SELECT id, image_path, plate_number, confidence, timestamp, lane_number
            FROM processing_logs 
            WHERE timestamp >= ? AND lane_number = ? AND plate_number = '00-0000'
            ORDER BY timestamp DESC LIMIT 3
        """, (cutoff_ts, lane))
        negs = cursor.fetchall()
        
        # 2. Select Positives (Trucks) for this lane
        cursor.execute("""
            SELECT id, image_path, plate_number, confidence, timestamp, lane_number
            FROM processing_logs 
            WHERE timestamp >= ? AND lane_number = ? AND plate_number != '00-0000'
            ORDER BY timestamp DESC LIMIT 3
        """, (cutoff_ts, lane))
        poss = cursor.fetchall()
        
        lane_count = len(negs) + len(poss)
        if lane_count > 0:
            logger.info(f"Lane {lane}: Found {len(negs)} Negs, {len(poss)} Poss")
            final_samples.extend(negs)
            final_samples.extend(poss)
        # else: logger.debug(f"Lane {lane}: No recent data.")
            
    conn.close()
    
    logger.info(f"Total samples selected: {len(final_samples)}")
    return final_samples, [] # Return single list, second return can be empty or we just modify caller to expect one list

# --- Google Drive Logic ---

def get_drive_service():
    """Load credentials and return Drive Service."""
    token_path = os.path.join(PROJECT_ROOT, "token.json")
    if not os.path.exists(token_path):
        logger.error(f"Token file not found: {token_path}")
        return None
    
    try:
        creds = Credentials.from_authorized_user_file(token_path, ['https://www.googleapis.com/auth/drive'])
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Auth failed: {e}")
        return None

def create_folder_if_not_exists(service, folder_name, parent_id):
    """Check if folder exists inside parent, else create it."""
    query = f"'{parent_id}' in parents and name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])
    
    if files:
        return files[0]['id']
    
    # Create
    meta = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    file = service.files().create(body=meta, fields='id').execute()
    logger.info(f"Created GDrive Folder: {folder_name} ({file.get('id')})")
    return file.get('id')

def upload_file(service, file_path, file_name, parent_id):
    """Resumable upload for buffer images."""
    try:
        metadata = {'name': file_name, 'parents': [parent_id]}
        media = MediaFileUpload(file_path, mimetype='image/png', resumable=True)
        file = service.files().create(body=metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        logger.error(f"Upload Error ({file_name}): {e}")
        raise e

def get_upload_path_info(lane_num):
    """
    Determine Category, Group, and CamID based on Lane Number.
    
    Logic:
    - Lanes are 1-based (from DB or Loop).
    - Group = (lane - 1) // 4 + 1
    - Position = (lane - 1) % 4
    
    If Position == 0 (Lane 1, 5, 9...):
        Category = "plate"
        Path Structure: images/plate/{Factory}/L{Group}
        
    If Position > 0 (Lane 2, 3, 4, 6...):
        Category = "sugarcane"
        CamID = lane * 100 + 1 (e.g., L2->201)
        Path Structure: images/sugarcane/{Factory}/L{Group}/{CamID}
    """
    if not lane_num:
        lane_num = 1
        
    group = (lane_num - 1) // 4 + 1
    position = (lane_num - 1) % 4
    
    if position == 0:
        category = "plate"
        # For Plate, we don't use CamID in folder path, just Lane Group
        subfolder = f"L{group}"
    else:
        category = "sugarcane"
        cam_id = lane_num * 100 + 1
        subfolder = f"L{group}/{cam_id}"
        
    return category, subfolder

def upload_to_drive(samples, root_folder_id):
    if not samples:
        logger.info("No samples provided for upload.")
        print("No images found in database query to upload.")
        return
        
    if not root_folder_id:
        return
    
    service = get_drive_service()
    if not service:
        print("Failed to connect to Google Drive Service.")
        return
    
    try:
        # Base Folders
        images_f = create_folder_if_not_exists(service, "images", root_folder_id)
        plate_root = create_folder_if_not_exists(service, "plate", images_f)
        sugar_root = create_folder_if_not_exists(service, "sugarcane", images_f)
        
        # Factory Folders
        plate_factory = create_folder_if_not_exists(service, FACTORY_ID, plate_root)
        sugar_factory = create_folder_if_not_exists(service, FACTORY_ID, sugar_root)
        
        # Cache for specific destination folders
        # Key: "category/subfolder/date" -> folder_id
        folder_cache = {} 
        
        logger.info(f"Uploading {len(samples)} files...")
        
        for row in samples:
            # Unpack: SELECT id, image_path, plate_number, confidence, timestamp, lane_number
            img_path = row[1]
            plate_val = row[2]
            conf_val = row[3]
            ts_val = row[4]
            lane_val = row[5] or 1
            
            if not os.path.exists(img_path):
                continue
            
            # Determine Path Info
            category, subpath = get_upload_path_info(lane_val)
            
            # Select Root based on category
            current_parent = plate_factory if category == "plate" else sugar_factory
            
            # Parse Date
            try:
                dt_obj = datetime.strptime(ts_val, "%Y-%m-%d %H:%M:%S")
            except ValueError: # Catch specific error for datetime conversion
                logger.warning(f"Invalid timestamp format: {ts_val}. Using current datetime.")
                dt_obj = datetime.now()
            date_str = dt_obj.strftime("%Y-%m-%d")
            
            # Generate Cache Key
            cache_key = f"{category}/{subpath}/{date_str}"
            
            if cache_key in folder_cache:
                target_folder = folder_cache[cache_key]
            else:
                # Recursively create subpath (can be "L1" or "L1/201")
                parts = subpath.split("/")
                for part in parts:
                    current_parent = create_folder_if_not_exists(service, part, current_parent)
                
                # Create Date Folder
                target_folder = create_folder_if_not_exists(service, date_str, current_parent)
                folder_cache[cache_key] = target_folder
            
            # Filename
            time_part = dt_obj.strftime("%H%M")
            safe_plate = "".join([c for c in plate_val if c.isalnum() or c in "-_"]) if plate_val else "UNKNOWN"
            new_filename = f"{time_part}_{safe_plate}_{float(conf_val):.2f}.jpg"
            
            # Upload
            logger.info(f"Uploading {new_filename} -> {category}/{subpath}/{date_str}")
            metadata = {'name': new_filename, 'parents': [target_folder]}
            media = MediaFileUpload(img_path, mimetype='image/jpeg')
            
            try:
                service.files().create(body=metadata, media_body=media, fields='id').execute()
            except Exception as e:
                logger.error(f"Failed to upload {new_filename}: {e}")
                
        logger.info("Upload complete.")
            
    except Exception as e:
        logger.error(f"GDrive Upload Error: {e}")

def check_model_update_for_category(root_folder_id, category, model_filename):
    """
    Check for model updates in: models/{category}/{Factory}/{model_filename}
    Example: models/plate/S60/objectdetection.pt
    """
    service = get_drive_service()
    if not service:
        return

    try:
        # Navigate Path: models -> {category} -> {FACTORY_ID}
        models_root = get_folder_id(service, "models", root_folder_id)
        if not models_root:
            logger.info(f"Models root folder not found under {root_folder_id}.")
            return # Models folder doesn't exist
            
        category_folder = get_folder_id(service, category, models_root)
        if not category_folder:
            logger.info(f"Category folder '{category}' not found under models.")
            return # Category folder (plate/sugarcane) doesn't exist
            
        factory_folder = get_folder_id(service, FACTORY_ID, category_folder)
        if not factory_folder:
            logger.info(f"Factory folder '{FACTORY_ID}' not found under {category}.")
            return # Factory folder doesn't exist
            
        # List files in Factory folder
        results = service.files().list(
            q=f"'{factory_folder}' in parents and name = '{model_filename}' and trashed = false",
            fields="files(id, name, modifiedTime, size)",
            pageSize=1
        ).execute()
        
        items = results.get('files', [])
        if not items:
            logger.info(f"No model file '{model_filename}' found for category '{category}'.")
            return # No model file found
            
        latest_file = items[0]
        file_id = latest_file['id']
        # cloud_ts = latest_file['modifiedTime'] # ISO String
        
        # Local Path
        local_model_dir = os.path.join(PROJECT_ROOT, "..", "models")
        if not os.path.exists(local_model_dir):
            os.makedirs(local_model_dir)
        local_model_path = os.path.join(local_model_dir, model_filename)
        
        should_download = False
        if not os.path.exists(local_model_path):
            should_download = True
            logger.info(f"Model {model_filename} missing locally. Downloading...")
        else:
            local_size = os.path.getsize(local_model_path)
            cloud_size = int(latest_file.get('size', 0))
            if local_size != cloud_size:
                should_download = True
                logger.info(f"Model {model_filename} size mismatch (Cloud: {cloud_size} vs Local: {local_size}). Updating...")
            else:
                logger.info(f"Local model {model_filename} is up to date (size matches).")
        
        if should_download:
            logger.info(f"Downloading new model: {model_filename}...")
            temp_model_path = local_model_path + ".new"
            request = service.files().get_media(fileId=file_id)
            with open(temp_model_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
            
            if os.path.exists(temp_model_path) and os.path.getsize(temp_model_path) > 0:
                # Backup old model if exists
                if os.path.exists(local_model_path):
                    backup_path = local_model_path + ".bak"
                    shutil.move(local_model_path, backup_path)
                    logger.info(f"Backed up old model to {backup_path}")
                
                shutil.move(temp_model_path, local_model_path)
                logger.info(f"Model {model_filename} updated successfully.")
                # Trigger restart if any model was updated
                os._exit(100) # Orchestration batch script handles this
            else:
                logger.error(f"Downloaded model {model_filename} is empty or invalid.")
            
    except Exception as e:
        logger.error(f"Error checking model update for {category}: {e}", exc_info=True)

def get_or_create_root_folder_by_name(service, folder_name="ai-sugarcane-all-sites"):
    """
    Finds a folder in 'root' with the given name. 
    If not found, creates it.
    """
    try:
        # Search in root
        query = f"'root' in parents and name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            found_id = files[0]['id']
            logger.info(f"Found existing root folder '{folder_name}': {found_id}")
            return found_id
        
        # Create if not found
        meta = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': ['root'] # Explicitly in My Drive root
        }
        file = service.files().create(body=meta, fields='id').execute()
        new_id = file.get('id')
        logger.info(f"Created new root folder '{folder_name}': {new_id}")
        return new_id
        
    except Exception as e:
        logger.error(f"Failed to resolve root folder '{folder_name}': {e}")
        return None

def check_model_update(root_folder_id):
    """Wrapper to check both models."""
    logger.info("Checking for model updates...")
    # 1. Plate Model (Object Detection)
    check_model_update_for_category(root_folder_id, "plate", "objectdetection.pt")
    
    # 2. Sugarcane Model (Classification)
    check_model_update_for_category(root_folder_id, "sugarcane", "classification.pt")

def upload_buffer_images(root_folder_id):
    """
    Scan `./buffer_images` for periodic snapshots, upload to GDrive, and delete locally.
    Filename: {ts}_{Factory}_{Lend}_{Cam}.png
    Target: images/buffer/{Factory}/{Lane}/{Date}
    """
    BUFFER_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "..", "buffer_images"))
    if not os.path.exists(BUFFER_DIR):
        return

    logger.info(f"Checking {BUFFER_DIR} for periodic snapshots...")
    service = get_drive_service()
    if not service: return

    # Base Folders Cache
    images_f = create_folder_if_not_exists(service, "images", root_folder_id)
    buffer_root = create_folder_if_not_exists(service, "buffer", images_f)
    
    folder_cache = {}
    count = 0
    
    # Walk directory
    for root, dirs, files in os.walk(BUFFER_DIR):
        for file in files:
            if not (file.lower().endswith(".png") or file.lower().endswith(".jpg")): 
                continue
            
            file_path = os.path.join(root, file)
            
            # Parse: 20251217_13_S60_L1_101.png
            try:
                parts = file.replace(".png", "").replace(".jpg","").split("_")
                
                # New Format: {Date}_{Hour}_{Factory}_{Lane}_{Cam} (5 parts)
                # Old Format (Backward Compat check): {Date-Time}_{Fac}_{Lane}_{Cam} (4 parts)
                
                if len(parts) >= 5:
                    ts_day = parts[0]
                    ts_hr = parts[1]
                    fac = parts[2]
                    lane = parts[3]
                    
                    # Date: 20251217 -> 2025-12-17
                    date_fmt = f"{ts_day[:4]}-{ts_day[4:6]}-{ts_day[6:8]}"
                    
                elif len(parts) == 4:
                    # Legacy support for files captured before update/restart
                    ts = parts[0] # YYYYMMDD-HHMMSS
                    fac = parts[1]
                    lane = parts[2]
                    date_str = ts.split("-")[0]
                    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                else:
                    continue # Skip invalid files

                # Structure: images/buffer/{Factory}/{Lane}/{Date}
                
                # 1. Factory
                if fac not in folder_cache:
                    folder_cache[fac] = create_folder_if_not_exists(service, fac, buffer_root)
                fac_id = folder_cache[fac]
                
                # 2. Lane
                lane_key = f"{fac}_{lane}"
                if lane_key not in folder_cache:
                    folder_cache[lane_key] = create_folder_if_not_exists(service, lane, fac_id)
                lane_f_id = folder_cache[lane_key]
                
                # 3. Date
                date_key = f"{lane_key}_{date_fmt}"
                if date_key not in folder_cache:
                    folder_cache[date_key] = create_folder_if_not_exists(service, date_fmt, lane_f_id)
                parent_id = folder_cache[date_key]
                
                # Upload
                logger.info(f"Uploading Buffer: {file}")
                upload_file(service, file_path, file, parent_id)
                
                # Delete local
                os.remove(file_path)
                count += 1

                    
            except Exception as e:
                logger.error(f"Failed to upload buffer {file}: {e}")
                
    if count > 0:
        logger.info(f"Successfully uploaded {count} buffer images.")


def run_test_mode(root_folder_id):
    """
    Simulate uploads for ALL configured lanes (1..TOTAL_LANES).
    Verifies path creation for both Plate and Sugarcane categories.
    """
    logger.info("--- RUNNING CONNECTIVITY TEST MODE (ALL LANES) ---")
    
    if not root_folder_id:
        logger.error("Root folder ID missing.")
        return

    service = get_drive_service()
    if not service:
        logger.error("Failed to connect to Drive.")
        return

    try:
        # Base Folders
        images_f = create_folder_if_not_exists(service, "images", root_folder_id)
        plate_root = create_folder_if_not_exists(service, "plate", images_f)
        sugar_root = create_folder_if_not_exists(service, "sugarcane", images_f)
        
        # Factory Folders
        plate_factory = create_folder_if_not_exists(service, FACTORY_ID, plate_root)
        sugar_factory = create_folder_if_not_exists(service, FACTORY_ID, sugar_root)
        
        # Iterate ALL Configured Lanes
        logger.info(f"Simulating lanes 1 to {TOTAL_LANES}...")
        
        for lane in range(1, TOTAL_LANES + 1):
            category, subpath = get_upload_path_info(lane)
            
            logger.info(f"Lane {lane} -> {category} -> {subpath}")
            
            # Determine Parent
            current_parent = plate_factory if category == "plate" else sugar_factory
            
            # Traverse/Create Subpath
            parts = subpath.split("/")
            for part in parts:
                current_parent = create_folder_if_not_exists(service, part, current_parent)
                
            # Create TEST_CONNECTION folder
            test_f = create_folder_if_not_exists(service, "TEST_CONNECTION", current_parent)
            
            # Create Dummy File
            dummy_filename = f"TEST_L{lane}_{category}.txt"
            dummy_path = os.path.join(PROJECT_ROOT, dummy_filename)
            with open(dummy_path, "w", encoding="utf-8") as f: # Added encoding
                f.write(f"Test Connection for Lane {lane} ({category}) at {datetime.now()}")
                
            # Upload
            logger.info(f"Uploading {dummy_filename} to TEST_CONNECTION...")
            metadata = {'name': dummy_filename, 'parents': [test_f]}
            media = MediaFileUpload(dummy_path, mimetype='text/plain')
            service.files().create(body=metadata, media_body=media, fields='id').execute()
            
            # Cleanup
            if os.path.exists(dummy_path):
                os.remove(dummy_path)
                
        logger.info("Test Mode Completed. Please check Google Drive folders.")
        print("Test Upload Successful! Checked all configured lanes.")

    except Exception as e:
        logger.error(f"Test Mode Failed: {e}", exc_info=True)
        print(f"Test Mode Failed: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Do not upload, just simulate")
    parser.add_argument("--test", action="store_true", help="Run in connectivity test mode (force upload)")
    args = parser.parse_args()
    
    logger.info(f"Starting Data Sync Task ({FACTORY_ID})...")
    
    # Logic:
    # 1. Try config.txt (via global GDRIVE_FOLDER_ID)
    # 2. If valid ID, use it.
    # 3. If placeholder/missing, USE AUTO-DISCOVERY of "ai-sugarcane-all-sites"
    
    folder_id = GDRIVE_FOLDER_ID
    
    # Check if placeholder
    if folder_id == "YOUR_FOLDER_ID_HERE":
        folder_id = None
    
    # Auto-Discovery Fallback
    if not folder_id:
        logger.info("No Folder ID in config. Using Auto-Discovery for 'ai-sugarcane-all-sites'...")
        service = get_drive_service()
        if service:
            folder_id = get_or_create_root_folder_by_name(service)
    
    if not folder_id:
        logger.error("Could not determine GDrive Folder ID (Config missing and Auto-Discovery failed). Aborting.")
        return

    # TEST MODE CHECK
    if args.test:
        run_test_mode(folder_id)
        return

    try:
        # 1. Upload Periodic Buffer Snapshots (Priority)
        # This handles the "Auto Capture" images for retraining
        upload_buffer_images(folder_id)

        # 2. Select Data
        # Ensure we get samples from ALL lanes?
        # Current select_samples gets random mix.
        # But if Sugarcane lanes are mostly empty/negative, we might miss them.
        # However, for now, let's keep database sampling as is (user didn't explicitly ask to change SQL)
        # We just need to ensure correct Routing if they DO exist.
        neg_samples, pos_samples = select_samples()
        
        all_samples = neg_samples + pos_samples
        
        if args.dry_run:
            logger.info(f"Dry Run: Would upload {len(all_samples)} files.")
        else:
            # 2. Upload
            upload_to_drive(all_samples, folder_id)
            
            # 3. Check Updates
            check_model_update(folder_id)
        
    except Exception as e:
        logger.error(f"Data Sync Failed: {e}", exc_info=True)

if __name__ == "__main__":
    main()
