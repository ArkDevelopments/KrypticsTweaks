"""A small, dependency-free Windows gaming tweak terminal. Python 3.9+."""

import ctypes
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


STATE_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GameTweakTerminal" / "restore.json"
GUID = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.I)
COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=20)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or "Windows rejected the request.")
    return result.stdout.strip()


def powershell(command):
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "$ErrorActionPreference = 'Stop'; " + command])


def load_state():
    if not STATE_FILE.exists():
        return {}
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("Restore file is invalid; keep it for recovery before making more changes.")
    if "power_plan" in state and not GUID.fullmatch(str(state["power_plan"])):
        raise ValueError("Saved power plan is invalid.")
    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp.replace(STATE_FILE)


def active_plan():
    output = run(["powercfg", "/getactivescheme"])
    match = GUID.search(output)
    if not match:
        raise RuntimeError("Could not identify the current power plan.")
    name = re.search(r"\((.*)\)", output)
    return match.group(), name.group(1) if name else match.group()


def performance_power():
    current, _ = active_plan()
    high_performance = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    if current.lower() == high_performance:
        print("High performance is already active.")
        return
    available = run(["powercfg", "/list"])
    if high_performance not in available.lower():
        print("This PC does not expose the High performance plan.")
        print("Use Windows Settings > System > Power & battery > Power mode instead.")
        return
    print("High performance may reduce power-saving delays, but uses more power and heat.")
    print("Best used while plugged in; FPS improvements are not guaranteed.")
    if input("Apply High performance? [y/N] ").strip().lower() != "y":
        return
    state = load_state()
    # Save before changing Windows so an interrupted run still has a restore point.
    state.setdefault("power_plan", current)
    save_state(state)
    run(["powercfg", "/setactive", high_performance])
    print(paint("High performance enabled. Your original plan is saved.", "92"))


def game_priority():
    raw = powershell(
        "@(Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | "
        "Sort-Object ProcessName | Select-Object Id,ProcessName) | ConvertTo-Json -Compress"
    )
    processes = json.loads(raw) if raw else []
    if isinstance(processes, dict):
        processes = [processes]
    if not processes:
        print("No windowed applications found. Start your game first.")
        return
    print(paint("RUNNING APPLICATIONS", "96"))
    for index, process in enumerate(processes, 1):
        print(f"  {index:>2}  {process['ProcessName']:<34} PID {process['Id']}")
    print("\nChoose your game's executable, rather than its launcher.")
    choice = input("Application number (Enter to cancel): ").strip()
    if not choice:
        return
    if not choice.isdigit() or not 1 <= int(choice) <= len(processes):
        print("Choose one of the numbers listed above.")
        return
    pid = int(processes[int(choice) - 1]["Id"])
    details = json.loads(powershell(
        f"$p = Get-Process -Id {pid}; "
        "[pscustomobject]@{ Start=$p.StartTime.ToUniversalTime().Ticks.ToString(); "
        "Priority=$p.PriorityClass.ToString() } | ConvertTo-Json -Compress"
    ))
    if details["Priority"] != "Normal":
        print(f"Current priority is {details['Priority']}. Only Normal processes are adjusted.")
        return
    state = load_state()
    key = str(pid)
    state.setdefault("processes", {})[key] = details
    save_state(state)
    set_priority(pid, details["Start"], "AboveNormal")
    print(paint("Above normal priority applied for this running session.", "92"))
    print("This may help under CPU contention. Protected games can reject the change.")


def set_priority(pid, start, priority):
    if priority not in {"Normal", "AboveNormal"} or not str(start).isdigit():
        raise ValueError("Invalid saved process settings.")
    # PID + start time prevents modifying another app if Windows reuses a PID.
    return powershell(
        f"$p = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
        f"if ($null -eq $p -or $p.StartTime.ToUniversalTime().Ticks.ToString() -ne '{start}') "
        "{ 'expired' } else { "
        f"$p.PriorityClass = '{priority}'; 'applied' }}"
    )


