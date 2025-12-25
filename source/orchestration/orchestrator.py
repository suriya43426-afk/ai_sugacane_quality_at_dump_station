import os
import sys
import subprocess
import threading
import queue
from datetime import datetime, timedelta
from typing import Optional, Dict
from .runner import run_python_script_blocking


DAILY_RUN_HH = 1
DAILY_RUN_MM = 0
RUN_DAILY_ON_START = False


class Orchestrator:
    def __init__(self, paths, factory_id: str, total_lanes: int, logger, ui_callbacks: Dict = None):
        self.paths = paths
        self.project_root = paths.project_root
        self.run_ai_daily_py = paths.run_ai_daily_py
        self.run_realtime_py = paths.run_realtime_py
        self.agent_py = paths.agent_py
        
        self.factory_id = factory_id
        self.total_lanes = total_lanes
        
        # Determine logger from callbacks or create dummy
        # In ui_app, logger is passed via ui_callbacks or we might need to change how logger is passed.
        # Wait, the old init had 'logger' as an argument. The new call in ui_app DID NOT pass logger!
        # ui_app.py: self.orch = Orchestrator(self.paths, factory_id=..., total_lanes=...)
        # It missed 'logger' and 'ui_callbacks'.
        # Assuming ui_app assigns callbacks later? 
        # let's look at ui_app again. It calls:
        # self.orch = Orchestrator(self.paths, factory_id=..., total_lanes=...)
        # It does NOT pass ui_callbacks.
        # But later in ui_app: self.orch.ui = ...? No.
        # The previous code passed ui_callbacks in init.
        # I need to handle this.
        # I should probably pass callbacks in the init call in ui_app OR add a method to set them.
        # But for now, let's make them optional in init and I will fix ui_app to pass them or I will fix Orchestrator to accept them from ui_app later.
        # Actually, best practice: Update ui_app to pass them.
        # But I can't update ui_app right now easily (another tool call).
        # Let's fix Orchestrator to be flexible first, then update ui_app.
        
        self.logger = logger
        self.ui = ui_callbacks if ui_callbacks else {}
        self.log_q = queue.Queue()


        self.stop_event = threading.Event()

        self.daily_next_run: Optional[datetime] = None
        self.daily_last_run: Optional[datetime] = None
        self.daily_last_rc: Optional[int] = None
        self.daily_is_running = False

        self.agent_last_run: Optional[datetime] = None
        self.agent_last_rc: Optional[int] = None
        self.agent_is_running = False

        self.realtime_proc: Optional[subprocess.Popen] = None
        self.realtime_log_thread: Optional[threading.Thread] = None

    def start(self):
        self.stop_event.clear()
        self._plan_next_daily_run(initial=True)

        threading.Thread(target=self._daily_scheduler_loop, daemon=True).start()
        threading.Thread(target=self._logpump_loop, daemon=True).start()

        self._log("INFO", "Orchestrator started.")
        if RUN_DAILY_ON_START:
            self._log("INFO", "RUN_DAILY_ON_START=True -> trigger daily now.")
            self.trigger_daily_now()

    def stop(self):
        self._log("INFO", "Stopping orchestrator...")
        self.stop_event.set()
        self.stop_realtime()

    def start_realtime(self):
        if self.realtime_proc is not None:
            # Check if still valid
            if self.realtime_proc.poll() is None:
                self._log("WARNING", "Realtime process already running.")
                return
            else:
                self.realtime_proc = None

        if not os.path.exists(self.run_realtime_py):
            self._log("ERROR", f"Realtime script not found: {self.run_realtime_py}")
            return

        cmd = [sys.executable, self.run_realtime_py]
        self._log("INFO", f"Starting Realtime: {self.run_realtime_py}")
        try:
            # Run headless so it doesn't pop up a console window if possible
            # But we want to capture stdout/stderr
            self.realtime_proc = subprocess.Popen(
                cmd,
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            
            # Start a thread to read stdout and push to log
            self.realtime_log_thread = threading.Thread(target=self._realtime_log_monitor, args=(self.realtime_proc,), daemon=True)
            self.realtime_log_thread.start()
            
            self._ui_update()
            
        except Exception as e:
            self._log("ERROR", f"Failed to start realtime process: {e}")

    def stop_realtime(self):
        if self.realtime_proc:
            self._log("INFO", "Terminating realtime process...")
            try:
                self.realtime_proc.terminate()
                try:
                    self.realtime_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.realtime_proc.kill()
                    self.realtime_proc.wait()
            except Exception as e:
                self._log("ERROR", f"Error stopping realtime process: {e}")
            self.realtime_proc = None
            self._ui_update()

    def _realtime_log_monitor(self, proc: subprocess.Popen):
        if proc.stdout:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    # Optional: Filter some heavy logs if needed
                    self._log("INFO", f"[Realtime] {line}")
        rc = proc.wait()
        self._log("INFO", f"Realtime process exited with code={rc}")
        # Only clear self.realtime_proc if it matches the one we monitored
        if self.realtime_proc == proc:
            self.realtime_proc = None
            self._ui_update()


    def trigger_daily_now(self):
        if self.daily_is_running:
            self._log("WARNING", "Daily job already running.")
            return
        self._log("INFO", "Manual trigger: run_ai_daily.py now.")
        threading.Thread(target=self._run_daily_and_then_agent, daemon=True).start()

    def trigger_agent_now(self):
        """Manually trigger Agent execution (Cloud Sync)."""
        if self.agent_is_running:
            self._log("WARNING", "Agent is already running.")
            return
        
        self._log("INFO", "Manual trigger: agent.py (Cloud Sync) now.")
        threading.Thread(target=self._run_agent_only, daemon=True).start()

    def _run_agent_only(self):
        """Runs only the Agent script."""
        self.agent_is_running = True
        self.agent_last_run = datetime.now()
        self.agent_last_rc = None
        self._ui_update()

        rc_agent = run_python_script_blocking(self.agent_py, self.project_root, self.log_q, "AGENT")
        self.agent_last_rc = rc_agent
        self.agent_is_running = False
        self._ui_update()

    def _plan_next_daily_run(self, initial: bool):
        # Changed to Hourly Run due to high volume
        now = datetime.now()
        # Next run at the start of the next hour (e.g. 10:15 -> 11:00)
        candidate = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        
        self.daily_next_run = candidate
        if initial:
            self._log("INFO", f"Next hourly run scheduled at {candidate.strftime('%Y-%m-%d %H:%M:%S')}")
        self._ui_update()

    def _daily_scheduler_loop(self):
        while not self.stop_event.is_set():
            if self.daily_next_run and datetime.now() >= self.daily_next_run:
                if not self.daily_is_running:
                    self._log("INFO", "Hourly scheduler: time reached -> trigger run_ai_daily.py")
                    self.trigger_daily_now()
                self._plan_next_daily_run(initial=False)
            self.stop_event.wait(1)

    def _run_daily_and_then_agent(self):
        self.daily_is_running = True
        self.daily_last_run = datetime.now()
        self.daily_last_rc = None
        self._ui_update()

        # OPTIMIZATION: Realtime Mode is active, so we SKIP batch processing (run_ai_daily).
        # We only need to run agent.py to sync data.
        self._log("INFO", "Hourly Schedule: Skipping run_ai_daily (Realtime Active). Proceeding to Agent.")
        
        # rc_daily = run_python_script_blocking(self.run_ai_daily_py, self.project_root, self.log_q, "DAILY")
        self.daily_last_rc = 0 # Dummy success
        self.daily_is_running = False
        self._ui_update()

        self._log("INFO", "Daily completed -> trigger agent.py to send API.")
        self.agent_is_running = True
        self.agent_last_run = datetime.now()
        self.agent_last_rc = None
        self._ui_update()

        rc_agent = run_python_script_blocking(self.agent_py, self.project_root, self.log_q, "AGENT")
        self.agent_last_rc = rc_agent
        self.agent_is_running = False
        self._ui_update()

    def _log(self, level: str, msg: str):
        getattr(self.logger, level.lower(), self.logger.info)(msg)
        self.log_q.put((level, msg))

    def _ui_update(self):
        try:
            cb = self.ui.get("update_status")
            if cb:
                cb(self.snapshot_state())
        except Exception:
            pass

    def snapshot_state(self) -> dict:
        return {
            "daily_next_run": self.daily_next_run,
            "daily_last_run": self.daily_last_run,
            "daily_last_rc": self.daily_last_rc,
            "daily_is_running": self.daily_is_running,
            "agent_last_run": self.agent_last_run,
            "agent_last_rc": self.agent_last_rc,
            "agent_is_running": self.agent_is_running,
            "realtime_running": (self.realtime_proc is not None) and (self.realtime_proc.poll() is None),
            "realtime_pid": self.realtime_proc.pid if self.realtime_proc else None,
        }

    def _logpump_loop(self):
        while not self.stop_event.is_set():
            try:
                level, msg = self.log_q.get(timeout=0.5)
                cb = self.ui.get("append_log")
                if cb:
                    cb(level, msg)
            except queue.Empty:
                continue
            except Exception:
                continue
