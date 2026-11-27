#!/usr/bin/env python3
"""
Konversi data Tanzil (format `surah|ayat|teks`) menjadi JSON statis
yang siap di-host di GitHub Pages / Cloudflare Pages.

Pemakaian:
  python build_quran_json.py \
      --arabic quran-uthmani.txt \
      --translation id.indonesian.txt \
      --meta quran-data.xml \
      --out docs

Output:
  docs/index.json              daftar 114 surah (+ start_page jika --meta ada)
  docs/surah/{n}.json          satu surah lengkap (Arab + terjemahan)
  docs/page/{n}.json           satu halaman Mushaf Madinah, 604 halaman (butuh --meta)
  docs/juz.json                halaman awal tiap juz, 30 angka (butuh --meta)
  docs/ayat/{n}/{a}.json       satu ayat (lewati dengan --skip-ayat)
  docs/meta.json               sumber, jumlah, dan checksum SHA-256 file input
"""
import argparse
import bisect
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TOTAL_PAGES = 604

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

ALL_KEYS = [(s, a) for s, c in enumerate(AYAH_COUNTS, start=1) for a in range(1, c + 1)]
POS = {k: i for i, k in enumerate(ALL_KEYS)}


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


def parse_partitions(path: Path):
    """Baca titik awal halaman dan juz dari quran-data.xml.
    Mengembalikan (pages, juzs): masing-masing list [(surah, ayat), ...]."""
    root = ET.parse(path).getroot()

    def collect(tag):
        items = []
        for el in root.iter(tag):
            idx, s, a = el.get("index"), el.get("sura"), el.get("aya")
            if idx and s and a:
                items.append((int(idx), int(s), int(a)))
        items.sort()
        return [(s, a) for _, s, a in items]

    return collect("page"), collect("juz")


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


def validate_pages(pages: list, juzs: list) -> None:
    errors = []
    if len(pages) != TOTAL_PAGES:
        errors.append(f"Jumlah halaman {len(pages)}, seharusnya {TOTAL_PAGES}")
    elif pages[0] != (1, 1):
        errors.append(f"Halaman 1 harus mulai di 1:1, ditemukan {pages[0]}")
    if juzs and len(juzs) != 30:
        errors.append(f"Jumlah juz {len(juzs)}, seharusnya 30")
    for s, a in pages + juzs:
        if not (1 <= s <= 114 and 1 <= a <= AYAH_COUNTS[s - 1]):
            errors.append(f"Titik awal tidak valid: {s}:{a}")
    if not errors:
        if pages != sorted(pages) or len(set(pages)) != len(pages):
            errors.append("Urutan halaman tidak naik secara ketat")
    if errors:
        print("VALIDASI HALAMAN GAGAL:", file=sys.stderr)
        for e in errors[:20]:
            print(" -", e, file=sys.stderr)
        sys.exit(1)
    print(f"Validasi halaman OK: {len(pages)} halaman, {len(juzs)} juz.")


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
    p.add_argument("--meta", type=Path, help="quran-data.xml dari Tanzil (nama surah + halaman)")
    p.add_argument("--out", type=Path, default=Path("dist"))
    p.add_argument("--skip-ayat", action="store_true", help="jangan buat file per ayat")
    args = p.parse_args()

    arabic = parse_tanzil(args.arabic)
    translation = parse_tanzil(args.translation)
    validate(arabic, translation)

    meta = parse_meta(args.meta) if args.meta else {}

    pages, juzs = ([], [])
    if args.meta:
        pages, juzs = parse_partitions(args.meta)
        if pages:
            validate_pages(pages, juzs)
        else:
            print("Peringatan: data halaman tidak ditemukan di file meta, halaman dilewati.")

    page_pos = [POS[k] for k in pages]
    juz_pos = [POS[k] for k in juzs]

    def ayah_obj(s, a):
        return {"surah": s, "number": a, "arabic": arabic[(s, a)], "translation": translation[(s, a)]}

    index = []
    for s, count in enumerate(AYAH_COUNTS, start=1):
        info = {"number": s, **meta.get(s, {}), "ayah_count": count}
        if page_pos:
            info["start_page"] = bisect.bisect_right(page_pos, POS[(s, 1)])
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

    if pages:
        for i in range(TOTAL_PAGES):
            start = page_pos[i]
            end = page_pos[i + 1] if i + 1 < TOTAL_PAGES else len(ALL_KEYS)
            page_obj = {"page": i + 1}
            if juz_pos:
                page_obj["juz"] = bisect.bisect_right(juz_pos, start)
            page_obj["ayat"] = [ayah_obj(s, a) for s, a in ALL_KEYS[start:end]]
            write_json(args.out / "page" / f"{i + 1}.json", page_obj)

        if juz_pos:
            # Halaman awal tiap juz (30 angka), untuk fitur lompat ke juz.
            write_json(args.out / "juz.json", [bisect.bisect_right(page_pos, jp) for jp in juz_pos])

    write_json(args.out / "index.json", index)
    meta_obj = {
        "total_surah": 114,
        "total_ayat": 6236,
        "sources": {
            "arabic": {"file": args.arabic.name, "sha256": sha256(args.arabic)},
            "translation": {"file": args.translation.name, "sha256": sha256(args.translation)},
        },
    }
    if pages:
        meta_obj["total_pages"] = TOTAL_PAGES
    write_json(args.out / "meta.json", meta_obj)
    print(f"Selesai. Output ada di: {args.out.resolve()}")


if __name__ == "__main__":
    main()
