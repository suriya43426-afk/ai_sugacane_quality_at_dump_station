import cv2
import os
import shutil
import numpy as np
from skimage.metrics import structural_similarity as ssim
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

def compare_images(img_path1, img_path2):
    """Compare two images and return the SSIM score."""
    img1 = cv2.imread(img_path1)
    img2 = cv2.imread(img_path2)
    
    if img1 is None or img2 is None:
        return 0.0
    
    # Resize to a smaller size for faster comparison if needed
    # But for accuracy, let's keep it or resize slightly
    img1_gray = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    img2_gray = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    
    # Ensure they are the same size
    if img1_gray.shape != img2_gray.shape:
        img2_gray = cv2.resize(img2_gray, (img1_gray.shape[1], img1_gray.shape[0]))

    # Apply Gaussian Blur to reduce noise sensitivity
    img1_gray = cv2.GaussianBlur(img1_gray, (5, 5), 0)
    img2_gray = cv2.GaussianBlur(img2_gray, (5, 5), 0)
    
    score, _ = ssim(img1_gray, img2_gray, full=True, win_size=3)
    return score

def process_channel_task(args):
    """Wrapper function to unpack arguments for parallel processing."""
    return process_channel(*args)

def process_channel(source_base, target_base, channel_folder, date_folder, threshold=0.80):
    """Process images in a specific channel and date folder."""
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
    first_img = files[0]
    shutil.copy2(os.path.join(source_dir, first_img), os.path.join(target_dir, first_img))
    last_kept_img_path = os.path.join(source_dir, first_img)
    count = 1
    
    # We remove internal tqdm for parallel execution to avoid messed up output
    # But we can print a start message? No, that messes up tqdm too.
    
    for i in range(1, len(files)):
        current_img_path = os.path.join(source_dir, files[i])
        
        score = compare_images(last_kept_img_path, current_img_path)
        
        # If score is low, images are different
        if score < threshold:
            shutil.copy2(current_img_path, os.path.join(target_dir, files[i]))
            last_kept_img_path = current_img_path
            count += 1
            
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
        # Try to find it relative to current dir if run from root but folder structure is slightly different
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

    # Process in parallel
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = [executor.submit(process_channel_task, task) for task in tasks]
        
        # Track progress
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(tasks), unit="folder"):
            try:
                result = future.result()
                # Optional: print result if needed, but might clutter tqdm
                # tqdm.write(result) 
            except Exception as e:
                tqdm.write(f"Task generated an exception: {e}")

    print("\nAll tasks completed.")

if __name__ == "__main__":
    multiprocessing.freeze_support() # For Windows executable support if generated later
    main()
