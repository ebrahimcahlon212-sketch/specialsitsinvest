#!/usr/bin/env python3
"""Install the newest special-sits-kit zip without moving files around.

It looks for kit zips in your Windows Downloads and Desktop folders (including
OneDrive ones) and your Linux home folder, reads the version inside each, and
installs the newest one if it is newer than what you have. Only the program
files are replaced. Your settings, deals, finder history, ledger and library
are never touched, and the program files it replaces are backed up first.

Usage
  upgrade.py               install the newest zip found, if it is newer
  upgrade.py --force       install the newest zip even if it isn't newer
  upgrade.py --rollback    put back the version from before the last upgrade
  upgrade.py --kit PATH    the kit folder, when running this file from elsewhere
"""
import glob
import os
import shutil
import stat
import sys
import zipfile

PROGRAM = ["run.sh", "AGENTS.md", "CLAUDE.md", "README.md", "VERSION", "LICENSE", ".gitignore", "settings.example.env",
           "lib/", "prompts/", "templates/", "docs/", "case-studies/", "refclass/", "tests/"]
PATTERNS = ["~/special-sits-kit*.zip", "~/Downloads/special-sits-kit*.zip",
            "/mnt/c/Users/*/Downloads/special-sits-kit*.zip", "/mnt/c/Users/*/Desktop/special-sits-kit*.zip",
            "/mnt/c/Users/*/OneDrive*/Downloads/special-sits-kit*.zip", "/mnt/c/Users/*/OneDrive*/Desktop/special-sits-kit*.zip"]


def vkey(v):
    parts = []
    for p in (v or "0").strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def zip_version(path):
    try:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith("special-sits-kit/VERSION")), None)
            return z.read(name).decode("utf-8", "replace").strip() if name else "0"
    except (zipfile.BadZipFile, OSError, KeyError):
        return None


def installed_version(kit):
    p = os.path.join(kit, "VERSION")
    return open(p).read().strip() if os.path.exists(p) else "0"


def find_zips():
    found = []
    for pat in PATTERNS:
        for path in glob.glob(os.path.expanduser(pat)):
            v = zip_version(path)
            if v is not None:
                found.append((vkey(v), os.path.getmtime(path), v, path))
    found.sort(reverse=True)
    return found


def backup(kit, version):
    dest = os.path.join(kit, ".backups", version)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    for item in PROGRAM:
        src = os.path.join(kit, item.rstrip("/"))
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, item.rstrip("/")), ignore=shutil.ignore_patterns("__pycache__"))
        elif os.path.exists(src):
            shutil.copy2(src, os.path.join(dest, item))
    return dest


def make_runnable(kit):
    for p in [os.path.join(kit, "run.sh")] + glob.glob(os.path.join(kit, "lib", "*.py")):
        if os.path.exists(p):
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install(kit, path):
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if "special-sits-kit/" not in name or name.endswith("/"):
                continue
            rel = name.split("special-sits-kit/", 1)[1]
            if not any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in PROGRAM) or "__pycache__" in rel:
                continue
            dest = os.path.join(kit, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".new"
            with open(tmp, "wb") as fh:
                fh.write(z.read(name))
            os.replace(tmp, dest)
    make_runnable(kit)


def rollback(kit):
    root = os.path.join(kit, ".backups")
    versions = sorted(os.listdir(root), key=vkey) if os.path.isdir(root) else []
    if not versions:
        sys.exit("There is no earlier version to go back to.")
    prev = versions[-1]
    src = os.path.join(root, prev)
    for item in PROGRAM:
        s = os.path.join(src, item.rstrip("/"))
        d = os.path.join(kit, item.rstrip("/"))
        if os.path.isdir(s):
            if os.path.isdir(d):
                shutil.rmtree(d)
            shutil.copytree(s, d)
        elif os.path.exists(s):
            shutil.copy2(s, d)
    make_runnable(kit)
    shutil.rmtree(src)
    print("Went back to version %s." % prev)


def main():
    args = sys.argv[1:]
    kit = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--kit" in args:
        kit = os.path.abspath(os.path.expanduser(args[args.index("--kit") + 1]))
    if not os.path.isdir(os.path.join(kit, "deals")) and not os.path.exists(os.path.join(kit, "run.sh")):
        sys.exit("%s doesn't look like the kit folder." % kit)
    if "--rollback" in args:
        return rollback(kit)
    have = installed_version(kit)
    zips = find_zips()
    if not zips:
        sys.exit("No special-sits-kit zip found in your Downloads, Desktop or Linux home folder. Download the latest one first.")
    _, _, newest, path = zips[0]
    print("You have version %s. The newest zip found is version %s," % (have, newest))
    print("  %s" % path)
    if "--second-pass" in args:
        install(kit, path)
        return
    if vkey(newest) <= vkey(have) and "--force" not in args:
        print("Nothing to do, you're up to date. If you just downloaded a newer one, check it finished downloading.")
        return
    saved = backup(kit, have)
    before = open(os.path.abspath(__file__), "rb").read()
    install(kit, path)
    # A new version may install files the old installer didn't know about, so let the new installer run once more
    after_path = os.path.join(kit, "lib", "upgrade.py")
    if "--second-pass" not in args and os.path.exists(after_path) and open(after_path, "rb").read() != before:
        import subprocess
        subprocess.call([sys.executable, after_path, "--kit", kit, "--force", "--second-pass"], stdout=subprocess.DEVNULL)
    print("Upgraded to version %s. Your settings, deals and history are untouched." % installed_version(kit))
    print("The previous program files are in %s, and ./run.sh upgrade --rollback puts them back." % os.path.relpath(saved, kit))


if __name__ == "__main__":
    main()
