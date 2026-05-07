"""
wpp-drive-mapper.py

Maps subfolders located in the same directory as the executable to virtual
drive letters via Windows `subst`, following winPenPack conventions.

Behaviour
---------
- Single-letter folder (e.g. "W"):  attempt to use that letter; if already
  taken, fall back to the first free letter scanning backwards from Z.
- Multi-letter folder (e.g. "Tools"): assign the first free letter from Z.
- For every folder: if winPenPackNet.exe or winPenPack.exe exists inside it,
  launch it (fire-and-forget) and immediately move on to the next folder.
  If the executable is already running, it is not launched again.

Drive mapping
-------------
Runs `cmd /c subst` in a hidden window so mappings are:
  - volatile (session-scoped, removed automatically on logoff)
  - not persistent across reboots
  - immediately visible in Explorer / "This PC"
identical to typing `subst` at a command prompt.

State file (INI)
----------------
A file named <exe-name>.ini (same directory as the exe) records every
letter-to-folder mapping.  On the next run:
  - If the INI entry exists AND the subst mapping is already active  -> skip subst.
  - If the INI entry exists BUT the subst mapping is gone (reboot)   -> redo subst.
  - New mappings are appended to the INI.
  - /unmap clears the INI entries it removes.

Unmap mode
----------
Pass /unmap (or /u) to remove all virtual drives whose target path points
to a subfolder of the executable's directory.  Only mappings created by
this program are affected; physical drives and unrelated subst mappings
are left untouched.

Logging
-------
Default mode  : a log file is created ONLY if at least one error occurs.
Verbose mode  : pass /v or /verbose; every operation is logged (INFO level)
                and the log file is always created.

Log file name : YYYY-MM-DD_HH-MM-SS_<program-name>.log (same directory).
Every log line begins with the local date/time of that specific event.
No output is ever produced to stdout/stderr.
"""

import configparser
import ctypes
import ctypes.wintypes
import datetime
import logging
import os
import string
import subprocess
import sys

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_exe_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_program_name() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.basename(sys.executable)
    else:
        base = os.path.basename(__file__)
    return os.path.splitext(base)[0]


def get_ini_path(exe_dir: str) -> str:
    return os.path.join(exe_dir, f"{get_program_name()}.ini")


# ---------------------------------------------------------------------------
# Command-line parsing
# ---------------------------------------------------------------------------

def parse_args() -> tuple:
    """Return (verbose: bool, unmap: bool)."""
    args = {a.lstrip("/-").lower() for a in sys.argv[1:]}
    return bool(args & {"v", "verbose"}), bool(args & {"u", "unmap"})


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class _LazyFileHandler(logging.Handler):
    """Creates the log file only on first emit (no empty files on clean runs)."""

    def __init__(self, path: str, encoding: str = "utf-8") -> None:
        super().__init__()
        self._path = path
        self._encoding = encoding
        self._fh = None

    def _ensure_open(self) -> None:
        if self._fh is None:
            self._fh = logging.FileHandler(self._path, encoding=self._encoding)
            self._fh.setFormatter(self.formatter)

    def emit(self, record):
        self._ensure_open()
        self._fh.emit(record)

    def close(self):
        if self._fh is not None:
            self._fh.close()
        super().close()


def build_logger(exe_dir: str, verbose: bool) -> logging.Logger:
    ts  = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(exe_dir, f"{ts}_{get_program_name()}.log")
    level = logging.INFO if verbose else logging.ERROR
    fmt   = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.FileHandler(path, encoding="utf-8") if verbose \
              else _LazyFileHandler(path)
    handler.setLevel(level)
    handler.setFormatter(fmt)
    logger = logging.getLogger("wpp-drive-mapper")
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger


# ---------------------------------------------------------------------------
# INI state file
# ---------------------------------------------------------------------------

_INI_SECTION = "mappings"


