# Stay in Path

![Stay in Path logo](assets/stay-in-path.png)

An **offline-first** Windows habit tracker with a GitHub-style contribution heatmap,
a floating desktop widget, mission progress, focus timer and weekly review.

## Features

- **Yes/No habits** and **timed habits** (minutes per day)
- **Edit a habit** (rename, change the daily target) or **archive** it
- **Restore archived habits** or delete them permanently from the Habits page
- **Weighted heatmap**: average completion of active habits, normalized to each target
- **Individual heatmaps** and **current/longest daily streaks**
- **One Main Mission** with a title, optional deadline, completed and total milestones
- **Focus Timer** that adds recorded time to a timed habit when you press *Stop & Save*
- **Crash/sleep-safe timer**: a running session is remembered and offered again after a restart
- **Weekly Review**: completion percentages, focus minutes, and prior-week comparison
- **Always-on-top desktop widget**, movable by dragging its heading, and hide/show via tray
- **Windows tray icon** and optional **Start with Windows** control *(see below)*
- **Private SQLite database**, no account, tracking, cloud service, or API key needed

### Screenshot / visuals

The app uses a dark, calm "control room" look: a slowly drifting aurora background, glass
cards with neon corner ticks, animated rings/counters/bars, a pulsing focus timer, crossfading
page changes and slide-in toasts. Motion is deliberately subtle and never blocks input.
The logo was generated for the project and is distributed with the app.

## Install on Windows (from source)

1. Install **Python 3.10–3.15**, enabling the `py` launcher (from [python.org](https://www.python.org/downloads/windows/)). Python 3.15 is supported by current PySide6 and PyInstaller releases.
2. Download this repository as a ZIP, extract it, and double-click **`run_windows.bat`**.
3. On the first launch, the script creates `.venv` and installs PySide6; subsequent starts reuse it.
4. To set up an automatic login launch, use the instructions below. You can pin the app to the taskbar or create a Windows shortcut to the built executable.

In PowerShell/Command Prompt instead:

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Make a standalone `.exe` (Windows only)

Double-click **`build_windows.bat`**. When it finishes:

```text
dist\StayInPath.exe
```

That standalone file includes Python, PySide6 and icons; end users do **not** need Python.
To keep Windows autostart stable, move the executable to its **final folder before enabling autostart**. Avoid running a downloaded executable directly from your Downloads folder if you plan to move it later.

**Important:** PyInstaller builds the target executable for the OS it runs on. This repo also includes a Windows GitHub Actions workflow that produces an EXE artifact on demand (Actions → Build Windows app → Run workflow), so you can create the EXE with GitHub even without running the build script yourself.

## System tray and autostart

The app minimizes to the tray when closing the main dashboard. Right-click the tray icon to reopen the main window, show/hide the widget, or **Quit completely**.

**To start automatically on Windows:** run `StayInPath.exe`, use the `Start with Windows` checkbox near the bottom of the Dashboard, or create a standard Windows Startup shortcut to the executable. If the checkbox is unavailable, the shortcut method works: press `Win+R`, enter `shell:startup`, and place a shortcut to the EXE there. Avoid enabling both methods simultaneously.

The widget is an always-on-top **floating window**, not an Explorer wallpaper-embedded gadget. You can drag it by the upper area. It stays available while the main app is in the tray.

## Data and privacy

Your personal data is stored separately from the code in:

```text
%LOCALAPPDATA%\StayInPath\stay_in_path.db
```

Do not commit that folder to GitHub. If you upgrade the app, keep this database to preserve your history.
For manual backup, **Quit completely** using the tray menu before copying the database file.

## Sharing on GitHub

1. Create a **public** repository named `stay-in-path` on GitHub.
2. Upload this project, including `README.md`, `LICENSE`, `assets`, `.github` and source files; never upload `.venv`, `dist`, private data, or `.db` files.
3. On your own Windows PC, run `build_windows.bat` and verify `dist\StayInPath.exe` works.
4. On GitHub, select **Releases → Draft a new release**, create a tag `v0.1.0`, attach **`dist\StayInPath.exe`**, write a short description and publish.
5. Other people can open **Releases**, download the EXE, and run it without installing Python.

**Unsigned executable warning:** Windows SmartScreen may display an unfamiliar-publisher warning for a new, unsigned app. Do not recommend bypassing protections. Distribute source alongside binaries, use a trusted release channel, and consider code signing when sharing more widely.

## Developer tests

```sh
python -m unittest discover -s tests -v
```

## Limitations of v0.1

- Windows is the target platform. The floating widget is **always on top**, not part of the Windows desktop wallpaper.
- Focus time is saved to the date when *Stop & Save* is clicked. Timer state survives sleep and restarts, but a session is only written to your habit log when you stop it.
- Archived habits keep their stored data but aren't included in current graphs and statistics. Restore one from the Habits page to bring it back.
- There is no account sync, export UI, notifications, or automated code signing.

## License

MIT (see `LICENSE`). PySide6 uses LGPL/GPL and commercial license options; Qt's LGPL obligations also apply when distributing binaries. Review the official Qt licensing terms before broad distribution.
