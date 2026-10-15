"""Kryptic's Tweaks — Windows desktop utility, Python 3.9+, standard library."""
import ctypes
from datetime import datetime
import math
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import queue
import random
import re
import subprocess
import shutil
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import winreg

BG = '#090b18'
PANEL = '#14172d'
CARD = '#202447'
TEXT = '#f7f8ff'
MUTED = '#a6afd0'
ACCENT = '#00d9ff'
GREEN = '#63f5b0'
PINK = '#ff4fd8'
BORDER = '#354071'
ASSETS = Path(__file__).resolve().parent / 'kryptic_assets'
ROOT = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'KrypticTweaks'
STATE = ROOT / 'restore.json'
APP_NAME = "Kryptic's Tweaks"
APP_VERSION = '0.7'
GUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', re.I)
HIGH = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
REGISTRY = {
    'game_mode': ('Software\\Microsoft\\GameBar', {'AutoGameModeEnabled': 1}),
    'capture': ('System\\GameConfigStore', {'GameDVR_Enabled': 0}),
    'background_capture': ('Software\\Microsoft\\Windows\\CurrentVersion\\GameDVR',
                           {'AppCaptureEnabled': 0, 'HistoricalCaptureEnabled': 0}),
    'transparency': ('Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize',
                     {'EnableTransparency': 0}),
}
POWER_OPTIONS = {
    'usb': ('2a737441-1930-4402-8d77-b2bebba308a3', '48e6b7a6-50f5-4782-a5d4-53bb8f07e226', 0),
    'pcie': ('501a4d13-42af-4429-9fd1-a8218c268e20', 'ee12f906-d277-404b-b6da-e5fa1a576df5', 0),
    'wifi': ('19cbb8fa-5279-450e-9fac-8a3d5fedd0c1', '12bbebe6-58d6-4636-95bb-3217ef867c1a', 0),
}


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Could not read {path.name}: {error}') from error


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def active_scheme():
    match = GUID.search(run(['powercfg', '/getactivescheme']))
    if not match:
        raise RuntimeError('Windows did not return a power plan.')
    return match.group().lower()


def advanced_power(name, undo=False):
    subgroup, setting, value = POWER_OPTIONS[name]
    state = load()
    backups = state.setdefault('power_options', {})
    if undo:
        keys = [key for key, item in backups.items() if item['name'] == name]
        if not keys:
            return 'No saved changes for this power setting.'
        for key in keys:
            item = backups[key]
            plan = item['plan']
            if not GUID.fullmatch(plan) or not isinstance(item['value'], int) or not 0 <= item['value'] <= 0xffffffff:
                raise ValueError('Invalid saved power setting.')
            run(['powercfg', '/setacvalueindex', plan, subgroup, setting, str(item['value'])])
            if active_scheme() == plan:
                run(['powercfg', '/setactive', plan])
            del backups[key]
            save(state)
    else:
        plan = active_scheme()
        key = plan + '/' + name
        output = run(['powercfg', '/query', plan, subgroup, setting])
        indices = re.findall(r'0x([0-9a-fA-F]{8})\b', output)
        if len(indices) != 2:
            raise RuntimeError('This device does not expose a readable AC/DC value for this setting.')
        if key not in backups:
            backups[key] = {'name': name, 'plan': plan, 'value': int(indices[0], 16)}
            save(state)
        run(['powercfg', '/setacvalueindex', plan, subgroup, setting, str(value)])
        run(['powercfg', '/setactive', plan])
    if not backups:
        state.pop('power_options', None)
    save(state)
    return 'Original plugged-in setting restored.' if undo else 'Applied to the current plan, plugged-in mode only. Battery settings were not changed.'


def input_tweak(name, undo=False):
    if name not in ('mouse', 'animation'):
        raise ValueError('Unknown input setting.')
    state = load()
    backups = state.setdefault('input', {})
    spi = ctypes.windll.user32.SystemParametersInfoW
    if undo and name not in backups:
        return 'No saved input setting to restore.'
    if name == 'mouse':
        current = (ctypes.c_int * 3)()
        if not spi(0x0003, 0, current, 0):
            raise RuntimeError('Could not read mouse acceleration settings.')
        if not undo and name not in backups:
            backups[name] = list(current)
            save(state)
        values = backups[name] if undo else [0, 0, 0]
        if not isinstance(values, list) or len(values) != 3 or any(not isinstance(x, int) for x in values):
            raise ValueError('Invalid mouse backup.')
        if not spi(0x0004, 0, (ctypes.c_int * 3)(*values), 3):
            raise RuntimeError('Windows rejected mouse setting changes.')
    else:
        current = ctypes.c_int()
        if not spi(0x1042, 0, ctypes.byref(current), 0):
            raise RuntimeError('Could not read client-area animation setting.')
        if not undo and name not in backups:
            backups[name] = bool(current.value)
            save(state)
        value = backups[name] if undo else False
        if not isinstance(value, bool):
            raise ValueError('Invalid animation backup.')
        if not spi(0x1043, 0, ctypes.c_void_p(int(value)), 3):
            raise RuntimeError('Windows rejected animation setting changes.')
    if undo:
        del backups[name]
    if not backups:
        state.pop('input', None)
    save(state)
    return 'Original setting restored.' if undo else 'Setting applied immediately. Original value saved.'


def system_report():
    return ps("$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1; "
              "$os=Get-CimInstance Win32_OperatingSystem; "
              "$gpu=Get-CimInstance Win32_VideoController; "
              "'CPU: '+$cpu.Name; 'Cores / threads: '+$cpu.NumberOfCores+' / '+$cpu.NumberOfLogicalProcessors; "
              "'Windows: '+$os.Caption+' (build '+$os.BuildNumber+')'; "
              "'Memory: '+[math]::Round($os.TotalVisibleMemorySize/1MB,1)+' GB'; "
              "$gpu | ForEach-Object { 'GPU: '+$_.Name+' | Driver: '+$_.DriverVersion }; "
              "Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | ForEach-Object { "
              "'Network: '+$_.InterfaceDescription+' | Link: '+$_.LinkSpeed }")


def export_report():
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / ('system-report-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.txt')
    report = system_report()
    path.write_text("Kryptic's Tweaks 0.5\n" + datetime.now().isoformat(timespec='seconds') + '\n\n' + report,
                    encoding='utf-8')
    return f'Saved to {path}\n\n{report}'


def process_report():
    return ps("Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 12 "
              "ProcessName,Id,@{n='MemoryMB';e={[math]::Round($_.WorkingSet64/1MB)}} | Format-Table -AutoSize | Out-String")


def launch_tool(name):
    if name not in ('taskmgr.exe', 'resmon.exe'):
        raise ValueError('Unknown Windows tool.')
    subprocess.Popen([str(Path(os.environ['WINDIR']) / 'System32' / name)])
    return 'Windows tool opened.'


def apply_profile(names):
    results = []
    for name in names:
        try:
            results.append(name + ': ' + registry_tweak(name))
        except Exception as error:
            results.append(name + ': FAILED — ' + str(error))
    return '\n\n'.join(results) + '\n\nEach original value is retained in Restore & activity.'


def run(args, timeout=30):
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors='replace',
                                timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f'Command timed out after {timeout}s: {args[0]}') from error
    except OSError as error:
        raise RuntimeError(f'Could not start {args[0]}: {error}') from error
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or 'Windows rejected this action.')
    return result.stdout.strip()


def ps(script):
    return run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                "$ErrorActionPreference='Stop'; " + script])


