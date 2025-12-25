# -*- coding: utf-8 -*-
"""
snapshotter.py
- Open RTSP per channel and save a single frame to event folder
- Avoid UI, only filesystem + camera IO
- No knowledge of detection logic (low coupling)
"""

from __future__ import annotations

import os
import time
import json
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import cv2

BBox = Tuple[int, int, int, int]


@dataclass
class SnapshotConfig:
    rtsp_base: str
    images_dir: str
    capture_max_read_sec: float = 4.0
    capture_min_frame_index: int = 5


@dataclass
class EventMeta:
    event_id: str
    factory: str
    lane: int
    ts_trigger: float
    ts_iso: str
    channels: List[int]
    primary_channel: int

    plate_text: Optional[str] = None
    plate_conf: Optional[float] = None
    plate_bbox: Optional[BBox] = None

    saved: Dict[int, str] = None  # channel -> filename
    errors: List[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


class Snapshotter:
    def __init__(self, cfg: SnapshotConfig, logger: Optional[logging.Logger] = None):
        self.cfg = cfg
        self.log = logger or logging.getLogger("run_realtime.snapshotter")
        os.makedirs(self.cfg.images_dir, exist_ok=True)

    def make_event_folder(self, event_id: str) -> str:
        folder = os.path.join(self.cfg.images_dir, event_id)
        os.makedirs(folder, exist_ok=True)
        return folder

    def snap_event(
        self,
        factory: str,
        lane: int,
        channels: List[int],
        primary_channel: int,
        ts_trigger: float,
        plate_text: Optional[str],
        plate_conf: Optional[float],
        plate_bbox: Optional[BBox],
    ) -> tuple[str, EventMeta]:
        """
        Capture frames for given channels and write meta.json into the event folder.
        Returns (event_folder, meta)
        """
        event_id = self._event_id(factory, lane, ts_trigger)
        event_folder = self.make_event_folder(event_id)

        meta = EventMeta(
            event_id=event_id,
            factory=factory,
            lane=lane,
            ts_trigger=ts_trigger,
            ts_iso=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts_trigger)),
            channels=channels,
            primary_channel=primary_channel,
            plate_text=plate_text,
            plate_conf=plate_conf,
            plate_bbox=plate_bbox,
            saved={},
            errors=[],
        )

        for ch in channels:
            try:
                fn = self._capture_one(ch, event_folder, plate_text if ch == primary_channel else None)
                if fn:
                    meta.saved[ch] = fn
            except Exception as e:
                meta.errors.append(f"capture ch{ch}: {e}")

        # write meta.json atomically
        tmp = os.path.join(event_folder, "meta.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(meta.to_json())
        os.replace(tmp, os.path.join(event_folder, "meta.json"))

        return event_folder, meta

    def _capture_one(self, channel: int, event_folder: str, plate_text_for_name: Optional[str]) -> Optional[str]:
        url = f"{self.cfg.rtsp_base}{channel}"
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        t0 = time.time()

        try:
            while cap.isOpened() and (time.time() - t0) < self.cfg.capture_max_read_sec:
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                fn_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                if fn_idx < self.cfg.capture_min_frame_index:
                    continue

                if plate_text_for_name:
                    safe = (plate_text_for_name or "NO_PLATE").replace(" ", "").replace("/", "-").replace("\\", "-")
                    filename = f"{channel}_{safe}.jpg"
                else:
                    filename = f"{channel}.jpg"

                out = os.path.join(event_folder, filename)
                cv2.imwrite(out, frame)
                return filename
        finally:
            try:
                cap.release()
            except Exception:
                pass

        return None

    @staticmethod
    def _event_id(factory: str, lane: int, ts_trigger: float) -> str:
        ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(ts_trigger))
        return f"{ts}_{factory}_L{lane}"
