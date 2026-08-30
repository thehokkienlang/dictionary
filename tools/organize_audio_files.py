"""Organize pronunciation audio files into initial-consonant folders.

The script imports the desktop IME module and uses its Lomari/Hangul audio
filename helpers so folder placement follows the app's own spelling rules.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
IME_PATH = REPO_ROOT / "desktop" / "Hokkien Tangliengim IME Pad.py"
AUDIO_ROOT = REPO_ROOT / "public" / "audio_files"

INITIAL_FOLDERS = {
    "ᄀ": "ㄱ",
    "ᄁ": "ㄲ",
    "ᄂ": "ㄴ",
    "ᄃ": "ㄷ",
    "ᄄ": "ㄸ",
    "ᄅ": "ㄹ",
    "ᄆ": "ㅁ",
    "ᄇ": "ㅂ",
    "ᄈ": "ㅃ",
    "ᄉ": "ㅅ",
    "ᄋ": "ㅇ",
    "ᅙ": "ㆆ",
    "ᄌ": "ㅈ",
    "ᄍ": "ㅉ",
    "ᄎ": "ㅊ",
    "ᄏ": "ㅋ",
    "ᄐ": "ㅌ",
    "ᄑ": "ㅍ",
    "ᄒ": "ㅎ",
}

INITIAL_PREFIXES = [
    ("ng", "ㆆ"),
    ("kh", "ㅋ"),
    ("th", "ㅌ"),
    ("ph", "ㅍ"),
    ("ch", "ㅊ"),
    ("js", "ㅉ"),
    ("k", "ㄱ"),
    ("g", "ㄲ"),
    ("n", "ㄴ"),
    ("t", "ㄷ"),
    ("r", "ㄸ"),
    ("l", "ㄹ"),
    ("m", "ㅁ"),
    ("p", "ㅂ"),
    ("b", "ㅃ"),
    ("s", "ㅅ"),
    ("j", "ㅈ"),
    ("h", "ㅎ"),
]

TONE_SUFFIX_RE = re.compile(r"(?:[_-]?t?[12345]|[ˆˋ`ˊˉꞈˎˏˍ])$")
AUDIO_SUFFIXES = {".wav", ".wave"}


def load_ime_module():
    spec = importlib.util.spec_from_file_location("tangliengim_ime", IME_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load IME module from {IME_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def filename_stem(name: str) -> str:
    return TONE_SUFFIX_RE.sub("", Path(name).stem)


def build_stem_folder_index(ime) -> dict[str, str]:
    stem_to_folder: dict[str, str] = {}
    medials = list(ime.LOMARI_V_TO_RIME.keys())
    finals = list(ime.LOMARI_FINAL_TO_CODA.keys())
    initials = ["ᄋ", "ᅙ", *ime.LOMARI_INITIAL_TO_L.values()]

    seen_initials: set[str] = set()
    for initial in initials:
        if initial not in INITIAL_FOLDERS or initial in seen_initials:
            continue
        seen_initials.add(initial)
        for medial in medials:
            for final in finals:
                if final and medial == "ힻ":
                    continue
                try:
                    unit = ime.compose_syllable(initial, medial, final)
                    stem = ime.audio_lomari_filename_stem(unit, "1")
                except Exception:
                    stem = ""
                if stem:
                    stem_to_folder.setdefault(stem.lower(), INITIAL_FOLDERS[initial])

    # Legacy/current syllabic nasal recordings: ng1.wav is 응, not ㆆ.
    stem_to_folder["ng"] = "ㅇ"
    stem_to_folder["m"] = "ㅇ"
    return stem_to_folder


def classify_audio_file(path: Path, stem_to_folder: dict[str, str]) -> str:
    stem = filename_stem(path.name).lower()
    if stem in stem_to_folder:
        return stem_to_folder[stem]

    if stem == "ng" or stem == "m":
        return "ㅇ"
    if stem.startswith("ng"):
        return "ㆆ"

    for prefix, folder in INITIAL_PREFIXES[1:]:
        if stem.startswith(prefix):
            return folder

    return "ㅇ"


def iter_audio_files(audio_root: Path):
    for path in sorted(audio_root.rglob("*")):
        if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES:
            yield path


def organize_audio_files(dry_run: bool) -> Counter:
    ime = load_ime_module()
    stem_to_folder = build_stem_folder_index(ime)
    counts: Counter[str] = Counter()

    for folder in INITIAL_FOLDERS.values():
        if not dry_run:
            (AUDIO_ROOT / folder).mkdir(parents=True, exist_ok=True)

    for path in iter_audio_files(AUDIO_ROOT):
        if path.parent.name in INITIAL_FOLDERS.values():
            counts[path.parent.name] += 1
            continue

        folder = classify_audio_file(path, stem_to_folder)
        counts[folder] += 1
        destination = AUDIO_ROOT / folder / path.name
        if not dry_run and path.resolve() != destination.resolve():
            if destination.exists():
                raise FileExistsError(f"Destination already exists: {destination}")
            shutil.move(str(path), str(destination))

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="move files instead of dry-run")
    args = parser.parse_args()

    counts = organize_audio_files(dry_run=not args.apply)
    mode = "applied" if args.apply else "dry-run"
    print(f"{mode}: {sum(counts.values())} audio files")
    for folder in INITIAL_FOLDERS.values():
        print(f"{folder}\t{counts[folder]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