def ini_load(ini_path: str) -> configparser.ConfigParser:
    """Load (or create empty) the INI state file."""
    cfg = configparser.ConfigParser()
    cfg.optionxform = str          # preserve letter case
    if os.path.isfile(ini_path):
        cfg.read(ini_path, encoding="utf-8")
    if not cfg.has_section(_INI_SECTION):
        cfg.add_section(_INI_SECTION)
    return cfg


def ini_save(cfg: configparser.ConfigParser, ini_path: str) -> None:
    with open(ini_path, "w", encoding="utf-8") as f:
        cfg.write(f)


def ini_set(cfg: configparser.ConfigParser, letter: str, folder: str) -> None:
    cfg.set(_INI_SECTION, letter.upper(), folder)


def ini_remove(cfg: configparser.ConfigParser, letter: str) -> None:
    cfg.remove_option(_INI_SECTION, letter.upper())


def ini_get_letter_for_folder(cfg: configparser.ConfigParser,
                               folder: str) -> str | None:
    """Return the letter recorded in the INI for *folder*, or None."""
    folder_norm = os.path.normcase(os.path.normpath(folder))
    for letter, path in cfg.items(_INI_SECTION):
        if os.path.normcase(os.path.normpath(path)) == folder_norm:
            return letter.upper()
    return None


# ---------------------------------------------------------------------------
# Hidden-window subprocess helper
# ---------------------------------------------------------------------------

def _run_hidden(cmd: str) -> tuple:
    """Run *cmd* via cmd.exe with a fully hidden window. Returns (rc, stderr)."""
    si = subprocess.STARTUPINFO()
    si.dwFlags    |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0   # SW_HIDE
    result = subprocess.run(
        ["cmd.exe", "/c", cmd],
        startupinfo=si,
        creationflags=0x08000000,   # CREATE_NO_WINDOW
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.returncode, result.stderr.strip()


# ---------------------------------------------------------------------------
# Windows drive-letter helpers
# ---------------------------------------------------------------------------

def used_drive_letters() -> set:
    """All letters in use: physical, USB, network, Google Drive, pCloud, subst…"""
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    return {l for i, l in enumerate(string.ascii_uppercase) if bitmask & (1 << i)}


def first_free_from_z(reserved: set) -> str | None:
    taken = used_drive_letters() | reserved
    for l in reversed(string.ascii_uppercase):
        if l not in taken:
            return l
    return None


def get_subst_target(letter: str) -> str | None:
    """Return the Win32 path for a subst mapping, or None if not a subst drive."""
    buf = ctypes.create_unicode_buffer(4096)
    ret = ctypes.windll.kernel32.QueryDosDeviceW(f"{letter.upper()}:", buf, len(buf))
    if not ret:
        return None
    nt = buf.value
    return nt[4:] if nt.startswith("\\??\\") else None


# ---------------------------------------------------------------------------
# subst helpers
# ---------------------------------------------------------------------------

def run_subst(letter: str, folder: str, logger: logging.Logger) -> bool:
    logger.info("Mapping %s: -> '%s'", letter.upper(), folder)
    rc, err = _run_hidden(f'subst {letter.upper()}: "{folder}"')
    if rc == 0:
        logger.info("OK  %s: -> '%s'", letter.upper(), folder)
        return True
    logger.error("subst failed '%s' -> %s: (rc=%d) %s", folder, letter, rc, err)
    return False


def remove_subst(letter: str, logger: logging.Logger) -> bool:
    logger.info("Unmapping %s:", letter.upper())
    rc, err = _run_hidden(f"subst {letter.upper()}: /D")
    if rc == 0:
        logger.info("OK  %s: removed.", letter.upper())
        return True
    logger.error("subst /D failed %s: (rc=%d) %s", letter, rc, err)
    return False


# ---------------------------------------------------------------------------
# Process detection
# ---------------------------------------------------------------------------

def _enum_process_paths() -> list:
    """
    Return a list of full executable paths for all running processes.
    Uses EnumProcesses + OpenProcess + QueryFullProcessImageNameW.
    Processes that cannot be opened (access denied) are silently skipped.
    """
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    count   = 1024
    while True:
        buf  = (ctypes.wintypes.DWORD * count)()
        cb   = ctypes.sizeof(buf)
        cb_needed = ctypes.wintypes.DWORD(0)
        ok = ctypes.windll.psapi.EnumProcesses(
            ctypes.byref(buf), cb, ctypes.byref(cb_needed)
        )
        if not ok:
            return []
        n = cb_needed.value // ctypes.sizeof(ctypes.wintypes.DWORD)
        if cb_needed.value < cb:
            pids = list(buf[:n])
            break
        count *= 2   # buffer was too small, retry

    paths = []
    for pid in pids:
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not h:
            continue
        try:
            name_buf  = ctypes.create_unicode_buffer(32768)
            name_size = ctypes.wintypes.DWORD(32768)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                h, 0, name_buf, ctypes.byref(name_size)
            ):
                paths.append(name_buf.value)
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    return paths


