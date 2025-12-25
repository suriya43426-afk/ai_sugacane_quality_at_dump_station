import cv2
import os
import time

def fastify_vdo(input_path, output_path, target_fps=25.0):
    print(f"Fastifying: {os.path.basename(input_path)}")
    
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"Error: Could not open {input_path}")
        return

    # Get metadata from the 1 FPS video
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # We want to play back these frames at target_fps
    fourcc = cv2.VideoWriter_fourcc(*'mp4v') 
    out = cv2.VideoWriter(output_path, fourcc, target_fps, (w, h))

    count = 0
    start_time = time.time()

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # Just write every frame from the 1fps video into the 25fps video
        out.write(frame)
        count += 1
        if count % 100 == 0:
            print(f"  Processed {count} frames...")

    cap.release()
    out.release()
    
    duration = time.time() - start_time
    print(f"Finished: {output_path}")
    print(f"Re-encoded {count} frames at {target_fps} FPS in {duration:.2f}s")

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outcome_dir = os.path.join(base_dir, "testing", "outcome")
    
    if not os.path.exists(outcome_dir):
        print(f"Error: Directory not found: {outcome_dir}")
        return

    # Look for the _testing.mp4 files we just created
    files = [f for f in os.listdir(outcome_dir) if f.endswith('_testing.mp4')]
    
    if not files:
        print(f"No optimized video files found in {outcome_dir}")
        return

    print(f"Found {len(files)} files to speed up. Target Playback: 25 FPS")
    
    for filename in files:
        name_only = filename.replace("_testing.mp4", "")
        input_path = os.path.join(outcome_dir, filename)
        output_path = os.path.join(outcome_dir, f"{name_only}_fast.mp4")
        
        fastify_vdo(input_path, output_path)

if __name__ == "__main__":
    main()
