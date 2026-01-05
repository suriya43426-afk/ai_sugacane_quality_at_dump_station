import cv2
import os
import shutil
import numpy as np
from datetime import datetime
import configparser
from tqdm import tqdm
import concurrent.futures
import multiprocessing

def load_config(config_path="config.txt"):
    if not os.path.exists(config_path):
        config_path = os.path.join("..", "config.txt")
        if not os.path.exists(config_path):
            return None
    
    config = configparser.ConfigParser()
    config.read(config_path)
    return config

def calculate_dhash(image, hash_size=8):
    """
    Calculate the difference hash (dHash) of an image.
    This is extremely fast and robust for deduplication.
    """
    if image is None: return 0
    
    # 1. Resize to (hash_size + 1) x hash_size (e.g. 9x8)
    # We ignore aspect ratio - it's fine for hashing
    resized = cv2.resize(image, (hash_size + 1, hash_size))
    
    # 2. Convert to grayscale
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    
    # 3. Compare adjacent pixels
    # diff[i, j] = gray[i, j+1] > gray[i, j]
    diff = gray[:, 1:] > gray[:, :-1]
    
    # 4. Convert binary array to 64-bit integer
    # Using a simple bitwise packing
    return sum([2**i for (i, v) in enumerate(diff.flatten()) if v])

def hamming_distance(hash1, hash2):
    """Calculate the Hamming distance between two 64-bit hashes."""
    # XOR comparison, then count the number of set bits (1s)
    return bin(int(hash1) ^ int(hash2)).count('1')

def process_channel_task(args):
    """Wrapper function to unpack arguments for parallel processing."""
    return process_channel(*args)

def process_channel(source_base, target_base, channel_folder, date_folder, threshold=12):
    """Process images in a specific channel and date folder using dHash."""
    source_dir = os.path.join(source_base, channel_folder, date_folder)
    target_dir = os.path.join(target_base, channel_folder, date_folder)
    
    if not os.path.exists(source_dir):
        return f"{channel_folder}/{date_folder}: Skipped (Source not found)"
    
    # List all jpg files and sort them by name (which includes timestamp)
    files = sorted([f for f in os.listdir(source_dir) if f.lower().endswith(('.jpg', '.jpeg'))])
    
    if not files:
        return f"{channel_folder}/{date_folder}: Skipped (No images)"

    print(f"[STARTED] {channel_folder}/{date_folder} ({len(files)} images)")
    
    # Create target directory if it doesn't exist (only if we have files to process)
    os.makedirs(target_dir, exist_ok=True)

    # Always copy the first image
    first_img_name = files[0]
    first_img_path = os.path.join(source_dir, first_img_name)
    shutil.copy2(first_img_path, os.path.join(target_dir, first_img_name))
    
    # Calculate hash for the first kept image
    first_img_mat = cv2.imread(first_img_path)
    last_kept_hash = calculate_dhash(first_img_mat)
    
    count = 1
    
    for i in range(1, len(files)):
        current_img_path = os.path.join(source_dir, files[i])
        
        # Read image
        current_img_mat = cv2.imread(current_img_path)
        if current_img_mat is None: continue
        
        # Calculate Hash
        current_hash = calculate_dhash(current_img_mat)
        
        # Compare with last kept image
        distance = hamming_distance(last_kept_hash, current_hash)
        
        # If distance > threshold, it means images are "different enough"
        # Threshold 10-12 is usually distinct scenes.
        if distance > threshold:
            shutil.copy2(current_img_path, os.path.join(target_dir, files[i]))
            last_kept_hash = current_hash
            count += 1
        
        if i % 1000 == 0:
             print(f"[PROGRESS] {channel_folder}/{date_folder} - {i}/{len(files)}...", flush=True)
            
    print(f"[FINISHED] {channel_folder}/{date_folder} - Kept {count}/{len(files)}")
    return f"{channel_folder}/{date_folder}: Processed {len(files)} imgs, Kept {count}."

def main():
    config = load_config()
    factory = "MDC"
    if config:
        factory = config['DEFAULT'].get('factory', 'MDC')
        
    source_base = os.path.join("mdc_snap", "image", f"snap_image_{factory}")
    target_base = os.path.join("mdc_snap", "image", f"ok_image_{factory}")
    
    # If the script is run from inside mdc_snap, adjust paths
    if not os.path.exists("mdc_snap") and os.path.exists("image"):
         source_base = os.path.join("image", f"snap_image_{factory}")
         target_base = os.path.join("image", f"ok_image_{factory}")

    if not os.path.exists(source_base):
        print(f"Source directory not found: {source_base}")
        # Try to find it relative to current dir
        if os.path.exists(os.path.join("mdc_snap", "image")):
             source_base = os.path.join("mdc_snap", "image", f"snap_image_{factory}")
             target_base = os.path.join("mdc_snap", "image", f"ok_image_{factory}")
        else:
             return

    # Collect all tasks
    tasks = []
    print("Scanning directories...")
    try:
        categories = sorted(os.listdir(source_base))
    except Exception as e:
        print(f"Error accessing source base: {e}")
        return

    for ch_name in categories:
        ch_path = os.path.join(source_base, ch_name)
        if os.path.isdir(ch_path) and ch_name.startswith("ch"):
            try:
                date_folders = sorted(os.listdir(ch_path))
                for date_folder in date_folders:
                    date_path = os.path.join(ch_path, date_folder)
                    if os.path.isdir(date_path):
                        tasks.append((source_base, target_base, ch_name, date_folder))
            except Exception as e:
                print(f"Error reading channel {ch_name}: {e}")

    if not tasks:
        print("No image folders found to process.")
        return

    max_workers = multiprocessing.cpu_count()
    print(f"Found {len(tasks)} folders. Starting parallel processing with {max_workers} cores...")
    print("Algorithm: dHash (Strictness: High)")

    # Process in parallel
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = [executor.submit(process_channel_task, task) for task in tasks]
        
        # Track progress
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(tasks), unit="folder"):
            try:
                result = future.result()
            except Exception as e:
                tqdm.write(f"Task generated an exception: {e}")

    print("\nAll tasks completed.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