def restore():
    state = load_state()
    if not state:
        print("No saved tweaks to restore.")
        return
    if "power_plan" in state:
        try:
            run(["powercfg", "/setactive", state["power_plan"]])
            del state["power_plan"]
            save_state(state)
            print("Original power plan restored.")
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            print(f"Power plan restore failed: {error}")
    for pid, details in list(state.get("processes", {}).items()):
        try:
            result = set_priority(pid, details["Start"], details["Priority"])
            del state["processes"][pid]
            save_state(state)
            print(f"PID {pid}: " + ("already exited." if result == "expired" else "priority restored."))
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
            print(f"PID {pid}: restore failed: {error}")
    if not state.get("processes"):
        state.pop("processes", None)
    save_state(state)
    print("Restore finished." if not state else "Some settings could not be restored; their backups are retained.")


def tips():
    print(paint("QUICK GAME SETUP", "96"))
    print("""
  1. Enable Windows Game Mode in Gaming settings.
  2. Disable background gameplay recording if you do not use it.
  3. Use your monitor's highest supported refresh rate.
  4. Enable NVIDIA Reflex or AMD Anti-Lag when supported by the game.
  5. Reduce ray tracing, shadows, and volumetrics if GPU-limited.
  6. Pick a sustainable FPS cap for steadier frame times.
  7. Close heavy background apps and unused recording overlays.
  8. Compare the same scene before and after each change.

  V-sync, frame caps, and VRR settings involve latency/tearing tradeoffs.
  Use the game's frame-time graph to check what works on your system.
""")


def main():
    global COLOR
    if sys.platform != "win32":
        print("Game Tweak Terminal requires Windows 10 or 11.")
        return 1
    if COLOR:
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        COLOR = bool(kernel.GetConsoleMode(handle, ctypes.byref(mode)) and
                     kernel.SetConsoleMode(handle, mode.value | 4))
    actions = {
        "1": performance_power,
        "2": game_priority,
        "3": lambda: os.startfile("ms-settings:gaming-gamemode"),
        "4": lambda: os.startfile("ms-settings:display-advanced"),
        "5": tips,
        "6": restore,
    }
    while True:
        if sys.stdout.isatty():
            os.system("cls")
        print(paint("\n  +----------------------------------------------------------+", "96"))
        print(paint("  |  PULSE  /  GAME TWEAK TERMINAL                            |", "96"))
        print(paint("  +----------------------------------------------------------+", "96"))
        print(paint("    PERFORMANCE  /  FRAME TIMES  /  CONTROL\n", "90"))
        try:
            _, plan = active_plan()
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            plan = "Unavailable"
        print(f"    SYSTEM   Windows {platform.release()}  |  {os.cpu_count()} logical CPUs")
        print(f"    POWER    {plan}\n")
        for key, title, subtitle in [
            ("1", "Performance power", "Switch to High performance"),
            ("2", "Game priority", "Boost a running game to Above normal"),
            ("3", "Game Mode settings", "Open Windows gaming controls"),
            ("4", "Display settings", "Check your monitor refresh rate"),
            ("5", "FPS & latency guide", "Practical in-game adjustments"),
            ("6", "Restore tweaks", "Restore saved power and priority settings"),
        ]:
            print(f"    {paint('[' + key + ']', '96')} {title:<23} {paint(subtitle, '90')}")
        print(f"\n    {paint('[0]', '96')} Exit\n")
        choice = input("    pulse > ").strip()
        if choice == "0":
            print("\n    Power settings persist. Use Restore tweaks to undo changes.")
            return 0
        print()
        try:
            action = actions.get(choice)
            if action:
                action()
            else:
                print("Choose a menu option from 0 to 6.")
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            print(paint(f"Could not complete the action: {error}", "91"))
            print("If Windows reports access denied, try an elevated terminal.")
        input("\n    Press Enter to return...")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nExited. Saved tweaks can be restored on the next launch.")
