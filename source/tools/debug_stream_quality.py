import cv2
import os
import sys
import time

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from source.database import DatabaseManager

def test_stream_optimization():
    # 1. Apply Optimized Flags
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|strict;experimental"
    
    print("="*60)
    print(" RTSP Stream Optimization Test")
    print(" Flags Applied: rtsp_transport;tcp|fflags;nobuffer|flags;low_delay")
    print("="*60)

    # 2. Connect to Database to get a valid URL
    config_path = "config.txt"
    if not os.path.exists(config_path):
        # Try parent dir
        config_path = os.path.join("..", "..", "config.txt")
        
    db = DatabaseManager("sugarcane_v2.db")
    dumps = db.get_active_dumps()
    
    if not dumps:
        print("No active dumps found in DB.")
        return

    # Pick the first camera of the first dump
    d_id = dumps[0]['dump_id']
    urls = db.get_cameras_for_dump(d_id)
    
    target_url = None
    target_ch = None
    
    # Prefer CH201 (Top) as it usually has more detail/motion
    if 'CH201' in urls:
        target_url = urls['CH201']
        target_ch = 'CH201'
    elif 'CH101' in urls:
        target_url = urls['CH101']
        target_ch = 'CH101'
        
    if not target_url:
        print(f"No cameras found for {d_id}")
        return
        
    print(f"Testing Stream: {d_id} - {target_ch}")
    print(f"URL: {target_url}")
    print("\nAttempting connection... (Press 'q' to exit)")
    
    cap = cv2.VideoCapture(target_url)
    
    if not cap.isOpened():
        print("FAILED to open stream.")
        return
        
    frame_count = 0
    start_time = time.time()
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Frame drop / Stream ended.")
            break
            
        frame_count += 1
        
        # Calculate FPS
        elapsed = time.time() - start_time
        fps = frame_count / elapsed if elapsed > 0 else 0
        
        # Display check
        cv2.putText(frame, f"FPS: {fps:.2f}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("Optimized Stream Test", frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    test_stream_optimization()
