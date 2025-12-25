import os
import configparser
from dataclasses import dataclass
from typing import Tuple, Dict


@dataclass(frozen=True)
class AppPaths:
    project_root: str
    config_file: str
    run_ai_daily_py: str
    run_realtime_py: str
    agent_py: str
    log_file: str


def build_paths() -> AppPaths:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return AppPaths(
        project_root=project_root,
        config_file=os.path.join(project_root, "config.txt"),
        run_ai_daily_py=os.path.join(project_root, "source", "run_ai_daily.py"),
        run_realtime_py=os.path.join(project_root, "source", "run_realtime.py"),
        agent_py=os.path.join(project_root, "source", "agent.py"),
        log_file=os.path.join(project_root, "ai_orchestration.log"),
    )


def load_config(config_path: str) -> Tuple[configparser.ConfigParser, Dict[str, str]]:
    cp = configparser.ConfigParser()
    
    # Try multiple encodings to be robust against Windows Notepad (ANSI vs UTF-8)
    encodings = ["utf-8-sig", "cp874", "latin1"]
    
    if os.path.exists(config_path):
        for enc in encodings:
            try:
                cp.read(config_path, encoding=enc)
                # Check if we actually read something useful (e.g. has sections)
                if cp.sections() or cp.defaults():
                    break
            except Exception:
                continue

    cfg: Dict[str, str] = {}

    # ConfigParser's DEFAULT section is treated specially
    # access via cp["DEFAULT"] or cp.defaults()
    # Note: cp.has_section("DEFAULT") might return False but defaults() has data
    
    # Merge defaults first
    for k, v in cp.defaults().items():
        cfg[k.lower().strip()] = v.strip()

    if cp.has_section("DEFAULT"):
        for k, v in cp["DEFAULT"].items():
            cfg[k.lower().strip()] = v.strip()

    if cp.has_section("NVR1"):
        for k, v in cp["NVR1"].items():
            cfg[f"nvr1_{k.lower().strip()}"] = v.strip()

    return cp, cfg


def clamp_lanes(lanes: int, min_lane: int = 1, max_lane: int = 8) -> int:
    return max(min_lane, min(max_lane, int(lanes)))


def get_total_lanes(cp: configparser.ConfigParser, fallback: int = 1) -> int:
    try:
        return cp.getint("DEFAULT", "total_lanes", fallback=fallback)
    except Exception:
        return fallback


def get_rtsp_base(cfg: Dict[str, str]) -> str:
    ip = cfg.get("nvr1_camera_ip", "")
    user = cfg.get("nvr1_camera_username", "")
    pwd = cfg.get("nvr1_camera_password", "")
    return f"rtsp://{user}:{pwd}@{ip}/Streaming/channels/"
