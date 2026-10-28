"""
Batch-konverterar seriearkiv (CBZ/CBR/ZIP/RAR) till bildmappar (image_folder).
Kodex stödjer image_folder-formatet direkt — inga extra verktyg behövs för
att läsa bildmappar vs. paketerade arkiv.

Användning:
    python convert_to_folders.py /data/comics
    python convert_to_folders.py /data/comics --dry-run          # förhandsgranskning
    python convert_to_folders.py /data/comics --delete-originals  # ta bort arkiv efter extrahering
    python convert_to_folders.py /data/comics --zip-only         # byt bara .zip → .cbz (ingen extrahering)

Vad skriptet gör:
    1. Letar rekursivt efter .cbz / .zip / .cbr / .rar i målmappen.
    2. Skapar en undermapp med samma namn som arkivet (utan ändelsen).
    3. Extraherar alla bildfiler dit.
    4. Tar valfritt bort originalarkivet om --delete-originals anges.

Alternativet --zip-only byter bara filändelse .zip → .cbz och .rar → .cbr
utan att extrahera innehållet — användbart om skannern redan hanterar arkiv
men filerna har fel ändelse.
"""

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".tif", ".tiff"}


def is_rar(path: Path) -> bool:
    """Kolla RAR-magic bytes istället för att lita på filändelsen."""
    try:
        with open(path, "rb") as f:
            return f.read(7) in (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01")
    except OSError:
        return False


def extract_zip(archive: Path, dest: Path, dry_run: bool) -> int:
    """Extraherar ZIP/CBZ. Returnerar antal extraherade bildfiler."""
    if dry_run:
        try:
            with zipfile.ZipFile(archive) as zf:
                count = sum(1 for n in zf.namelist() if Path(n).suffix.lower() in IMAGE_EXTENSIONS)
            print(f"  [dry] skulle extrahera {count} bilder → {dest.name}/")
            return count
        except zipfile.BadZipFile:
            print(f"  [varning] inte ett giltigt ZIP-arkiv: {archive.name}", file=sys.stderr)
            return 0

    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                if Path(member.filename).suffix.lower() in IMAGE_EXTENSIONS:
                    # Platta ut mapphierarkin — alla bilder hamnar direkt i dest/
                    target = dest / Path(member.filename).name
                    with zf.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    count += 1
    except zipfile.BadZipFile:
        print(f"  [varning] inte ett giltigt ZIP-arkiv: {archive.name}", file=sys.stderr)
        shutil.rmtree(dest, ignore_errors=True)
        return 0
    return count


def extract_rar(archive: Path, dest: Path, dry_run: bool) -> int:
    """Extraherar RAR/CBR med rarfile-biblioteket (pip install rarfile)."""
    try:
        import rarfile  # type: ignore
    except ImportError:
        print(
            f"  [skip] {archive.name} — rarfile-paketet saknas.\n"
            "  Installera med: pip install rarfile\n"
            "  (kräver också att unrar.exe finns i PATH: https://www.rarlab.com/rar_add.htm)",
            file=sys.stderr,
        )
        return 0

    if dry_run:
        try:
            with rarfile.RarFile(archive) as rf:
                count = sum(1 for n in rf.namelist() if Path(n).suffix.lower() in IMAGE_EXTENSIONS)
            print(f"  [dry] skulle extrahera {count} bilder → {dest.name}/")
            return count
        except Exception as e:  # noqa: BLE001 - one bad archive must not stop the batch
            print(f"  [varning] {archive.name}: {e}", file=sys.stderr)
            return 0

    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        with rarfile.RarFile(archive) as rf:
            for member in rf.infolist():
                if Path(member.filename).suffix.lower() in IMAGE_EXTENSIONS:
                    target = dest / Path(member.filename).name
                    with rf.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    count += 1
    except Exception as e:  # noqa: BLE001 - one bad archive must not stop the batch
        print(f"  [varning] {archive.name}: {e}", file=sys.stderr)
        shutil.rmtree(dest, ignore_errors=True)
        return 0
    return count


def rename_extension(archive: Path, new_ext: str, dry_run: bool) -> Path:
    target = archive.with_suffix(new_ext)
    if target.exists():
        print(f"  [skip] mål finns redan: {target.name}")
        return archive
    if dry_run:
        print(f"  [dry] {archive.name} → {target.name}")
        return archive
    archive.rename(target)
    print(f"  Bytte namn: {archive.name} → {target.name}")
    return target


def process_directory(root: Path, dry_run: bool, delete_originals: bool, zip_only: bool) -> None:
    archives = sorted(
        p for p in root.rglob("*") if p.suffix.lower() in {".cbz", ".zip", ".cbr", ".rar"} and p.is_file()
    )

    if not archives:
        print("Inga arkivfiler hittades.")
        return

    print(f"Hittade {len(archives)} arkiv under {root}\n")

    for archive in archives:
        suffix = archive.suffix.lower()
        print(f"{archive.relative_to(root)}")

        if zip_only:
            if suffix == ".zip":
                rename_extension(archive, ".cbz", dry_run)
            elif suffix == ".rar" and is_rar(archive):
                rename_extension(archive, ".cbr", dry_run)
            else:
                print("  [skip] redan rätt ändelse")
            continue

        # Bestäm extraktionsmapp — samma plats och namn som arkivet, utan ändelsen
        dest = archive.parent / archive.stem

        if dest.exists() and any(dest.iterdir()):
            print(f"  [skip] målmappen finns redan och är inte tom: {dest.name}/")
            continue

        if suffix in {".cbz", ".zip"}:
            count = extract_zip(archive, dest, dry_run)
        elif suffix in {".cbr", ".rar"} and is_rar(archive):
            count = extract_rar(archive, dest, dry_run)
        else:
            print("  [skip] okänt format eller inte ett riktigt RAR-arkiv")
            continue

        if count == 0:
            continue

        if not dry_run:
            print(f"  Extraherade {count} bilder → {dest.name}/")

        if delete_originals and not dry_run and count > 0:
            archive.unlink()
            print(f"  Raderade: {archive.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Konverterar seriearkiv till bildmappar för Kodex.")
    parser.add_argument("directory", help="Rotkatalog att bearbeta (t.ex. /data/comics)")
    parser.add_argument("--dry-run", action="store_true", help="Visa vad som skulle göras utan att ändra något")
    parser.add_argument("--delete-originals", action="store_true", help="Ta bort arkivet efter lyckad extrahering")
    parser.add_argument("--zip-only", action="store_true", help="Byt bara .zip→.cbz och .rar→.cbr, extrahera inte")
    args = parser.parse_args()

    root = Path(args.directory)
    if not root.is_dir():
        print(f"Fel: {root} är inte en giltig katalog.", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("=== DRY RUN — inga filer ändras ===\n")

    process_directory(root, args.dry_run, args.delete_originals, args.zip_only)


if __name__ == "__main__":
    main()
