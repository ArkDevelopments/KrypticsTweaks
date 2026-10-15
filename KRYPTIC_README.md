# Kryptic's Tweaks — desktop edition 0.7

## What's new in 0.6

- Centralized application versioning so the interface and installer stay in sync.
- Safer JSON persistence with explicit encoding, newline-terminated files, and atomic replacement.
- Clearer subprocess diagnostics for missing Windows tools, launch failures, and timeouts.

## What's new in 0.5

- Removed the earlier-terminal restore feature and its bundled dependency.
- Updated app branding, executable version information, and per-user installation.
- Added a branded launch website, portable release package, release checksums, and share assets.

## What's new in 0.4

- Animated startup screen with an orbital logo treatment, named initialization stages, and a smoothly animated percentage bar. It opens sign-in after startup completes; the bar represents initialization stages, not fake PC optimization.
- Redesigned dashboard with quick controls, original artwork, backup counts, real CPU/RAM meters, and nine workspace sections.
- **Profiles:** choose Gaming light, Gaming without recording, or Desktop simplicity; select and save your own custom combination of Game Mode, recording, and transparency preferences.
- **Input & power:** restoreable pointer acceleration, client-area animation, desktop transparency, AC USB selective suspend, AC PCIe link-state power saving, and AC wireless-adapter performance settings.
- **System tools:** hardware/driver inventory, exportable reports, top-memory process list, Resource Monitor, Task Manager, and Windows settings shortcuts.
- **Latency lab:** saved measurement history and comparison with the previous measurement to the same IP.
- Search cards on each page (**Ctrl+F**); refresh a page with **Ctrl+R**.
- Persistent activity history, themed result windows with Copy, and single-instance protection.
- Windows executable version information and versioned per-user installation.

Input changes can alter pointer feel. Desktop animations/transparency are desktop preferences, not game FPS boosts. Power options apply only while plugged in and may be unavailable on some devices. Increased power use can increase heat. Originals are stored per setting and per power plan. Restore all includes these settings, retaining failed backups for retry.

## Open the Windows app

Double-click **KrypticsTweaks.exe**. Python and Command Prompt are not needed.
Password: **Kryptic**.

To install for your Windows account, open **Restore & activity → Install app & shortcuts**.
This creates Desktop and Start menu shortcuts and copies the executable to
`%LOCALAPPDATA%\Programs\KrypticsTweaks`. No administrator access is needed for installation.

The portable ZIP contains the executable and this guide. Extract it before running.
There is no public download website configured; the ZIP can be distributed as a file.
The executable is currently unsigned.

To remove the app, first restore any settings you want undone, close the app, and
delete its installation folder and shortcuts. Restore data remains in
`%LOCALAPPDATA%\KrypticTweaks` until you remove it yourself.

### New design

Original K emblem and Windows icon, charcoal/amber dashboard, quick Apply/Restore
controls, live CPU and memory meters, CPU history graph, and game/latency tiles.
Meters display real Windows system counters, not an optimization score.

## Run from source

Python 3.9+ / Windows 10–11 / standard library + Tkinter (included with normal Python installations).

```powershell
python Scripts/kryptic_tweaks.py
```

Password: **Kryptic** (case-sensitive). The animated local password gate is cosmetic access control, not a secure licensing system. The password is discoverable in distributed Python code.

## Included

- Dark desktop interface with scrollable pages, sidebar navigation, and scramble-lock login.
- Reversible current-user Game Mode, Game DVR, and capture preferences.
- Existing High performance power-plan selection and restore.
- Optional Above normal priority for the running Roblox desktop player; PID and start time are checked during restore.
- Ten-probe ICMP baseline: average/min/max RTT, successive variation, and probe loss. Results are saved locally. This does not measure Roblox server ping or end-to-end input latency.
- Windows shortcuts for GPU settings, refresh rate, mouse, startup apps, recording, and network settings.
- Roblox-specific guidance and guidance-only profiles for Fortnite, VALORANT, CS2, and Minecraft.
- Restore center for Kryptic's current saved settings and persistent activity history.

Windows registry preferences may be overridden or ignored by device policies or Windows versions. Restart games after changing settings; sign out or reboot if Windows requires it. Manual changes in Windows settings are not tracked by app restore. Exiting does not undo applied changes. Keep `%LOCALAPPDATA%\KrypticTweaks\restore.json` until restoration is complete. Use one instance at a time.

The first release is a local preview, not a verified commercial optimization product. Frame rate, frame pacing, network RTT, and input latency are different metrics. Compare one change at a time; no guaranteed improvement is claimed. Supported games listed here have not been benchmark-certified.

## Rebuild the executable

From the Scripts directory, using a development environment:

```powershell
python -m pip install pyinstaller pillow
python build_kryptic.py
```

Output: `dist\KrypticsTweaks.exe`. Test the resulting build on clean Windows machines before distribution. An executable bundles the app; it does not make the password secure.

For a paid release, implement individual license entitlements with a server or signed license tokens, establish a support/update workflow, sign releases, and collect reproducible compatibility/benchmark results. This preview does not implement payment processing or licensing.
