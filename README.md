# wpp-drive-mapper

A silent Windows utility that maps subfolders — placed alongside the executable — to virtual drive letters using the built-in `subst` command. Designed for [winPenPack](https://www.winpenpack.com/) portable software ecosystems, where each portable suite lives in its own folder and is accessed via a consistent drive letter.

---

## How it works

On launch the program scans every **immediate subfolder** in the same directory as the `.exe` and applies the following rules:

| Folder name | Behaviour |
|---|---|
| Single letter (e.g. `W`) | Try to assign that exact letter. If already taken, fall back to the first free letter scanning **Z → A**. |
| Multiple letters (e.g. `Tools`) | Assign the first free letter scanning **Z → A**. |

After each `subst` call, if a `winPenPack.exe` is found inside the folder it is launched automatically. The program waits for it to exit before processing the next folder.

The executable runs **completely silently** — no console window, no dialogs, no output of any kind.

---

## Command-line flags

| Flag | Effect |
|---|---|
| *(none)* | Silent mode. No log file is written unless an error occurs. |
| `/v` or `/verbose` | Verbose mode. Every operation is logged (INFO level) and the log file is always created, even on a clean run. |

Flags are **case-insensitive** (`/V`, `/Verbose`, `/VERBOSE` all work).

Example — run from a shortcut or scheduled task with verbose logging:

```
wpp-drive-mapper.exe /v
```

---

## Logging

Log files are written to the **same directory as the executable** and named:

```
YYYY-MM-DD_HH-MM-SS_wpp-drive-mapper.log
```

Every line begins with the local **date and time of that specific event** (`YYYY-MM-DD HH:MM:SS`), followed by the severity level and the message:

```
2026-05-06 14:32:01 [INFO    ] === wpp-drive-mapper started (verbose mode) ===
2026-05-06 14:32:01 [INFO    ] Base directory: 'D:\Portable'
2026-05-06 14:32:01 [INFO    ] Found 3 subfolder(s): D, Tools, W
2026-05-06 14:32:01 [INFO    ] --- Processing folder: 'D' ---
2026-05-06 14:32:01 [INFO    ] Preferred letter D: is free, using it.
2026-05-06 14:32:01 [INFO    ] Running: subst D: "D:\Portable\D"
2026-05-06 14:32:01 [INFO    ] OK  D: -> 'D:\Portable\D'
2026-05-06 14:32:01 [INFO    ] No winPenPack.exe in 'D:\Portable\D', skipping.
2026-05-06 14:32:01 [INFO    ] --- Processing folder: 'Tools' ---
2026-05-06 14:32:01 [INFO    ] Multi-character name, searching first free letter from Z.
2026-05-06 14:32:01 [INFO    ] Letter assigned: Z
2026-05-06 14:32:01 [INFO    ] Running: subst Z: "D:\Portable\Tools"
2026-05-06 14:32:01 [INFO    ] OK  Z: -> 'D:\Portable\Tools'
2026-05-06 14:32:02 [INFO    ] Launching winPenPack.exe in 'D:\Portable\Tools'.
2026-05-06 14:32:10 [INFO    ] winPenPack.exe exited (rc=0).
```

In **default (silent) mode** the log file is only created if at least one error is recorded — no empty files are left behind on successful runs.

---

## Directory layout example

```
wpp-drive-mapper.exe        ← this program
W\                          ← mapped to W: (or fallback from Z)
│   winPenPack.exe          ← launched automatically after subst
D\                          ← mapped to D: (or fallback from Z)
Tools\                      ← multi-letter: first free letter from Z
│   winPenPack.exe          ← launched automatically after subst
Archive\                    ← multi-letter: next free letter from Z
```

---

## Requirements

- **Windows only** (uses `subst` and the Win32 `GetLogicalDrives` API)
- Python 3.10+ (only needed to build from source)
- [PyInstaller](https://pyinstaller.org/) (only needed to build from source)

No third-party Python packages are required at runtime.

---

## Building from source

Install the build dependency once:

```
pip install pyinstaller
```

Then run either build script from the project root:

**Command Prompt:**
```
build.bat
```

**PowerShell:**
```powershell
.\build.ps1
```

The compiled executable will be produced at:

```
dist\wpp-drive-mapper.exe
```

PyInstaller flags used:

| Flag | Purpose |
|---|---|
| `--onefile` | Bundle everything into a single `.exe` |
| `--windowed` | No console window (background / GUI-subsystem mode) |
| `--clean` | Remove cached build artefacts before each build |

---

## Notes

- Drive letter assignment within a single run is tracked internally to avoid double-booking, even if an individual `subst` call fails.
- The program exits silently with code `1` on non-Windows systems.
- `subst` mappings are **session-scoped** — they are removed when the user logs off. To remove one manually: `subst LETTER: /D`.

---

## License

MIT