def load():
    if not STATE.exists():
        return {}
    value = json.loads(STATE.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Invalid restore file. Keep the file for recovery.')
    return value


def save(state):
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    temporary.replace(STATE)


def read_value(path, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, kind = winreg.QueryValueEx(key, name)
        if kind not in (winreg.REG_DWORD, winreg.REG_SZ):
            raise ValueError('Unexpected registry value type; no change made.')
        return {'exists': True, 'value': value, 'type': kind}
    except FileNotFoundError:
        return {'exists': False}


def write_value(path, name, original):
    if original['exists']:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, original['type'], original['value'])
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


def registry_tweak(name, undo=False):
    path, values = REGISTRY[name]
    state = load()
    backups = state.setdefault('registry', {})
    if undo:
        if name not in backups:
            return 'No saved change for this setting.'
        for field, original in backups[name].items():
            if field not in values:
                raise ValueError('Unknown saved registry setting.')
            write_value(path, field, original)
        del backups[name]
    else:
        if name not in backups:
            backups[name] = {field: read_value(path, field) for field in values}
            save(state)
        for field, value in values.items():
            write_value(path, field, {'exists': True, 'value': value, 'type': winreg.REG_DWORD})
    if not backups:
        state.pop('registry', None)
    save(state)
    return ('Original values restored.' if undo else 'Applied; original values saved.') + ' Restart your game; Windows may require sign-out.'


def power(undo=False):
    state = load()
    if undo:
        target = state.get('power')
        if not target:
            return 'No saved power change.'
        if not GUID.fullmatch(target):
            raise ValueError('Invalid saved power plan.')
    else:
        output = run(['powercfg', '/getactivescheme'])
        match = GUID.search(output)
        if not match:
            raise RuntimeError('Cannot read current power plan.')
        if match.group().lower() == HIGH:
            return 'High performance is already active.'
        if HIGH not in run(['powercfg', '/list']).lower():
            return 'High performance is unavailable on this PC. Use Windows Power settings instead.'
        state.setdefault('power', match.group())
        save(state)
        target = HIGH
    run(['powercfg', '/setactive', target])
    if undo:
        state.pop('power')
        save(state)
    return 'Original power plan restored.' if undo else 'High performance enabled. Monitor temperatures and frame times.'


def process_priority(pid, start, priority):
    if not str(start).isdigit() or priority not in ('Normal', 'AboveNormal'):
        raise ValueError('Invalid process backup.')
    return ps(f'$p=Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; '
              "if ($null -eq $p) { 'expired' } "
              f"elseif ($p.StartTime.ToUniversalTime().Ticks.ToString() -ne '{start}') {{ 'expired' }} "
              f"else {{ $p.PriorityClass='{priority}'; 'applied' }}")


def roblox_priority():
    raw = ps("@(Get-Process -Name RobloxPlayerBeta -ErrorAction SilentlyContinue | "
             "Select-Object Id,@{n='Start';e={$_.StartTime.ToUniversalTime().Ticks.ToString()}},"
             "@{n='Priority';e={$_.PriorityClass.ToString()}}) | ConvertTo-Json -Compress")
    processes = json.loads(raw) if raw else []
    if isinstance(processes, dict):
        processes = [processes]
    if not processes:
        return 'Roblox desktop player was not found. Join an experience first. Store/client variants may use different processes.'
    results = []
    for item in processes:
        if item['Priority'] != 'Normal':
            results.append(f"PID {item['Id']}: already {item['Priority']}; left as-is.")
            continue
        state = load()
        state.setdefault('processes', {})[str(item['Id'])] = item
        save(state)
        result = process_priority(item['Id'], item['Start'], 'AboveNormal')
        results.append(f"PID {item['Id']}: {result}.")
    return '\n'.join(results) + '\nPriority may help CPU contention; it does not lower server ping.'


def restore_all():
    results = []
    for name in list(load().get('input', {})):
        try:
            results.append(name + ': ' + input_tweak(name, True))
        except Exception as error:
            results.append(name + ': ' + str(error))
    for name in {item['name'] for item in load().get('power_options', {}).values()}:
        try:
            results.append(name + ': ' + advanced_power(name, True))
        except Exception as error:
            results.append(name + ': ' + str(error))
    for name in list(load().get('registry', {})):
        try:
            results.append(name + ': ' + registry_tweak(name, True))
        except Exception as error:
            results.append(name + ': ' + str(error))
    try:
        results.append(power(True))
    except Exception as error:
        results.append('Power: ' + str(error))
    for pid, item in list(load().get('processes', {}).items()):
        try:
            result = process_priority(pid, item['Start'], item['Priority'])
            state = load()
            del state['processes'][pid]
            if not state['processes']:
                state.pop('processes')
            save(state)
            results.append(f'PID {pid}: {result}.')
        except Exception as error:
            results.append(f'PID {pid}: {error}')
    return '\n'.join(results) + '\nFailed restores retain their backups for retry.'


def network_test(target):
    target = str(ipaddress.ip_address(target.strip()))
    raw = ps(
        "$ping=New-Object System.Net.NetworkInformation.Ping; $out=@(); "
        "try { for($i=0;$i -lt 10;$i++) { "
        f"$r=$ping.Send('{target}',1000); "
        "$out += [pscustomobject]@{ok=($r.Status -eq 'Success'); ms=$r.RoundtripTime}; "
        "Start-Sleep -Milliseconds 200 } } finally { $ping.Dispose() }; "
        '$out | ConvertTo-Json -Compress'
    )
    samples = json.loads(raw)
    times = [float(item['ms']) for item in samples if item['ok']]
    if not times:
        return f'{target}: no ICMP replies. The target or firewall may block probes; this does not prove a game connection is down.'
    variation = sum(abs(b-a) for a, b in zip(times, times[1:])) / max(1, len(times)-1)
    result = (f"Target: {target} | Replies: {len(times)}/10\n"
              f"Average: {sum(times)/len(times):.1f} ms | Min: {min(times):.0f} ms | Max: {max(times):.0f} ms\n"
              f"Mean successive RTT variation: {variation:.1f} ms | Probe loss: {(10-len(times))*10}%\n"
              'ICMP diagnostic only; not Roblox ping or mouse-to-screen latency.')
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'network-results.txt').open('a', encoding='utf-8') as file:
        file.write(datetime.now().isoformat(timespec='seconds') + '\n' + result + '\n\n')
    records = read_json(ROOT / 'network-history.json', [])
    previous = next((item for item in reversed(records) if item['target'] == target), None)
    average = sum(times) / len(times)
    records.append({'target': target, 'average': average, 'loss': (10-len(times))*10,
                    'variation': variation, 'time': datetime.now().isoformat(timespec='seconds')})
    write_json(ROOT / 'network-history.json', records[-100:])
    if previous:
        result += f"\nCompared with previous test to this IP: {average-previous['average']:+.1f} ms average RTT.\nDifferent conditions can affect comparisons."
    return result


class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                ('total', ctypes.c_ulonglong), ('available', ctypes.c_ulonglong),
                ('page_total', ctypes.c_ulonglong), ('page_available', ctypes.c_ulonglong),
                ('virtual_total', ctypes.c_ulonglong), ('virtual_available', ctypes.c_ulonglong),
                ('extended_available', ctypes.c_ulonglong)]


class Telemetry:
    def __init__(self):
        self.previous = None

    def sample(self):
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        cpu = None
        if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            values = idle.value, kernel.value + user.value
            if self.previous:
                elapsed = values[1] - self.previous[1]
                if elapsed > 0:
                    cpu = max(0, min(100, 100 * (1 - (values[0] - self.previous[0]) / elapsed)))
            self.previous = values
        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        ram = total = None
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            ram = memory.load
            total = memory.total / (1024 ** 3)
        return cpu, ram, total


