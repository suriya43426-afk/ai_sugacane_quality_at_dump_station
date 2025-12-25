import cv2
import os
import time

def resize_vdo_to_1fps(input_path, output_path):
    print(f"Processing: {os.path.basename(input_path)}")
    
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"Error: Could not open {input_path}")
        return

    # Get original metadata
    orig_fps = cap.get(cv2.CAP_PROP_FPS)
    if orig_fps <= 0: orig_fps = 25 # Fallback
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Original FPS: {orig_fps}, Total Frames: {total_frames}")

    # Output settings
    out_w, out_h = 1920, 1080
    out_fps = 1.0 # Target 1 fps
    
    # Use H.264 codec (if available) or MP4V
    fourcc = cv2.VideoWriter_fourcc(*'mp4v') 
    out = cv2.VideoWriter(output_path, fourcc, out_fps, (out_w, out_h))

    count = 0
    saved_count = 0
    start_time = time.time()

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # Logic to skip frames to achieve 1 FPS
        # We save a frame every 'orig_fps' frames
        if count % int(orig_fps) == 0:
            resized_frame = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
            out.write(resized_frame)
            saved_count += 1
            if saved_count % 10 == 0:
                print(f"  Processed {saved_count} seconds of video...")

        count += 1

    cap.release()
    out.release()
    
    duration = time.time() - start_time
    print(f"Finished: {output_path}")
    print(f"Extracted {saved_count} frames (1 FPS) in {duration:.2f}s")

def main():
    # Fix paths to be relative to script location OR run from root
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    input_dir = os.path.join(base_dir, "testing", "vdo")
    output_dir = os.path.join(base_dir, "testing", "outcome")
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if not os.path.exists(input_dir):
        print(f"Error: Directory not found: {input_dir}")
        return

    files = [f for f in os.listdir(input_dir) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))]
    
    if not files:
        print(f"No video files found in {input_dir}")
        return

    print(f"Found {len(files)} files. Starting optimization...")
    
    for filename in files:
        name, ext = os.path.splitext(filename)
        input_path = os.path.join(input_dir, filename)
        output_path = os.path.join(output_dir, f"{name}_testing.mp4")
        
        resize_vdo_to_1fps(input_path, output_path)

if __name__ == "__main__":
    main()
