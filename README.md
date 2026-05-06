# wpp-drive-mapper

A silent Windows utility that maps subfolders — placed alongside the executable — to virtual drive letters using the Win32 `DefineDosDeviceW` API, following winPenPack conventions. Mappings are session-scoped and automatically removed on logoff, identical to running `subst` at a command prompt.

---

## How it works

On launch the program scans every **immediate subfolder** in the same directory as the `.exe` and applies the following rules:

| Folder name | Behaviour |
|---|---|
| Single letter (e.g. `W`) | Try to assign that exact letter. If already taken, fall back to the first free letter scanning **Z → A**. |
| Multiple letters (e.g. `Tools`) | Assign the first free letter scanning **Z → A**. |

After each mapping, if `winPenPackNet.exe` or `winPenPack.exe` exists inside the folder it is launched automatically (`Net` variant takes priority) as a fire-and-forget process — the program immediately moves on to the next folder without waiting for it to exit.

The executable runs **completely silently** — no console window, no dialogs, no output of any kind.

---

## Command-line flags

Flags are **case-insensitive** and accept both `/` and `-` as prefix.

| Flag | Effect |
|---|---|
| *(none)* | **Map mode** — assign drive letters to subfolders (default). |
| `/unmap` or `/u` | **Unmap mode** — remove all virtual drives that point to a subfolder of the executable's directory. Physical drives and unrelated mappings are never touched. |
| `/verbose` or `/v` | Log every operation at INFO level; log file is always created. |

Flags can be combined:

```
wpp-drive-mapper.exe /unmap /v
```

---

## Logging

Log files are written to the **same directory as the executable** and named:

```
YYYY-MM-DD_HH-MM-SS_wpp-drive-mapper.log
```

Every line begins with the local **date and time of that specific event**:

```
2026-05-06 14:32:01 [INFO    ] === wpp-drive-mapper started (verbose, mode=map) ===
2026-05-06 14:32:01 [INFO    ] Found 3 subfolder(s): D, Tools, W
2026-05-06 14:32:01 [INFO    ] --- Processing folder: 'W' ---
2026-05-06 14:32:01 [INFO    ] Preferred letter W: is free, using it.
2026-05-06 14:32:01 [INFO    ] Mapping W: -> 'D:\Portable\W'
2026-05-06 14:32:01 [INFO    ] OK  W: -> 'D:\Portable\W'
2026-05-06 14:32:01 [INFO    ] Launching winPenPackNet.exe in 'D:\Portable\W'.
2026-05-06 14:32:09 [INFO    ] winPenPackNet.exe exited (rc=0).
...
2026-05-06 14:35:00 [INFO    ] === wpp-drive-mapper started (verbose, mode=unmap) ===
2026-05-06 14:35:00 [INFO    ] Found own mapping: W: -> 'D:\Portable\W', removing.
2026-05-06 14:35:00 [INFO    ] OK  W: removed.
2026-05-06 14:35:00 [INFO    ] Done. Letters unmapped: W:, Z:, Y:
```

In **default (silent) mode** the log file is only created when at least one error is recorded.

---

## Directory layout example

```
wpp-drive-mapper.exe        ← this program
W\                          ← mapped to W: (or fallback from Z)
│   winPenPackNet.exe       ← launched automatically after mapping
D\                          ← mapped to D: (or fallback from Z)
Tools\                      ← multi-letter: first free letter from Z
│   winPenPack.exe          ← launched automatically after mapping
Archive\                    ← multi-letter: next free letter from Z
```

---

## Requirements

- **Windows only** (uses `DefineDosDeviceW` and `QueryDosDeviceW` Win32 APIs)
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

- Drive mappings are **session-scoped**: `DefineDosDeviceW` is called directly in-process (not via a child `cmd.exe`), so mappings behave identically to `subst` typed at a prompt and are removed automatically on logoff.
- `/unmap` uses `QueryDosDeviceW` to inspect every active drive letter and only removes mappings whose target is a direct subfolder of the executable's directory. It will never touch physical drives or unrelated virtual mappings.
- To remove a single mapping manually before logoff: `subst LETTER: /D`.

---

## License

MIT
