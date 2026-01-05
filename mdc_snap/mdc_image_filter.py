import cv2
import os
import shutil
import numpy as np
from skimage.metrics import structural_similarity as ssim
from datetime import datetime
import configparser
from tqdm import tqdm

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

def process_channel(source_base, target_base, channel_folder, date_folder, threshold=0.80):
    """Process images in a specific channel and date folder."""
    source_dir = os.path.join(source_base, channel_folder, date_folder)
    target_dir = os.path.join(target_base, channel_folder, date_folder)
    
    if not os.path.exists(source_dir):
        return
    
    # List all jpg files and sort them by name (which includes timestamp)
    files = sorted([f for f in os.listdir(source_dir) if f.lower().endswith(('.jpg', '.jpeg'))])
    
    if not files:
        return
    
    print(f"Processing {channel_folder}/{date_folder}: {len(files)} images found.")
    
    # Create target directory if it doesn't exist (only if we have files to process)
    os.makedirs(target_dir, exist_ok=True)

    # Always copy the first image
    first_img = files[0]
    shutil.copy2(os.path.join(source_dir, first_img), os.path.join(target_dir, first_img))
    last_kept_img_path = os.path.join(source_dir, first_img)
    count = 1
    
    # Use tqdm for progress bar
    for i in tqdm(range(1, len(files)), desc=f"Filtering {channel_folder}", unit="img"):
        current_img_path = os.path.join(source_dir, files[i])
        
        score = compare_images(last_kept_img_path, current_img_path)
        
        # If score is low, images are different
        if score < threshold:
            shutil.copy2(current_img_path, os.path.join(target_dir, files[i]))
            last_kept_img_path = current_img_path
            count += 1
            
    print(f"  -> Kept {count} unique images out of {len(files)}.")

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

    # Iterate through channels
    for ch_name in sorted(os.listdir(source_base)):
        ch_path = os.path.join(source_base, ch_name)
        if os.path.isdir(ch_path) and ch_name.startswith("ch"):
            # Iterate through date folders
            for date_folder in sorted(os.listdir(ch_path)):
                date_path = os.path.join(ch_path, date_folder)
                if os.path.isdir(date_path):
                    process_channel(source_base, target_base, ch_name, date_folder)

if __name__ == "__main__":
    main()
