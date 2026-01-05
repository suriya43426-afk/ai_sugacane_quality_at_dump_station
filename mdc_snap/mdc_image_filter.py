import cv2
import os
import shutil
import numpy as np
from datetime import datetime
import configparser
from tqdm import tqdm
import concurrent.futures
import multiprocessing
import boto3
import json
import time

# ==============================================================================
# AWS CONFIGURATION
# ==============================================================================
AWS_REGION = "ap-southeast-1"
S3_BUCKET = "mitrphol-ai-sugarcane-data-lake"
GLUE_DB = "mitrphol_sagemaker_db"
GLUE_TABLE = "sugarcane_monitoring_log"

def load_config(config_path="config.txt"):
    if not os.path.exists(config_path):
        config_path = os.path.join("..", "config.txt")
        if not os.path.exists(config_path):
            return None
    
    config = configparser.ConfigParser()
    config.read(config_path)
    return config

def crop_center_square(image):
    """Crop the image to a square (1:1 aspect ratio) from the center."""
    h, w, _ = image.shape
    min_dim = min(h, w)
    
    start_x = (w - min_dim) // 2
    start_y = (h - min_dim) // 2
    
    return image[start_y:start_y+min_dim, start_x:start_x+min_dim]

def is_corrupted(image, threshold=0.05):
    """
    Check if the image is corrupted (glitched).
    Heuristic: Check for large blocks of pure white or Magenta.
    """
    # 1. Check for White Blocks (common bug)
    white_mask = np.all(image > 225, axis=-1)
    white_ratio = np.sum(white_mask) / white_mask.size
    if white_ratio > threshold: return True
        
    # 2. Check for Magenta/Pink artifacts
    pink_mask = (image[:,:,2] > 200) & (image[:,:,0] > 200) & (image[:,:,1] < 100)
    pink_ratio = np.sum(pink_mask) / pink_mask.size
    if pink_ratio > threshold: return True

    # 3. Check for Green artifacts
    green_mask = (image[:,:,1] > 200) & (image[:,:,2] < 100) & (image[:,:,0] < 100)
    green_ratio = np.sum(green_mask) / green_mask.size
    if green_ratio > threshold: return True
        
    return False

def calculate_dhash(image, hash_size=8):
    """Calculate the difference hash (dHash) of an image."""
    if image is None: return 0
    resized = cv2.resize(image, (hash_size + 1, hash_size))
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    diff = gray[:, 1:] > gray[:, :-1]
    return sum([2**i for (i, v) in enumerate(diff.flatten()) if v])

def hamming_distance(hash1, hash2):
    return bin(int(hash1) ^ int(hash2)).count('1')

def upload_to_datalake(local_path, filename, factory="MDC", process="A"):
    """
    Uploads Image and JSON Metadata to S3 Data Lake.
    """
    try:
        s3 = boto3.client('s3', region_name=AWS_REGION)
        
        # 1. Parse Metadata from Filename
        # Expected Format: truck_{plate}_{timestamp}.jpg OR just {timestamp}.jpg
        # Fallback to current time if parsing fails
        try:
            name_parts = filename.replace('.jpg', '').split('_')
            # Heuristic parsing
            if "truck" in name_parts:
                plate = name_parts[name_parts.index("truck") + 1]
            else:
                plate = "Unknown"
            
            # Timestamp usually at the end
            ts_str = name_parts[-1]
            if len(ts_str) == 6: # HHMMSS, likely missing date in filename, use file creation time?
                # For simplicity in this demo, use current time or try to parse
                iso_timestamp = datetime.utcnow().isoformat() + "Z"
            elif len(ts_str) >= 14: # YYYYMMDDHHMMSS
                dt = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
                iso_timestamp = dt.isoformat() + "Z"
            else:
                iso_timestamp = datetime.utcnow().isoformat() + "Z"
                
        except Exception:
            plate = "Unknown"
            iso_timestamp = datetime.utcnow().isoformat() + "Z"

        # 2. Upload Image
        date_folder = datetime.now().strftime("%Y-%m-%d")
        s3_key_image = f"images/{factory}/{date_folder}/{filename}"
        s3_path_full = f"s3://{S3_BUCKET}/{s3_key_image}"
        
        s3.upload_file(local_path, S3_BUCKET, s3_key_image)

        # 3. Upload JSON Log (Glue Schema)
        log_record = {
            "factory": factory,
            "process": process,
            "dump_no": 1, # Default or extract from folder name
            "plate": plate,
            "ai_result": 0, # 0 = Pending/Unknown (Since this script is just filtering)
            "captured_at": iso_timestamp,
            "image_s3_path": s3_path_full,
            "agent_id": "M4-PRO-MAX-PRODUCTION"
        }
        
        json_filename = f"log_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        s3_key_json = f"tables/{GLUE_TABLE}/{json_filename}"
        
        # Avoid writing local JSON file to disk to speed up IO
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key_json,
            Body=json.dumps(log_record),
            ContentType='application/json'
        )
        
        return True
    except Exception as e:
        # Log error but don't stop processing
        print(f"[ERROR] AWS Upload Failed for {filename}: {e}")
        return False

