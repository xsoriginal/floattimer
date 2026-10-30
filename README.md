# FloatTimer

A compact, always-on-top Windows countdown timer.

## Run

Install Python 3.11 or later on Windows, then in this folder:

```powershell
py -m pip install -r requirements.txt
py floattimer.py
```

## Package as an executable

```powershell
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --onefile --windowed --name FloatTimer floattimer.py
```

The executable will be in `dist\FloatTimer.exe`.

## Using it

- Drag the top bar to reposition.
- Click a preset on the right to select its duration.
- Click the large time display to enter a custom time (`MM:SS` or minutes).
- Use play/pause and reset beneath the timer.
- Use the gear icon to change presets, font, colours, opacity and behaviour.
- The app saves its settings to `%APPDATA%\FloatTimer\settings.json`.
- Closing the window hides it to the system tray; use **Quit** in the tray menu to exit.

The app uses a monotonic clock so the countdown stays accurate if the system is busy.

## Top-centre dock mode

- Click the **⇧** button in the timer title bar to dock it at the top centre of its current monitor.
- Only the countdown remains visible; click the countdown to restore the full timer to its previous position.
- The timer keeps counting while docked. The tray menu also has **Dock / restore**.

## Build on GitHub (no Python needed on your Surface)

1. Create a GitHub repository and upload **the contents of this folder**, including `.github/workflows/build-windows.yml` (the `.github` folder may be hidden in some file managers).
2. Open the repository's **Actions** tab and select **Build Windows EXE**.
3. Click **Run workflow** (or push a change to `main`/`master`).
4. When the workflow succeeds, open its run and download the **FloatTimer-Windows** artifact.
5. Extract the downloaded ZIP to obtain `FloatTimer.exe`. Copy it to the Surface and run it; no Python installation required.

If your school blocks unsigned executables, request IT approval rather than bypassing device policies. Windows SmartScreen may also warn about newly built unsigned software.
