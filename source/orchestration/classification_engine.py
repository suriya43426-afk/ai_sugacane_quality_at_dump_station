import logging
import cv2
import numpy as np
import torch
from ultralytics import YOLO
from typing import Optional, Dict, Any

import threading

class ClassificationEngine:
    def __init__(self, model_path: str, logger: Optional[logging.Logger] = None, use_gpu: bool = False, global_lock: Optional[threading.Lock] = None):
        self.log = logger or logging.getLogger("ClassificationEngine")
        self._lock = global_lock if global_lock else threading.Lock()
        self.log.info(f"Loading Classification model: {model_path}")
        self.model = YOLO(model_path)
        self.device = 0 if use_gpu and torch.cuda.is_available() else "cpu"
        
    def analyze(self, frame_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Analyze top-view frame for sugarcane status.
        Returns: {cane_detected, cane_percentage, dumping, contamination_level}
        """
        if frame_bgr is None:
            return {}

        with self._lock:
            results = self.model(frame_bgr, verbose=False, device=self.device)
        
        # Heuristic/Placeholder: Assuming classes: 0=Cane, 1=Dirt, 2=Trash
        # In a real classification model, we might get a single class result.
        # If it's a YOLOv8 detection model used for classification-like tasks:
        
        cane_detected = False
        cane_percentage = 0
        dumping = False
        contamination = "NONE"

        detections = []
        if results and (hasattr(results[0], 'boxes') and results[0].boxes is not None and len(results[0].boxes) > 0):
            # Detection model path
            cane_detected = True
            total_area = frame_bgr.shape[0] * frame_bgr.shape[1]
            cane_area = 0
            for box in results[0].boxes:
                # cls 0 = sugarcane
                if int(box.cls) == 0:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cane_area += (x2 - x1) * (y2 - y1)
                    detections.append((x1, y1, x2, y2))
                
            cane_percentage = min(100, int((cane_area / total_area) * 200)) # Scale factor
            if 10 < cane_percentage < 90:
                dumping = True
        elif results and (hasattr(results[0], 'probs') and results[0].probs is not None):
            # Classification model path
            probs = results[0].probs
            top1_idx = int(probs.top1)
            top1_conf = float(probs.top1conf)
            
            # Assuming class 0 is 'cane' or similar based on project context
            if top1_idx == 0 and top1_conf > 0.5:
                cane_detected = True
                cane_percentage = int(top1_conf * 100)
                dumping = True # If we detect cane in classification, assume it might be dumping
                
        return {
            'cane_detected': cane_detected,
            'cane_percentage': cane_percentage,
            'dumping': dumping,
            'contamination': contamination,
            'detections': detections
        }