def is_process_running(exe_path: str) -> bool:
    """
    Return True if a process whose full image path matches *exe_path*
    (case-insensitive) is currently running.
    """
    target = os.path.normcase(os.path.normpath(exe_path))
    return any(
        os.path.normcase(os.path.normpath(p)) == target
        for p in _enum_process_paths()
    )


# ---------------------------------------------------------------------------
# winPenPack launcher
# ---------------------------------------------------------------------------

_DETACHED_PROCESS         = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def launch_winpenpack(folder: str, logger: logging.Logger) -> None:
    """
    Look for winPenPackNet.exe then winPenPack.exe.  Skip if already running.
    Launch fully detached so the parent continues immediately.
    """
    for candidate in ("winPenPackNet.exe", "winPenPack.exe"):
        exe_path = os.path.join(folder, candidate)
        if not os.path.isfile(exe_path):
            continue
        if is_process_running(exe_path):
            logger.info("%s already running in '%s', skipping launch.", candidate, folder)
            return
        logger.info("Launching %s in '%s'.", candidate, folder)
        try:
            subprocess.Popen(
                [exe_path],
                cwd=folder,
                creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            logger.info("%s launched.", candidate)
        except Exception as exc:
            logger.error("Failed to launch %s in '%s': %s", candidate, folder, exc)
        return

    logger.info("No winPenPack launcher found in '%s', skipping.", folder)


def is_single_letter(name: str) -> bool:
    return len(name) == 1 and name.upper() in string.ascii_uppercase


# ---------------------------------------------------------------------------
# Map mode
# ---------------------------------------------------------------------------

def process_folders(exe_dir: str, logger: logging.Logger) -> None:
    ini_path = get_ini_path(exe_dir)
    cfg      = ini_load(ini_path)
    ini_dirty = False

    try:
        entries = os.listdir(exe_dir)
    except Exception as exc:
        logger.error("Cannot list directory '%s': %s", exe_dir, exc)
        return

    folders = sorted(e for e in entries if os.path.isdir(os.path.join(exe_dir, e)))
    logger.info("Found %d subfolder(s): %s", len(folders), ", ".join(folders) or "(none)")

    # Seed reserved with every currently occupied letter (physical, network,
    # Google Drive, pCloud, etc.) so we never collide.
    reserved: set = used_drive_letters()

    for folder_name in folders:
        folder_path = os.path.join(exe_dir, folder_name)
        logger.info("--- Processing folder: '%s' ---", folder_name)

        # 1. Check if subst mapping already active for this exact path.
        active_letter = None
        for l in string.ascii_uppercase:
            t = get_subst_target(l)
            if t and os.path.normcase(os.path.normpath(t)) == \
                     os.path.normcase(os.path.normpath(folder_path)):
                active_letter = l
                break

        if active_letter is not None:
            logger.info(
                "Mapping %s: -> '%s' already active, skipping subst.",
                active_letter, folder_path,
            )
            reserved.add(active_letter)
            # Keep INI in sync in case it was missing this entry.
            if ini_get_letter_for_folder(cfg, folder_path) is None:
                ini_set(cfg, active_letter, folder_path)
                ini_dirty = True
            launch_winpenpack(folder_path, logger)
            continue

        # 2. Check INI for a previously assigned letter.
        ini_letter = ini_get_letter_for_folder(cfg, folder_path)
        if ini_letter is not None and ini_letter not in reserved:
            # The INI has a letter for this folder and it is currently free
            # (subst was lost, e.g. after reboot) -> reuse the same letter.
            assigned = ini_letter
            logger.info(
                "INI has letter %s for this folder (subst gone), reusing.", assigned
            )
        else:
            # 3. Assign a new letter.
            if is_single_letter(folder_name):
                desired = folder_name.upper()
                if desired not in reserved:
                    assigned = desired
                    logger.info("Preferred letter %s: is free, using it.", desired)
                else:
                    logger.info("Letter %s: is taken, searching from Z.", desired)
                    assigned = first_free_from_z(reserved)
                    if assigned is None:
                        logger.error("No free drive letter for '%s'.", folder_name)
                        continue
                    logger.info("Fallback letter: %s", assigned)
            else:
                logger.info("Multi-char name, searching first free letter from Z.")
                assigned = first_free_from_z(reserved)
                if assigned is None:
                    logger.error("No free drive letter for '%s'.", folder_name)
                    continue
                logger.info("Letter assigned: %s", assigned)

        # Reserve immediately to avoid double-booking in this session.
        reserved.add(assigned)
        if run_subst(assigned, folder_path, logger):
            ini_set(cfg, assigned, folder_path)
            ini_dirty = True
        launch_winpenpack(folder_path, logger)

    if ini_dirty:
        try:
            ini_save(cfg, ini_path)
            logger.info("INI state saved to '%s'.", ini_path)
        except Exception as exc:
            logger.error("Failed to save INI '%s': %s", ini_path, exc)

    # Final summary.
    summary = [
        f"{l}: -> '{get_subst_target(l)}'"
        for l in sorted(reserved)
        if get_subst_target(l)
    ]
    logger.info("Done. Mapped %d drive(s): %s", len(summary),
                ", ".join(summary) if summary else "(none)")


# ---------------------------------------------------------------------------
# Unmap mode
# ---------------------------------------------------------------------------

def unmap_folders(exe_dir: str, logger: logging.Logger) -> None:
    ini_path  = get_ini_path(exe_dir)
    cfg       = ini_load(ini_path)
    ini_dirty = False

    exe_dir_norm = os.path.normcase(os.path.normpath(exe_dir))
    removed = []

    for letter in string.ascii_uppercase:
        target = get_subst_target(letter)
        if target is None:
            continue
        target_parent = os.path.normcase(os.path.normpath(os.path.dirname(target)))
        if target_parent == exe_dir_norm:
            logger.info("Found own mapping: %s: -> '%s', removing.", letter, target)
            if remove_subst(letter, logger):
                removed.append(f"{letter}: (was '{target}')")
                ini_remove(cfg, letter)
                ini_dirty = True

    if ini_dirty:
        try:
            ini_save(cfg, ini_path)
            logger.info("INI updated.")
        except Exception as exc:
            logger.error("Failed to save INI '%s': %s", ini_path, exc)

    logger.info("Done. Unmapped %d drive(s): %s", len(removed),
                ", ".join(removed) if removed else "(none)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if os.name != "nt":
        sys.exit(1)
    verbose, unmap = parse_args()
    exe_dir = get_exe_dir()
    logger  = build_logger(exe_dir, verbose)
    if verbose:
        logger.info("=== %s started (verbose, mode=%s) ===",
                    get_program_name(), "unmap" if unmap else "map")
        logger.info("Base directory: '%s'", exe_dir)
    if unmap:
        unmap_folders(exe_dir, logger)
    else:
        process_folders(exe_dir, logger)
    if verbose:
        logger.info("=== %s finished ===", get_program_name())


if __name__ == "__main__":
    main()
