#!/usr/bin/env python3
"""
mcpe_backup.py - back up a Minecraft Bedrock (MCPE) world to a .mcworld file.

Runs in Termux on Android. Standard library only, nothing extra to install.
Each time you run it, it makes ONE backup and exits.

======================================================================
STEP-BY-STEP SETUP (do this once)
======================================================================
1. Install Termux on your phone (from F-Droid or GitHub; the Play Store
   version is outdated).

2. Open Termux and install Python:
       pkg update
       pkg install python

3. Give Termux access to your phone's storage:
       termux-setup-storage
   Tap "Allow" on the permission popup. Then check it worked:
       ls ~/storage/shared
   You should see folders like Download, DCIM, and games. If you don't,
   redo this step.

4. Get this file into Termux's home folder. If you downloaded it to your
   phone's Downloads folder, run:
       cp ~/storage/shared/Download/mcpe_backup.py ~/
   Check it's there with:
       ls ~/mcpe_backup.py

5. See which worlds the script can find:
       python mcpe_backup.py --list
   It prints each world's name with its folder name in brackets. Use the
   name (not the folder) in the next step. If the list is empty, see
   TROUBLESHOOTING at the bottom.

======================================================================
MAKING A BACKUP
======================================================================
6. Run the backup, putting your world's name in quotes:
       python mcpe_backup.py "My World"
   When it finishes it prints where the file was saved and how big it is.
   Partial names work if they match only one world, e.g. "My Wor".

7. Find the backup. By default it is saved in your Downloads folder:
       /storage/emulated/0/Download/
   as a file like My_World_2026-10-02_14-30-00.mcworld. Open your file
   manager and look in Downloads.

Options you can add to the command:
       --keep 5          keep only the newest 5 backups of that world
       --out FOLDER      save somewhere else, e.g.
                         --out ~/storage/shared/Documents
       --worlds-dir DIR  point at a different minecraftWorlds folder

Example with options:
       python mcpe_backup.py "My World" --keep 5

======================================================================
OPTIONAL: MAKE A SHORTCUT CALLED "worldsave"
======================================================================
8. Run this once in Termux (change My World to your world's name):
       cat > $PREFIX/bin/worldsave << 'EOF'
       #!/data/data/com.termux/files/usr/bin/sh
       exec python ~/mcpe_backup.py "My World" --keep 5 "$@"
       EOF
       chmod +x $PREFIX/bin/worldsave
   (Type the lines without the leading spaces shown here.)

9. From now on, just type this in Termux to make a backup:
       worldsave

======================================================================
RESTORING A BACKUP
======================================================================
10. In your file manager, tap the .mcworld file and choose to open it
    with Minecraft. It imports as a new world and your original is not
    touched. If tapping doesn't work, open Minecraft and use the import
    option, or rename the file to end in .zip, unzip it, and copy the
    contents into a new folder inside minecraftWorlds.

======================================================================
TROUBLESHOOTING
======================================================================
- "Couldn't find minecraftWorlds": run termux-setup-storage again, or
  pass the location yourself with --worlds-dir.
- --list shows nothing: newer Minecraft versions may keep worlds in
  Android/data/com.mojang.minecraftpe/..., which Termux usually can't
  read on Android 11 and later. Check whether your worlds are in
  games/com.mojang/minecraftWorlds on shared storage instead.
- "No world matching": run --list and copy the name exactly.
- "skipped <file>" messages: a file was locked while Minecraft was
  running. For the most consistent backup, back up when the game is
  closed or you're idle.
- Backup missing from Downloads: make sure step 3 worked. Without it,
  the files end up in a Termux-private folder your file manager can't see.

A .mcworld file is just a zip with the world files at the top level, so the
backups can be restored by opening them with Minecraft (or copying them back).
"""

import argparse
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# Default locations (after running `termux-setup-storage` once).
# Minecraft versions that keep data in Android/data use the second path;
# note that Termux usually can't read that folder on Android 11+.
WORLD_DIRS = [
    Path.home() / "storage/shared/games/com.mojang/minecraftWorlds",
    Path("/storage/emulated/0/games/com.mojang/minecraftWorlds"),
    Path("/storage/emulated/0/Android/data/com.mojang.minecraftpe/files/games/com.mojang/minecraftWorlds"),
]
DEFAULT_BACKUP_DIR = Path.home() / "storage/shared/Download"


def find_worlds_dir(custom=None):
    candidates = [Path(custom)] if custom else WORLD_DIRS
    for d in candidates:
        try:
            if d.is_dir():
                return d
        except PermissionError:
            continue
    return None


def world_name(folder):
    """Bedrock stores the display name in levelname.txt."""
    try:
        return (folder / "levelname.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return folder.name


def list_worlds(worlds_dir):
    worlds = []
    for f in sorted(worlds_dir.iterdir()):
        if f.is_dir() and (f / "level.dat").exists():
            worlds.append((world_name(f), f))
    return worlds


def find_world(worlds_dir, query):
    worlds = list_worlds(worlds_dir)
    # exact folder or name match first, then case-insensitive partial match
    for name, folder in worlds:
        if query in (name, folder.name):
            return name, folder
    matches = [(n, f) for n, f in worlds if query.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"'{query}' matches more than one world:")
        for n, f in matches:
            print(f"  {n}  ({f.name})")
    return None


def safe(name):
    return re.sub(r'[^\w\- ]+', "_", name).strip().replace(" ", "_") or "world"


def backup_world(name, folder, backup_dir):
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out = backup_dir / f"{safe(name)}_{stamp}.mcworld"
    tmp = out.with_suffix(".tmp")

    count = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(folder):
            for fname in files:
                full = Path(root) / fname
                try:
                    z.write(full, full.relative_to(folder))
                    count += 1
                except OSError as e:
                    # a file can vanish/lock while the game is running
                    print(f"  skipped {full.name}: {e}")
    tmp.rename(out)
    size = out.stat().st_size / (1024 * 1024)
    print(f"Backed up '{name}' -> {out}  ({count} files, {size:.1f} MB)")
    return out


def prune(backup_dir, name, keep):
    if keep <= 0:
        return
    old = sorted(backup_dir.glob(f"{safe(name)}_*.mcworld"))
    for f in old[:-keep]:
        f.unlink()
        print(f"Deleted old backup: {f.name}")


def main():
    p = argparse.ArgumentParser(description="Back up a Minecraft Bedrock world.")
    p.add_argument("world", nargs="?", help="world name or folder name")
    p.add_argument("--list", action="store_true", help="list available worlds")
    p.add_argument("--worlds-dir", help="path to minecraftWorlds (overrides defaults)")
    p.add_argument("--out", default=str(DEFAULT_BACKUP_DIR), help="backup folder")
    p.add_argument("--keep", type=int, default=0,
                   help="keep only the newest N backups of this world (0 = keep all)")
    args = p.parse_args()

    worlds_dir = find_worlds_dir(args.worlds_dir)
    if not worlds_dir:
        sys.exit("Couldn't find minecraftWorlds. Run `termux-setup-storage` first, "
                 "or pass --worlds-dir.")

    if args.list or not args.world:
        print(f"Worlds in {worlds_dir}:")
        for n, f in list_worlds(worlds_dir):
            print(f"  {n}  ({f.name})")
        return

    found = find_world(worlds_dir, args.world)
    if not found:
        sys.exit(f"No world matching '{args.world}'. Use --list to see them.")
    name, folder = found
    backup_dir = Path(args.out)

    backup_world(name, folder, backup_dir)
    prune(backup_dir, name, args.keep)


if __name__ == "__main__":
    main()
