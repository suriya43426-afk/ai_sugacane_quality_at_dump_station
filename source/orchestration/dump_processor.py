import cv2
import time
import threading
import logging
import os
from datetime import datetime
from source.orchestration.dump_state_manager import StateManager, DumpState
from source.utils.image_merger import merge_production_images

class DumpProcessor(threading.Thread):
    def __init__(self, dump_id, db, lpr_engine, cls_engine, logger=None, testing_mode=False):
        super().__init__(name=f"Processor_{dump_id}", daemon=True)
        self.dump_id = dump_id
        self.db = db
        self.lpr_engine = lpr_engine
        self.cls_engine = cls_engine
        self.log = logger or logging.getLogger(f"DumpProcessor_{dump_id}")
        self.testing_mode = testing_mode
        
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
        self.latest_frames = {} 
        self.latest_cls_res = {} # Store real AI results
        self.ai_enabled = True # Default
        self.last_snap_time = 0

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
                        if not ret:
                            # If video file, loop back to start
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ret, frame = cap.read()
                        
                        if ret: frames[ch] = frame
                
                # Update latest_frames for UI consumption with STANDARDIZED KEYS
                # Sort keys to ensure consistency: 1st key = LPR, 2nd key = AI (Top)
                sorted_keys = sorted(frames.keys())
                normalized_frames = {}
                if len(sorted_keys) > 0: normalized_frames['LPR'] = frames[sorted_keys[0]]
                if len(sorted_keys) > 1: normalized_frames['AI'] = frames[sorted_keys[1]]
                
                self.latest_frames = normalized_frames
                
                # 2. Analyze at ~2 FPS (Optimized for CPU stability)
                now = time.time()
                if now - last_analysis > 0.5:
                    last_analysis = now
                    # Pass raw frames to processing or adapted ones?
                    # The internal processing also uses hardcoded CH101/CH201. We should fix that too.
                    self._process_cycle(frames)
                
                time.sleep(0.01)
            except Exception as e:
                self.log.error(f"Error in main loop: {e}")
                time.sleep(1)

    def _init_streams(self):
        for ch, url in self.urls.items():
            try:
                connected = False
                
                # 0. Check Testing Mode
                if self.testing_mode:
                    self.log.info(f"{ch}: Testing Mode=ON. Skipping RTSP, using fallback VDO.")
                else:
                    # 1. Try RTSP (Priority)
                    if url and url.strip():
                        self.log.info(f"Opening RTSP {ch}: {url}")
                        try:
                            # Attempt to set a lower timeout (backend dependent, often doesn't work directly in cv2 props)
                            # but we can try opening with API preference if needed.
                            # For now, we rely on standard open but log clearly.
                            cap = cv2.VideoCapture(url)
                            if cap.isOpened():
                                self.caps[ch] = cap
                                connected = True
                                self.log.info(f"Connected to RTSP {ch}")
                            else:
                                self.log.warning(f"RTSP failed to open {ch}")
                        except Exception as e:
                            self.log.error(f"RTSP Exception {ch}: {e}")

                # 2. Key Fallback: If not connected (or Testing Mode), try Testing VDO
                if not connected:
                    if not self.testing_mode:
                        self.log.info(f"Camera not connected for {ch}. Searching for fallback VDO...")
                    vdo_path = self._find_fallback_vdo(ch)
                    if vdo_path:
                        self.log.info(f"Checking fallback VDO: {vdo_path}")
                        if os.path.exists(vdo_path):
                            self.caps[ch] = cv2.VideoCapture(vdo_path)
                            if self.caps[ch].isOpened():
                                connected = True
                                self.log.info(f"Successfully opened fallback VDO: {vdo_path}")
                            else:
                                self.log.error(f"Failed to open video file: {vdo_path}")
                        else:
                            self.log.error(f"Video file path does not exist: {vdo_path}")
                    else:
                        self.log.error(f"No fallback VDO found for pattern {ch}")

                if not connected:
                    self.log.error(f"Failed to initialize {ch} (No VDO and No RTSP)")
            except Exception as e:
                self.log.error(f"Failed to initialize {ch}: {e}")

    def _find_fallback_vdo(self, ch_prefix):
        """Finds a speed-optimized file in testing/outcome/ or local vdo."""
        # 1. Check outcome folder for _fast versions first (Priority)
        search_dirs = [
            os.path.join("testing", "outcome"),
            os.path.join("testing", "vdo")
        ]
        
        # Flex search: CH101 or CH_101
        patterns = [ch_prefix, ch_prefix.replace("CH", "CH_")]
        
        for vdo_dir in search_dirs:
            if not os.path.exists(vdo_dir):
                continue
            
            try:
                files = os.listdir(vdo_dir)
                # Sort to prefer '_fast.mp4'
                files.sort(key=lambda x: ("_fast" not in x.lower(), x))
                
                for f in files:
                    for p in patterns:
                        if f.upper().startswith(p.upper()):
                            return os.path.join(vdo_dir, f)
            except Exception:
                pass
        return None

    def _process_cycle(self, frames):
        # Dynamic Key Resolution
        sorted_keys = sorted(frames.keys())
        if len(sorted_keys) < 2: return # Need both
        
        f_key = sorted_keys[0] # LPR / Front
        t_key = sorted_keys[1] # AI / Top
        
        f_frame = frames.get(f_key)
        t_frame = frames.get(t_key)
        
        if f_frame is None or t_frame is None:
            return

        # Initialize normalized container for UI updates
        normalized_frames = {'LPR': f_frame, 'AI': t_frame}
        self.latest_frames = normalized_frames

        # --- AI TOGGLE LOGIC ---
        if not self.ai_enabled:
            # Fallback Snap Logic (10s interval)
            now = time.time()
            if now - self.last_snap_time > 10:
                self.last_snap_time = now
                self.log.info("AI OFF: Executing Fallback Snap...")
                self._save_snap_image(f_frame, "LPR", f_key)
                self._save_snap_image(t_frame, "TopView", t_key)
            return
        # -----------------------

        # 1. AI Analysis & Visualization
        # Front Camera (CH101) -> LPR [classification.pt]
        # Top Camera (CH201) -> AI Classification [objectdetection.pt]
        
        # --- LPR Detection (Front Frame) ---
        lpr_res = self.lpr_engine.detect(f_frame, skip_ocr=False)
        if lpr_res:
            x1, y1, x2, y2 = lpr_res.bbox
            cv2.rectangle(f_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            if lpr_res.text:
                cv2.putText(f_frame, lpr_res.text, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            self.plate_number = lpr_res.text if lpr_res.text else "UNKNOWN"
        else:
            self.plate_number = "-"

        # --- AI Classification (Top Frame) ---
        cls_res = self.cls_engine.analyze(t_frame)
        self.latest_cls_res = cls_res
        
        # Draw AI BBox (Trash/Cane)
        detections = cls_res.get('detections', [])
        for (x1, y1, x2, y2) in detections:
            cv2.rectangle(t_frame, (x1, y1), (x2, y2), (0, 165, 255), 2) # Orange
            
        # Update Results for UI consumption (Annotated)
        normalized_frames['LPR'] = f_frame
        normalized_frames['AI'] = t_frame
        self.latest_frames = normalized_frames
        
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

    def _save_snap_image(self, frame, view_type, ch_name):
        try:
            # Path: ./images/{factory}/raw_images/{view_type}/{ch_name}/{Date}/filename
            factory_info = self.db.get_factory_info()
            factory = factory_info.get('factory_id', 'MDC')
            
            date_folder = datetime.now().strftime("%Y%m%d")
            base_dir = os.path.join("images", factory, "raw_images", view_type, ch_name, date_folder)
            os.makedirs(base_dir, exist_ok=True)
            
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{factory}_{ch_name}_{ts_str}.jpg"
            save_path = os.path.join(base_dir, filename)
            
            # Save Raw Image
            cv2.imwrite(save_path, frame)
        except Exception as e:
            self.log.error(f"Failed to save snap: {e}")

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
