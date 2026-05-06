# wpp-drive-mapper

A silent Windows utility suite for [winPenPack](https://www.winpenpack.com/) portable software ecosystems. Subfolders placed alongside the executable are mapped to virtual drive letters using `subst`, launched via a hidden `cmd.exe` window — identical to typing `subst` at a prompt: volatile, session-scoped, immediately visible in Explorer, never persisted across reboots.

---

## Tools

| Executable | Purpose |
|---|---|
| `wpp-drive-mapper.exe` | Map subfolders to drive letters and launch winPenPack |
| `wpp-clean-drives.exe` | Remove stale or persistent subst mappings |

---

## wpp-drive-mapper

### How it works

Scans every **immediate subfolder** in the same directory as the `.exe`:

| Folder name | Behaviour |
|---|---|
| Single letter (e.g. `W`) | Try to assign that exact letter. If already taken, fall back to the first free letter scanning **Z → A**. |
| Multiple letters (e.g. `Tools`) | Assign the first free letter scanning **Z → A**. |

Before assigning, `GetLogicalDrives` is queried so physical disks, USB drives, network shares, Google Drive, pCloud and any other mounted volume are never overwritten.

After each mapping, if `winPenPackNet.exe` or `winPenPack.exe` exists inside the folder it is launched fully detached (`Net` variant takes priority). If the process is already running it is not launched again. The program moves on to the next folder immediately without waiting.

### State file (INI)

A file `wpp-drive-mapper.ini` is maintained in the same directory:

```ini
[mappings]
W = D:\Portable\W
Z = D:\Portable\Tools
```

On each run:
- If the mapping is **already active** → skip `subst`, just launch the exe.
- If the INI has a letter for the folder but the **mapping is gone** (after reboot) → redo `subst` with the same letter.
- New mappings are appended; `/unmap` removes its entries.

### Command-line flags

| Flag | Effect |
|---|---|
| *(none)* | **Map** subfolders to drive letters (default). |
| `/unmap` or `/u` | **Unmap** all drives pointing to subfolders of this directory. |
| `/verbose` or `/v` | Log every operation; log file always created. |

### Logging

Log file: `YYYY-MM-DD_HH-MM-SS_wpp-drive-mapper.log` (same directory).  
Default: created only on error. Verbose (`/v`): always created.

```
2026-05-06 14:32:01 [INFO    ] === wpp-drive-mapper started (verbose, mode=map) ===
2026-05-06 14:32:01 [INFO    ] Found 3 subfolder(s): D, Tools, W
2026-05-06 14:32:01 [INFO    ] --- Processing folder: 'W' ---
2026-05-06 14:32:01 [INFO    ] Preferred letter W: is free, using it.
2026-05-06 14:32:01 [INFO    ] Mapping W: -> 'D:\Portable\W'
2026-05-06 14:32:01 [INFO    ] OK  W: -> 'D:\Portable\W'
2026-05-06 14:32:01 [INFO    ] Launching winPenPackNet.exe in 'D:\Portable\W'.
2026-05-06 14:32:01 [INFO    ] winPenPackNet.exe launched.
2026-05-06 14:32:01 [INFO    ] Done. Mapped 3 drive(s): D: -> '...', W: -> '...', Z: -> '...'
```

---

## wpp-clean-drives

Standalone utility to remove subst mappings that erroneously survived a logoff or reboot.

### How it works

Inspects every drive letter A–Z with `QueryDosDeviceW`. A drive is considered stale if:
- It IS a subst mapping (NT path starts with `\??\`), **and**
- Its target folder **no longer exists** on disk.

Those drives are removed with `subst LETTER: /D` via a hidden window.

### Command-line flags

| Flag | Effect |
|---|---|
| *(none)* | Remove only **stale** subst drives (target path missing). |
| `/all` or `/a` | Remove **all** subst drives unconditionally. |
| `/verbose` or `/v` | Log every operation; log file always created. |

### Logging

Log file: `YYYY-MM-DD_HH-MM-SS_wpp-clean-drives.log` (same directory as the exe).

---

## Directory layout example

```
wpp-drive-mapper.exe        ← main mapper
wpp-drive-mapper.ini        ← state file (auto-created)
wpp-clean-drives.exe        ← cleanup utility
W\                          ← mapped to W:
│   winPenPackNet.exe
D\                          ← mapped to D:
Tools\                      ← multi-letter, first free letter from Z
│   winPenPack.exe
Archive\                    ← multi-letter, next free letter from Z
```

---

## Requirements

- **Windows only**
- Python 3.10+ and [PyInstaller](https://pyinstaller.org/) to build from source

---

## Building from source

```
pip install pyinstaller
```

**Command Prompt:**
```
build.bat
```

**PowerShell:**
```powershell
.\build.ps1
```

Output: `dist\wpp-drive-mapper.exe` and `dist\wpp-clean-drives.exe`.

---

## Notes

- Mappings use `cmd /c subst` in a hidden window — volatile by construction, never written to the registry.
- To remove a single mapping manually: `subst LETTER: /D`.
- `wpp-clean-drives.exe /all` is the nuclear option: removes every subst on the system.

---

## License

MIT
