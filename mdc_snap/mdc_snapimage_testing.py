import cv2
import configparser
import os
import time
import numpy as np
from datetime import datetime

def load_config(config_path="config.txt"):
    # Try current directory first
    if not os.path.exists(config_path):
        # Try parent directory
        config_path = os.path.join("..", "config.txt")
        if not os.path.exists(config_path):
            print(f"Error: Config file not found at {config_path}")
            return None
    
    config = configparser.ConfigParser()
    config.read(config_path)
    return config

def get_nvr_config(config):
    try:
        nvr_ip = config['NVR']['ip']
        nvr_user = config['NVR']['username']
        nvr_pass = config['NVR']['password']
        return nvr_ip, nvr_user, nvr_pass
    except KeyError as e:
        print(f"Error: Missing NVR config key: {e}")
        return None, None, None

def capture_and_create_grid(nvr_ip, nvr_user, nvr_pass, factory):
    # Grid Settings
    total_channels = 16
    grid_cols = 4
    target_width = 1920
    target_height = 1080
    
    # Calculate cell size
    cell_w = target_width // grid_cols
    cell_h = target_height // grid_cols # 4 rows
    
    collected_frames = []

    print("\n" + "="*50)
    print(f"Starting Capture Cycle at {datetime.now().strftime('%H:%M:%S')}...")

    for i in range(1, total_channels + 1):
        # Construct RTSP URL
        channel_id = f"{i}01"
        rtsp_url = f"rtsp://{nvr_user}:{nvr_pass}@{nvr_ip}:554/Streaming/Channels/{channel_id}"
        
        print(f"[{i}/{total_channels}] Connecting...", end="", flush=True)
        
        cap = cv2.VideoCapture(rtsp_url)
        
        # Skip initial frames to wait for Keyframe/stable image
        # Reading ~12 frames
        for _ in range(12):
            if cap.isOpened():
                cap.read()
        
        frame_to_store = None
        capture_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                # Save Image
                try:
                    # image/snap_image_{factory}/ch{i}/{date_folder}
                    # date_folder = 04_01_2026
                    date_folder = datetime.now().strftime('%d_%m_%Y')
                    save_dir = os.path.join("image", f"snap_image_{factory}", f"ch{i}", date_folder)
                    os.makedirs(save_dir, exist_ok=True)
                    
                    # {factory}_{channel}_{datetime}.jpg
                    filename = f"{factory}_{i}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    cv2.imwrite(os.path.join(save_dir, filename), frame)
                except Exception as e:
                    print(f" Save Error: {e}")

                # Resize for Grid
                frame_to_store = cv2.resize(frame, (cell_w, cell_h))
                print(f" SUCCESS.")
            else:
                print(" FAILED (No Frame).")
        else:
            print(f" FAILED (Connection). URL: {rtsp_url}")
            
        cap.release()
        
        # If failure, use black image
        if frame_to_store is None:
            frame_to_store = np.zeros((cell_h, cell_w, 3), dtype=np.uint8)
            cv2.putText(frame_to_store, f"CH {i} OFF", (10, cell_h // 2), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        # Draw White Border (Grid Line)
        cv2.rectangle(frame_to_store, (0, 0), (cell_w-1, cell_h-1), (255, 255, 255), 2)
        
        # Draw Timestamp
        text_size = cv2.getTextSize(capture_time_str, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        text_x = cell_w - text_size[0] - 10
        text_y = cell_h - 10
        # Background block for text compatibility
        cv2.rectangle(frame_to_store, (text_x - 5, text_y - 20), (text_x + text_size[0] + 5, text_y + 5), (0,0,0), -1)
        cv2.putText(frame_to_store, capture_time_str, (text_x, text_y), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        collected_frames.append(frame_to_store)

    # Stitching
    rows = []
    current_row = []
    
    for frame in collected_frames:
        current_row.append(frame)
        if len(current_row) == 4:
            rows.append(np.hstack(current_row))
            current_row = []
            
    final_grid = np.vstack(rows)
    final_grid = cv2.resize(final_grid, (target_width, target_height))
    
    return final_grid

def main():
    # Force OpenCV to use TCP for RTSP to reduce artifacts
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
    
    # Setup directories
    output_dir = os.path.join("testing", "nvr_snaps")
    os.makedirs(output_dir, exist_ok=True)
    
    config = load_config()
    if not config: return
    
    nvr_ip, nvr_user, nvr_pass = get_nvr_config(config)
    factory = config['DEFAULT'].get('factory', 'Unknown')
    
    if not nvr_ip: return

    print(f"Target NVR: {nvr_ip}")
    print("Press 'ESC' or 'q' in the window to Stop.")
    
    while True:
        start_time = time.time()
        
        # Capture and Create Grid
        grid_image = capture_and_create_grid(nvr_ip, nvr_user, nvr_pass, factory)
        
        # Show Image
        window_name = "MDC NVR Field Monitoring (Update every 20s)"
        cv2.imshow(window_name, grid_image)
        
        # Wait logic (Wait 20 seconds, checking for key press every 100ms)
        elapsed = time.time() - start_time
        wait_time = max(0, 20 - elapsed)
        print(f"Waiting {wait_time:.1f} seconds for next cycle...")
        
        # Loop for the wait duration to keep UI responsive
        end_wait = time.time() + wait_time
        while time.time() < end_wait:
            key = cv2.waitKey(100)
            if key == 27 or key == ord('q'): # ESC or q
                print("Exiting...")
                cv2.destroyAllWindows()
                return

if __name__ == "__main__":
    main()
