"""
wpp-clean-drives.py

Standalone utility to remove ALL subst drive mappings from the current
Windows session.

How it works
------------
QueryDosDeviceW inspects every drive letter A-Z.  A letter is identified as
a subst mapping (not a physical disk, USB, network share, Google Drive,
pCloud, etc.) when its NT device name starts with \\??\\ — that prefix is
exclusively used by subst / DefineDosDeviceW virtual mappings.

Every such mapping is removed via `cmd /c subst LETTER: /D` in a hidden
window.

Flags
-----
  /v  /verbose   Log every operation; log file always created.
                 (Default: log file created only on error.)

No other flags are needed: the utility's sole purpose is to wipe all subst
mappings in one shot.

Logging
-------
Log file: YYYY-MM-DD_HH-MM-SS_wpp-clean-drives.log  (same directory as exe).
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
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_program_name() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.basename(sys.executable)
    else:
        base = os.path.basename(__file__)
    return os.path.splitext(base)[0]


# ---------------------------------------------------------------------------
# Command-line parsing
# ---------------------------------------------------------------------------

def parse_args() -> bool:
    """Return verbose flag."""
    args = {a.lstrip("/-").lower() for a in sys.argv[1:]}
    return bool(args & {"v", "verbose"})


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class _LazyFileHandler(logging.Handler):
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
    ts   = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
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
    logger = logging.getLogger("wpp_clean_drives")
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger


# ---------------------------------------------------------------------------
# Drive inspection
# ---------------------------------------------------------------------------

def get_subst_target(letter: str) -> str | None:
    """
    Return the Win32 target path if *letter*: is a subst mapping, else None.
    Only NT device names starting with \\?\\  are subst mappings; physical
    disks, network shares, and cloud drives all have different NT prefixes.
    """
    buf = ctypes.create_unicode_buffer(4096)
    ret = ctypes.windll.kernel32.QueryDosDeviceW(f"{letter.upper()}:", buf, len(buf))
    if not ret:
        return None
    nt = buf.value
    return nt[4:] if nt.startswith("\\??\\") else None


def find_all_subst() -> list:
    """Return [(letter, target_path), ...] for every active subst mapping."""
    result = []
    for letter in string.ascii_uppercase:
        target = get_subst_target(letter)
        if target is not None:
            result.append((letter, target))
    return result


# ---------------------------------------------------------------------------
# Hidden-window removal
# ---------------------------------------------------------------------------

def _run_hidden(cmd: str) -> tuple:
    si = subprocess.STARTUPINFO()
    si.dwFlags    |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
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


def remove_subst(letter: str, logger: logging.Logger) -> bool:
    cmd = 'subst ' + letter.upper() + ': /D'
    rc, err = _run_hidden(cmd)
    if rc == 0:
        logger.info("OK  %s: removed.", letter.upper())
        return True
    logger.error("subst /D failed for %s: (rc=%d) %s", letter, rc, err)
    return False


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def clean_all_subst(logger: logging.Logger) -> None:
    mappings = find_all_subst()

    if not mappings:
        logger.info("No subst mappings found.")
        return

    logger.info(
        "Found %d subst mapping(s): %s",
        len(mappings),
        ", ".join(f"{l}: -> '{t}'" for l, t in mappings),
    )

    removed = []
    failed  = []

    for letter, target in mappings:
        logger.info("Removing %s: -> '%s'", letter, target)
        if remove_subst(letter, logger):
            removed.append(f"{letter}: (was '{target}')")
        else:
            failed.append(f"{letter}:")

    logger.info(
        "Done. Removed: %s  |  Failed: %s",
        ", ".join(removed) if removed else "(none)",
        ", ".join(failed)  if failed  else "(none)",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if os.name != "nt":
        sys.exit(1)
    verbose = parse_args()
    exe_dir = get_exe_dir()
    logger  = build_logger(exe_dir, verbose)
    if verbose:
        logger.info("=== %s started ===", get_program_name())
    clean_all_subst(logger)
    if verbose:
        logger.info("=== %s finished ===", get_program_name())


if __name__ == "__main__":
    main()
