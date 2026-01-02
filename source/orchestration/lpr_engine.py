# -*- coding: utf-8 -*-
"""
lpr_engine.py
- YOLO + OCR for license plate recognition (LPR)
- normalize plate text (swap ambiguous letters to digits)
- no knowledge about lanes/cameras/filesystem layout (low coupling)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np
from ultralytics import YOLO
import easyocr

BBox = Tuple[int, int, int, int]


@dataclass(frozen=True)
class LPRResult:
    bbox: BBox
    text: Optional[str]
    conf: float


import threading

class LPREngine:
    def __init__(
        self,
        model_path: str,
        conf_th: float = 0.7,
        logger: Optional[logging.Logger] = None,
        ocr_lang: str = "en",
        use_gpu: bool = False,
        global_lock: Optional[threading.Lock] = None
    ):
        self.log = logger or logging.getLogger("run_realtime.lpr")
        self.conf_th = float(conf_th)
        self._lock = global_lock if global_lock else threading.Lock()

        self.log.info("Loading YOLO model: %s", model_path)
        self.model = YOLO(model_path)

        self.log.info("Loading EasyOCR (lang=%s, gpu=%s) ...", ocr_lang, use_gpu)
        # gpu=False for compatibility, can be True if CUDA available
        self.reader = easyocr.Reader([ocr_lang], gpu=use_gpu)
        
        # Determine device for YOLO
        self.device = 0 if use_gpu else "cpu"
        self.log.info("LPR engine ready. YOLO Device=%s", self.device)

        # Aggressive alpha -> digit swap
        # Based on user request: "Only numbers", pattern "xx-xxxx"
        self._text_swap = {
            "O": "0", "D": "0", "Q": "0", "U": "0", "C": "0",
            "I": "1", "L": "1", "T": "1", "J": "1",
            "Z": "2",
            "A": "4",
            "S": "5",
            "G": "6", "E": "6",
            "Y": "7", "V": "7",
            "B": "8",
            "P": "9", "F": "??" # P->9 sometimes, F? ambiguous
        }

    def detect(self, frame_bgr: np.ndarray, skip_ocr: bool = False) -> Optional[LPRResult]:
        """
        Detect plate bbox + OCR text from a single BGR frame.
        """
        if frame_bgr is None:
            return None

        # YOLO detect (Global Lock)
        with self._lock:
            results = self.model(frame_bgr, verbose=False, device=self.device)
        if not results:
            return None

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return None

        # Find best plate (class 0, highest conf)
        best = None
        for b in boxes:
            try:
                if int(b.cls) != 0:
                    continue
                conf = float(b.conf)
                if conf < self.conf_th:
                    continue
                if best is None or conf > float(best.conf):
                    best = b
            except Exception:
                continue

        if best is None:
            return None

        conf = float(best.conf)
        x1, y1, x2, y2 = map(int, best.xyxy[0])
        
        if skip_ocr:
             return LPRResult(bbox=(x1, y1, x2, y2), text=None, conf=conf)

        # Safe crop
        h, w = frame_bgr.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        plate_text = self._ocr_plate(frame_bgr, (x1, y1, x2, y2))
        return LPRResult(bbox=(x1, y1, x2, y2), text=plate_text, conf=conf)

    def _ocr_plate(self, frame_bgr: np.ndarray, bbox: BBox) -> Optional[str]:
        x1, y1, x2, y2 = bbox
        try:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            roi = gray[y1:y2, x1:x2]
            if roi.size == 0:
                return "00-0000"

            # Resize for better OCR
            roi_disp = cv2.resize(roi, (300, 100))

            # Allowlist: digits + hyphen + some alphas to swap later?
            # EasyOCR best works if we let it read everything then we filter.
            with self._lock:
                result = self.reader.readtext(
                    roi_disp, 
                    detail=1,
                    paragraph=False,
                    allowlist=None 
                )

            if not result:
                return "00-0000"

            best_text = ""
            best_conf = -1.0
            
            for (_, text, conf) in result:
                if conf > best_conf:
                    best_conf = conf
                    best_text = text
            
            if not best_text:
                return "00-0000"

            return self.normalize_text(best_text)

        except Exception:
            return "00-0000"

    def normalize_text(self, text: str) -> str:
        # 1. Upper case & generic cleanup
        t = (text or "").upper().strip().replace(" ", "")
        
        # 2. Aggressive Swap (Alpha -> Digit)
        # Apply strict mapping to fix common OCR errors
        t_list = list(t)
        swapped_chars = []
        for ch in t_list:
            if ch in self._text_swap:
                swapped_chars.append(self._text_swap[ch])
            elif ch.isdigit():
                 swapped_chars.append(ch)
            # Ignore hyphens or unknown chars for now, we only want digits to build the pattern
        
        digits = "".join(swapped_chars)

        # 3. Enforce Pattern: xx-xxxx (Total 6 digits)
        if len(digits) == 6:
            return f"{digits[:2]}-{digits[2:]}"
        
        # Fallback if we don't have exactly 6 identifiable digits
        return "00-0000"

