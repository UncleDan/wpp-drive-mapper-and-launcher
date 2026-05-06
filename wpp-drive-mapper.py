"""
wpp-drive-mapper.py

Maps subfolders located in the same directory as the executable to virtual
drive letters via Windows `subst`, following winPenPack conventions.

Behaviour
---------
- Single-letter folder (e.g. "W"):  attempt to use that letter; if already
  taken, fall back to the first free letter scanning backwards from Z.
- Multi-letter folder (e.g. "Tools"): assign the first free letter from Z.
- For every folder: if winPenPack.exe exists inside it, launch it and wait
  for it to exit before moving to the next folder.

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

def is_verbose() -> bool:
    """
    Return True if /v or /verbose (case-insensitive) is present in sys.argv.
    Works both when run as a plain script and as a frozen PyInstaller exe.
    """
    flags = {"/v", "/verbose"}
    return any(arg.lower() in flags for arg in sys.argv[1:])


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

    verbose=False  →  ERROR level, lazy file creation (no file if no errors).
    verbose=True   →  INFO level, file always created immediately.

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
        # In verbose mode open the file immediately so the header line is
        # written even when no errors occur.
        handler = logging.FileHandler(log_path, encoding="utf-8")
    else:
        handler = _LazyFileHandler(log_path)

    handler.setLevel(level)
    handler.setFormatter(fmt)

    logger = logging.getLogger("wpp-drive-mapper")
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


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def run_subst(letter: str, folder: str, logger: logging.Logger) -> bool:
    """
    Execute ``subst LETTER: FOLDER``.
    Returns True on success; logs an error and returns False otherwise.
    """
    cmd = f'subst {letter}: "{folder}"'
    logger.info("Running: %s", cmd)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode == 0:
            logger.info("OK  %s: -> '%s'", letter, folder)
            return True
        logger.error(
            "subst failed for '%s' -> %s: (rc=%d) %s",
            folder, letter, result.returncode, result.stderr.strip(),
        )
        return False
    except Exception as exc:
        logger.error("Exception running subst for '%s': %s", folder, exc)
        return False


def launch_winpenpack(folder: str, logger: logging.Logger) -> None:
    """
    Look for winPenPackNet.exe first, then winPenPack.exe.
    If found, launch it and block until it exits.
    """
    for candidate in ("winPenPackNet.exe", "winPenPack.exe"):
        exe_path = os.path.join(folder, candidate)
        if os.path.isfile(exe_path):
            logger.info("Launching %s in '%s'.", candidate, folder)
            try:
                proc = subprocess.Popen([exe_path], cwd=folder)
                proc.wait()
                logger.info("%s exited (rc=%d).", candidate, proc.returncode)
            except Exception as exc:
                logger.error("Failed to launch %s in '%s': %s", candidate, folder, exc)
            return  # launch at most one executable per folder

    logger.info("No winPenPack launcher found in '%s', skipping.", folder)


def is_single_letter(name: str) -> bool:
    """True if *name* is exactly one ASCII letter (A-Z, case-insensitive)."""
    return len(name) == 1 and name.upper() in string.ascii_uppercase


# ---------------------------------------------------------------------------
# Main processing logic
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

    logger.info("Found %d subfolder(s): %s", len(folders), ", ".join(folders) or "(none)")

    # Letters booked during this session (avoids double-assignment)
    reserved = set()

    for folder_name in folders:
        folder_path = os.path.join(exe_dir, folder_name)
        logger.info("--- Processing folder: '%s' ---", folder_name)

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
                        "No free drive letter available for folder '%s'.", folder_name
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
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if os.name != "nt":
        sys.exit(1)

    verbose = is_verbose()
    exe_dir = get_exe_dir()
    logger = build_logger(exe_dir, verbose)

    if verbose:
        logger.info(
            "=== %s started (verbose mode) ===", get_program_name()
        )
        logger.info("Base directory: '%s'", exe_dir)

    process_folders(exe_dir, logger)

    if verbose:
        logger.info("=== %s finished ===", get_program_name())


if __name__ == "__main__":
    main()