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

Drive mapping
-------------
Uses DefineDosDeviceW (Win32 API) directly instead of spawning a child
``subst`` process.  This guarantees the mappings are session-scoped and
automatically removed on logoff, identical to running ``subst`` at a prompt.

Unmap mode
----------
Pass /unmap (or /u) to remove all virtual drives whose target path points
to a subfolder of the executable's directory.  Only mappings created by
this program are affected; physical drives and unrelated subst mappings
are left untouched.

Logging
-------
Default mode  : a log file is created ONLY if at least one error occurs.
Verbose mode  : pass /v or /verbose on the command line; every operation is
                logged (INFO level) and the file is always created.

Log file name : YYYY-MM-DD_HH-MM-SS_<program-name>.log
                placed in the same directory as the executable.

Every log line begins with the local date/time of that specific event.
No output is ever produced to stdout/stderr.
"""

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
    """Return the directory that contains the executable (or this script)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_program_name() -> str:
    """Return the program name without extension, used in the log filename."""
    if getattr(sys, "frozen", False):
        base = os.path.basename(sys.executable)
    else:
        base = os.path.basename(__file__)
    return os.path.splitext(base)[0]


# ---------------------------------------------------------------------------
# Command-line parsing
# ---------------------------------------------------------------------------

def parse_args() -> tuple:
    """
    Parse sys.argv and return (verbose: bool, unmap: bool).
    Flags are case-insensitive and may use / or - as prefix.
    """
    args = {a.lstrip("/-").lower() for a in sys.argv[1:]}
    verbose = bool(args & {"v", "verbose"})
    unmap   = bool(args & {"u", "unmap"})
    return verbose, unmap


# ---------------------------------------------------------------------------
# Logger construction
# ---------------------------------------------------------------------------

class _LazyFileHandler(logging.Handler):
    """
    A file handler that creates the log file on disk only when the first
    record is actually emitted.  In error-only mode this means no empty log
    files are left behind on successful runs.
    """

    def __init__(self, path: str, encoding: str = "utf-8") -> None:
        super().__init__()
        self._path = path
        self._encoding = encoding
        self._fh = None

    def _ensure_open(self) -> None:
        if self._fh is None:
            self._fh = logging.FileHandler(self._path, encoding=self._encoding)
            self._fh.setFormatter(self.formatter)

    def emit(self, record: logging.LogRecord) -> None:
        self._ensure_open()
        self._fh.emit(record)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
        super().close()


