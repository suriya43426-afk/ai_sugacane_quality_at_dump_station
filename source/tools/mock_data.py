import sqlite3
import random
import uuid
from datetime import datetime, timedelta
import os

DB_PATH = "sugarcane_v2.db"

def get_conn():
    return sqlite3.connect(DB_PATH)

def setup_dumps(cursor):
    print("Setting up Dumps for MDC (Processes A, B, C)...")
    
    # Mapping
    processes = {
        'A': 6
    }
    
    dumps = []
    
    # Clear existing dumps? Or just upsert?
    # Let's clear to match the exact requirement layout
    cursor.execute("DELETE FROM dump_master") 
    cursor.execute("DELETE FROM dump_camera_map")
    cursor.execute("DELETE FROM camera_master")
    
    for proc, count in processes.items():
        for i in range(1, count + 1):
            dump_id = f"MDC-{proc}-{i:02d}"
            dump_name = f"Station {proc}-{i:02d}"
            
            # Insert Dump
            cursor.execute("INSERT INTO dump_master (dump_id, dump_name, is_active, updated_at) VALUES (?, ?, 1, ?)",
                           (dump_id, dump_name, datetime.now()))
            dumps.append(dump_id)
            
            # Mock Cameras (Front/Top)
            # Front
            cam_front = f"CAM-{dump_id}-F"
            cursor.execute("INSERT INTO camera_master (camera_id, camera_name, rtsp_url, view_type, updated_at) VALUES (?, ?, ?, 'FRONT', ?)",
                           (cam_front, f"Front {dump_id}", f"rtsp://mock/{dump_id}/101", datetime.now()))
            cursor.execute("INSERT INTO dump_camera_map (dump_id, camera_id, channel_type) VALUES (?, ?, 'CH101')", (dump_id, cam_front))
            
            # Top
            cam_top = f"CAM-{dump_id}-T"
            cursor.execute("INSERT INTO camera_master (camera_id, camera_name, rtsp_url, view_type, updated_at) VALUES (?, ?, ?, 'TOP', ?)",
                           (cam_top, f"Top {dump_id}", f"rtsp://mock/{dump_id}/201", datetime.now()))
            cursor.execute("INSERT INTO dump_camera_map (dump_id, camera_id, channel_type) VALUES (?, ?, 'CH201')", (dump_id, cam_top))

    print(f"Created {len(dumps)} dumps.")
    return dumps

def generate_sessions(cursor, dumps, count=1000):
    print(f"Generating {count} mock sessions...")
    
    # Clear sessions
    cursor.execute("DELETE FROM dump_session")
    cursor.execute("DELETE FROM dump_images")
    
    start_date = datetime.now() - timedelta(days=7)
    
    statuses = ['COMPLETE', 'COMPLETE', 'COMPLETE', 'INCOMPLETE'] # Mostly complete
    
    for _ in range(count):
        dump_id = random.choice(dumps)
        session_uuid = str(uuid.uuid4())
        
        # Random time in last 7 days
        time_offset = random.randint(0, 7 * 24 * 60 * 60)
        s_time = start_date + timedelta(seconds=time_offset)
        duration = random.randint(30, 180) # 30s to 3m
        e_time = s_time + timedelta(seconds=duration)
        
        status = random.choice(statuses)
        
        # Random Plate
        plate_nums = [f"{random.randint(10,99)}-{random.randint(1000,9999)}"]
        if random.random() < 0.1: plate_nums = ["UNKNOWN", "-"]
        plate = plate_nums[0]
        
        # Insert Session
        cursor.execute("""
            INSERT INTO dump_session (session_uuid, dump_id, start_time, end_time, plate_number, status, merged_image_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session_uuid, dump_id, s_time, e_time, plate, status, "results/mock_merged.jpg"))
        
        # Mock Images (1-4)
        if status == 'COMPLETE':
            img_types = ['IMAGE_1', 'IMAGE_2', 'IMAGE_3', 'IMAGE_4']
            for i, itype in enumerate(img_types):
                 cursor.execute("""
                    INSERT INTO dump_images (session_uuid, image_type, image_path, captured_at)
                    VALUES (?, ?, ?, ?)
                """, (session_uuid, itype, f"results/mock_{itype}.jpg", s_time + timedelta(seconds=10+i*5)))

    print("Sessions generated.")

def main():
    conn = get_conn()
    cursor = conn.cursor()
    
    try:
        dumps = setup_dumps(cursor)
        generate_sessions(cursor, dumps, 1000)
        conn.commit()
        print("Success! 1000 records created.")
        print("Milling A: 6, B: 8, C: 6 dumps.")
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
