#!/usr/bin/env python3
"""
FFmpegMassConv - Mass video conversion using FFmpeg
Supports multiple PCs working on shared drives simultaneously.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import random
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

APP_NAME         = "ffmpeg_mass_conv"
TASK_CONFIG_NAME = "conversion-config.json"
USER_CONFIG_NAME = "settings.json"
LOCK_TIMEOUT     = 60     # seconds before a lock is considered stale
LOCK_MAX_WAIT    = 120    # seconds to wait before giving up on a lock
LOCK_POLL_BASE   = 0.25   # base polling interval (seconds)

# \0 is illegal in filenames on every OS — this key can never collide with a
# real video entry in the task config.  Valid JSON, impossible as a path.
LOCK_KEY = '\0lock'
# Same null-byte trick for the timestamp backlog — \0 can never appear in a
# real filename, so this key is safe in the shared task config.
TIMESTAMP_BACKLOG_KEY = '\0timestamp_backlog'

# Statuses from which a task can be picked up and worked on
WORKABLE_STATUSES = {"todo", "failed", "killed", "canceled"}

# Escape prefix for passing values that start with '-' through argparse.
# Argparse treats any token beginning with '-' as a flag, so list arguments
# like -v (video encoder flags) cannot take values such as -qp directly.
# Prefix the value with ^ to signal that the leading ^ should be stripped:
#
#   -v ^-qp 22    ->  -c:v -qp 22
#   -s ^-y        ->  -y
#   -e ^-map 0    ->  -map 0
#
# ^ is safe on every common shell (bash, zsh, fish, cmd, PowerShell).
ESCAPE_PREFIX = "^"

# Tokens that expand to per-field defaults in list arguments
PLACEHOLDER_TOKENS: dict[str, dict[str, str]] = {
    "regex":  {"{a}": ".*\\.mp4$",  "{b}": ".*\\.mkv$"},
    "start":  {"{a}": "-y"},
    "video":  {"{a}": "hevc_nvenc", "{b}": "-qp", "{c}": "22"},
    "audio":  {"{a}": "copy"},
    "ending": {"{a}": "-map", "{b}": "0", "{c}": "-map_metadata", "{d}": "0"},
}

# Keys excluded from the user settings file (session-only or derived)
NOT_SAVED = {"config_file", "directories", "workingdir",
             "extra_dirs", "translator", "dry_run",
             "path_add", "path_remove", "path_list", "path_use",
             "path_use_all"}


# ──────────────────────────────────────────────────────────────────────────────
# Platform helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_platform() -> str:
    return platform.system()  # "Linux" | "Darwin" | "Windows"


def get_user_config_dir() -> Path:
    system = get_platform()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    config_dir = base / APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_machine_uuid() -> str:
    system = get_platform()
    if system in ("Linux", "Darwin"):
        for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                return Path(candidate).read_text().strip()
            except OSError:
                pass
    if system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\\Microsoft\\Cryptography")
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return value
        except Exception:
            pass
    return str(uuid.getnode())


def is_pid_alive(pid: int) -> bool:
    if get_platform() == "Windows":
        PROCESS_QUERY_INFORMATION = 0x0400
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Path translation
# ──────────────────────────────────────────────────────────────────────────────
#
# Design notes on path handling:
#
# Paths in the shared task config are stored exactly as the writing PC provided
# them — no normalization.  This preserves backslashes that are legal filename
# characters on Linux/macOS (even though they're separators on Windows).
#
# Comparison in PathMap uses PurePath to split paths into parts, which handles
# both slash styles on each OS correctly without blindly replacing \ with /.
# On Linux, PurePosixPath('/a/b') and PurePosixPath('/a\\b') are different
# ('/a/b' has parts ['/', 'a', 'b'], '/a\\b' has parts ['/', 'a\\b']), so a
# Linux path with a literal backslash in a filename component is correctly
# treated as opaque and never misidentified as a separator.
#
# The 'prefer_local' flag: if True and the local path exists on disk, skip
# translation (the original path is already valid locally).  Useful when both
# PCs happen to mount the share at the same path.

def _path_parts(p: str) -> tuple[str, ...]:
    """
    Split a path string into parts using the current OS's path rules.
    Falls back gracefully if PurePath can't parse it.
    """
    try:
        return PurePath(p).parts
    except Exception:
        return (p,)


def _path_starts_with(path_str: str, prefix_str: str) -> bool:
    """
    Return True if path_str starts with prefix_str as a path prefix
    (not just a string prefix), using OS-native path splitting.
    """
    path_parts   = _path_parts(path_str)
    prefix_parts = _path_parts(prefix_str)
    if len(prefix_parts) > len(path_parts):
        return False
    return path_parts[:len(prefix_parts)] == prefix_parts


def _apply_prefix_swap(path_str: str, old_prefix: str,
                        new_prefix: str) -> Optional[str]:
    """
    Replace old_prefix with new_prefix in path_str using path-part-aware logic.

    Uses PurePath.parts for splitting so separator style doesn't matter:
    both '//nas/share' and '\\\\nas\\share' produce the same parts on their
    respective OS.  Backslashes that are literal filename characters on Linux
    remain opaque because PurePosixPath never treats them as separators.

    Returns None if old_prefix is not a path-prefix of path_str.
    """
    path_parts   = _path_parts(path_str)
    prefix_parts = _path_parts(old_prefix)
    if path_parts[:len(prefix_parts)] != prefix_parts:
        return None
    suffix_parts = path_parts[len(prefix_parts):]
    base = new_prefix.rstrip("/\\")
    if suffix_parts:
        return base + os.sep + os.sep.join(suffix_parts)
    return base


@dataclass
class PathMap:
    """
    One named mount-point translation rule.

    'remote'       — path as stored in the shared task config
    'local'        — how this machine accesses the same location
    'prefer_local' — if True and the local path exists, skip translation
    """
    name:         str
    remote:       str
    local:        str
    prefer_local: bool = False

    def to_local(self, path: str) -> Optional[str]:
        """
        Translate path from remote to local.
        Returns None if this rule doesn't apply.
        """
        if self.prefer_local and Path(path).exists():
            return path   # already accessible locally, skip translation
        return _apply_prefix_swap(path, self.remote, self.local)

    def to_remote(self, path: str) -> Optional[str]:
        """
        Translate path from local to remote.
        Returns None if this rule doesn't apply.
        """
        return _apply_prefix_swap(path, self.local, self.remote)

    def to_dict(self) -> dict:
        return {
            "name":         self.name,
            "remote":       self.remote,
            "local":        self.local,
            "prefer_local": self.prefer_local,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PathMap":
        return cls(
            name=d["name"],
            remote=d["remote"],
            local=d["local"],
            prefer_local=d.get("prefer_local", False),
        )


class PathTranslator:
    """
    Apply an ordered list of PathMap rules; first match wins.
    Only the maps named in 'active' are used; all maps are stored.
    """

    def __init__(self, all_maps: list[PathMap],
                 active_names: Optional[list[str]] = None,
                 prefer_local: bool = False):
        """
        active_names=None  -> use all maps (same as passing all names)
        active_names=[]    -> use no maps (translation disabled)
        active_names=[...] -> use only the named maps, in order
        prefer_local=True  -> globally skip translation when the local path exists
        """
        self.all_maps = {m.name: m for m in all_maps}
        if active_names is None:
            raw = list(all_maps)
        else:
            raw = [self.all_maps[n] for n in active_names
                   if n in self.all_maps]
        if prefer_local:
            self._active = [PathMap(name=m.name, remote=m.remote,
                                    local=m.local, prefer_local=True)
                           for m in raw]
        else:
            self._active = raw

    def to_local(self, path: str) -> str:
        for m in self._active:
            result = m.to_local(path)
            if result is not None:
                return result
        return path

    def to_remote(self, path: str) -> str:
        for m in self._active:
            result = m.to_remote(path)
            if result is not None:
                return result
        return path

    def list_all(self) -> list[PathMap]:
        return list(self.all_maps.values())


# ──────────────────────────────────────────────────────────────────────────────
# JSON helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ──────────────────────────────────────────────────────────────────────────────
# User settings  (local to this machine, never shared)
# ──────────────────────────────────────────────────────────────────────────────

def load_user_settings(config_path: Path) -> dict:
    return _load_json(config_path)


def save_user_settings(config_path: Path, args: argparse.Namespace,
                       saved_maps: list[PathMap],
                       previous: dict) -> None:
    data = {k: v for k, v in vars(args).items() if k not in NOT_SAVED}
    data["last_directories"] = args.directories
    # Store the full set of saved translations (never the translated values)
    data["path_maps"] = [m.to_dict() for m in saved_maps]
    if data != previous:
        _save_json(config_path, data)
        print(f"Settings saved -> {config_path}\n")


# ──────────────────────────────────────────────────────────────────────────────
# Shared task config  (lives inside each target folder, visible to all PCs)
# ──────────────────────────────────────────────────────────────────────────────

def task_config_path(folder: Path) -> Path:
    return folder / TASK_CONFIG_NAME


def load_task_config(folder: Path) -> dict:
    return _load_json(task_config_path(folder))


def save_task_config(folder: Path, config: dict) -> None:
    _save_json(task_config_path(folder), config)


def acquire_lock(folder: Path) -> dict:
    """
    Spin-wait until the advisory lock in the task config is free, then claim it.
    Returns the config with the lock already written to disk.

    The lock is a timestamp stored under LOCK_KEY ('\0lock').
    A lock older than LOCK_TIMEOUT seconds is considered stale and broken.
    """
    deadline = time.monotonic() + LOCK_MAX_WAIT
    poll     = LOCK_POLL_BASE + random.uniform(0.0, 0.15)  # jitter

    while True:
        config = load_task_config(folder)
        stamp  = config.get(LOCK_KEY)   # None = unlocked

        if stamp is None or stamp < time.time() - LOCK_TIMEOUT:   # free or stale
            config[LOCK_KEY] = time.time()
            save_task_config(folder, config)
            return config

        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Could not acquire lock on {folder} after {LOCK_MAX_WAIT}s")

        time.sleep(poll)


def release_lock(folder: Path, config: dict) -> None:
    """Clear the lock and flush config to disk."""
    config[LOCK_KEY] = None
    save_task_config(folder, config)


# ──────────────────────────────────────────────────────────────────────────────
# Simulate mode
# ──────────────────────────────────────────────────────────────────────────────

class SimulateState:
    """
    Deterministic fake outcomes for dry-run mode so every status path is hit.

    Sequence:
      1 video  -> success
      2 videos -> fail, success
      3+       -> fail, cancel, then all remaining succeed

    Intentional fails/cancels are clearly labelled in output.
    """

    def __init__(self, total_tasks: int):
        self.total     = total_tasks
        self.index     = 0
        self.completed = 0
        self.failed    = 0
        self.canceled  = 0

        if total_tasks == 1:
            self._sequence = ["completed"]
        elif total_tasks == 2:
            self._sequence = ["failed", "completed"]
        else:
            self._sequence = (["failed", "canceled"]
                              + ["completed"] * (total_tasks - 2))

    def next_outcome(self) -> str:
        outcome = (self._sequence[self.index]
                   if self.index < len(self._sequence)
                   else "completed")
        self.index += 1
        return outcome

    def record(self, outcome: str) -> None:
        if outcome == "completed":
            self.completed += 1
        elif outcome == "failed":
            self.failed += 1
        elif outcome == "canceled":
            self.canceled += 1

    def print_legend(self) -> None:
        if self.total == 1:
            print("[sim] Outcome plan: 1 video -> success\n")
        elif self.total == 2:
            print("[sim] Outcome plan: 2 videos -> fail, success\n")
        else:
            print(f"[sim] Outcome plan: {self.total} videos -> "
                  f"fail, cancel, then {self.total - 2}x success\n"
                  "[sim] (Intentional fail/cancel exercise all status paths.)\n")


# ──────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ──────────────────────────────────────────────────────────────────────────────

def str2bool(v: str | bool) -> bool:
    if isinstance(v, bool):
        return v
    return v.strip().lower() in ("yes", "true", "t", "y", "1")


def expand_tokens(values: list[str], field: str) -> list[str]:
    """Replace {a}/{b}/... placeholders with per-field defaults."""
    mapping = PLACEHOLDER_TOKENS.get(field, {})
    return [mapping.get(item, item) for item in values]


def unescape_values(values: list[str]) -> list[str]:
    """Strip ESCAPE_PREFIX from values that carry it."""
    return [v.removeprefix(ESCAPE_PREFIX) if v.startswith(ESCAPE_PREFIX) and len(v) > 1 else v
            for v in values]


def build_parser(saved: dict, default_config_path: Path) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ffmpeg-conv.py",
        description=(
            "Mass FFmpeg video converter with multi-PC shared-drive support.\n"
            "\n"
            "Tokens {a} {b} {c} {d} in list arguments expand to their per-field\n"
            "defaults, letting you override only part of a default list.\n"
            "Example:  -v libx264 {b} {c}  ->  -c:v libx264 -qp 22\n"
            "\n"
            "Prefix a value with ^ to pass it through argparse without flag\n"
            "interpretation.  This lets you write flags like -qp or -map in\n"
            "list arguments:  -e ^-map 0 ^-map_metadata 0\n"
        ),
        epilog=(
            "Default Generated FFmpeg command:\n"
            "  ffmpeg -y -i INPUT -c:v hevc_nvenc -qp 22"
            " -c:a copy -map 0 -map_metadata 0 OUTPUT"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    g = p.add_argument_group("Configuration")
    g.add_argument("-c", "--config-file", metavar="PATH",
                   default=str(default_config_path),
                   help=f"Local user settings file (not shared)\n"
                        f"(default: {default_config_path})")

    g = p.add_argument_group("Directories")
    g.add_argument("directories", nargs="*", metavar="DIR",
                   help="Target directories (positional)")
    g.add_argument("-d", "--dirs", dest="extra_dirs", nargs="+", metavar="DIR",
                   default=[],
                   help="Additional target directories (flag form)")
    g.add_argument("-w", "--working-dir", dest="workingdir", metavar="PATH",
                   default=saved.get("workingdir"),
                   help="Change working directory before resolving relative paths")

    g = p.add_argument_group(
        "Path translation  (multi-PC / different mount points)\n"
        "\n"
        "Translations are stored by name in your local settings file.\n"
        "Use -A to add/update, -R to remove, -L to list, -P to activate.\n"
        "\n"
        "'remote' is the path as written into the shared task config.\n"
        "'local'  is how this machine accesses the same files.\n"
        "\n"
        "Use -p to prefer local paths globally (saved in config).\n"
        "When enabled, translation is skipped if the local path already exists.\n"
    )
    g.add_argument("-A", "--path-add", dest="path_add",
                   nargs="+", metavar="ARG",
                   help=(
                       "Add or update a saved translation:\n"
                       "  -A NAME REMOTE LOCAL\n"
                       "Example:  -A nas-share //nas/videos /mnt/videos\n"
                       "Use -p to set prefer-local globally for all rules."
                   ))
    g.add_argument("-R", "--path-remove", dest="path_remove",
                   nargs="+", metavar="NAME",
                   help="Remove saved translation(s) by name:\n"
                        "  -R nas-share  or  -R nas-share ssd-output")
    g.add_argument("-L", "--path-list", dest="path_list",
                   action="store_true", default=False,
                   help="List all saved translations and exit")
    g.add_argument("-P", "--path-use", dest="path_use",
                   nargs="+", metavar="NAME",
                   default=None,
                   help=(
                       "Activate specific saved translations by name for this run.\n"
                       "  -P nas-share\n"
                       "  -P nas-share ssd-output\n"
                       "To activate all saved translations, use -U instead."
                   ))
    g.add_argument("-U", "--path-use-all", dest="path_use_all",
                   action="store_true", default=False,
                   help="Activate all saved translations for this run")
    g.add_argument("-p", "--prefer-local", dest="prefer_local",
                   type=str2bool, nargs="?", const=True, metavar="Yes or No",
                   default=saved.get("prefer_local", False),
                   help="Skip path translation when the local path already exists\n"
                        "(saved in config)")

    g = p.add_argument_group("FFmpeg settings")
    g.add_argument("-f", "--ffmpeg", metavar="BIN",
                   default=saved.get("ffmpeg", "ffmpeg"),
                   help="Path to ffmpeg binary  (default: ffmpeg)")
    g.add_argument("-i", "--input-flags", dest="input_flags", action="append",
                   metavar="FLAG", default=None,
                   help=(
                       "Flag(s) inserted before the input file  (default: -i)\n"
                       "Repeat the option for each token:\n"
                       "  --input-flags ^-ss 30 ^-i\n"
                       "Or attach with = to avoid shell splitting:\n"
                       "  --input-flags=-ss --input-flags=30 --input-flags=-i"
                   ))
    g.add_argument("-r", "--regex", nargs="+", metavar="PAT",
                   default=saved.get("regex", ["{a}", "{b}"]),
                   help="Filename regex patterns to match  (default: mp4 + mkv)")
    g.add_argument("-o", "--output", metavar="TMPL",
                   default=saved.get("output", "{n}-q22.{e}"),
                   help="Output name template: {n}=stem {e}=ext  (default: {n}-q22.{e})")
    g.add_argument("-s", "--start", nargs="+", metavar="ARG",
                   default=saved.get("start", ["{a}"]),
                   help="Args after 'ffmpeg', before input  (default: -y)\n"
                        "Prefix flags with ^ to avoid argparse interception:\n"
                        "  -s ^-y ^-hwaccel cuda")
    g.add_argument("-v", "--video-encoder", dest="video", nargs="+", metavar="ARG",
                   default=saved.get("video", ["{a}", "{b}", "{c}"]),
                   help="Video encoder flags  (-c:v is prepended automatically)\n"
                        "(default: hevc_nvenc -qp 22)\n"
                        "Do NOT include -c:v itself:\n"
                        "  -v libx264 ^-qp 18    ->  -c:v libx264 -qp 18\n"
                        "Prefix flags with ^ to avoid argparse interception.")
    g.add_argument("-a", "--audio-encoder", dest="audio", nargs="+", metavar="ARG",
                   default=saved.get("audio", ["{a}"]),
                   help="Audio encoder flags  (-c:a is prepended automatically)\n"
                        "(default: copy)\n"
                        "Do NOT include -c:a itself:\n"
                        "  -a aac ^-b:a 192k    ->  -c:a aac -b:a 192k\n"
                        "Prefix flags with ^ to avoid argparse interception.")
    g.add_argument("-e", "--ending", nargs="+", metavar="ARG",
                   default=saved.get("ending", ["{a}", "{b}", "{c}", "{d}"]),
                   help="Args appended after the output file\n"
                        "(default: -map 0 -map_metadata 0)\n"
                        "Prefix flags with ^ to avoid argparse interception:\n"
                        "  -e ^-map 0 ^-map_metadata 0 ^-c:s copy")

    g = p.add_argument_group("Behaviour")
    g.add_argument("-x", "--remove-failed", dest="remove_failed",
                   type=str2bool, nargs="?", const=True, metavar="Yes or No",
                   default=saved.get("remove_failed", True),
                   help="Remove partial output after a failed conversion  (default: on)")
    g.add_argument("-X", "--remove-original", dest="remove_original",
                   type=str2bool, nargs="?", const=True, metavar="Yes or No",
                   default=saved.get("remove_original", False),
                   help="Delete source file after success  (IRREVERSIBLE; default: off)")
    g.add_argument("-m", "--max-convert", dest="max_convert", type=int,
                   default=saved.get("max_convert", -1),
                   help="Stop after N successful conversions per run  (-1 = unlimited)")
    g.add_argument("-S", "--simulate",
                   type=str2bool, nargs="?", const=True, metavar="Yes or No",
                   default=saved.get("simulate", False),
                   help="Simulate mode (saved in config). Use -S True or -S False.\n"
                        "For one-off simulation without saving, use --dry-run.")
    g.add_argument("-n", "--dry-run", action="store_true", default=False,
                   help="Simulate this run only (not saved). Overrides -S.")
    g.add_argument("-k", "--keep-timestamps", dest="keep_timestamps",
                   type=str2bool, nargs="?", const=True, metavar="Yes or No",
                   default=saved.get("keep_timestamps", True),
                   help="Preserve source file timestamps on output  (default: on)")
    g.add_argument("-t", "--timestamp-backlog-only", dest="timestamp_backlog_only",
                   type=str2bool, nargs="?", const=True, metavar="Yes or No",
                   default=saved.get("timestamp_backlog_only", False),
                   help="Process timestamp backlog and exit (no conversions)")

    return p


def _parse_path_add(raw: list[str], prefer_local_flag: bool) -> PathMap:
    """
    Parse -PA arguments into a PathMap.
    Accepts:  NAME REMOTE LOCAL
    """
    if len(raw) != 3:
        raise ValueError(
            f"-PA requires exactly: NAME REMOTE LOCAL  (got: {raw!r})")
    return PathMap(name=raw[0], remote=raw[1],
                   local=raw[2], prefer_local=prefer_local_flag)


def with_json(path: Path) -> Path:
    return path.with_suffix(path.suffix or ".json") if path.suffix else Path(str(path) + ".json")


def resolve_config_path(raw: str | None, user_dir: Path, default_config_path: Path) -> Path:
    if not raw:
        return default_config_path

    p = Path(raw)
    # 1) exact path as given
    if p.exists():
        return p

    # 2) try given + .json
    given_json = with_json(p)
    if given_json.exists():
        return given_json

    # 3) try relative to user dir (preserve any suffix)
    rel = user_dir / raw
    if rel.exists():
        return rel

    # 4) try user_dir / (given + .json)
    rel_json = with_json(rel)
    if rel_json.exists():
        return rel_json

    # 5) if raw still given
    if raw:
        # and p is not in a subfolder place in conf folder
        if os.sep not in raw:
            candidate = user_dir / raw
        # otherwise just use as given
        else:
            candidate = p
        return with_json(candidate) if not candidate.exists() else candidate

    return default_config_path


def parse_arguments() -> tuple[argparse.Namespace, list[PathMap], PathTranslator]:
    """
    Returns (args, saved_maps, translator).

    saved_maps — the full list of all named translations for this machine
                 (to be persisted on next save_user_settings call)
    translator — the translator built from whichever maps are active this run
    """
    # First pass: extract --config-file so we can load saved defaults
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("-c", "--config-file", default=None)
    pre_args, _ = pre.parse_known_args()

    config_dir = get_user_config_dir()
    default_config_path = config_dir / USER_CONFIG_NAME

    config_path = resolve_config_path(pre_args.config_file, config_dir, default_config_path)

    saved = load_user_settings(config_path)
    saved_copy = dict(saved)

    parser = build_parser(saved, default_config_path)
    args, leftovers = parser.parse_known_args()

    # Unrecognised tokens treated as extra directory paths
    if leftovers:
        args.directories = list(args.directories) + leftovers

    # Resolve input_flags early (action="append" gives None when not provided)
    # so that _commit_settings never writes null to the settings file.
    if args.input_flags is None:
        args.input_flags = saved.get("input_flags") or ["-i"]
    args.input_flags = unescape_values(args.input_flags)

    # ── Handle path-management side-effects before anything else ──────────────

    # Load existing saved maps from settings
    saved_maps: dict[str, PathMap] = {
        m["name"]: PathMap.from_dict(m)
        for m in saved.get("path_maps", [])
        if isinstance(m, dict) and "name" in m
    }

    if args.path_list:
        _print_path_list(saved_maps)
        sys.exit(0)

    if args.path_remove:
        for name in args.path_remove:
            if name in saved_maps:
                del saved_maps[name]
                print(f"Removed translation: {name}")
            else:
                print(f"Warning: translation '{name}' not found.")
        _commit_settings(config_path, args, list(saved_maps.values()), saved_copy)
        if not args.directories and not args.extra_dirs:
            sys.exit(0)

    if args.path_add:
        try:
            new_map = _parse_path_add(args.path_add, args.prefer_local)
        except ValueError as e:
            parser.error(str(e))
        saved_maps[new_map.name] = new_map
        print(f"Saved translation '{new_map.name}': "
              f"{new_map.remote!r} -> {new_map.local!r}"
              f"{' (prefer-local)' if new_map.prefer_local else ''}")
        _commit_settings(config_path, args, list(saved_maps.values()), saved_copy)
        if not args.directories and not args.extra_dirs:
            sys.exit(0)

    # Build the set of active maps for this run
    if args.path_use_all:
        active_maps: list[PathMap] = list(saved_maps.values())
    elif args.path_use is not None:
        missing = [n for n in args.path_use if n not in saved_maps]
        if missing:
            parser.error(f"Unknown translation name(s): {', '.join(missing)}\n"
                         f"Use -PL to list saved translations.")
        active_maps = [saved_maps[n] for n in args.path_use]
    else:
        # Neither -P nor -PU given: no translations active this run
        active_maps = []

    # Build translator: active_names=None means "use all", [] means "use none"
    if args.path_use is None and not getattr(args, "path_use_all", False):
        active_names: Optional[list[str]] = []   # -P not given: no translation
    elif getattr(args, "path_use_all", False) or len(args.path_use) == 0:
        active_names = None                       # use all saved translations
    else:
        active_names = [m.name for m in active_maps]
    translator = PathTranslator(list(saved_maps.values()), active_names,
                                prefer_local=args.prefer_local)
    args.translator = translator

    # ── Resolve working directory ──────────────────────────────────────────────
    if args.workingdir:
        wd = Path(args.workingdir)
        if wd.is_dir():
            os.chdir(wd)
        else:
            print(f"Warning: --working-dir '{args.workingdir}' not found, ignoring.\n")
    args.workingdir = str(Path.cwd())

    # Combine positional + flag directories, resolve to absolute paths
    raw_dirs = list(args.directories) + list(args.extra_dirs)
    if not raw_dirs:
        raw_dirs = saved.get("last_directories", [])
    args.directories = [str(Path(d).resolve()) for d in raw_dirs if Path(d).is_dir()]

    if not args.directories:
        parser.print_help()
        print("\nError: no valid directories to process.")
        sys.exit(1)

    # Strip stale -c:v/-c:a prefixes from saved defaults (migration)
    if args.video and args.video[0] == "-c:v":
        args.video = args.video[1:]
    if args.audio and args.audio[0] == "-c:a":
        args.audio = args.audio[1:]

    # Expand placeholder tokens in list arguments
    args.regex  = unescape_values(expand_tokens(args.regex,  "regex"))
    args.start  = unescape_values(expand_tokens(args.start,  "start"))
    args.video  = unescape_values(expand_tokens(args.video, "video"))
    args.audio  = unescape_values(expand_tokens(args.audio, "audio"))
    args.ending = unescape_values(expand_tokens(args.ending, "ending"))

    # Persist settings (skip in dry-run mode so one-off sims don't save)
    if not args.dry_run:
        _commit_settings(config_path, args, list(saved_maps.values()), saved_copy)

    return args, list(saved_maps.values()), translator


def _print_path_list(saved_maps: dict[str, PathMap]) -> None:
    if not saved_maps:
        print("No saved translations.")
        return
    print("Saved path translations:")
    for m in saved_maps.values():
        pl = "  [prefer-local]" if m.prefer_local else ""
        print(f"  {m.name}:  {m.remote!r}  ->  {m.local!r}{pl}")


def _commit_settings(config_path: Path, args: argparse.Namespace,
                     saved_maps: list[PathMap], previous: dict) -> None:
    data = {k: v for k, v in vars(args).items() if k not in NOT_SAVED}
    data["last_directories"] = getattr(args, "directories", [])
    data["path_maps"] = [m.to_dict() for m in saved_maps]
    if data != previous:
        _save_json(config_path, data)
        print(f"Settings saved -> {config_path}\n")


# ──────────────────────────────────────────────────────────────────────────────
# FFmpeg command builder
# ──────────────────────────────────────────────────────────────────────────────

def build_ffmpeg_cmd(args: argparse.Namespace,
                     input_file: str, output_file: str) -> list[str]:
    return (
        [args.ffmpeg]
        + args.start
        + args.input_flags      # e.g. ["-i"]  or  ["-ss", "30", "-i"]
        + [input_file]
        + ["-c:v"] + args.video
        + ["-c:a"] + args.audio
        + args.ending
        + [output_file]
    )


def fmt_cmd(cmd: list[str]) -> str:
    parts = [cmd[0]] + [f"'{a}'" if " " in a else a for a in cmd[1:]]
    return " ".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# FolderProcessor
# ──────────────────────────────────────────────────────────────────────────────

class FolderProcessor:
    """
    All logic for converting videos inside one target directory.

    Responsibilities (each has its own method or group of methods):
      - Discover which files match the regex
      - Reconcile discoveries with the shared task config
      - Recover tasks abandoned by crashed workers on this machine
      - Claim, convert, and finalise individual tasks
      - Simulate outcomes deterministically for dry-run mode
    """

    def __init__(self, folder: Path, args: argparse.Namespace,
                 machine_uuid: str, pid: int,
                 sim: Optional[SimulateState]):
        self.folder       = folder
        self.args         = args
        self.translator   = args.translator
        self.machine_uuid = machine_uuid
        self.pid          = pid
        self.sim          = sim          # None = real run
        self.counters: dict[str, int] = {"completed": 0, "failed": 0, "canceled": 0, "skipped": 0}
        self.interrupted  = False   # True when Ctrl+C was caught
        self.max_reached  = False   # True when --max-convert limit was hit
        self.max_left     = args.max_convert  # -1 = unlimited

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> None:
        self._process_timestamp_backlog()

        if self.args.timestamp_backlog_only:
            return

        found = self._discover_tasks()
        if not found:
            print("  No matching files found.\n")
            return

        if self.sim is not None:
            self.sim.print_legend()

        config = self._reconcile(found)
        self._process_tasks(config)

    # ── Discovery ─────────────────────────────────────────────────────────────

    def _discover_tasks(self) -> dict[str, dict]:
        """Return {filename: task_dict} for every file matching the regex."""
        tasks: dict[str, dict] = {}
        try:
            entries = os.listdir(self.folder)
        except PermissionError as e:
            print(f"  Warning: cannot list folder: {e}")
            return tasks

        for name in entries:
            if not any(re.match(pat, name) for pat in self.args.regex):
                continue
            stem, dot_ext = os.path.splitext(name)
            out_name = self.args.output.format(n=stem, e=dot_ext.lstrip("."))
            if os.path.isabs(out_name):
                print(f"  Warning: output template produces an absolute path "
                      f"for '{name}' — this is probably unintentional.")
            tasks[name] = {
                "output":      out_name,
                "status":      "todo",
                "worker_uuid": None,
                "worker_pid":  None,
                "timestamp":   None,
            }
        return tasks

    # ── Reconciliation ────────────────────────────────────────────────────────

    def _reconcile(self, found: dict[str, dict]) -> dict:
        """
        Lock the shared config, recover dead tasks, merge new files, unlock.
        Returns the up-to-date config dict.
        """
        config = self._acquire()

        # Never convert files that are themselves outputs of a prior conversion.
        # Compare basenames because outputs may be in a subdir (e.g. out/foo.mkv)
        # while the actual file sits in the root directory as foo.mkv.
        output_basenames: set[str] = set()
        for v in found.values():
            output_basenames.add(os.path.basename(v["output"]))
        for name, v in config.items():
            if name != LOCK_KEY and isinstance(v, dict):
                output_basenames.add(os.path.basename(v.get("output", "")))

        for name in list(found):
            if name in output_basenames:
                del found[name]

        # Also prune existing config entries whose filename matches another
        # entry's output — prevents processing stale output files that were
        # accidentally registered before this fix existed.
        for name in list(config):
            if name == LOCK_KEY or not isinstance(config.get(name), dict):
                continue
            if name in output_basenames:
                del config[name]

        self._recover_abandoned(config)
        self._merge_new_tasks(config, found)

        self._release(config)
        return config

    def _recover_abandoned(self, config: dict) -> None:
        """Reset pending tasks whose owning PID on this machine is gone."""
        for name, details in config.items():
            if name == LOCK_KEY or not isinstance(details, dict):
                continue
            if details.get("status") != "pending":
                continue
            if details.get("worker_uuid") != self.machine_uuid:
                continue   # belongs to a different machine — don't touch it
            owner_pid = details.get("worker_pid")
            if owner_pid and is_pid_alive(int(owner_pid)):
                continue   # still running on this machine
            config[name].update(
                status="killed", worker_uuid=None,
                worker_pid=None, timestamp=None)
            print(f"  Recovered abandoned task: {name}")

    def _merge_new_tasks(self, config: dict, found: dict[str, dict]) -> None:
        """Add newly discovered files; update output path if template changed."""
        for name, details in found.items():
            if name not in config:
                config[name] = details
            else:
                existing = config[name]
                if (existing.get("status") in WORKABLE_STATUSES
                        and existing.get("output") != details["output"]):
                    if self.sim is not None:
                        print(f"  [sim] Output path changed for '{name}': "
                              f"{existing['output']} -> {details['output']}")
                    else:
                        config[name]["output"] = details["output"]

    # ── Task loop ─────────────────────────────────────────────────────────────

    def _process_tasks(self, config: dict) -> None:
        names = [
            name for name in config
            if name != LOCK_KEY
            and isinstance(config.get(name), dict)
            and config[name].get("status") in WORKABLE_STATUSES
        ]
        # In simulation mode with 4+ tasks, skip exactly one file to exercise
        # the skipped-path code.  Only do this when max_convert is unlimited
        # or high enough that we have room (>= 4) so the skip logic is visible.
        if (self.sim is not None and len(names) >= 4
                and (self.args.max_convert == -1 or self.args.max_convert >= 4)):
            self.max_left = len(names) - 3
        for i, name in enumerate(names):
            if self.max_left == 0:
                remaining = len(names) - i
                if self.sim is not None:
                    for skip_idx in range(i, len(names)):
                        print(f"  [sim] Skipping '{names[skip_idx]}' "
                              f"(intentional — tests the skipped path)")
                else:
                    print(f"  Max conversions reached "
                          f"({self.args.max_convert} total)."
                          f" Skipping {remaining} remaining file(s)"
                          f" in this folder.\n")
                self.counters["skipped"] += remaining
                break

            stop_reason = self._handle_task(name)
            if stop_reason:
                if stop_reason == "canceled":
                    self.interrupted = True
                else:  # "max_reached"
                    self.max_reached = True
                    if self.sim is not None:
                        for skip_idx in range(i + 1, len(names)):
                            print(f"  [sim] Skipping '{names[skip_idx]}' "
                                  f"(intentional — tests the skipped path)")
                # Count every workable task we never started as skipped
                self.counters["skipped"] += len(names) - i - 1
                break

    def _handle_task(self, name: str) -> Optional[str]:
        """
        Claim, convert, and finalise one task.
        Returns None to continue, "canceled" on Ctrl+C, "max_reached" on limit.
        """
        live_config, live_details, local_input, local_output = \
            self._claim_task(name)
        if live_config is None:
            return False   # skipped cleanly

        outcome = self._convert(name, local_input, local_output)

        # All post-run steps run regardless of outcome so the config is always
        # written cleanly before we propagate any interrupt.
        self._handle_cleanup(outcome, local_input, local_output)
        backlog_entry = self._restore_timestamps(local_input, local_output)
        self._finalise_task(name, live_details["output"], outcome, backlog_entry)
        self._record(outcome)

        print(f"  Status: {outcome}\n---\n")

        if outcome == "canceled":
            if self.sim is not None:
                return None   # intentional simulation test — continue
            return "canceled"
        if outcome == "completed" and self.max_left > 0:
            self.max_left -= 1
            if self.max_left == 0:
                return "max_reached"
        return None

    def _claim_task(
        self, name: str
    ) -> tuple[Optional[dict], Optional[dict], Optional[Path], Optional[Path]]:
        """
        Acquire the lock, verify the task is still claimable, mark it pending,
        release the lock.
        Returns (live_config, live_details, local_input, local_output)
        or (None, None, None, None) when the task should be skipped.
        """
        try:
            live_config = self._acquire()
        except TimeoutError as e:
            print(f"  Error: {e} — stopping folder.\n")
            return None, None, None, None

        live_details = live_config.get(name)
        if not isinstance(live_details, dict):
            self._release(live_config)
            return None, None, None, None
        if live_details.get("status") not in WORKABLE_STATUSES:
            self._release(live_config)
            return None, None, None, None   # another PC grabbed it

        local_input = self.folder / name
        if not local_input.is_file():
            print(f"  Warning: '{local_input}' not found, skipping.\n")
            self._release(live_config)
            return None, None, None, None

        local_output = self._resolve_output(live_details["output"])

        if self.sim is None:
            live_config[name].update(
                status="pending",
                worker_uuid=self.machine_uuid,
                worker_pid=self.pid,
                timestamp=time.time())
        else:
            print(f"  [sim] Claiming '{name}' "
                  f"(uuid={self.machine_uuid}, pid={self.pid})")

        self._release(live_config)
        return live_config, live_details, local_input, local_output

    # ── Conversion ────────────────────────────────────────────────────────────

    def _convert(self, name: str,
                 local_input: Path, local_output: Path) -> str:
        """Run FFmpeg (or simulate) and return 'completed'/'failed'/'canceled'."""
        cmd = build_ffmpeg_cmd(self.args, str(local_input), str(local_output))
        prefix = "[sim] " if self.sim is not None else ""
        print(f"\n{prefix}Command:\n  {fmt_cmd(cmd)}\n")

        if self.sim is not None:
            return self._simulated_outcome()

        try:
            result = subprocess.run(cmd)
            return "completed" if result.returncode == 0 else "failed"
        except KeyboardInterrupt:
            return "canceled"

    def _simulated_outcome(self) -> str:
        assert self.sim is not None
        outcome = self.sim.next_outcome()
        labels = {
            "completed": "[sim] -> completed  (simulated success)",
            "failed":    "[sim] -> failed     (intentional — tests the fail path)",
            "canceled":  "[sim] -> canceled   (intentional — tests the cancel path)",
        }
        print(labels[outcome])
        return outcome

    # ── Post-conversion steps ─────────────────────────────────────────────────

    def _handle_cleanup(self, outcome: str,
                        local_input: Path, local_output: Path) -> None:
        if outcome == "failed" and self.args.remove_failed:
            self._remove_file(local_output, "failed output",
                              f"Would remove failed output: {local_output}")
        elif outcome == "completed" and self.args.remove_original:
            self._remove_file(local_input, "original",
                              f"Would remove original: {local_input}")

    def _restore_timestamps(self, local_input: Path,
                            local_output: Path) -> Optional[dict]:
        """
        Restore atime/mtime from the source file onto the output (and input if
        it still exists).  Returns a backlog entry on failure, or None on
        success / when timestamps are disabled.
        """
        if not self.args.keep_timestamps or self.sim is not None:
            return None
        try:
            stat  = os.stat(local_input)
            times = (stat.st_atime, stat.st_mtime)
        except OSError:
            return None          # source gone — nothing to restore

        any_failed = False
        for target in (local_output, local_input):
            if target.is_file():
                try:
                    os.utime(target, times)
                except OSError:
                    any_failed = True

        if not any_failed:
            return None

        # Prefer to record the output path because it is the file that matters
        # most (the newly created file whose timestamp should match the source).
        store_path = (local_output if local_output.is_file()
                      else local_input if local_input.is_file()
                      else None)
        if store_path is None:
            return None          # neither file still exists
        return {
            "before_translated_path": str(store_path),
            "set_to_unix": times[1],
        }

    def _finalise_task(self, name: str, stored_output: str, outcome: str,
                       backlog_entry: Optional[dict] = None) -> None:
        """Write the final task status back to the shared config."""
        if self.sim is not None:
            print(f"  [sim] Would write status='{outcome}' for '{name}'\n")
            return
        try:
            final = self._acquire()
        except TimeoutError:
            final = load_task_config(self.folder)
        final[name] = {
            "output":      stored_output,
            "status":      outcome,
            "worker_uuid": None,
            "worker_pid":  None,
            "timestamp":   None,
        }
        # Update the timestamp backlog (list of dicts)
        backlog = final.get(TIMESTAMP_BACKLOG_KEY)
        if backlog_entry is not None:
            if not isinstance(backlog, list):
                backlog = []
            backlog.append(backlog_entry)
            final[TIMESTAMP_BACKLOG_KEY] = backlog
        self._release(final)

    def _record(self, outcome: str) -> None:
        self.counters[outcome] = self.counters.get(outcome, 0) + 1
        if self.sim is not None:
            self.sim.record(outcome)

    # ── Timestamp backlog ─────────────────────────────────────────────────────

    def _process_timestamp_backlog(self) -> bool:
        """
        Process all entries in the timestamp backlog.

        For each entry, try os.utime() on the stored path.  If it succeeds,
        remove the entry.  If it fails, keep the entry and move on.

        Returns True if any backlog entry was processed (even if failed),
        False if the backlog was empty or skipped.
        """
        try:
            config = self._acquire()
        except TimeoutError:
            print("  Warning: could not acquire lock to process timestamp "
                  "backlog.\n")
            return False

        backlog = config.get(TIMESTAMP_BACKLOG_KEY)
        if not isinstance(backlog, list) or not backlog:
            self._release(config)
            return False

        print(f"  Processing timestamp backlog ({len(backlog)} entry/entries)...")
        remaining = []
        for entry in backlog:
            path = entry.get("before_translated_path", "")
            unix_ts = entry.get("set_to_unix")
            if not path or not isinstance(unix_ts, (int, float)):
                continue
            try:
                os.utime(path, (unix_ts, unix_ts))
                print(f"    Restored timestamp: {path}")
            except OSError as e:
                print(f"    Still blocked ({e}): {path}")
                remaining.append(entry)

        changed = len(remaining) != len(backlog)
        if changed:
            if remaining:
                config[TIMESTAMP_BACKLOG_KEY] = remaining
            else:
                config.pop(TIMESTAMP_BACKLOG_KEY, None)
        self._release(config)
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_output(self, stored_output: str) -> Path:
        """Convert a stored output path to a local filesystem Path."""
        if os.path.isabs(stored_output):
            return Path(self.translator.to_local(stored_output))
        return self.folder / stored_output

    def _remove_file(self, path: Path, label: str, sim_msg: str) -> None:
        if self.sim is not None:
            print(f"  [sim] {sim_msg}")
            return
        if path.is_file():
            path.unlink()
            print(f"  Removed {label}: {path}")
        else:
            print(f"  Warning: {label} '{path}' not found — cannot remove.")

    def _acquire(self) -> dict:
        return acquire_lock(self.folder)

    def _release(self, config: dict) -> None:
        release_lock(self.folder, config)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _count_workable(folder: Path, regex_list: list[str]) -> int:
    """
    Count how many files in folder match the regex and have a workable status
    in the task config (or are not yet registered, which counts as 'todo').
    Used to report how many tasks were skipped due to an interrupt.
    """
    config = load_task_config(folder)
    try:
        entries = set(os.listdir(folder))
    except OSError:
        return 0
    count = 0
    for name in entries:
        if not any(re.match(pat, name) for pat in regex_list):
            continue
        status = config.get(name, {}).get("status", "todo") if isinstance(config.get(name), dict) else "todo"
        if status in WORKABLE_STATUSES:
            count += 1
    return count


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    """Returns an exit code: 0 = all good, 1 = at least one task failed."""
    args, saved_maps, translator = parse_arguments()
    pid    = os.getpid()
    m_uuid = get_machine_uuid()

    # --dry-run overrides -S for this run only (never saved)
    if args.dry_run:
        args.simulate = True

    if args.simulate:
        print("=== SIMULATION MODE — no files will be changed ===\n")

    print("---\n")
    total: dict[str, int] = {"completed": 0, "failed": 0, "canceled": 0, "skipped": 0}
    interrupted = False   # Ctrl+C was caught
    max_reached = False   # --max-convert limit was hit

    for raw_folder in args.directories:
        folder = Path(raw_folder)

        if interrupted or max_reached:
            # Count workable tasks in skipped folders without running them
            skipped = _count_workable(folder, args.regex)
            total["skipped"] += skipped
            if skipped:
                reason = "interrupted" if interrupted else "max conversions reached"
                print(f"Skipped folder ({reason}): {folder}  ({skipped} task(s))")
            continue

        print(f"Processing: {folder}\n")

        sim: Optional[SimulateState] = None
        if args.simulate:
            try:
                n = sum(1 for f in os.listdir(folder)
                        if any(re.match(p, f) for p in args.regex))
            except OSError:
                n = 1
            sim = SimulateState(max(n, 1))

        processor = FolderProcessor(folder, args, m_uuid, pid, sim)
        processor.run()

        for key in total:
            total[key] += processor.counters.get(key, 0)

        if processor.interrupted or processor.max_reached:
            interrupted = processor.interrupted
            max_reached = processor.max_reached
            # loop continues to count skipped tasks in remaining folders

    # ── Summary ───────────────────────────────────────────────────────────────
    prefix = "[sim] " if args.simulate else ""
    if interrupted:
        print(f"{prefix}Stopped early (interrupted).")
    elif max_reached:
        print(f"{prefix}Stopped after reaching --max-convert limit ({args.max_convert}).")
    else:
        print(f"{prefix}All tasks finished.")
    skipped_str = f"  skipped: {total['skipped']}" if total['skipped'] else ""
    print(f"{prefix}Results — "
          f"completed: {total['completed']}  "
          f"failed: {total['failed']}  "
          f"canceled: {total['canceled']}"
          f"{skipped_str}\n")

    if interrupted:
        raise KeyboardInterrupt
    return 1 if (total["failed"] > 0 or total["canceled"] > 0) else 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        code = 130
    sys.exit(code)
