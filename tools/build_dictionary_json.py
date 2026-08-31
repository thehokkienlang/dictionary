"""Build web-ready dictionary JSON from data/hokkien_hanri_dict.tsv."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TSV_PATH = REPO_ROOT / "data" / "hokkien_hanri_dict.tsv"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "public" / "data" / "hokkien-hanri-dict.json"
DEFAULT_AUDIO_ROOT = REPO_ROOT / "public" / "audio_files"
TONE_MARKER_PATH = REPO_ROOT / "desktop" / "hokkien_tone_marker_gui.py"
IME_PATH = REPO_ROOT / "desktop" / "Hokkien Tangliengim IME Pad.py"

SCHEMA_VERSION = 1


def load_tone_marker_module():
    spec = importlib.util.spec_from_file_location("tangliengim_tone_marker", TONE_MARKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load tone marker module from {TONE_MARKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_ime_module():
    spec = importlib.util.spec_from_file_location("tangliengim_ime", IME_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load IME module from {IME_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_for_search(value: str) -> str:
    """Lowercase and remove combining marks/punctuation for broad lookup keys."""
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^0-9A-Za-z\u1100-\u11FF\u3130-\u318F\u3400-\u4DBF\u4E00-\u9FFF\U00020000-\U0002EBEF]+", "", plain).lower()


def normalized_reading(tone_marker, value: str) -> str:
    return tone_marker.normalize_tone_symbols_to_digits(
        tone_marker.strip_nonstandard_reading_mark(str(value or "").strip())
    )


def safe_priority(value: str) -> int:
    try:
        return int(str(value or "").strip())
    except Exception:
        return 9999


def row_kind(tone_marker, hanri: str) -> str:
    if tone_marker.field_is_plain_cjk_key(hanri):
        return "plain_hanri"
    if tone_marker.field_is_mixed_hanri_key(hanri):
        return "mixed_hanri"
    if tone_marker.hangul_override_key(hanri):
        return "hangul_override"
    if str(hanri or "").strip().isdigit():
        return "numeric_override"
    return "other"


def reading_to_lomari(tone_marker, reading: str) -> str:
    if not reading:
        return ""
    try:
        return tone_marker.auto_lomari_from_hangul(reading)
    except Exception:
        return ""


def web_path(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def audio_for_reading(ime, audio_root: Path, reading: str) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    files: list[str] = []
    missing: list[str] = []
    seen_files: set[str] = set()
    seen_missing: set[str] = set()

    if not reading:
        return {"segments": segments, "files": files, "missing": missing}

    try:
        audio_units, unknown_hanri = ime.visible_text_to_audio_segments(reading)
    except Exception:
        return {"segments": segments, "files": files, "missing": [reading]}

    raw_segments: list[dict[str, Any]] = []
    for unit, tone, trim_start, trim_end, english_cluster_reduction in audio_units:
        try:
            if ime.is_silent_audio_unit(unit, tone):
                continue
            paths, labels = ime.resolve_audio_files_for_unit(audio_root, unit, tone)
        except Exception:
            paths, labels = [], [f"{unit}{tone}"]

        fallback_parts = ime.split_untoned_hangul_units(unit) if len(paths) > 1 else []
        for idx, path in enumerate(paths):
            try:
                url = web_path(path)
            except ValueError:
                url = str(path).replace("\\", "/")
            if url not in seen_files:
                files.append(url)
                seen_files.add(url)

            segment_unit = fallback_parts[idx] if idx < len(fallback_parts) else unit
            segment_tone = str(tone if (not fallback_parts or idx == len(paths) - 1) else "3")
            raw_segments.append({
                "file": url,
                "unit": segment_unit,
                "tone": segment_tone,
                "trimStart": bool(trim_start or idx > 0),
                "trimEnd": bool(trim_end or idx < len(paths) - 1),
                "lFinal": bool(ime.audio_unit_has_l_final(segment_unit)),
                "shortOverlapFinal": bool(ime.audio_unit_has_short_overlap_final(segment_unit)),
                "englishClusterHelper": bool(english_cluster_reduction),
            })

        for label in labels:
            if label and label not in seen_missing:
                missing.append(label)
                seen_missing.add(label)

    for item in unknown_hanri:
        label = str(item)
        if label and label not in seen_missing:
            missing.append(label)
            seen_missing.add(label)

    speed_all_segments = len(raw_segments) > 1
    for idx, segment in enumerate(raw_segments):
        speed = 1.0
        if speed_all_segments:
            previous_l_final = idx > 0 and bool(raw_segments[idx - 1]["lFinal"])
            next_l_final = idx + 1 < len(raw_segments) and bool(raw_segments[idx + 1]["lFinal"])
            if segment["englishClusterHelper"]:
                speed = float(ime.AUDIO_ENGLISH_CLUSTER_SPEED_FACTOR)
            elif str(segment["tone"]) == "4":
                speed = float(ime.AUDIO_TONE4_SPEED_FACTOR)
            elif segment["lFinal"] and (previous_l_final or next_l_final):
                speed = float(ime.AUDIO_L_FINAL_SPEED_FACTOR)
            else:
                speed = float(ime.AUDIO_MULTI_SYLLABLE_SPEED_FACTOR)
        segment["speed"] = speed
        segments.append(segment)

    return {"segments": segments, "files": files, "missing": missing}


def append_index(index: dict[str, list[str]], key: str, entry_id: str) -> None:
    key = str(key or "")
    if key:
        index.setdefault(key, []).append(entry_id)


def build_dictionary(tsv_path: Path, audio_root: Path = DEFAULT_AUDIO_ROOT) -> dict[str, Any]:
    tone_marker = load_tone_marker_module()
    ime = load_ime_module()
    source_bytes = tsv_path.read_bytes()

    entries: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    duplicate_keys: list[dict[str, Any]] = []
    seen_effective_pairs: dict[tuple[str, str], str] = {}
    counts: Counter[str] = Counter()

    with tsv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = [str(name or "").strip() for name in (reader.fieldnames or [])]
        required = {"reading", "hanri"}
        missing = sorted(required - set(fieldnames))
        if missing:
            raise ValueError(f"TSV is missing required column(s): {', '.join(missing)}")

        for row_number, row in enumerate(reader, start=2):
            raw_reading = str(row.get("reading") or "").strip()
            hanri = str(row.get("hanri") or "").strip()
            priority_text = str(row.get("priority") or "").strip()
            corrected_raw = str(row.get("corrected") or "").strip()

            if not raw_reading and not hanri and not corrected_raw:
                counts["blank_rows"] += 1
                continue

            if raw_reading.startswith("#") and not hanri:
                skipped_rows.append({
                    "row": row_number,
                    "reason": "comment",
                    "text": raw_reading,
                })
                counts["comment_rows"] += 1
                continue

            reading = normalized_reading(tone_marker, raw_reading)
            corrected = normalized_reading(tone_marker, corrected_raw) if corrected_raw else ""
            effective_reading = corrected or reading
            priority = safe_priority(priority_text)
            kind = row_kind(tone_marker, hanri)
            active = bool(hanri and effective_reading)
            skip_reason = ""

            if reading and reading[0].isdigit() and corrected:
                active = False
                skip_reason = "numeric reading with corrected override is skipped by desktop loader"

            entry_id = f"tsv-{row_number:05d}"
            lomari = reading_to_lomari(tone_marker, effective_reading)
            reading_base = tone_marker.strip_reading_tones(effective_reading)
            audio = audio_for_reading(ime, audio_root, effective_reading)
            entry = {
                "id": entry_id,
                "row": row_number,
                "kind": kind,
                "active": active,
                "hanri": hanri,
                "reading": effective_reading,
                "readingBase": reading_base,
                "lomari": lomari,
                "lomariKey": normalize_for_search(lomari),
                "audio": audio,
                "priority": priority,
                "raw": {
                    "reading": raw_reading,
                    "hanri": hanri,
                    "priority": priority_text,
                    "corrected": corrected_raw,
                },
            }
            if corrected:
                entry["correctedFrom"] = reading
            if skip_reason:
                entry["skipReason"] = skip_reason

            pair = (hanri, effective_reading)
            if active and pair in seen_effective_pairs:
                duplicate_keys.append({
                    "firstId": seen_effective_pairs[pair],
                    "duplicateId": entry_id,
                    "hanri": hanri,
                    "reading": effective_reading,
                })
            elif active:
                seen_effective_pairs[pair] = entry_id

            entries.append(entry)
            counts[f"kind_{kind}"] += 1
            counts["active_entries" if active else "inactive_entries"] += 1
            if corrected:
                counts["corrected_entries"] += 1

    entries.sort(key=lambda item: (item["priority"], item["row"], item["reading"], item["hanri"]))

    indexes: dict[str, dict[str, list[str]]] = {
        "byHanri": {},
        "byReading": {},
        "byReadingBase": {},
        "byLomari": {},
        "byLomariKey": {},
        "byFirstHanriChar": {},
    }

    for entry in entries:
        if not entry["active"]:
            continue
        entry_id = entry["id"]
        append_index(indexes["byHanri"], entry["hanri"], entry_id)
        append_index(indexes["byReading"], entry["reading"], entry_id)
        append_index(indexes["byReadingBase"], entry["readingBase"], entry_id)
        append_index(indexes["byLomari"], entry["lomari"], entry_id)
        append_index(indexes["byLomariKey"], entry["lomariKey"], entry_id)
        if entry["hanri"]:
            append_index(indexes["byFirstHanriChar"], entry["hanri"][0], entry_id)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": str(tsv_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "sourceBytes": len(source_bytes),
        "sourceSha256": file_sha256(tsv_path),
        "columns": ["reading", "hanri", "priority", "corrected"],
        "sort": "priority, row, reading, hanri",
        "counts": dict(sorted(counts.items())),
        "skippedRows": skipped_rows,
        "duplicateEffectiveReadings": duplicate_keys,
        "entries": entries,
        "indexes": indexes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_TSV_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--audio-root", type=Path, default=DEFAULT_AUDIO_ROOT)
    parser.add_argument("--check", action="store_true", help="validate only; do not write output")
    args = parser.parse_args()

    data = build_dictionary(args.input, args.audio_root)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"

    if args.check:
        print(f"ok: {len(data['entries'])} entries, {data['counts'].get('active_entries', 0)} active")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    relative_output = args.output.relative_to(REPO_ROOT)
    print(f"wrote {relative_output} ({len(encoded.encode('utf-8'))} bytes)")
    print(f"entries: {len(data['entries'])}; active: {data['counts'].get('active_entries', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
