import cv2
import os
import configparser
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from source.database import DatabaseManager

def test_cameras():
    config = configparser.ConfigParser()
    config.read("config.txt", encoding="utf-8")
    
    db_path = config.get("DATABASE", "path", fallback="sugarcane_v2.db")
    print(f"Reading database: {db_path}")
    db = DatabaseManager(db_path)
    
    dumps = db.get_active_dumps()
    print(f"Found {len(dumps)} active dump stations.")
    
    # Set TCP transport for testing
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;5000"

    for d in dumps:
        dump_id = d['dump_id']
        urls = db.get_cameras_for_dump(dump_id)
        print(f"\n--- Testing Station: {dump_id} ---")
        
        for ch, url in urls.items():
            print(f"  Channel {ch}: {url}")
            if not url or "rtsp" not in url.lower():
                print(f"  [SKIP] Invalid URL: {url}")
                continue
                
            cap = cv2.VideoCapture(url)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    print(f"  [OK] Successfully connected and grabbed frame from {ch}")
                else:
                    print(f"  [WARN] Connected to {ch} but failed to grab frame")
                cap.release()
            else:
                print(f"  [ERROR] Failed to connect to {ch}")

if __name__ == "__main__":
    test_cameras()
