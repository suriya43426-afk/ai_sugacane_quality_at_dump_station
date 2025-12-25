# -*- coding: utf-8 -*-
"""
tracker.py
- Small state machine to decide "TRIGGER" based on stable bbox over time
- Also provides anti-duplicate gap control per lane
- No camera/RTSP knowledge, no filesystem knowledge (low coupling)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

BBox = Tuple[int, int, int, int]


@dataclass
class TriggerDecision:
    triggered: bool
    stable_for: float = 0.0
    bbox: Optional[BBox] = None


class StabilityTracker:
    """
    Tracks a moving bbox and triggers when it stays stable for >= stable_sec.

    - Uses position similarity tolerance to match bboxes
    - Uses exit_tolerance to clear stale tracks if bbox disappears
    - Does not assume plate text is present
    """

    def __init__(
        self,
        stable_sec: float,
        pos_tolerance_px: int,
        exit_tolerance: int,
        min_gap_sec: float,
    ):
        self.stable_sec = float(stable_sec)
        self.pos_tol = int(pos_tolerance_px)
        self.exit_tol = int(exit_tolerance)
        self.min_gap_sec = float(min_gap_sec)

        self._pos_start: Dict[BBox, float] = {}
        self._exit_count: Dict[BBox, int] = {}
        self._last_trigger_ts: float = 0.0

    def can_attempt(self, now_ts: float) -> bool:
        return (now_ts - self._last_trigger_ts) >= self.min_gap_sec

    def mark_trigger(self, now_ts: float) -> None:
        self._last_trigger_ts = now_ts

    def update(self, now_ts: float, bbox: Optional[BBox]) -> TriggerDecision:
        """
        Update tracker state for a new detection result (bbox or None).
        Returns TriggerDecision(triggered=True) when stable criteria is met.
        """
        if bbox is None:
            self._handle_no_bbox()
            return TriggerDecision(triggered=False)

        matched = None
        for prev in list(self._pos_start.keys()):
            if self._pos_similar(prev, bbox):
                matched = prev
                break

        if matched is None:
            # new candidate
            self._pos_start[bbox] = now_ts
            self._exit_count[bbox] = 0
            return TriggerDecision(triggered=False, bbox=bbox)

        # existing candidate continues
        t0 = self._pos_start.get(matched, now_ts)
        stable_for = now_ts - t0
        self._exit_count[matched] = 0

        if stable_for >= self.stable_sec:
            # cleanup only that object
            self._pos_start.pop(matched, None)
            self._exit_count.pop(matched, None)
            return TriggerDecision(triggered=True, stable_for=stable_for, bbox=bbox)

        return TriggerDecision(triggered=False, stable_for=stable_for, bbox=bbox)

    def _handle_no_bbox(self) -> None:
        for k in list(self._pos_start.keys()):
            self._exit_count[k] = self._exit_count.get(k, 0) + 1
            if self._exit_count[k] >= self.exit_tol:
                self._pos_start.pop(k, None)
                self._exit_count.pop(k, None)

    def _pos_similar(self, a: BBox, b: BBox) -> bool:
        return (
            abs(a[0] - b[0]) <= self.pos_tol
            and abs(a[1] - b[1]) <= self.pos_tol
            and abs(a[2] - b[2]) <= self.pos_tol
            and abs(a[3] - b[3]) <= self.pos_tol
        )
