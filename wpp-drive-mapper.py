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
Runs `cmd /c subst` in a hidden window so mappings are:
  - volatile (session-scoped, removed automatically on logoff)
  - not persistent across reboots
  - immediately visible in Explorer / "This PC"
identical to typing `subst` at a command prompt.

Before assigning a letter the program checks that it is truly free:
GetLogicalDrives covers physical disks, USB drives, network shares, Google
Drive, pCloud and any other mounted volume.  QueryDosDeviceW is used to
detect existing subst mappings to the same target (skip + launch only).

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
# Hidden-window subprocess helper
# ---------------------------------------------------------------------------

def _run_hidden(cmd: str) -> tuple:
    """
    Run *cmd* via cmd.exe with a fully hidden window.
    Returns (returncode, stderr_text).

    STARTF_USESHOWWINDOW + SW_HIDE ensures no console flashes even when
    the parent process has no console (--windowed PyInstaller build).
    CREATE_NO_WINDOW is set as a creation flag for belt-and-suspenders.
    """
    si = subprocess.STARTUPINFO()
    si.dwFlags    |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE

    CREATE_NO_WINDOW = 0x08000000

    result = subprocess.run(
        ["cmd.exe", "/c", cmd],
        startupinfo=si,
        creationflags=CREATE_NO_WINDOW,
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
    """
    Return the set of drive letters currently in use (physical + subst +
    network shares + Google Drive + pCloud + any other mounted volume).
    Uses the Win32 GetLogicalDrives bitmask which covers all of the above.
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


def get_subst_target(letter: str):
    """
    Return the target path if *letter*: is a subst/virtual mapping, else None.
    Uses QueryDosDeviceW; virtual drives have NT names starting with \\??\\.
    Physical disks, network shares, Google Drive, pCloud etc. do not.
    """
    device = f"{letter.upper()}:"
    buf = ctypes.create_unicode_buffer(4096)
    ret = ctypes.windll.kernel32.QueryDosDeviceW(device, buf, len(buf))
    if ret == 0:
        return None
    nt_name = buf.value          # e.g.  \??\D:\Portable\W
    prefix  = "\\??\\"
    if nt_name.startswith(prefix):
        return nt_name[len(prefix):]   # plain Win32 path
    return None   # physical drive or non-subst device


# ---------------------------------------------------------------------------
# Core map / unmap operations
# ---------------------------------------------------------------------------

def run_subst(letter: str, folder: str, logger: logging.Logger) -> bool:
    """
    Map *letter*: to *folder* by running ``cmd /c subst LETTER: FOLDER``
    in a hidden window.  This is identical to typing subst at a prompt:
    volatile, session-scoped, immediately visible in Explorer, not
    persisted to the registry or across reboots.
    """
    cmd = f'subst {letter.upper()}: "{folder}"'
    logger.info("Mapping %s: -> '%s'", letter.upper(), folder)
    rc, err = _run_hidden(cmd)
    if rc == 0:
        logger.info("OK  %s: -> '%s'", letter.upper(), folder)
        return True
    logger.error(
        "subst failed for '%s' -> %s: (rc=%d) %s", folder, letter, rc, err
    )
    return False


def remove_subst(letter: str, logger: logging.Logger) -> bool:
    """
    Remove the virtual drive *letter*: by running ``cmd /c subst LETTER: /D``
    in a hidden window.
    """
    cmd = f'subst {letter.upper()}: /D'
    logger.info("Unmapping %s:", letter.upper())
    rc, err = _run_hidden(cmd)
    if rc == 0:
        logger.info("OK  %s: removed.", letter.upper())
        return True
    logger.error(
        "subst /D failed for %s: (rc=%d) %s", letter, rc, err
    )
    return False


# ---------------------------------------------------------------------------
# winPenPack launcher
# ---------------------------------------------------------------------------

# DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP: child gets its own session,
# inherits no handles, never blocks the parent.
_DETACHED_PROCESS         = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def launch_winpenpack(folder: str, logger: logging.Logger) -> None:
    """
    Look for winPenPackNet.exe first, then winPenPack.exe.
    Launch it fully detached so execution continues immediately.
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

    # Letters booked during this session (avoids double-assignment).
    # Seeded with all currently occupied letters so we never collide with
    # physical disks, USB drives, network shares, Google Drive, pCloud, etc.
    reserved: set = used_drive_letters()

    for folder_name in folders:
        folder_path = os.path.join(exe_dir, folder_name)
        logger.info("--- Processing folder: '%s' ---", folder_name)

        # Check whether a subst mapping to this exact folder already exists.
        existing_letter = None
        for letter in string.ascii_uppercase:
            target = get_subst_target(letter)
            if target and os.path.normcase(os.path.normpath(target)) == \
                          os.path.normcase(os.path.normpath(folder_path)):
                existing_letter = letter
                break

        if existing_letter is not None:
            logger.info(
                "Mapping %s: -> '%s' already exists, skipping subst.",
                existing_letter, folder_path,
            )
            reserved.add(existing_letter)
            launch_winpenpack(folder_path, logger)
            continue

        if is_single_letter(folder_name):
            desired = folder_name.upper()
            if desired not in reserved:
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

        # Reserve before calling subst so the next iteration never double-books.
        reserved.add(assigned)
        run_subst(assigned, folder_path, logger)
        launch_winpenpack(folder_path, logger)

    # Final summary: re-read actual mappings from the OS.
    summary_parts = []
    for l in sorted(reserved - used_drive_letters() | reserved):
        target = get_subst_target(l)
        if target:
            summary_parts.append(f"{l}: -> '{target}'")
    logger.info(
        "Done. Mapped %d drive(s): %s",
        len(summary_parts),
        ", ".join(summary_parts) if summary_parts else "(none)",
    )


# ---------------------------------------------------------------------------
# Unmap mode
# ---------------------------------------------------------------------------

def unmap_folders(exe_dir: str, logger: logging.Logger) -> None:
    """
    Scan all current drive letters and remove every subst mapping whose
    target is a direct subfolder of *exe_dir*.
    Physical drives and unrelated subst mappings are never touched.
    """
    exe_dir_norm = os.path.normcase(os.path.normpath(exe_dir))
    removed = []

    for letter in string.ascii_uppercase:
        target = get_subst_target(letter)
        if target is None:
            continue  # physical drive or not mapped at all

        target_parent = os.path.normcase(
            os.path.normpath(os.path.dirname(target))
        )
        if target_parent == exe_dir_norm:
            logger.info("Found own mapping: %s: -> '%s', removing.", letter, target)
            if remove_subst(letter, logger):
                removed.append(f"{letter}: (was '{target}')")

    logger.info(
        "Done. Unmapped %d drive(s): %s",
        len(removed),
        ", ".join(removed) if removed else "(none)",
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