def build_logger(exe_dir: str, verbose: bool) -> logging.Logger:
    """
    Build and return the application logger.

    verbose=False  ->  ERROR level, lazy file creation (no file if no errors).
    verbose=True   ->  INFO level, file always created immediately.

    Every log record includes the local timestamp of that specific event via
    the %(asctime)s field (formatted as YYYY-MM-DD HH:MM:SS).
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = os.path.join(exe_dir, f"{ts}_{get_program_name()}.log")

    level = logging.INFO if verbose else logging.ERROR

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if verbose:
        handler = logging.FileHandler(log_path, encoding="utf-8")
    else:
        handler = _LazyFileHandler(log_path)

    handler.setLevel(level)
    handler.setFormatter(fmt)

    logger = logging.getLogger("wpp_drive_mapper")
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger


# ---------------------------------------------------------------------------
# Windows drive-letter helpers
# ---------------------------------------------------------------------------

def used_drive_letters() -> set:
    """
    Return the set of drive letters currently in use (physical + subst).
    Uses the Win32 GetLogicalDrives bitmask so virtual drives are included.
    """
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    return {
        letter
        for i, letter in enumerate(string.ascii_uppercase)
        if bitmask & (1 << i)
    }


def letter_is_free(letter: str, reserved: set) -> bool:
    """True if *letter* is neither in use by the OS nor pre-booked this run."""
    return letter.upper() not in (used_drive_letters() | reserved)


def first_free_from_z(reserved: set):
    """Return the first free drive letter scanning Z -> A, or None if exhausted."""
    taken = used_drive_letters() | reserved
    for letter in reversed(string.ascii_uppercase):
        if letter not in taken:
            return letter
    return None


def get_subst_target(letter: str) -> str | None:
    """
    Return the target path of a subst/virtual drive, or None if the drive
    is not a virtual (subst) mapping.

    Uses QueryDosDeviceW to read the NT device name.  Virtual drives created
    by subst or DefineDosDeviceW have names in the form \??\<path>.
    """
    device = f"{letter.upper()}:"
    buf = ctypes.create_unicode_buffer(4096)
    ret = ctypes.windll.kernel32.QueryDosDeviceW(device, buf, len(buf))
    if ret == 0:
        return None
    nt_name = buf.value  # e.g. \??\D:\Portable\W
    prefix = "\\??\\"
    if nt_name.startswith(prefix):
        return nt_name[len(prefix):]  # strip the NT prefix -> plain Win32 path
    return None  # physical drive or other device, not a subst mapping


# ---------------------------------------------------------------------------
# DefineDosDeviceW flags
# ---------------------------------------------------------------------------

# DDD_RAW_TARGET_PATH     = 0x00000001  create/remove without "\\??\\" mangling
# DDD_REMOVE_DEFINITION   = 0x00000002  remove instead of create
# DDD_EXACT_MATCH_ON_REMOVE = 0x00000004  match target exactly when removing
# DDD_NO_BROADCAST_SYSTEM = 0x00000008  suppress WM_SETTINGCHANGE broadcast
_DDD_RAW_TARGET_PATH        = 0x00000001
_DDD_REMOVE_DEFINITION      = 0x00000002
_DDD_EXACT_MATCH_ON_REMOVE  = 0x00000004
_DDD_NO_BROADCAST_SYSTEM    = 0x00000008


# ---------------------------------------------------------------------------
# Core map / unmap operations
# ---------------------------------------------------------------------------

def run_subst(letter: str, folder: str, logger: logging.Logger) -> bool:
    """
    Map *letter*: to *folder* by calling DefineDosDeviceW directly in the
    current process.  This is exactly what the subst command does internally,
    but because the call is made in-process (not in a child cmd.exe) the
    mapping is owned by the current logon session and is automatically
    removed on logoff — identical behaviour to typing ``subst`` at a prompt.
    """
    device  = f"{letter.upper()}:"
    nt_path = f"\\??\\{folder}"
    flags   = _DDD_RAW_TARGET_PATH | _DDD_NO_BROADCAST_SYSTEM
    logger.info("Mapping %s -> '%s'", device, folder)
    try:
        ok = ctypes.windll.kernel32.DefineDosDeviceW(flags, device, nt_path)
        if ok:
            logger.info("OK  %s -> '%s'", device, folder)
            return True
        err = ctypes.get_last_error()
        logger.error(
            "DefineDosDeviceW failed for '%s' -> %s (error %d)", folder, letter, err
        )
        return False
    except Exception as exc:
        logger.error("Exception mapping '%s': %s", folder, exc)
        return False


def remove_subst(letter: str, folder: str, logger: logging.Logger) -> bool:
    """
    Remove the virtual drive *letter*: whose target is *folder*.
    Uses DDD_EXACT_MATCH_ON_REMOVE so only the specific mapping is deleted;
    if the letter was somehow reassigned to a different path it is left alone.
    """
    device  = f"{letter.upper()}:"
    nt_path = f"\\??\\{folder}"
    flags   = (_DDD_RAW_TARGET_PATH | _DDD_REMOVE_DEFINITION
               | _DDD_EXACT_MATCH_ON_REMOVE | _DDD_NO_BROADCAST_SYSTEM)
    logger.info("Unmapping %s (was '%s')", device, folder)
    try:
        ok = ctypes.windll.kernel32.DefineDosDeviceW(flags, device, nt_path)
        if ok:
            logger.info("OK  %s removed.", device)
            return True
        err = ctypes.get_last_error()
        logger.error(
            "DefineDosDeviceW remove failed for %s (error %d)", device, err
        )
        return False
    except Exception as exc:
        logger.error("Exception unmapping %s: %s", device, exc)
        return False


# ---------------------------------------------------------------------------
# winPenPack launcher
# ---------------------------------------------------------------------------

# CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS: the child gets its own
# console session and inherits no handles from the parent, so it runs
# fully independently and never blocks the parent's execution.
_DETACHED_PROCESS       = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def launch_winpenpack(folder: str, logger: logging.Logger) -> None:
    """
    Look for winPenPackNet.exe first, then winPenPack.exe.
    Launch it fully detached from the parent process (DETACHED_PROCESS +
    CREATE_NEW_PROCESS_GROUP, stdin/stdout/stderr all redirected to DEVNULL)
    so execution continues immediately with the next folder regardless of
    what the child process does.
    """
    for candidate in ("winPenPackNet.exe", "winPenPack.exe"):
        exe_path = os.path.join(folder, candidate)
        if os.path.isfile(exe_path):
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
                logger.error(
                    "Failed to launch %s in '%s': %s", candidate, folder, exc
                )
            return  # launch at most one executable per folder

    logger.info("No winPenPack launcher found in '%s', skipping.", folder)


def is_single_letter(name: str) -> bool:
    """True if *name* is exactly one ASCII letter (A-Z, case-insensitive)."""
    return len(name) == 1 and name.upper() in string.ascii_uppercase


# ---------------------------------------------------------------------------
# Map mode
# ---------------------------------------------------------------------------

def process_folders(exe_dir: str, logger: logging.Logger) -> None:
    """Scan immediate subfolders of *exe_dir* and apply the subst mapping."""
    try:
        entries = os.listdir(exe_dir)
    except Exception as exc:
        logger.error("Cannot list directory '%s': %s", exe_dir, exc)
        return

    folders = sorted(
        entry for entry in entries
        if os.path.isdir(os.path.join(exe_dir, entry))
    )

    logger.info(
        "Found %d subfolder(s): %s", len(folders), ", ".join(folders) or "(none)"
    )

    # Letters booked during this session (avoids double-assignment)
    reserved: set = set()

    for folder_name in folders:
        folder_path = os.path.join(exe_dir, folder_name)
        logger.info("--- Processing folder: '%s' ---", folder_name)

        # Check whether a mapping to this exact folder already exists.
        existing_letter = None
        for letter in string.ascii_uppercase:
            target = get_subst_target(letter)
            if target and os.path.normcase(os.path.normpath(target)) == \
                          os.path.normcase(os.path.normpath(folder_path)):
                existing_letter = letter
                break

        if existing_letter is not None:
            # Mapping already present and correct — skip subst, just launch.
            logger.info(
                "Mapping %s: -> '%s' already exists, skipping subst.",
                existing_letter, folder_path,
            )
            reserved.add(existing_letter)
            launch_winpenpack(folder_path, logger)
            continue

        if is_single_letter(folder_name):
            desired = folder_name.upper()
            if letter_is_free(desired, reserved):
                assigned = desired
                logger.info("Preferred letter %s: is free, using it.", desired)
            else:
                logger.info("Letter %s: is taken, searching from Z.", desired)
                assigned = first_free_from_z(reserved)
                if assigned is None:
                    logger.error(
                        "No free drive letter available for folder '%s'.",
                        folder_name,
                    )
                    continue
                logger.info("Fallback letter assigned: %s", assigned)
        else:
            logger.info("Multi-character name, searching first free letter from Z.")
            assigned = first_free_from_z(reserved)
            if assigned is None:
                logger.error(
                    "No free drive letter available for folder '%s'.", folder_name
                )
                continue
            logger.info("Letter assigned: %s", assigned)

        # Reserve the letter immediately so the next iteration never picks the
        # same one, regardless of whether GetLogicalDrives has caught up yet.
        reserved.add(assigned)
        run_subst(assigned, folder_path, logger)
        launch_winpenpack(folder_path, logger)

    logger.info(
        "Done. Letters mapped this session: %s",
        ", ".join(sorted(reserved)) if reserved else "(none)",
    )


# ---------------------------------------------------------------------------
# Unmap mode
# ---------------------------------------------------------------------------

def unmap_folders(exe_dir: str, logger: logging.Logger) -> None:
    """
    Scan all current drive letters and remove every virtual (subst) mapping
    whose target path is a direct subfolder of *exe_dir*.
    Physical drives and unrelated subst mappings are never touched.
    """
    exe_dir_norm = os.path.normcase(os.path.normpath(exe_dir))
    removed = []

    for letter in string.ascii_uppercase:
        target = get_subst_target(letter)
        if target is None:
            continue  # not a virtual drive

        target_norm   = os.path.normcase(os.path.normpath(target))
        target_parent = os.path.normcase(os.path.normpath(os.path.dirname(target)))

        # Only remove if the target's *parent* is exe_dir (i.e. it is a direct
        # subfolder of our base directory, not some unrelated mapping).
        if target_parent == exe_dir_norm:
            logger.info(
                "Found own mapping: %s: -> '%s', removing.", letter, target
            )
            if remove_subst(letter, target, logger):
                removed.append(f"{letter}:")

    logger.info(
        "Done. Letters unmapped: %s", ", ".join(removed) if removed else "(none)"
    )


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
        mode = "unmap" if unmap else "map"
        logger.info(
            "=== %s started (verbose, mode=%s) ===", get_program_name(), mode
        )
        logger.info("Base directory: '%s'", exe_dir)

    if unmap:
        unmap_folders(exe_dir, logger)
    else:
        process_folders(exe_dir, logger)

    if verbose:
        logger.info("=== %s finished ===", get_program_name())


if __name__ == "__main__":
    main()