def draw_logo(canvas, size=52):
    """Original split-chevron K inside an open hexagonal enclosure."""
    scale = size / 100
    def coords(points):
        return [value * scale for point in points for value in point]
    canvas.create_line(*coords([(76, 12), (29, 12), (10, 31), (10, 72), (29, 90), (75, 90), (90, 75)]),
                       fill=ACCENT, width=max(2, size / 25), joinstyle='round')
    canvas.create_polygon(*coords([(29, 29), (43, 29), (43, 72), (29, 72)]), fill=TEXT)
    canvas.create_polygon(*coords([(48, 48), (68, 28), (86, 28), (61, 53), (84, 75), (65, 75), (48, 58)]), fill=ACCENT)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'{APP_NAME}  /  {APP_VERSION}')
        width = min(1500, self.winfo_screenwidth()-36)
        height = min(960, self.winfo_screenheight()-80)
        self.geometry(f'{width}x{height}+{max(0, (self.winfo_screenwidth()-width)//2)}+30')
        self.minsize(min(1180, width), min(780, height))
        self.configure(bg=BG)
        self.option_add('*Font', ('Segoe UI', 10))
        self.events = queue.Queue()
        self.busy = False
        self.buttons = []
        self.history = []
        self.session_unlocked = False
        self.current_page = None
        self.telemetry = Telemetry()
        self.samples = []
        self.cpu = self.ram = self.ram_total = None
        self.startup_notices = []
        logo_path = ASSETS / 'kryptic-logo-v2.png'
        if logo_path.exists():
            self._window_logo = tk.PhotoImage(file=str(logo_path))
            self.iconphoto(True, self._window_logo)
        elif (ASSETS / 'kryptic.ico').exists():
            self.iconbitmap(str(ASSETS / 'kryptic.ico'))
        self.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Vertical.TScrollbar', background=CARD, troughcolor=BG, bordercolor=BG)
        style.configure('TCombobox', fieldbackground=CARD, background=CARD, foreground=TEXT,
                        arrowcolor=ACCENT, padding=7)
        style.map('TCombobox', fieldbackground=[('readonly', CARD)], foreground=[('readonly', TEXT)])
        self.splash()
        self.after(100, self.poll)
        self.after(300, self.refresh_telemetry)

    def splash(self):
        self.loading = tk.Frame(self, bg=BG)
        self.loading.pack(fill='both', expand=True)
        self.splash_canvas = tk.Canvas(self.loading, bg=BG, highlightthickness=0)
        self.splash_canvas.pack(fill='both', expand=True)
        self.splash_frame = tk.Frame(self.splash_canvas, bg=BG)
        self.splash_window = self.splash_canvas.create_window(660, 420, window=self.splash_frame, anchor='center')
        emblem = tk.Canvas(self.splash_frame, width=106, height=106, bg=BG, highlightthickness=0)
        emblem.pack(pady=(0, 25))
        draw_logo(emblem, 106)
        tk.Label(self.splash_frame, text='KRYPTIC OPERATIONS  /  LOCAL SYSTEM', bg=BG, fg=ACCENT,
                 font=('Consolas', 11)).pack(anchor='w')
        tk.Label(self.splash_frame, text='TACTICAL PERFORMANCE\nWORKSPACE', bg=BG, fg=TEXT,
                 justify='left', font=('Segoe UI Semibold', 42)).pack(anchor='w', pady=(14, 6))
        tk.Label(self.splash_frame, text='MEASURE  •  TUNE  •  RESTORE', bg=BG, fg=PINK,
                 font=('Consolas', 11)).pack(anchor='w', pady=(0, 38))
        self.loading_bar = tk.Canvas(self.splash_frame, width=620, height=12, bg=CARD, highlightthickness=0)
        self.loading_bar.pack()
        self.loading_fill = self.loading_bar.create_rectangle(0, 0, 0, 9, fill=ACCENT, outline='')
        line = tk.Frame(self.splash_frame, bg=BG)
        line.pack(fill='x', pady=12)
        self.loading_text = tk.Label(line, text='Initializing workspace…', bg=BG, fg=MUTED,
                                     font=('Segoe UI', 10))
        self.loading_text.pack(side='left')
        self.loading_percent = tk.Label(line, text='0%', bg=BG, fg=ACCENT, font=('Consolas', 11))
        self.loading_percent.pack(side='right')
        briefing = tk.Frame(self.splash_frame, bg=BG)
        briefing.pack(fill='x', pady=24)
        tk.Label(briefing, text='OPERATION STATUS', bg=BG, fg=MUTED,
                 font=('Consolas', 8)).pack(side='left')
        tk.Label(briefing, text='SECURE LOCAL SESSION  //  NO CLOUD REQUIRED', bg=BG, fg=GREEN,
                 font=('Consolas', 8)).pack(side='right')
        self.loading_progress = 0
        self.loading_tick = 0
        self.splash_canvas.bind('<Configure>', lambda _: self.paint_splash())
        self.after(30, self.animate_splash)
        self.after(180, self.startup_stage, 0)

    def paint_splash(self):
        canvas = self.splash_canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        canvas.delete('decoration')
        for x in range(0, width, 64):
            canvas.create_line(x, 0, x, height, fill='#111936', tags='decoration')
        for y in range(0, height, 64):
            canvas.create_line(0, y, width, y, fill='#111936', tags='decoration')
        sweep = (self.loading_tick * 5) % max(width, 1)
        canvas.create_line(sweep, 0, sweep - 190, height, fill='#14265a', width=3, tags='decoration')
        cx, cy = width * .78, height * .28
        canvas.create_oval(cx-130, cy-130, cx+130, cy+130, outline='#20316a', width=2, tags='decoration')
        canvas.create_oval(cx-78, cy-78, cx+78, cy+78, outline='#253d80', tags='decoration')
        canvas.create_line(cx-160, cy, cx+160, cy, fill='#2c4b91', tags='decoration')
        canvas.create_line(cx, cy-160, cx, cy+160, fill='#2c4b91', tags='decoration')
        canvas.create_oval(cx-4, cy-4, cx+4, cy+4, fill=PINK, outline='', tags='decoration')
        canvas.tag_lower('decoration')
        canvas.coords(self.splash_window, width/2, height/2)

    def animate_splash(self):
        if not self.loading.winfo_exists():
            return
        self.loading_tick += 1
        self.paint_splash()
        self.after(35, self.animate_splash)

    def startup_stage(self, index):
        def history():
            records = read_json(ROOT / 'activity.json', [])
            if not isinstance(records, list) or not all(isinstance(item, str) for item in records):
                raise ValueError('Activity file has an invalid format.')
            self.history = records[-100:]
        stages = [
            ('Checking Windows environment', lambda: sys.platform == 'win32'),
            ('Reading saved restore points', load),
            ('Loading activity history', history),
            ('Connecting system counters', self.telemetry.sample),
            ('Preparing tuning workspace', lambda: len(REGISTRY) + len(POWER_OPTIONS)),
        ]
        if index >= len(stages):
            self.loading_text.config(text='Ready. Opening secure sign-in…', fg=GREEN)
            self.after(380, self.finish_startup)
            return
        title, work = stages[index]
        self.loading_text.config(text=title + '…')
        try:
            work()
        except Exception as error:
            self.startup_notices.append(title + ': ' + str(error))
        self.progress_to((index+1)*20, index, 0)

    def progress_to(self, target, stage, tick):
        fraction = min(1, tick/22)
        percent = stage*20 + 20*(1-(1-fraction)**3)
        self.loading_bar.coords(self.loading_fill, 0, 0, 620*percent/100, 12)
        self.loading_percent.config(text=f'{percent:.0f}%')
        if fraction < 1:
            self.after(18, self.progress_to, target, stage, tick+1)
        else:
            self.after(80, self.startup_stage, stage+1)

    def finish_startup(self):
        self.loading.destroy()
        self.login()

    def label(self, parent, text, size=10, fg=TEXT, bg=None, **kwargs):
        label = tk.Label(parent, text=text, fg=fg, bg=bg or parent.cget('bg'),
                         font=('Segoe UI', size), justify='left', **kwargs)
        label.pack(anchor='w', pady=4)
        return label

    def button(self, parent, text, command, primary=False):
        button = tk.Button(parent, text=text, command=command, bg=ACCENT if primary else CARD,
                           fg=BG if primary else TEXT, activebackground=GREEN, activeforeground=BG,
                           relief='flat', bd=0, padx=14, pady=8, cursor='hand2',
                           disabledforeground=MUTED)
        button.pack(side='left', padx=(0, 8), pady=7)
        button.bind('<Enter>', lambda _: button.config(bg='#a894ff' if primary else '#26345d') if button.cget('state') != 'disabled' else None)
        button.bind('<Leave>', lambda _: button.config(bg=ACCENT if primary else CARD))
        return button

    def login(self):
        self.gate = tk.Frame(self, bg=BG)
        self.gate.place(relx=.5, rely=.5, anchor='center', width=760, height=470)
        self.gate.grid_columnconfigure(0, weight=1)
        self.gate.grid_columnconfigure(1, weight=1)
        visual = tk.Frame(self.gate, bg='#0c1124', padx=34, pady=34,
                          highlightbackground=BORDER, highlightthickness=1)
        visual.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        logo = tk.Canvas(visual, width=112, height=112, bg='#0c1124', highlightthickness=0)
        logo.pack(anchor='w', pady=(0, 26))
        draw_logo(logo, 112)
        tk.Label(visual, text='K R Y P T I C', bg='#0c1124', fg=ACCENT,
                 font=('Segoe UI Semibold', 12)).pack(anchor='w')
        tk.Label(visual, text='Performance\nwithout the noise.', bg='#0c1124', fg=TEXT,
                 justify='left', font=('Segoe UI Semibold', 27)).pack(anchor='w', pady=(12, 10))
        tk.Label(visual, text='A reversible Windows tuning workspace\nfor measured, intentional changes.',
                 bg='#0c1124', fg=MUTED, justify='left', font=('Segoe UI', 10)).pack(anchor='w')
        tk.Label(visual, text=f'DESKTOP EDITION  {APP_VERSION}  •  LOCAL', bg='#0c1124', fg='#6877a0',
                 font=('Segoe UI', 8)).pack(anchor='w', side='bottom')
        panel = tk.Frame(self.gate, bg=PANEL, padx=34, pady=34,
                         highlightbackground=BORDER, highlightthickness=1)
        panel.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        self.label(panel, 'WELCOME BACK', 9, ACCENT)
        self.label(panel, 'Unlock workspace', 24, TEXT)
        self.label(panel, 'Your changes stay local and reversible.', 10, MUTED)
        self.lock = self.label(panel, '[ # / X 7 * / # ]   LOCKED', 15, ACCENT)
        self.label(panel, 'ACCESS PASSWORD', 9, MUTED)
        self.password = tk.Entry(panel, show='•', bg=BG, fg=TEXT, insertbackground=ACCENT,
                                 relief='flat', font=('Segoe UI', 15))
        self.password.pack(fill='x', ipady=11, pady=(8, 12))
        self.password.bind('<Return>', lambda _: self.unlock())
        self.password.focus_set()
        self.login_message = self.label(panel, 'Enter your password to unlock.', 10, MUTED)
        row = tk.Frame(panel, bg=PANEL)
        row.pack(fill='x')
        self.unlock_button = self.button(row, 'Unlock workspace  →', self.unlock, True)

    def unlock(self):
        if self.unlock_button.cget('state') == 'disabled':
            return
        entered = hashlib.sha256(self.password.get().encode()).digest()
        expected = hashlib.sha256(b'Kryptic').digest()
        if not hmac.compare_digest(entered, expected):
            self.login_message.config(text='Incorrect password. Try again.', fg='#ff8f9b')
            self.password.delete(0, 'end')
            return
        self.unlock_button.config(state='disabled')
        self.password.config(state='disabled')
        self.scramble(0)

    def scramble(self, frame):
        word = 'UNLOCKED'
        progress = min(len(word), frame // 2)
        text = word[:progress] + ''.join(random.choice('01#X/*') for _ in word[progress:])
        self.lock.config(text='[ ' + ' '.join(text) + ' ]', fg=GREEN)
        if progress < len(word):
            self.after(45, self.scramble, frame + 1)
        else:
            self.after(220, self.workspace)

    def workspace(self):
        self.session_unlocked = True
        self.gate.destroy()
        sidebar = tk.Frame(self, bg='#0b1020', width=220, padx=15, pady=22)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        logo = tk.Canvas(sidebar, width=58, height=58, bg=sidebar.cget('bg'), highlightthickness=0)
        logo.pack(anchor='w', padx=7)
        draw_logo(logo, 58)
        self.label(sidebar, 'KRYPTIC', 22)
        self.label(sidebar, 'T W E A K S', 9, ACCENT)
        self.label(sidebar, '\nWORKSPACE', 8, MUTED)
        self.nav = {}
        icons = ('▦', '◈', '⚙', '⌘', '↔', '◇', '▤', '⊞', '↺')
        for icon, page in zip(icons, ('Overview', 'Profiles', 'Windows tweaks', 'Input & power', 'Latency lab', 'Roblox', 'Other games', 'System tools', 'Restore & activity')):
            button = tk.Button(sidebar, text=icon + '   ' + page, anchor='w', bg='#0b1020', fg=MUTED,
                               activebackground=CARD, activeforeground=TEXT, bd=0, padx=12,
                               pady=9, relief='flat', cursor='hand2', command=lambda p=page: self.show(p))
            button.pack(fill='x', pady=3)
            self.nav[page] = button
        lower = tk.Frame(sidebar, bg=sidebar.cget('bg'))
        lower.pack(side='bottom', fill='x')
        self.label(lower, '●  LOCAL WORKSPACE', 8, GREEN)
        self.label(lower, f'Desktop edition {APP_VERSION}\nWindows 10 / 11', 9, MUTED)
        main = tk.Frame(self, bg=BG)
        main.pack(side='left', fill='both', expand=True)
        top = tk.Frame(main, bg=BG, padx=28, pady=13)
        top.pack(fill='x')
        tk.Label(top, text="Kryptic's Tweaks", bg=BG, fg=TEXT,
                 font=('Segoe UI Semibold', 11)).pack(side='left')
        tk.Label(top, text='●  SYSTEM CONNECTED     /     DESKTOP', bg=BG, fg=MUTED,
                 font=('Segoe UI', 9)).pack(side='right')
        tk.Frame(main, bg=BORDER, height=1).pack(fill='x')
        footer = tk.Frame(main, bg=PANEL, padx=20, pady=8)
        footer.pack(side='bottom', fill='x')
        self.status = self.label(footer, 'Ready • Changes are saved individually for restore.', 10, GREEN)
        self.canvas = tk.Canvas(main, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(main, orient='vertical', command=self.canvas.yview)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.content = tk.Frame(self.canvas, bg=BG, padx=26, pady=16)
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self.content.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(self.window, width=e.width))
        self.bind_all('<MouseWheel>', lambda e: self.canvas.yview_scroll(int(-e.delta/120), 'units'))
        self.show('Overview')
        self.bind('<Control-f>', self.focus_search)
        self.bind('<Control-r>', lambda _: self.show(self.current_page) if not self.busy else None)
        if self.startup_notices:
            messagebox.showwarning('Startup notes', '\n\n'.join(self.startup_notices), parent=self)

    def focus_search(self, event=None):
        if hasattr(self, 'search_entry') and self.search_entry.winfo_exists():
            self.search_entry.focus_set()
            self.search_entry.select_range(0, 'end')

    def card(self, title, body, actions=()):
        frame = tk.Frame(self.content, bg=PANEL, padx=19, pady=12,
                         highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill='x', pady=6)
        self.search_cards.append((frame, (title + ' ' + body).lower()))
        self.label(frame, title, 13)
        description = self.label(frame, body, 10, MUTED, wraplength=750)
        frame.bind('<Configure>', lambda e: description.config(wraplength=max(200, e.width-42)))
        if actions:
            row = tk.Frame(frame, bg=PANEL)
            row.pack(fill='x')
            for caption, action, primary in actions:
                button = self.button(row, caption, action, primary)
                self.buttons.append(button)
                if self.busy:
                    button.config(state='disabled')
        return frame

    def refresh_telemetry(self):
        self.cpu, self.ram, self.ram_total = self.telemetry.sample()
        if self.cpu is not None:
            self.samples.append(self.cpu)
            self.samples = self.samples[-40:]
        if self.current_page == 'Overview' and self.session_unlocked:
            self.render_meters()
        self.after(1600, self.refresh_telemetry)

    def render_meters(self):
        for canvas, value, caption, tint in (
                (self.cpu_meter, self.cpu, 'CPU LOAD', GREEN),
                (self.ram_meter, self.ram, 'MEMORY', ACCENT)):
            canvas.delete('all')
            canvas.create_oval(13, 9, 113, 109, outline=BORDER, width=7)
            if value is not None and value > 0:
                canvas.create_arc(13, 9, 113, 109, start=90, extent=-max(.1, value*3.599),
                                  style='arc', outline=tint, width=7)
            canvas.create_text(63, 54, text='—' if value is None else f'{value:.0f}%', fill=TEXT,
                               font=('Segoe UI Semibold', 20))
            canvas.create_text(63, 78, text=caption, fill=MUTED, font=('Segoe UI', 8))
        chart = self.chart
        chart.delete('all')
        width = max(chart.winfo_width(), 260)
        for y in (16, 43, 70):
            chart.create_line(0, y, width, y, fill=BORDER)
        if len(self.samples) > 1:
            points = []
            for i, value in enumerate(self.samples):
                points.extend((i*(width-4)/39+2, 76-value*.65))
            chart.create_line(*points, fill=GREEN, width=2)
        self.memory_info.config(text=(f'{self.ram_total:.1f} GB installed  •  Live system usage'
                                      if self.ram_total else 'Live system usage'))

    def dashboard(self):
        header = tk.Frame(self.content, bg=BG)
        header.pack(fill='x', pady=(0, 4))
        heading = tk.Frame(header, bg=BG)
        heading.pack(side='left')
        self.label(heading, 'LIVE CONTROL CENTER  /  DESKTOP EDITION ' + APP_VERSION, 9, PINK)
        self.label(heading, 'Your performance command center.', 24, TEXT)
        self.label(heading, 'Measure first. Tune only what helps. Restore anything that does not.', 11, MUTED)
        chip = tk.Frame(header, bg='#12382f', padx=16, pady=10)
        chip.pack(side='right', anchor='n', pady=8)
        tk.Label(chip, text='●  SYSTEM READY', bg='#12382f', fg=GREEN,
                 font=('Segoe UI Semibold', 9)).pack()
        strip = tk.Frame(self.content, bg=BG)
        strip.pack(fill='x', pady=(12, 4))
        try:
            state = load()
            backups = sum(len(state.get(key, {})) for key in ('registry', 'input', 'power_options', 'processes')) + bool(state.get('power'))
            count = str(backups)
        except Exception:
            count = '—'
        for index, (number, caption, note) in enumerate([
            ('11', 'TUNING CONTROLS', 'Individual apply & restore'),
                (count, 'SAVED RESTORE ITEMS', 'Your original values'),
                ('09', 'WORKSPACE SECTIONS', 'Profiles, diagnostics & more')]):
            strip.columnconfigure(index, weight=1, uniform='stats')
            tile = tk.Frame(strip, bg=PANEL, padx=14, pady=10, highlightbackground=BORDER, highlightthickness=1)
            tile.grid(row=0, column=index, sticky='nsew', padx=(0, 10 if index < 2 else 0))
            tk.Label(tile, text=number, bg=PANEL, fg=ACCENT if index != 1 else PINK,
                     font=('Segoe UI Semibold', 26)).pack(side='left', padx=(0, 13))
            text = tk.Frame(tile, bg=PANEL)
            text.pack(side='left')
            self.label(text, caption, 8)
            self.label(text, note, 8, MUTED)
        columns = tk.Frame(self.content, bg=BG)
        columns.pack(fill='both', expand=True, pady=12)
        columns.columnconfigure(0, weight=3, uniform='dashboard')
        columns.columnconfigure(1, weight=2, uniform='dashboard')
        left = tk.Frame(columns, bg=BG)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 16))
        right = tk.Frame(columns, bg=BG)
        right.grid(row=0, column=1, sticky='nsew')
        hero = tk.Frame(left, bg=PANEL, padx=22, pady=18, highlightbackground=BORDER, highlightthickness=1)
        hero.pack(fill='x', pady=(0, 14))
        art = tk.Canvas(hero, bg=PANEL, height=148, highlightthickness=0)
        art.pack(fill='x')
        def paint_hero(event=None):
            art.delete('all')
            width = max(art.winfo_width(), 400)
            for i in range(8):
                art.create_line(width-170+i*28, 0, width-260+i*28, 148, fill='#2c2b25', width=12)
            art.create_text(0, 10, text='KRYPTIC  /  PERFORMANCE LAB', anchor='nw', fill=ACCENT, font=('Segoe UI', 9))
            art.create_text(0, 40, text='Tune smarter.', anchor='nw', fill=TEXT, font=('Segoe UI Semibold', 30))
            art.create_text(0, 88, text='Play cleaner.', anchor='nw', fill=ACCENT, font=('Segoe UI Semibold', 30))
        art.bind('<Configure>', paint_hero)
        self.label(hero, 'Build a profile. Measure your session.\nKeep the changes that work for you.', 10, MUTED)
        row = tk.Frame(hero, bg=PANEL)
        row.pack(fill='x')
        self.button(row, 'Build your profile →', lambda: self.show('Profiles'), True)
        self.button(row, 'All tweaks', lambda: self.show('Windows tweaks'))
        self.label(left, 'QUICK CONTROLS', 9, MUTED)
        try:
            saved = load()
            backup_error = False
        except Exception:
            saved = {}
            backup_error = True
        controls = [
            ('Game Mode', 'Windows gaming preference', 'game_mode', lambda: registry_tweak('game_mode'), lambda: registry_tweak('game_mode', True)),
            ('Game capture', 'Disable the DVR preference', 'capture', lambda: registry_tweak('capture'), lambda: registry_tweak('capture', True)),
            ('Background recording', 'Disable background capture', 'background_capture', lambda: registry_tweak('background_capture'), lambda: registry_tweak('background_capture', True)),
            ('Performance power', 'Use High performance', 'power', power, lambda: power(True)),
        ]
        for title, detail, key, apply, undo in controls:
            active = bool(saved.get('power')) if key == 'power' else key in saved.get('registry', {})
            row = tk.Frame(left, bg=PANEL, padx=15, pady=9, highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill='x', pady=4)
            text = tk.Frame(row, bg=PANEL)
            text.pack(side='left', fill='x', expand=True)
            self.label(text, title, 11)
            self.label(text, 'Backup saved • restore available' if active else detail, 9, ACCENT if active else MUTED)
            command = undo if active else apply
            button = tk.Button(row, text='Restore ↺' if active else 'Apply +',
                               bg=CARD if active else '#161d36', fg=ACCENT,
                               activebackground=ACCENT, activeforeground=BG,
                               relief='flat', padx=12, pady=9, cursor='hand2',
                               command=lambda t=title, c=command: self.job(t, c))
            button.pack(side='right', padx=(8, 0))
            self.buttons.append(button)
            if self.busy or backup_error:
                button.config(state='disabled')
        self.label(left, 'Saved backup ≠ measured performance gain. Compare each change.', 8, MUTED, wraplength=440)
        if backup_error:
            self.label(left, 'Backup cannot be read. Open Restore & activity for details.', 9, '#ff8f9b', wraplength=440)
        monitor = tk.Frame(right, bg=PANEL, padx=18, pady=16, highlightbackground=BORDER, highlightthickness=1)
        monitor.pack(fill='x')
        self.label(monitor, 'SYSTEM PULSE', 9, MUTED)
        self.label(monitor, 'Live, not estimated gains.', 13)
        self.chart = tk.Canvas(monitor, height=88, bg=PANEL, highlightthickness=0)
        self.chart.pack(fill='x', pady=10)
        meters = tk.Frame(monitor, bg=PANEL)
        meters.pack(fill='x')
        self.cpu_meter = tk.Canvas(meters, width=126, height=120, bg=PANEL, highlightthickness=0)
        self.cpu_meter.pack(side='left', expand=True)
        self.ram_meter = tk.Canvas(meters, width=126, height=120, bg=PANEL, highlightthickness=0)
        self.ram_meter.pack(side='left', expand=True)
        self.memory_info = self.label(monitor, 'Reading system counters…', 9, MUTED)
        self.render_meters()
        for eyebrow, title, detail, destination in [
            ('FEATURED PROFILE', '◇  Roblox', 'Player priority + in-game tuning guide', 'Roblox'),
            ('MEASURE FIRST', '↔  Latency lab', 'Network RTT, variation & probe loss', 'Latency lab'),
            ('PRECISION SETTINGS', '⌘  Input & power', 'Mouse, USB, PCIe & Wi-Fi power', 'Input & power'),
            ('YOUR HARDWARE', '⊞  System tools', 'Inventory, processes & exportable reports', 'System tools')]:
            tile = tk.Frame(right, bg=PANEL, padx=17, pady=11, highlightbackground=BORDER, highlightthickness=1)
            tile.pack(fill='x', pady=(12, 0))
            self.label(tile, eyebrow, 8, ACCENT)
            button = tk.Button(tile, text=title + '   →', command=lambda p=destination: self.show(p),
                               bg=PANEL, fg=TEXT, activebackground=CARD, activeforeground=TEXT,
                               relief='flat', anchor='w', cursor='hand2', font=('Segoe UI Semibold', 13))
            button.pack(fill='x')
            self.label(tile, detail, 9, MUTED, wraplength=280)

    def job(self, title, action):
        if self.busy:
            return
        self.busy = True
        self.status.config(text=title + '…', fg=ACCENT)
        for button in self.buttons:
            button.config(state='disabled')
        def worker():
            try:
                self.events.put((title, str(action()), False))
            except Exception as error:
                self.events.put((title, str(error), True))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            title, result, failed = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.history.append(title + '\n' + result)
            self.history[-1] = datetime.now().strftime('%Y-%m-%d %H:%M') + '  /  ' + self.history[-1]
            self.history = self.history[-100:]
            try:
                write_json(ROOT / 'activity.json', self.history)
            except OSError as error:
                self.history.append('Could not save activity: ' + str(error))
            self.status.config(text=('Failed: ' if failed else 'Finished: ') + title,
                               fg='#ff8f9b' if failed else GREEN)
            for button in self.buttons:
                if button.winfo_exists():
                    button.config(state='normal')
            if self.current_page in ('Overview', 'Restore & activity', 'Latency lab'):
                self.show(self.current_page)
            self.result_panel(title, result, failed)
        self.after(100, self.poll)

    def result_panel(self, title, result, failed=False):
        dialog = tk.Toplevel(self)
        dialog.title(title + ' — Kryptic')
        dialog.configure(bg=BG)
        dialog.geometry('730x460')
        dialog.minsize(540, 340)
        dialog.transient(self)
        dialog.grab_set()
        body = tk.Frame(dialog, bg=BG, padx=25, pady=22)
        body.pack(fill='both', expand=True)
        self.label(body, 'ACTION FAILED' if failed else 'ACTION RESULT', 9, '#ff8f9b' if failed else GREEN)
        self.label(body, title, 21)
        area = tk.Frame(body, bg=PANEL)
        area.pack(fill='both', expand=True, pady=12)
        text = tk.Text(area, bg=PANEL, fg=TEXT, font=('Consolas', 10), relief='flat',
                       wrap='word', padx=15, pady=15, insertbackground=ACCENT)
        scroll = ttk.Scrollbar(area, command=text.yview)
        scroll.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        text.config(yscrollcommand=scroll.set)
        if failed:
            result += '\n\nIf access is denied, close the app and use Run as administrator on its shortcut.'
        text.insert('1.0', result)
        text.config(state='disabled')
        row = tk.Frame(body, bg=BG)
        row.pack(fill='x')
        self.button(row, 'Done', dialog.destroy, True)
        def copy():
            self.clipboard_clear()
            self.clipboard_append(result)
        self.button(row, 'Copy result', copy)
        dialog.bind('<Escape>', lambda _: dialog.destroy())

    def action(self, title, callback, primary=True):
        return (title, lambda: self.job(title, callback), primary)

    def setting(self, title, uri):
        return (title, lambda: self.job(title, lambda: self.open_settings(uri)), False)

    def open_settings(self, uri):
        os.startfile(uri)
        return 'Windows settings opened. Changes made there are managed by Windows, not by this app’s restore backup.'

    def show(self, page):
        self.current_page = page
        for child in self.content.winfo_children():
            child.destroy()
        self.buttons = []
        self.search_cards = []
        self.canvas.yview_moveto(0)
        for name, button in self.nav.items():
            button.config(bg='#20204a' if name == page else '#0b1020', fg=ACCENT if name == page else MUTED)
        self.label(self.content, 'KRYPTIC  /  CONTROL CENTER  /  ' + page.upper(), 8, ACCENT)
        self.label(self.content, 'Welcome back.' if page == 'Overview' else page, 25)
        if page != 'Overview':
            bar = tk.Frame(self.content, bg=CARD, padx=12, pady=8)
            bar.pack(fill='x', pady=(8, 12))
            tk.Label(bar, text='FIND ON THIS PAGE', bg=CARD, fg=MUTED, font=('Segoe UI', 8)).pack(side='left', padx=(0, 14))
            self.search_entry = tk.Entry(bar, bg=CARD, fg=TEXT, insertbackground=ACCENT, relief='flat')
            self.search_entry.pack(side='left', fill='x', expand=True)
            self.search_entry.bind('<KeyRelease>', self.filter_cards)
            tk.Label(bar, text='CTRL + F', bg=CARD, fg=MUTED, font=('Segoe UI', 8)).pack(side='right')
        if page == 'Overview':
            self.dashboard()
        elif page == 'Profiles':
            self.profiles_page()
        elif page == 'Input & power':
            self.input_power_page()
        elif page == 'System tools':
            self.system_page()
        elif page == 'Latency lab':
            self.card('Three different kinds of delay',
                      'NETWORK: round-trip time to a server.\nFRAME TIME: 1000 ÷ FPS; 60 FPS ≈ 16.7 ms, 144 FPS ≈ 6.9 ms. '
                      'This is frame duration, not total input latency.\nINPUT: mouse-to-screen delay; accurate end-to-end measurement needs appropriate capture hardware or supported game tools.')
            frame = self.card('Network baseline / 10 ICMP probes',
                              'Use an IP address. 1.1.1.1 is a public reference, not a Roblox server. Test before and after under similar conditions. Results are saved locally.')
            entry = tk.Entry(frame, bg=BG, fg=TEXT, insertbackground=TEXT, relief='flat')
            entry.insert(0, '1.1.1.1')
            entry.pack(fill='x', ipady=7, pady=6)
            row = tk.Frame(frame, bg=PANEL)
            row.pack(fill='x')
            def measure():
                target = entry.get()
                self.job('Network measurement', lambda: network_test(target))
            button = self.button(row, 'Measure connection', measure, True)
            self.buttons.append(button)
            button.config(state='disabled' if self.busy else 'normal')
            self.card('If your ping went up',
                      'Power and priority tweaks do not change server distance or routing. Restore prior tweaks and compare in the same experience/server. '
                      'Try Ethernet, pause uploads/downloads, and compare nearby servers where selection is available. '
                      'Router SQM can help congestion when configured for your line; DNS changes generally do not lower established-session ping.',
                      [self.setting('Network settings', 'ms-settings:network-status')])
            self.card('Input & display',
                      'Use the highest stable monitor refresh rate. In your mouse software, compare 500/1000 Hz; very high polling rates can increase CPU load. '
                      'Pointer acceleration affects aiming consistency, not network latency. Test V-sync/VRR tradeoffs in each game.',
                      [self.setting('Refresh rate', 'ms-settings:display-advanced'),
                       self.setting('Mouse settings', 'ms-settings:mousetouchpad')])
            try:
                records = read_json(ROOT / 'network-history.json', [])
                lines = [f"{item['time']}  •  {item['target']}  •  {item['average']:.1f} ms  •  {item['loss']}% loss"
                         for item in reversed(records[-8:])]
                self.card('Recent measurements', '\n'.join(lines) or 'Run a measurement to start your comparison history.')
            except (ValueError, KeyError, TypeError) as error:
                self.card('Recent measurements', 'History could not be read: ' + str(error))
        elif page == 'Windows tweaks':
            self.card('Apply separately. Compare. Keep the winners.',
                      'Apply/Restore buttons below change saved settings. Open-settings buttons let you configure Windows manually. '
                      'Windows builds and device policies can override individual settings.')
            for name, title, body in [
                ('game_mode', 'Game Mode', 'Enable the current-user Game Mode preference. Intended to prioritize gaming workloads; verify its status in Windows Gaming settings.'),
                ('capture', 'Game DVR preference', 'Disable the current-user Game DVR preference. Useful if you do not record through Xbox Game Bar. Restart your game.'),
                ('background_capture', 'Background game capture', 'Disable current-user app/background capture preferences. This may remove recording features; it does not disable OBS or GPU-vendor recording.')]:
                self.card(title, body, [self.action('Apply', lambda n=name: registry_tweak(n)),
                                       self.action('Restore', lambda n=name: registry_tweak(n, True), False)])
            self.card('High performance power',
                      'Use the existing Windows plan. Can increase heat and battery drain; thermal throttling may worsen frame times on some systems.',
                      [self.action('Apply', power), self.action('Restore', lambda: power(True), False)])
            for title, body, caption, uri in [
                ('GPU preference / HAGS', 'Choose the high-performance GPU for a game on multi-GPU systems. Hardware GPU scheduling is device-dependent; compare on/off and reboot when Windows requests it.', 'Graphics settings', 'ms-settings:display-advancedgraphics'),
                ('Capture controls', 'Check background recording and audio capture preferences in Windows.', 'Capture settings', 'ms-settings:gaming-gamedvr'),
                ('Startup & background load', 'Disable only startup apps you recognize and do not need. Close downloads and recording overlays before benchmarking.', 'Startup apps', 'ms-settings:startupapps'),
                ('Power mode', 'Modern Standby devices may expose power modes instead of the classic High performance plan.', 'Power settings', 'ms-settings:powersleep')]:
                self.card(title, body, [self.setting(caption, uri)])
        elif page == 'Roblox':
            self.card('ROBLOX / Primary profile',
                      'Automatic action: desktop-player process priority. Windows tweaks also apply system-wide. '
                      'Graphics and FPS adjustments below are guided in-game settings; this app does not edit Roblox client files.')
            self.card('Session CPU priority / Optional',
                      'Join an experience first. Raise Normal priority to Above normal for RobloxPlayerBeta. '
                      'May help when other programs compete for CPU time; can also have no benefit. Protected clients may deny access. '
                      'Restart Roblox or restore to reset.', [self.action('Adjust running Roblox', roblox_priority)])
            self.card('01 / Graphics quality',
                      'In an experience, open Esc → Settings. Set Graphics Mode to Manual and lower Graphics Quality gradually. '
                      'Compare the same view. This mainly helps when rendering is the bottleneck.')
            self.card('02 / Maximum frame rate',
                      'Use the built-in Maximum Frame Rate setting if your client exposes it. Choose a sustainable rate rather than blindly selecting the highest option. '
                      'Higher FPS can reduce frame duration but increases load and heat.')
            self.card('03 / Performance Stats',
                      'Enable Performance Stats in the in-game Settings menu. Record FPS/frame time and ping separately. '
                      'Use the same experience and server for comparisons; busy servers and experience scripts affect results.')
            self.card('04 / What this profile cannot change',
                      'Server tick rate, experience scripts, server region availability, ISP routing, or anti-cheat restrictions. '
                      'No modified clients, FastFlag packs, DLL injection, or external FPS unlockers are installed.')
        elif page == 'Other games':
            self.card('Compatibility / Guided profiles',
                      'Windows-level tweaks are broadly applicable. The profiles below are guidance only: no automatic game-config edits or tested compatibility guarantee. '
                      'Game versions and anti-cheat permissions vary.')
            for title, body in [
                ('Fortnite', 'Compare Performance rendering mode with DX12 on your hardware. Use in-game NVIDIA Reflex if supported. Reduce shadows and heavy effects. Shader compilation may affect early runs.'),
                ('VALORANT', 'Use supported in-game Reflex settings and a stable FPS cap. Compare Multithreaded Rendering where available. Anti-cheat and Windows security settings are managed by the game and OS.'),
                ('Counter-Strike 2', 'Use supported in-game Reflex settings. Compare frame times with a sustainable FPS cap and lower demanding graphics settings. Network/server delay is separate.'),
                ('Minecraft Java / Bedrock', 'Reduce render distance; simulation distance can affect CPU load. Java and Bedrock have different settings. This tool does not change JVM memory allocations or install mods.'),
                ('Other titles / Unsupported automation', 'Use the Windows and latency sections. There are no automatic profiles for other executables, launchers, consoles, or mobile games.')]:
                self.card(title, body)
        else:
            try:
                state = load()
                summary = (f"Registry groups: {len(state.get('registry', {}))}  •  "
                           f"Power backup: {'yes' if state.get('power') else 'no'}  •  "
                           f"Process backups: {len(state.get('processes', {}))}\n"
                           f"Input settings: {len(state.get('input', {}))}  •  Power options: {len(state.get('power_options', {}))}")
            except Exception as error:
                summary = str(error)
            self.card('Saved changes', summary + '\nRestore affects only settings changed by this app. Manual Windows settings changes are not backed up.',
                      [self.action('Restore all saved tweaks', restore_all)])
            self.card('Local data', str(ROOT) + '\nKeep restore.json until your changes are restored. Run only one copy of the app.',
                      [self.action('Open data folder', open_data, False)])
            self.card('Activity / Recent history', '\n\n'.join(reversed(self.history[-12:])) or 'No actions yet.')
            self.card('Desktop app / Install for this account',
                      'The standalone EXE includes Python. Install a local copy and create Desktop and Start menu shortcuts. '
                      'Your restore data stays in your user profile. To remove the app later, delete its shortcuts and installation folder after restoring any tweaks.',
                      [self.action('Install app & shortcuts', install_app, False)])
            self.card(f'Kryptic’s Tweaks / Desktop edition {APP_VERSION}',
                      'Original K emblem • Local password access • No subscription or license server connected. '
                      'Game profiles are not benchmark-certified. This release is not digitally signed.')

    def filter_cards(self, event=None):
        query = self.search_entry.get().strip().lower()
        for frame, text in self.search_cards:
            frame.pack_forget()
            if query in text:
                frame.pack(fill='x', pady=6)
        self.canvas.yview_moveto(0)

    def profiles_page(self):
        self.card('Your session, your preset',
                  'Select individual preferences and apply them together. Original values are saved per setting. '
                  'Power and mouse settings stay individually controlled in Input & power.')
        options = self.card('Gaming session / Customize before applying',
                            'The default selection enables Game Mode. Recording settings are optional if you use clips or Xbox capture.')
        presets = {'Gaming light': ['game_mode'],
                   'Gaming without recording': ['game_mode', 'capture', 'background_capture'],
                   'Desktop simplicity': ['transparency']}
        try:
            saved = read_json(ROOT / 'custom-profile.json', [])
            if isinstance(saved, list) and all(key in REGISTRY for key in saved):
                presets['Saved custom'] = saved
        except (OSError, ValueError):
            pass
        preset = ttk.Combobox(options, state='readonly', values=list(presets))
        preset.set('Gaming light')
        preset.pack(fill='x', pady=8)
        choices = {}
        for key, caption, default in [('game_mode', 'Enable Game Mode', True),
                                      ('capture', 'Disable Game DVR preference', False),
                                      ('background_capture', 'Disable background capture', False),
                                      ('transparency', 'Disable desktop transparency (desktop appearance only)', False)]:
            value = tk.BooleanVar(value=default)
            choices[key] = value
            check = tk.Checkbutton(options, text=caption, variable=value, bg=PANEL, fg=TEXT,
                                   selectcolor=CARD, activebackground=PANEL, activeforeground=ACCENT,
                                   anchor='w', pady=7, relief='flat')
            check.pack(fill='x')
        def select_preset(event=None):
            for key, value in choices.items():
                value.set(key in presets[preset.get()])
        preset.bind('<<ComboboxSelected>>', select_preset)
        row = tk.Frame(options, bg=PANEL)
        row.pack(fill='x')
        def apply():
            selected = [key for key, value in choices.items() if value.get()]
            if selected:
                self.job('Custom gaming profile', lambda: apply_profile(selected))
            else:
                messagebox.showinfo('Select settings', 'Select at least one preference.', parent=self)
        button = self.button(row, 'Apply selected settings →', apply, True)
        self.buttons.append(button)
        button.config(state='disabled' if self.busy else 'normal')
        def save_custom():
            selected = [key for key, value in choices.items() if value.get()]
            def persist():
                write_json(ROOT / 'custom-profile.json', selected)
                return 'Your custom selection is saved. Reopen Profiles and choose Saved custom to load it.'
            self.job('Save custom profile', persist)
        button = self.button(row, 'Save custom', save_custom)
        self.buttons.append(button)
        button.config(state='disabled' if self.busy else 'normal')
        self.card('Roblox session checklist',
                  '1. Apply your selected Windows preferences.\n2. Join the same Roblox experience/server.\n'
                  '3. Compare graphics quality and a sustainable frame-rate cap.\n4. Try the optional Roblox priority control.\n'
                  '5. Record FPS and server ping separately.',
                  [('Open Roblox profile →', lambda: self.show('Roblox'), True)])
        self.card('Fresh baseline', 'Restore saved changes before testing a new configuration. Existing backups always retain the first original value.',
                  [self.action('Restore all saved tweaks', restore_all, False)])

    def input_power_page(self):
        self.card('Precision controls / Individually reversible',
                  'Input controls change Windows pointer behavior. Advanced power options change only plugged-in values on the current power plan. '
                  'Availability varies by device; increased power use can increase heat.')
        for name, title, body in [
            ('mouse', '01 / Pointer acceleration', 'Disable Enhance Pointer Precision and acceleration thresholds for consistent desktop pointer movement. Raw-input games may ignore this. This changes aiming feel, not ping.'),
            ('animation', '02 / Client-area animations', 'Disable Windows client-area animations for snappier desktop interactions. Applications may implement their own animations. This is a desktop preference, not a game FPS boost.')]:
            self.card(title, body, [self.action('Apply', lambda n=name: input_tweak(n)),
                                   self.action('Restore', lambda n=name: input_tweak(n, True), False)])
        self.card('03 / Desktop transparency', 'Disable Windows transparency effects. This changes desktop appearance; games normally render independently.',
                  [self.action('Apply', lambda: registry_tweak('transparency')),
                   self.action('Restore', lambda: registry_tweak('transparency', True), False)])
        for name, title, body in [
            ('usb', '04 / USB selective suspend', 'Disable selective suspend while plugged in. Useful when troubleshooting USB device sleep or disconnects. It does not increase polling rate or guarantee lower input latency.'),
            ('pcie', '05 / PCIe link-state power saving', 'Disable link-state power saving while plugged in. Can avoid some power-state transitions, but increases power use. Compare frame times and temperatures.'),
            ('wifi', '06 / Wireless adapter power mode', 'Request maximum wireless performance while plugged in. Driver support varies. This does not change signal quality, ISP routing, or server distance.')]:
            self.card(title, body, [self.action('Apply on AC', lambda n=name: advanced_power(n)),
                                   self.action('Restore', lambda n=name: advanced_power(n, True), False)])

    def system_page(self):
        self.card('System inventory', 'Read your CPU, GPU, graphics driver version, Windows build, memory, and active physical network adapters.',
                  [self.action('Scan hardware', system_report), self.action('Export report', export_report, False)])
        self.card('Background memory usage', 'List the twelve processes with the largest working sets. This is memory usage, not a CPU-load ranking. Review apps before closing them yourself.',
                  [self.action('Inspect processes', process_report),
                   self.action('Task Manager', lambda: launch_tool('taskmgr.exe'), False)])
        self.card('Windows resource monitor', 'Inspect CPU, disk, network, and memory activity using the Windows resource monitor.',
                  [self.action('Open Resource Monitor', lambda: launch_tool('resmon.exe'), False)])
        self.card('Startup applications', 'Reduce unnecessary startup load by disabling only apps you recognize.',
                  [self.setting('Startup settings', 'ms-settings:startupapps')])
        self.card('Storage & maintenance', 'Review storage use and Windows cleanup recommendations. This app does not delete game caches or personal files.',
                  [self.setting('Storage settings', 'ms-settings:storagesense'),
                   self.setting('Windows Update', 'ms-settings:windowsupdate')])
        self.card('Connection & display', 'Check Ethernet/Wi-Fi status, monitor refresh rate, and per-game GPU preferences.',
                  [self.setting('Network', 'ms-settings:network-status'),
                   self.setting('Refresh rate', 'ms-settings:display-advanced'),
                   self.setting('Graphics', 'ms-settings:display-advancedgraphics')])

    def close(self):
        if self.busy:
            messagebox.showinfo('Action in progress', 'Wait for the current action to finish before closing.', parent=self)
            return
        self.destroy()


