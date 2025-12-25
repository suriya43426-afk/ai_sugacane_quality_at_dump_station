import cv2
import time
import threading
import logging
import os
from datetime import datetime
from source.orchestration.dump_state_manager import StateManager, DumpState
from source.utils.image_merger import merge_production_images

class DumpProcessor(threading.Thread):
    def __init__(self, dump_id, db, lpr_engine, cls_engine, logger=None):
        super().__init__(name=f"Processor_{dump_id}", daemon=True)
        self.dump_id = dump_id
        self.db = db
        self.lpr_engine = lpr_engine
        self.cls_engine = cls_engine
        self.log = logger or logging.getLogger(f"DumpProcessor_{dump_id}")
        
        self.sm = StateManager(dump_id, logger=self.log)
        self.running = True
        self.caps = {'CH101': None, 'CH201': None}
        self.urls = self.db.get_cameras_for_dump(dump_id)
        
        # Local session image buffer
        self.session_images = {
            'IMAGE_1': None, 
            'IMAGE_2': None, 
            'IMAGE_3': None, 
            'IMAGE_4': None
        }
        self.plate_number = "UNKNOWN"
        self.session_uuid = None

    def run(self):
        self.log.info(f"Starting processor for {self.dump_id}")
        self._init_streams()
        
        last_analysis = 0
        while self.running:
            try:
                # 1. Grab Frames
                frames = {}
                for ch, cap in self.caps.items():
                    if cap and cap.isOpened():
                        ret, frame = cap.read()
                        if ret: frames[ch] = frame
                
                # 2. Analyze at ~2-5 FPS to save CPU
                now = time.time()
                if now - last_analysis > 0.2:
                    last_analysis = now
                    self._process_cycle(frames)
                
                time.sleep(0.01)
            except Exception as e:
                self.log.error(f"Error in main loop: {e}")
                time.sleep(1)

    def _init_streams(self):
        for ch, url in self.urls.items():
            try:
                self.log.info(f"Opening {ch}: {url}")
                self.caps[ch] = cv2.VideoCapture(url)
                # Optimize for RTSP
                self.caps[ch].set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception as e:
                self.log.error(f"Failed to open {ch}: {e}")

    def _process_cycle(self, frames):
        f_frame = frames.get('CH101')
        t_frame = frames.get('CH201')
        
        if f_frame is None or t_frame is None:
            return

        # 1. AI Analysis
        # CH101 -> LPR / Truck
        lpr_res = self.lpr_engine.detect(f_frame, skip_ocr=True)
        
        # CH201 -> Classification / Cane
        cls_res = self.cls_engine.analyze(t_frame)
        
        # 2. Update FSM
        # Mapping model results to FSM inputs
        front_data = {
            'truck_detected': lpr_res is not None,
            'lifting': False, # Needs heuristic from box movement or ROI
            'lift_max': False, # Needs heuristic
            'lowering': False
        }
        
        # Simple heuristics for demo/placeholder - can be refined with ROI analysis
        # For production, we'd check if the plate bbox is in a specific Y-range
        if lpr_res:
            _, y1, _, y2 = lpr_res.bbox
            if y1 < 100: front_data['lift_max'] = True
            elif y1 < 250: front_data['lifting'] = True
            
        state_changed = self.sm.update(front_data, cls_res)
        
        if state_changed:
            self.log.info(f"State: {self.sm.state.name}")
            if self.session_uuid:
                self.db.log_state_transition(self.session_uuid, "PREV", self.sm.state.name)
            
            # Start Session at TRUCK_IN
            if self.sm.state == DumpState.TRUCK_IN and not self.session_uuid:
                self.session_uuid = self.db.create_session(self.dump_id)
                self.log.info(f"New Session: {self.session_uuid}")
                self.session_images = {k: None for k in self.session_images}
                self.plate_number = "UNKNOWN"
            
            # End Session at EMPTY_RESET
            if self.sm.state == DumpState.EMPTY_RESET and self.session_uuid:
                self._finalize_session()
                self.session_uuid = None

        # 3. Capture Logic
        trigger = self.sm.get_capture_trigger()
        if trigger and self.session_uuid:
            self._perform_capture(trigger, f_frame, t_frame)

    def _perform_capture(self, trigger, f_frame, t_frame):
        self.log.info(f"Capturing {trigger} for session {self.session_uuid}")
        
        img_to_save = None
        if trigger == 'IMAGE_1':
            # Perform OCR on Image 1
            lpr_full = self.lpr_engine.detect(f_frame, skip_ocr=False)
            if lpr_full and lpr_full.text:
                self.plate_number = lpr_full.text
                self.db.update_session(self.session_uuid, plate_number=self.plate_number)
            img_to_save = f_frame
        else:
            img_to_save = t_frame # Image 2, 3, 4 are TOP view
            
        if img_to_save is not None:
            # Save to disk
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{self.dump_id}_{self.session_uuid[:8]}_{trigger}_{ts_str}.jpg"
            path = os.path.join("results", filename)
            os.makedirs("results", exist_ok=True)
            cv2.imwrite(path, img_to_save)
            
            # Log To DB
            self.db.log_image(self.session_uuid, trigger, path)
            self.session_images[trigger] = img_to_save
            self.sm.mark_captured(trigger)

    def _finalize_session(self):
        self.log.info(f"Finalizing session {self.session_uuid}")
        
        # Check if all images exist
        all_captured = all(v is not None for v in self.session_images.values())
        status = 'COMPLETE' if all_captured else 'INCOMPLETE'
        
        # Merge
        factory_info = self.db.get_factory_info()
        meta = {
            'datetime': datetime.now().strftime("%d%m%Y-%H:%M:%S"),
            'factory': factory_info.get('factory_id', 'NA'),
            'milling': factory_info.get('milling_process', 'NA'),
            'dump': self.dump_id,
            'lpr': self.plate_number
        }
        
        merged_img = merge_production_images(list(self.session_images.values()), meta)
        
        # Save merged
        merged_filename = f"MERGED_{self.dump_id}_{self.session_uuid[:8]}.jpg"
        merged_path = os.path.join("results", merged_filename)
        cv2.imwrite(merged_path, merged_img)
        
        # Update Session in DB
        self.db.update_session(self.session_uuid, 
                              end_time=datetime.now(),
                              merged_image_path=merged_path,
                              status=status)
        
        self.log.info(f"Session {status}. Merged saved to {merged_path}")