def process_channel_task(args):
    """Wrapper function to unpack arguments for parallel processing."""
    return process_channel(*args)

def process_channel(source_base, target_base, channel_folder, date_folder, threshold=12):
    """Process images in a specific channel and date folder using dHash."""
    source_dir = os.path.join(source_base, channel_folder, date_folder)
    target_dir = os.path.join(target_base, channel_folder, date_folder)
    
    if not os.path.exists(source_dir):
        return f"{channel_folder}/{date_folder}: Skipped (Source not found)"
    
    files = sorted([f for f in os.listdir(source_dir) if f.lower().endswith(('.jpg', '.jpeg'))])
    
    if not files:
        return f"{channel_folder}/{date_folder}: Skipped (No images)"

    # Create target directory for local backup
    os.makedirs(target_dir, exist_ok=True)

    # Helper to calculate hash for a given image path
    def get_hash(img_path):
        img = cv2.imread(img_path, cv2.IMREAD_REDUCED_COLOR_2)
        if img is None: return None, True
        if is_corrupted(img): return None, True
        cropped = crop_center_square(img)
        return calculate_dhash(cropped), False

    last_kept_hash = None
    count = 0
    
    # Process Loop
    for i, filename in enumerate(files):
        current_img_path = os.path.join(source_dir, filename)
        
        current_hash, corrupted = get_hash(current_img_path)
        
        if corrupted or current_hash is None:
            continue
        
        # Decide whether to keep
        keep = False
        if last_kept_hash is None:
            keep = True # Always keep first valid
        else:
            distance = hamming_distance(last_kept_hash, current_hash)
            if distance > threshold:
                keep = True
        
        if keep:
            # 1. Local Backup
            target_path = os.path.join(target_dir, filename)
            shutil.copy2(current_img_path, target_path)
            
            # 2. Cloud Upload (The Optimization!)
            # Extract Process ID from channel name (e.g., ch1 -> A?)
            process_id = channel_folder.replace("ch", "") 
            upload_to_datalake(target_path, filename, factory="MDC", process=process_id)
            
            last_kept_hash = current_hash
            count += 1
        
        # Optional: Print progress sparingly
        if i % 1000 == 0 and i > 0:
             print(f"[PROGRESS] {channel_folder}/{date_folder} - {i}/{len(files)}...", flush=True)
            
    return f"{channel_folder}/{date_folder}: Processed {len(files)} imgs, Kept & Uploaded {count}."

def check_hardware():
    print("="*40)
    print("System Hardware Check")
    print("="*40)
    cpu_cores = multiprocessing.cpu_count()
    print(f"  [CPU] Cores: {cpu_cores}")
    
    # Simple GPU check
    if shutil.which("nvidia-smi"):
         print("  [GPU] Nvidia detected.")
    else:
         print("  [GPU] Not detected (using CPU optimized dHash).")

    print("-" * 40)
    print("Mitr Phol AI Agent - Production Mode")
    print(f"  - Target: {S3_BUCKET}")
    print(f"  - Parallel Threads: {cpu_cores}")
    print("="*40)

def main():
    check_hardware()
    config = load_config()
    factory = "MDC"
    if config:
        factory = config['DEFAULT'].get('factory', 'MDC')
        
    source_base = os.path.join("mdc_snap", "image", f"snap_image_{factory}")
    target_base = os.path.join("mdc_snap", "image", f"ok_image_{factory}")
    
    # Path adjustment for dev environments
    if not os.path.exists("mdc_snap") and os.path.exists("image"):
         source_base = os.path.join("image", f"snap_image_{factory}")
         target_base = os.path.join("image", f"ok_image_{factory}")

    if not os.path.exists(source_base):
        print(f"Source directory not found: {source_base}")
        if os.path.exists(os.path.join("mdc_snap", "image")):
             source_base = os.path.join("mdc_snap", "image", f"snap_image_{factory}")
             target_base = os.path.join("mdc_snap", "image", f"ok_image_{factory}")
        else:
             return

    # Task Collection
    tasks = []
    print("Scanning directories...")
    try:
        if os.path.exists(source_base):
            categories = sorted(os.listdir(source_base))
            for ch_name in categories:
                ch_path = os.path.join(source_base, ch_name)
                if os.path.isdir(ch_path) and ch_name.startswith("ch"):
                    date_folders = sorted(os.listdir(ch_path))
                    for date_folder in date_folders:
                         tasks.append((source_base, target_base, ch_name, date_folder))
    except Exception as e:
        print(f"Error accessing source base: {e}")
        return

    if not tasks:
        print("No image folders found to process.")
        return

    max_workers = multiprocessing.cpu_count()
    print(f"Starting processing for {len(tasks)} folders...")

    # Parallel Execution
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_channel_task, task) for task in tasks]
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(tasks), unit="folder"):
            try:
                future.result()
            except Exception as e:
                tqdm.write(f"Task exception: {e}")

    print("\n[COMPLETE] All images processed and synced to Data Lake.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