def open_data():
    ROOT.mkdir(parents=True, exist_ok=True)
    os.startfile(str(ROOT))
    return 'Local data folder opened.'


def install_app():
    if not getattr(sys, 'frozen', False):
        return 'Open the standalone KrypticsTweaks.exe to install. This copy is running from Python source.'
    folder = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'KrypticsTweaks'
    folder.mkdir(parents=True, exist_ok=True)
    executable = folder / f'KrypticsTweaks-{APP_VERSION}.exe'
    if Path(sys.executable).resolve() != executable.resolve():
        shutil.copy2(sys.executable, executable)
    escaped = str(executable).replace("'", "''")
    workdir = str(folder).replace("'", "''")
    ps("$w=New-Object -ComObject WScript.Shell; "
       "$places=@([Environment]::GetFolderPath('Desktop'),"
       "[Environment]::GetFolderPath('Programs')); foreach($p in $places) { "
       "$s=$w.CreateShortcut((Join-Path $p 'Kryptics Tweaks.lnk')); "
       f"$s.TargetPath='{escaped}'; $s.WorkingDirectory='{workdir}'; "
       f"$s.IconLocation='{escaped},0'; $s.Description='Kryptic performance workspace'; $s.Save() }}")
    return f'Installed to {folder}\nDesktop and Start menu shortcuts are ready. No Python installation is needed.'


if __name__ == '__main__':
    if sys.platform != 'win32':
        raise SystemExit('Kryptic’s Tweaks requires Windows 10 or 11.')
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex_name = 'Local\\KrypticTweaks-' + hashlib.sha256(str(Path.home()).encode()).hexdigest()[:16]
    mutex = kernel.CreateMutexW(None, False, mutex_name)
    if not mutex:
        raise ctypes.WinError()
    if kernel.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, 'Kryptic’s Tweaks is already running. Open its existing window.',
                                       'Kryptic’s Tweaks', 0x40)
        raise SystemExit(0)
    try:
        App().mainloop()
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)
