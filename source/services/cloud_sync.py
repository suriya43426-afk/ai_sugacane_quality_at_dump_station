import os
import time
import logging
import boto3
import cv2
import json
import numpy as np
import configparser
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QThread

# Reuse existing Logic from ai_batch_processor (adapted for Class)
from source.services.ai_batch_processor import load_config, is_corrupted, parse_timestamp, get_s3_client

class CloudSyncWorker(QObject):
    """
    Background worker for Batch Processing and S3 Sync.
    Designed for High Cohesion (Only Syncs) and Low Coupling (Talks via Signals).
    """
    # Signals to UI
    status_updated = Signal(str)  # "Syncing...", "Sleeping..."
    progress_updated = Signal(int, int) # uploaded, deleted
    error_occurred = Signal(str)
    
    def __init__(self):
        super().__init__()
        self._is_running = True
        self.config = load_config()
        self.factory = self.config['DEFAULT'].get('factory', 'MDC')
        self.milling_process = self.config['DEFAULT'].get('milling_process', 'A')
        
        # Determine Source Path
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.source_root = os.path.join(root, "ai_snap", "image", f"snap_image_{self.factory}")
        if not os.path.exists(self.source_root):
             self.source_root = os.path.join(root, "image", f"snap_image_{self.factory}")
        
        self.batch_interval = 3600 # 1 Hour

    def run(self):
        """Main Loop running in QThread."""
        self.status_updated.emit(f"Service Started. Monitoring: {self.source_root}")
        
        while self._is_running:
            try:
                if not os.path.exists(self.source_root):
                    self.status_updated.emit("Waiting for Source Directory...")
                    time.sleep(10)
                    continue

                self.status_updated.emit("Starting Batch Sync...")
                start_time = time.time()
                
                # Run the Processor
                self._process_batch()
                
                elapsed = time.time() - start_time
                sleep_time = max(0, self.batch_interval - elapsed)
                
                # Sleep Loop (responsive to stop)
                wake_time = time.time() + sleep_time
                while time.time() < wake_time and self._is_running:
                    remaining = int((wake_time - time.time()) / 60)
                    self.status_updated.emit(f"Sync Complete. Next run in {remaining} min.")
                    QThread.msleep(1000) # Sleep 1 sec
                    
            except Exception as e:
                self.error_occurred.emit(str(e))
                self.status_updated.emit("Error. Retrying in 1 min.")
                QThread.sleep(60)

    def stop(self):
        self._is_running = False

    def _process_batch(self):
        # ... (Logic from ai_batch_processor.py but using self vars) ...
        factory = self.factory
        milling_process = self.milling_process
        source_root = self.source_root
        
        pairs = []
        for i in range(1, 16, 2):
            pairs.append((f"ch{i}", f"ch{i+1}"))
        
        try:
            s3 = get_s3_client()
        except Exception as e:
            self.error_occurred.emit(f"AWS Connection Failed: {e}")
            return

        total_uploaded = 0
        total_deleted = 0

        for ch_a, ch_b in pairs:
            if not self._is_running: break
            
            path_a = os.path.join(source_root, ch_a)
            path_b = os.path.join(source_root, ch_b)
            
            if not os.path.exists(path_a) or not os.path.exists(path_b):
                continue
                
            dates_a = set(os.listdir(path_a))
            dates_b = set(os.listdir(path_b))
            common_dates = dates_a.intersection(dates_b)
            
            for date_folder in sorted(common_dates):
                if not self._is_running: break
                
                dir_a = os.path.join(path_a, date_folder)
                dir_b = os.path.join(path_b, date_folder)
                
                files_a = {parse_timestamp(f): f for f in os.listdir(dir_a) if f.endswith('.jpg')}
                files_b = {parse_timestamp(f): f for f in os.listdir(dir_b) if f.endswith('.jpg')}
                
                common_timestamps = set(files_a.keys()).intersection(set(files_b.keys())) - {None}
                
                files_to_upload = []
                files_to_delete = []
                
                # Orphans
                for ts in files_a.keys() - common_timestamps:
                    if ts: files_to_delete.append(os.path.join(dir_a, files_a[ts]))
                for ts in files_b.keys() - common_timestamps:
                    if ts: files_to_delete.append(os.path.join(dir_b, files_b[ts]))
                    
                for ts in common_timestamps:
                    file_a = files_a[ts]
                    file_b = files_b[ts]
                    full_path_a = os.path.join(dir_a, file_a)
                    full_path_b = os.path.join(dir_b, file_b)
                    
                    try:
                        img_a = cv2.imread(full_path_a, cv2.IMREAD_REDUCED_COLOR_2)
                        img_b = cv2.imread(full_path_b, cv2.IMREAD_REDUCED_COLOR_2)
                        
                        if is_corrupted(img_a) or is_corrupted(img_b):
                            files_to_delete.append(full_path_a)
                            files_to_delete.append(full_path_b)
                        else:
                            files_to_upload.append((ch_a, full_path_a, file_a))
                            files_to_upload.append((ch_b, full_path_b, file_b))
                    except Exception:
                        pass # Skip file read errors

                # Delete
                for f_path in files_to_delete:
                    try:
                        os.remove(f_path)
                        total_deleted += 1
                    except: pass
                
                # Upload
                for ch_name, local_path, filename in files_to_upload:
                    if not self._is_running: break
                    dump_no = ch_name.replace('ch', '')
                    s3_key = f"images/{factory}/raw_images/{dump_no}/{date_folder}/{filename}"
                    
                    try:
                        s3.upload_file(local_path, "mitrphol-ai-sugarcane-data-lake", s3_key)
                        os.remove(local_path)
                        total_uploaded += 1
                        # Emit specific progress for UI Feedback
                        # self.status_updated.emit(f"Uploaded: {filename}") 
                    except Exception as e:
                        logging.error(f"Upload Fail: {e}")

        # Final Report for this Batch
        self.progress_updated.emit(total_uploaded, total_deleted)
