# -*- coding: utf-8 -*-
"""Package the Kinetic BIM Standard extension for distribution.

Run on a developer machine with **CPython 3** (NOT inside Revit):

    python tools/build_extension.py

Produces, under ``dist/``:

    Kinetic-<version>.zip
        Kinetic.extension/   <- the loadable pyRevit extension (clean tree)
        install.ps1          <- the customer installer
        INSTALL.txt          <- quick-start instructions

The version is read from ``lib/bim_core/version.py`` (the single source of
truth) so the archive name always tracks the shipped build. The staging tree
strips everything a customer must never receive: the dev test suite, build
tooling, git metadata, bytecode caches, and the user-guide build script.

This is the M1 "distribution packaging" deliverable: customers install the
built ``Kinetic.extension`` folder via ``install.ps1`` rather than relying on
the developer junction used for in-Revit testing.
"""

from __future__ import print_function

import os
import re
import shutil
import sys
import zipfile

# --- paths ----------------------------------------------------------------

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TOOLS_DIR)

EXTENSION_NAME = "Kinetic.extension"
VERSION_FILE = os.path.join(REPO_ROOT, "lib", "bim_core", "version.py")
BUILD_DIR = os.path.join(REPO_ROOT, "build")
DIST_DIR = os.path.join(REPO_ROOT, "dist")

# Files that live at the repo root and ride along OUTSIDE the extension
# folder, at the top level of the archive.
ROOT_PAYLOAD = ["install.ps1", "INSTALL.txt"]

# --- what to leave out of the shipped extension ---------------------------

# Directory names excluded anywhere in the tree.
EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "tests",        # dev test suite
    "tools",        # build + fixture tooling (this script lives here)
    "build",        # our own staging output
    "dist",         # our own archive output
    ".pytest_cache",
    ".vscode",
    ".idea",
}

# Exact file names excluded anywhere in the tree.
EXCLUDE_FILES = {
    ".gitignore",
    "build_user_guide.py",   # dev script that regenerates the .docx guides
}

# Filename suffixes excluded anywhere in the tree.
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".pyd")

# Repo-root entries that are not part of the extension itself.
EXCLUDE_ROOT_ENTRIES = {
    "build",
    "dist",
    "tests",
    "tools",
    ".git",
    ".gitignore",
    "README.md",        # repo README; customers get INSTALL.txt instead
    "CHANGELOG.md",      # dev changelog stays in the repo, not the extension
    "install.ps1",      # rides at archive root, not inside the extension
    "INSTALL.txt",
}


def read_version():
    with open(VERSION_FILE) as fh:
        text = fh.read()
    match = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", text)
    if not match:
        raise SystemExit("Could not find __version__ in %s" % VERSION_FILE)
    return match.group(1)


def is_excluded_file(name):
    if name in EXCLUDE_FILES:
        return True
    return name.endswith(EXCLUDE_SUFFIXES)


def stage_extension(dst_root):
    """Copy the repo into ``dst_root`` as a clean extension tree.

    Returns the number of files copied.
    """
    copied = 0
    for entry in sorted(os.listdir(REPO_ROOT)):
        if entry in EXCLUDE_ROOT_ENTRIES:
            continue
        src = os.path.join(REPO_ROOT, entry)
        dst = os.path.join(dst_root, entry)
        if os.path.isdir(src):
            copied += _copy_tree(src, dst)
        elif not is_excluded_file(entry):
            shutil.copy2(src, dst)
            copied += 1
    return copied


def _copy_tree(src, dst):
    copied = 0
    for current, dirs, files in os.walk(src):
        # prune excluded directories in place so os.walk skips them
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        rel = os.path.relpath(current, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        if not os.path.isdir(target):
            os.makedirs(target)
        for fname in files:
            if is_excluded_file(fname):
                continue
            shutil.copy2(os.path.join(current, fname),
                         os.path.join(target, fname))
            copied += 1
    return copied


def copy_root_payload(staging):
    for name in ROOT_PAYLOAD:
        src = os.path.join(REPO_ROOT, name)
        if not os.path.isfile(src):
            raise SystemExit(
                "Required root payload file missing: %s\n"
                "(install.ps1 and INSTALL.txt must exist at the repo root.)"
                % src)
        shutil.copy2(src, os.path.join(staging, name))


def make_zip(staging, version):
    if not os.path.isdir(DIST_DIR):
        os.makedirs(DIST_DIR)
    zip_path = os.path.join(DIST_DIR, "Kinetic-%s.zip" % version)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for current, dirs, files in os.walk(staging):
            dirs.sort()
            for fname in sorted(files):
                full = os.path.join(current, fname)
                arc = os.path.relpath(full, staging)
                zf.write(full, arc)
    return zip_path


def main():
    version = read_version()
    print("Kinetic BIM Standard - packaging v%s" % version)

    # clean staging
    if os.path.isdir(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR)

    ext_root = os.path.join(BUILD_DIR, EXTENSION_NAME)
    os.makedirs(ext_root)

    n_files = stage_extension(ext_root)
    copy_root_payload(BUILD_DIR)

    # sanity: the staged extension must declare itself
    if not os.path.isfile(os.path.join(ext_root, "extension.json")):
        raise SystemExit("Staged extension is missing extension.json - aborting.")

    zip_path = make_zip(BUILD_DIR, version)
    size_kb = os.path.getsize(zip_path) / 1024.0

    print("  staged %d files into %s/" % (n_files, EXTENSION_NAME))
    print("  archive: %s (%.0f KB)" % (zip_path, size_kb))
    print("  contents:")
    for name in [EXTENSION_NAME + "/"] + ROOT_PAYLOAD:
        print("    %s" % name)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
