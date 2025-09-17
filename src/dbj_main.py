import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional, List

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    print("ERROR: Python >=3.11 required (needs tomllib).", file=sys.stderr)
    sys.exit(1)

@dataclass
class AppRule:
    name: str
    cmd: str
    class_regex: str
    workspace: int
    monitor: Optional[str] = None
    timeout_s: Optional[int] = None

@dataclass
class GeneralCfg:
    prewarm_workspaces: List[int]
    poll_interval_ms: int
    default_timeout_s: int

@dataclass
class Config:
    general: GeneralCfg
    apps: List[AppRule]

def run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def dispatch(cmd: str) -> None:
    run(f"hyprctl dispatch {cmd}")
def hypr_clients() -> list:
    out = run("hyprctl -j clients").stdout
    return json.loads(out) if out.strip() else []
def move_to_workspace(addr: str, ws: int) -> None:
    dispatch(f"movetoworkspace {ws} address:{addr}")

def move_to_monitor(addr: str, monitor: str) -> None:
    dispatch(f"focuswindow address:{addr}")
    dispatch(f"movetomonitor {monitor} address:{addr}")

def spawn(cmd: str) -> None:
    subprocess.Popen(cmd, shell=True)

def load_config(path: str) -> Config:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    general = data.get("general", {})
    gc = GeneralCfg(
        prewarm_workspaces=general.get("prewarm_workspaces", []),
        poll_interval_ms=int(general.get("poll_interval_ms", 200)),
        default_timeout_s=int(general.get("default_timeout_s", 20)),
    )

    apps: List[AppRule] = []
    for app in data.get("app", []):
        apps.append(AppRule(
            name=app["name"],
            cmd=app["cmd"],
            class_regex=app["class_regex"],
            workspace=int(app["workspace"]),
            monitor=app.get("monitor"),
            timeout_s=app.get("timeout_s"),
        ))
    return Config(general=gc, apps=apps)

def wait_for_window(class_regex: str, timeout_s: int, poll_ms: int) -> Optional[str]:
    pat = re.compile(class_regex)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        for c in hypr_clients():
            if pat.search(c.get("class", "") or ""):
                return c.get("address")
        time.sleep(poll_ms / 1000.0)
    return None

def prewarm_workspaces(ws_list: List[int]) -> None:
    if not ws_list:
        return
    batch_parts = [f"dispatch workspace {ws}" for ws in ws_list]
    run("hyprctl --batch '" + "; ".join(batch_parts) + "'")

def orchestrate(cfg: Config, dry_run: bool=False) -> int:
    prewarm_workspaces(cfg.general.prewarm_workspaces)

    for rule in cfg.apps:
        print(f"[dbj] launching: {rule.name} -> ws{rule.workspace}" + (f" @ {rule.monitor}" if rule.monitor else ""))
        if not dry_run:
            spawn(rule.cmd)

        timeout = rule.timeout_s or cfg.general.default_timeout_s
        addr = wait_for_window(rule.class_regex, timeout, cfg.general.poll_interval_ms)
        if not addr:
            print(f"[dbj][WARN] timeout esperando ventana de '{rule.name}' (regex={rule.class_regex})", file=sys.stderr)
            continue

        print(f"[dbj] found window {addr} for {rule.name}, moving to ws{rule.workspace}")
        if not dry_run:
            move_to_workspace(addr, rule.workspace)
            if rule.monitor:
                move_to_monitor(addr, rule.monitor)

    return 0

def parse_args():
    p = argparse.ArgumentParser(description="DBJ Orchestrator for Hyprland")
    p.add_argument("--config", default=os.path.expanduser("~/proyectos/dbj-autostart/config/config.toml"))
    p.add_argument("--dry-run", action="store_true", help="No lanza ni mueve; sólo imprime acciones")
    return p.parse_args()

def main():
    args = parse_args()
    if not os.path.exists(args.config):
        print(f"ERROR: No existe config: {args.config}", file=sys.stderr)
        sys.exit(2)

    cfg = load_config(args.config)
    rc = orchestrate(cfg, dry_run=args.dry_run)
    sys.exit(rc)

if __name__ == "__main__":
    main()



