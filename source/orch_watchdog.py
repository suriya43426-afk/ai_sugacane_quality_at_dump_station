import os, sys, time, subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ORCH_PY = os.path.join(PROJECT_ROOT, "source", "ai_orchestration.py")

RESTART_DELAY = 5

def main():
    while True:
        try:
            p = subprocess.Popen([sys.executable, ORCH_PY], cwd=PROJECT_ROOT)
            rc = p.wait()
            # ถ้า exit code = 0 ให้ถือว่าปิดปกติ (อาจตั้งใจปิด)
            if rc == 0:
                break
            time.sleep(RESTART_DELAY)
        except Exception:
            time.sleep(RESTART_DELAY)

if __name__ == "__main__":
    main()
