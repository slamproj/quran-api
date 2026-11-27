#!/usr/bin/env python3
"""
Konversi data Tanzil (format `surah|ayat|teks`) menjadi JSON statis
yang siap di-host di GitHub Pages / Cloudflare Pages.

Pemakaian:
  python build_quran_json.py \
      --arabic quran-uthmani.txt \
      --translation id.indonesian.txt \
      --meta quran-data.xml \
      --out dist

Output:
  dist/index.json              daftar 114 surah
  dist/surah/{n}.json          satu surah lengkap (Arab + terjemahan)
  dist/ayat/{n}/{a}.json       satu ayat (lewati dengan --skip-ayat)
  dist/meta.json               sumber, jumlah, dan checksum SHA-256 file input
"""
import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Jumlah ayat resmi per surah (total 6.236). Dipakai untuk validasi.
AYAH_COUNTS = [
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109,
    123, 111, 43, 52, 99, 128, 111, 110, 98, 135,
    112, 78, 118, 64, 77, 227, 93, 88, 69, 60,
    34, 30, 73, 54, 45, 83, 182, 88, 75, 85,
    54, 53, 89, 59, 37, 35, 38, 29, 18, 45,
    60, 49, 62, 55, 78, 96, 29, 22, 24, 13,
    14, 11, 11, 18, 12, 12, 30, 52, 52, 44,
    28, 28, 20, 56, 40, 31, 50, 40, 46, 42,
    29, 19, 36, 25, 22, 17, 19, 26, 30, 20,
    15, 21, 11, 8, 8, 19, 5, 8, 8, 11,
    11, 8, 3, 9, 5, 4, 7, 3, 6, 3,
    5, 4, 5, 6,
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_tanzil(path: Path) -> dict:
    """Baca file `surah|ayat|teks` -> {(surah, ayat): teks}."""
    data = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            try:
                s, a = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            data[(s, a)] = parts[2].strip()
    return data


def parse_meta(path: Path) -> dict:
    """Baca quran-data.xml (opsional) -> {nomor_surah: info}."""
    meta = {}
    for el in ET.parse(path).getroot().iter("sura"):
        n = int(el.get("index"))
        meta[n] = {
            "name_ar": el.get("name", ""),
            "name_latin": el.get("tname", ""),
            "name_en": el.get("ename", ""),
            "type": el.get("type", ""),
        }
    return meta


def validate(arabic: dict, translation: dict) -> None:
    errors = []
    if len(arabic) != 6236:
        errors.append(f"Total ayat Arab {len(arabic)}, seharusnya 6236")
    if len(translation) != 6236:
        errors.append(f"Total ayat terjemahan {len(translation)}, seharusnya 6236")
    for s, expected in enumerate(AYAH_COUNTS, start=1):
        for a in range(1, expected + 1):
            if not arabic.get((s, a)):
                errors.append(f"Arab kosong/hilang: {s}:{a}")
            if not translation.get((s, a)):
                errors.append(f"Terjemahan kosong/hilang: {s}:{a}")
        extra = [k for k in arabic if k[0] == s and k[1] > expected]
        if extra:
            errors.append(f"Surah {s} punya ayat berlebih: {extra[:3]}")
    if errors:
        print("VALIDASI GAGAL:", file=sys.stderr)
        for e in errors[:20]:
            print(" -", e, file=sys.stderr)
        if len(errors) > 20:
            print(f" ... dan {len(errors) - 20} masalah lain", file=sys.stderr)
        sys.exit(1)
    print("Validasi OK: 114 surah, 6.236 ayat, tidak ada yang kosong.")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--arabic", required=True, type=Path)
    p.add_argument("--translation", required=True, type=Path)
    p.add_argument("--meta", type=Path, help="quran-data.xml dari Tanzil (opsional)")
    p.add_argument("--out", type=Path, default=Path("dist"))
    p.add_argument("--skip-ayat", action="store_true", help="jangan buat file per ayat")
    args = p.parse_args()

    arabic = parse_tanzil(args.arabic)
    translation = parse_tanzil(args.translation)
    validate(arabic, translation)

    meta = parse_meta(args.meta) if args.meta else {}

    index = []
    for s, count in enumerate(AYAH_COUNTS, start=1):
        info = {"number": s, **meta.get(s, {}), "ayah_count": count}
        index.append(info)

        ayat = [
            {"number": a, "arabic": arabic[(s, a)], "translation": translation[(s, a)]}
            for a in range(1, count + 1)
        ]
        write_json(args.out / "surah" / f"{s}.json", {**info, "ayat": ayat})

        if not args.skip_ayat:
            for item in ayat:
                write_json(
                    args.out / "ayat" / str(s) / f"{item['number']}.json",
                    {"surah": s, **item},
                )

    write_json(args.out / "index.json", index)
    write_json(
        args.out / "meta.json",
        {
            "total_surah": 114,
            "total_ayat": 6236,
            "sources": {
                "arabic": {"file": args.arabic.name, "sha256": sha256(args.arabic)},
                "translation": {"file": args.translation.name, "sha256": sha256(args.translation)},
            },
        },
    )
    print(f"Selesai. Output ada di: {args.out.resolve()}")


if __name__ == "__main__":
    main()
