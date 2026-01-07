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
        # New Requirement: ./images/{factory}/raw_images
        self.source_root = os.path.join(root, "images", self.factory, "raw_images")
        
        # Fallback support for old path (optional, but good to keep for safety)
        if not os.path.exists(self.source_root):
             # Try old location just in case user reverts
             self.source_root_legacy = os.path.join(root, "ai_snap", "image", f"snap_image_{self.factory}")
        else:
             self.source_root_legacy = None
        
        self.batch_interval = 3600 # 1 Hour

    def run(self):
        """Main Loop running in QThread."""
        self.status_updated.emit(f"Service Started. Monitoring: {self.source_root}")
        
        while self._is_running:
            try:
                if not os.path.exists(self.source_root):
                    if self.source_root_legacy and os.path.exists(self.source_root_legacy):
                        self.source_root = self.source_root_legacy
                    else:
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
        """
        New Structure: images/{factory}/raw_images/{ViewType}/ch{N}/{Date}/filename
        Recursively scan and upload.
        """
        factory = self.factory
        source_root = self.source_root
        
        try:
            s3 = get_s3_client()
        except Exception as e:
            self.error_occurred.emit(f"AWS Connection Failed: {e}")
            return

        total_uploaded = 0
        total_deleted = 0
        
        # 1. Scan ViewTypes (LPR, TopView)
        if not os.path.exists(source_root): return
        
        view_types = [d for d in os.listdir(source_root) if os.path.isdir(os.path.join(source_root, d))]
        
        for view_type in view_types:
            view_path = os.path.join(source_root, view_type)
            
            # 2. Scan Channels (ch101, ch201...)
            channels = [d for d in os.listdir(view_path) if os.path.isdir(os.path.join(view_path, d))]
            
            for ch in channels:
                ch_path = os.path.join(view_path, ch)
                
                # 3. Scan Date Folders
                dates = [d for d in os.listdir(ch_path) if os.path.isdir(os.path.join(ch_path, d))]
                
                for date_folder in dates:
                    if not self._is_running: return
                    
                    date_path = os.path.join(ch_path, date_folder)
                    files = [f for f in os.listdir(date_path) if f.endswith('.jpg')]
                    
                    for filename in files:
                        if not self._is_running: return
                        
                        local_path = os.path.join(date_path, filename)
                        
                        # S3 Key: images/{factory}/raw_images/{view_type}/{ch}/{date}/{filename}
                        s3_key = f"images/{factory}/raw_images/{view_type}/{ch}/{date_folder}/{filename}"
                        
                        try:
                            # Quality Check
                            img = cv2.imread(local_path, cv2.IMREAD_REDUCED_COLOR_2)
                            if is_corrupted(img):
                                os.remove(local_path)
                                total_deleted += 1
                                continue
                                
                            # Upload
                            s3.upload_file(local_path, "mitrphol-ai-sugarcane-data-lake", s3_key)
                            os.remove(local_path)
                            total_uploaded += 1
                            
                        except Exception as e:
                            logging.error(f"Upload/Check Failed {filename}: {e}")

        self.progress_updated.emit(total_uploaded, total_deleted)
