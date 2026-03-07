import os
import sys
import subprocess
import string

def get_exe_dir():
    """Get the directory where the executable (or script) resides."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_used_drive_letters():
    """Return a set of currently used drive letters (uppercase)."""
    used = set()
    for letter in string.ascii_uppercase:
        if os.path.exists(f"{letter}:\\"):
            used.add(letter)
    return used

def subst_drive(letter, path):
    """Assign a drive letter to a path using subst. Returns True on success."""
    try:
        result = subprocess.run(
            ["subst", f"{letter}:", path],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False

def remove_subst(letter):
    """Remove a subst drive letter."""
    try:
        subprocess.run(["subst", f"{letter}:", "/D"], capture_output=True)
    except Exception:
        pass

def assign_drive_letter(folder_name, folder_path, used_letters):
    """
    Determine and assign the best available drive letter for a folder.
    - Single letter folder name: try that letter first, then go Z downward
    - Multi-letter folder name: go from X downward (X, W, V, ...)
    Only C: is reserved and never used. All other letters are fair game.
    Returns the assigned letter or None.
    """
    RESERVED = {'C'}
    assigned = None

    if len(folder_name) == 1:
        preferred = folder_name.upper()
        if preferred in string.ascii_uppercase and preferred not in RESERVED and preferred not in used_letters:
            if subst_drive(preferred, folder_path):
                assigned = preferred

        if assigned is None:
            # Fallback: Z downward, only skip C and already used
            for letter in reversed(string.ascii_uppercase):
                if letter in used_letters:
                    continue
                if letter in RESERVED:
                    continue
                if subst_drive(letter, folder_path):
                    assigned = letter
                    break
    else:
        # Multi-letter: start from X downward, wrap around if needed
        # Build full candidate list: X W V U ... A B D E F ... Y Z
        start_index = string.ascii_uppercase.index('X')
        descending = list(reversed(string.ascii_uppercase[:start_index + 1]))  # X, W, V, ... A
        ascending_rest = [l for l in string.ascii_uppercase[start_index + 1:]]  # Y, Z
        candidates = descending + ascending_rest

        for letter in candidates:
            if letter in used_letters:
                continue
            if letter in RESERVED:
                continue
            if subst_drive(letter, folder_path):
                assigned = letter
                break

    if assigned:
        used_letters.add(assigned)

    return assigned

def launch_winpenpack(drive_letter):
    """If winPenPack.exe exists on the drive, launch it."""
    exe_path = f"{drive_letter}:\\winPenPack.exe"
    if os.path.isfile(exe_path):
        try:
            subprocess.Popen([exe_path], cwd=f"{drive_letter}:\\")
            print(f"  -> Avviato: {exe_path}")
        except Exception as e:
            print(f"  -> Errore nell'avvio di winPenPack.exe: {e}")
    else:
        print(f"  -> winPenPack.exe non trovato su {drive_letter}:\\")

def main():
    base_dir = get_exe_dir()
    print(f"Cartella base: {base_dir}\n")

    # Get all subdirectories in the exe's folder
    try:
        entries = os.listdir(base_dir)
    except Exception as e:
        print(f"Errore nella lettura della cartella: {e}")
        input("Premi INVIO per uscire...")
        sys.exit(1)

    folders = [
        e for e in entries
        if os.path.isdir(os.path.join(base_dir, e))
    ]

    if not folders:
        print("Nessuna cartella trovata.")
        input("Premi INVIO per uscire...")
        sys.exit(0)

    used_letters = get_used_drive_letters()
    print(f"Lettere di unità già in uso: {', '.join(sorted(used_letters))}\n")

    for folder_name in sorted(folders):
        folder_path = os.path.join(base_dir, folder_name)
        print(f"Elaborazione cartella: '{folder_name}'")

        letter = assign_drive_letter(folder_name, folder_path, used_letters)

        if letter:
            print(f"  -> Assegnata unità {letter}: -> {folder_path}")
            launch_winpenpack(letter)
        else:
            print(f"  -> Impossibile assegnare una lettera di unità (nessuna lettera disponibile)")

        print()

    input("Operazioni completate. Premi INVIO per uscire...")

if __name__ == "__main__":
    main()
