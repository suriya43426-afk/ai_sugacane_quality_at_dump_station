import os
import time
import threading
import queue
from dataclasses import dataclass
import cv2


CAM_RECONNECT_SEC = 3
CAM_OPEN_TIMEOUT_SEC = 10


@dataclass
class CameraState:
    channel: int
    name: str
    status: str = "Disconnected"
    last_frame_ts: float = 0.0
    last_ok_ts: float = 0.0


def letterbox_to_fit(bgr, target_w: int, target_h: int):
    h, w = bgr.shape[:2]
    if w <= 0 or h <= 0:
        return None

    scale = min(target_w / w, target_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resized = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = cv2.cvtColor(
        cv2.copyMakeBorder(
            resized,
            top=(target_h - new_h) // 2,
            bottom=(target_h - new_h) - (target_h - new_h) // 2,
            left=(target_w - new_w) // 2,
            right=(target_w - new_w) - (target_w - new_w) // 2,
            borderType=cv2.BORDER_CONSTANT,
            value=(0, 0, 0),
        ),
        cv2.COLOR_BGR2RGB,
    )
    return canvas


class CameraWorker(threading.Thread):
    def __init__(self, rtsp_url: str, state: CameraState, frame_q: queue.Queue, stop_event: threading.Event, detector=None):
        super().__init__(daemon=True)
        self.rtsp_url = rtsp_url
        self.state = state
        self.frame_q = frame_q
        self.stop_event = stop_event
        self.detector = detector
        
        # Reader specific
        self.cap = None
        self.latest_frame = None
        self.lock = threading.Lock()
        self.reader_active = False

    def run(self):
        # Force TCP
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        
        while not self.stop_event.is_set():
            try:
                self.state.status = "Connecting..."
                self._push_status()

                # Open Camera
                self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                
                t0 = time.time()
                while not self.cap.isOpened() and not self.stop_event.is_set():
                    if time.time() - t0 > CAM_OPEN_TIMEOUT_SEC:
                        break
                    time.sleep(0.2)

                if not self.cap.isOpened():
                    self.state.status = "Disconnected"
                    self._push_status()
                    time.sleep(CAM_RECONNECT_SEC)
                    continue

                self.state.status = "Connected"
                self.state.last_ok_ts = time.time()
                self._push_status()

                # Start Reader Thread
                self.reader_active = True
                t_read = threading.Thread(target=self._reader_loop, daemon=True)
                t_read.start()

                # Processor Loop
                while not self.stop_event.is_set() and self.reader_active:
                    # Get latest frame
                    frame = None
                    with self.lock:
                        if self.latest_frame is not None:
                            frame = self.latest_frame.copy()
                    
                    if frame is None:
                        # No frame yet or stream died
                        if not self.reader_active:
                            break
                        time.sleep(0.01)
                        continue

                    # Current time logic
                    now = time.time()
                    self.state.last_frame_ts = now
                    self.state.last_ok_ts = now
                    self.state.status = "Connected"

                    # Run detector (Blocking here is fine now, it won't stop the reader!)
                    if self.detector:
                        try:
                            # Detector draws on 'frame' in-place
                            self.detector(frame, self.state.channel)
                        except Exception:
                            pass

                    # Manage UI Queue
                    try:
                        while self.frame_q.qsize() > 2:
                            self.frame_q.get_nowait()
                    except Exception:
                        pass

                    self.frame_q.put(("FRAME", self.state.channel, frame, now))
                    
                    # Cap processing FPS to ~25 to save CPU, or let detector limit it.
                    # Since detector has built-in 5fps limit in ui_app, this loop will spin fast 
                    # but only detect 5 times. 
                    # We should sleep a bit to not burn CPU on "copying" frames 1000 times/sec.
                    time.sleep(0.03) # ~30 FPS

                # Cleanup
                self.reader_active = False
                t_read.join(timeout=1.0)
                if self.cap:
                    self.cap.release()

            except Exception as e:
                self.state.status = f"Error: {e}"
                self._push_status()
                time.sleep(CAM_RECONNECT_SEC)

    def _reader_loop(self):
        """Reads frames as fast as possible to empty buffer"""
        while self.reader_active and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                self.reader_active = False
                break
            with self.lock:
                self.latest_frame = frame
        self.reader_active = False

    def _push_status(self):
        self.frame_q.put(("STATUS", self.state.channel, self.state.status, time.time()))


class CameraManager:
    def __init__(self, rtsp_base: str, channels: list[int], ui_q: queue.Queue, detector=None):
        self.rtsp_base = rtsp_base
        self.channels = channels
        self.ui_q = ui_q
        self.detector = detector

        self.stop_event = threading.Event()
        self.workers: list[CameraWorker] = []
        self.states: dict[int, CameraState] = {}
        self.frame_q: queue.Queue = queue.Queue()

        for ch in channels:
            self.states[ch] = CameraState(channel=ch, name=f"CAM_{ch}")

    def start(self):
        self.stop_event.clear()
        self.workers.clear()

        for ch in self.channels:
            url = f"{self.rtsp_base}{ch}"
            w = CameraWorker(url, self.states[ch], self.frame_q, self.stop_event, detector=self.detector)
            self.workers.append(w)
            w.start()

        threading.Thread(target=self._pump_loop, daemon=True).start()

    def stop(self):
        self.stop_event.set()

    def _pump_loop(self):
        while not self.stop_event.is_set():
            try:
                msg = self.frame_q.get(timeout=0.5)
                self.ui_q.put(msg)
            except queue.Empty:
                continue
            except Exception:
                continue

    def get_status(self, channel: int) -> tuple[str, float]:
        """Return (status, age_seconds)"""
        if channel in self.states:
            s = self.states[channel]
            age = max(0.0, time.time() - s.last_ok_ts)
            return s.status, age
        return "Unknown", 0.0
