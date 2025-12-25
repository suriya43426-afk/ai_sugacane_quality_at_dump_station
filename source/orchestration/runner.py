import os
import sys
import subprocess
import queue


def run_python_script_blocking(py_file: str, cwd: str, log_q: queue.Queue, title: str) -> int:
    if not os.path.exists(py_file):
        log_q.put(("ERROR", f"[{title}] File not found: {py_file}"))
        return 2

    cmd = [sys.executable, py_file]
    log_q.put(("INFO", f"[{title}] Starting: {' '.join(cmd)}"))

    try:
        p = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert p.stdout is not None
        for line in p.stdout:
            line = line.rstrip("\n")
            if line:
                log_q.put(("INFO", line))

        rc = p.wait()
        log_q.put(("INFO", f"[{title}] Finished with code={rc}"))
        return rc

    except Exception as e:
        log_q.put(("ERROR", f"[{title}] Failed: {e}"))
        return 1
