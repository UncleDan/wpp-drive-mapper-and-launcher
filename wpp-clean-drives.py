"""
wpp-clean-drives.py

Standalone utility to remove persistent (erroneously surviving) subst drive
mappings left over after logoff or reboot.

How it works
------------
QueryDosDeviceW is used to inspect every drive letter A-Z.  A drive is
considered a stale subst mapping if:
  - QueryDosDeviceW returns an NT path starting with \\?\\ (i.e. it IS a
    subst mapping, not a physical disk, USB, network share, etc.)
  - AND the target path does NOT actually exist on disk any more.

Those drives are removed via `cmd /c subst LETTER: /D` in a hidden window.

Optionally pass /all (or /a) to remove ALL subst mappings regardless of
whether the target still exists — useful for a full manual cleanup.

Logging
-------
Same convention as wpp-drive-mapper: error-only by default, full verbose
with /v or /verbose.  Log file: YYYY-MM-DD_HH-MM-SS_wpp-clean-drives.log
placed next to the executable.
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

def parse_args() -> tuple:
    """Return (verbose: bool, remove_all: bool)."""
    args = {a.lstrip("/-").lower() for a in sys.argv[1:]}
    verbose    = bool(args & {"v", "verbose"})
    remove_all = bool(args & {"a", "all"})
    return verbose, remove_all


# ---------------------------------------------------------------------------
# Logger (identical pattern to wpp-drive-mapper)
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
    logger = logging.getLogger("wpp-clean-drives")
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger


# ---------------------------------------------------------------------------
# Drive inspection
# ---------------------------------------------------------------------------

def get_subst_target(letter: str) -> str | None:
    """Return Win32 path if *letter*: is a subst mapping, else None."""
    buf = ctypes.create_unicode_buffer(4096)
    ret = ctypes.windll.kernel32.QueryDosDeviceW(f"{letter.upper()}:", buf, len(buf))
    if not ret:
        return None
    nt = buf.value
    return nt[4:] if nt.startswith("\\??\\") else None


def iter_subst_drives() -> list:
    """
    Return list of (letter, target_path) for every active subst mapping.
    Physical drives, USB, network, Google Drive, pCloud etc. are excluded
    because their NT device names do not start with \\?\\.
    """
    result = []
    for letter in string.ascii_uppercase:
        target = get_subst_target(letter)
        if target is not None:
            result.append((letter, target))
    return result


# ---------------------------------------------------------------------------
# Hidden-window subst /D
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
    rc, err = _run_hidden(f"subst {letter.upper()}: /D")
    if rc == 0:
        logger.info("OK  %s: removed.", letter.upper())
        return True
    logger.error("subst /D failed for %s: (rc=%d) %s", letter, rc, err)
    return False


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def clean_drives(logger: logging.Logger, remove_all: bool) -> None:
    drives = iter_subst_drives()

    if not drives:
        logger.info("No subst mappings found.")
        return

    logger.info(
        "Found %d subst mapping(s): %s",
        len(drives),
        ", ".join(f"{l}: -> '{t}'" for l, t in drives),
    )

    removed  = []
    skipped  = []

    for letter, target in drives:
        target_exists = os.path.exists(target)

        if remove_all:
            reason = "forced (/all)"
        elif not target_exists:
            reason = f"target does not exist: '{target}'"
        else:
            skipped.append(f"{letter}: -> '{target}' (target OK)")
            logger.info("Skipping %s: target exists and /all not set.", letter)
            continue

        logger.info("Removing %s: -> '%s'  [%s]", letter, target, reason)
        if remove_subst(letter, logger):
            removed.append(f"{letter}: (was '{target}')")

    logger.info(
        "Done. Removed %d, skipped %d.",
        len(removed), len(skipped),
    )
    if removed:
        logger.info("Removed : %s", ", ".join(removed))
    if skipped:
        logger.info("Skipped : %s", ", ".join(skipped))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if os.name != "nt":
        sys.exit(1)
    verbose, remove_all = parse_args()
    exe_dir = get_exe_dir()
    logger  = build_logger(exe_dir, verbose)
    if verbose:
        mode = "all subst drives" if remove_all else "stale subst drives"
        logger.info("=== %s started — removing %s ===", get_program_name(), mode)
    clean_drives(logger, remove_all)
    if verbose:
        logger.info("=== %s finished ===", get_program_name())


if __name__ == "__main__":
    main()
