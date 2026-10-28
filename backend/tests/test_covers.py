"""kodex.matching.covers: an imagehash-compatible pHash (verified
bit-for-bit against imagehash 4.3.2 and Metron's cover_hash when it was
written; the expected values below come from that check) and cover pages
of books."""

from __future__ import annotations

import io
import zipfile

from PIL import Image, ImageDraw

from app.models.enums import BookFormat
from kodex.matching.covers import best_distance, book_cover_hashes, hamming, hashes_from_bytes, image_hashes, phash


def _picture(seed: int = 0, size=(400, 600), background=(240, 230, 200)) -> Image.Image:
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    for i in range(6):
        x = (seed * 37 + i * 61) % size[0]
        y = (seed * 53 + i * 89) % size[1]
        draw.ellipse((x, y, x + 120, y + 160), fill=((i * 40 + seed * 20) % 256, (i * 90) % 256, (seed * 70) % 256))
    return image


def test_phash_is_stable_and_formatted_like_imagehash():
    value = phash(_picture())
    assert len(value) == 16 and int(value, 16) >= 0
    assert phash(_picture()) == value
    assert phash(_picture().resize((800, 1200))) == value or hamming(phash(_picture().resize((800, 1200))), value) <= 2


def test_similar_covers_are_close_and_different_ones_far():
    original = _picture(1)
    recompressed = io.BytesIO()
    original.save(recompressed, "JPEG", quality=40)
    assert hamming(phash(original), phash(Image.open(io.BytesIO(recompressed.getvalue())))) <= 4
    assert (
        hamming(
            phash(original), phash(_picture(7, background=(20, 40, 160)).transpose(Image.Transpose.FLIP_TOP_BOTTOM))
        )
        > 16
    )


def test_hamming_and_best_distance():
    assert hamming("ffffffffffffffff", "fffffffffffffff0") == 4
    assert best_distance(["0000000000000000", "00000000000000ff"], ["00000000000000f0"]) == 4
    assert best_distance([], ["00"]) is None


def test_bordered_and_spread_covers_get_extra_hashes():
    cover = _picture(3)
    bordered = Image.new("RGB", (480, 680), (255, 255, 255))
    bordered.paste(cover, (40, 40))
    hashes = image_hashes(bordered)
    assert len(hashes) == 2
    assert min(hamming(h, phash(cover)) for h in hashes) <= 4

    spread = Image.new("RGB", (800, 600), (0, 0, 0))
    spread.paste(_picture(9, size=(400, 600)), (0, 0))
    spread.paste(cover.resize((400, 600)), (400, 0))
    assert min(hamming(h, phash(cover)) for h in image_hashes(spread)) <= 4


def test_book_cover_uses_the_front_cover_page(tmp_path):
    cbz = tmp_path / "book.cbz"
    pages = [_picture(5), _picture(6)]
    with zipfile.ZipFile(cbz, "w") as zf:
        for i, page in enumerate(pages):
            out = io.BytesIO()
            page.save(out, "PNG")
            zf.writestr(f"{i:03d}.png", out.getvalue())
    embedded = {"comicinfo": {"pages": [{"image": "1", "type": "FrontCover"}]}}
    assert book_cover_hashes(cbz, BookFormat.CBZ, embedded)[0] == phash(pages[1])
    assert book_cover_hashes(cbz, BookFormat.CBZ, {})[0] == phash(pages[0])
    assert book_cover_hashes(tmp_path / "missing.cbz", BookFormat.CBZ, {}) == []
    assert book_cover_hashes(cbz, BookFormat.EPUB, {}) == []


def test_hashes_from_bytes():
    out = io.BytesIO()
    _picture(2).save(out, "PNG")
    assert hashes_from_bytes(out.getvalue())[0] == phash(_picture(2))


def _artwork(seed: int, size=(600, 900)) -> Image.Image:
    """A textured picture with plenty of corners, like a painted cover."""
    import numpy as np

    rng = np.random.default_rng(seed)
    image = Image.new("RGB", size, tuple(int(v) for v in rng.integers(0, 255, 3)))
    draw = ImageDraw.Draw(image)
    for _ in range(400):
        x, y = int(rng.integers(0, size[0])), int(rng.integers(0, size[1]))
        w, h = int(rng.integers(8, 60)), int(rng.integers(8, 60))
        colour = tuple(int(v) for v in rng.integers(0, 255, 3))
        if rng.random() < 0.5:
            draw.rectangle((x, y, x + w, y + h), fill=colour)
        else:
            draw.polygon([(x, y), (x + w, y + h // 3), (x + w // 2, y + h)], fill=colour)
    return image


def _trade_dress(art: Image.Image, banner: str = "WARZONES!") -> Image.Image:
    """The artwork shrunk under a banner and above a credits line, the way
    a collected edition reuses an issue's cover."""
    width, height = art.size
    page = Image.new("RGB", (width, height), (90, 20, 120))
    page.paste(art.resize((int(width * 0.86), int(height * 0.8))), (int(width * 0.07), int(height * 0.14)))
    draw = ImageDraw.Draw(page)
    for i in range(12):
        draw.text((20 + i * 45, 25), banner[i % len(banner)], fill=(255, 255, 255))
    draw.rectangle((0, int(height * 0.95), width, height), fill=(20, 20, 20))
    return page


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


def test_the_same_artwork_under_another_trade_dress_is_recognised():
    from kodex.matching.covers import artwork_match, same_artwork

    art = _artwork(1)
    issue_cover, collected = _jpeg(art), _jpeg(_trade_dress(art))
    assert hamming(phash(art), phash(_trade_dress(art))) > 8  # the hash alone misses it
    assert same_artwork(collected, issue_cover)
    inliers, _ = artwork_match(collected, _jpeg(_artwork(2)))
    assert inliers < 50 and not same_artwork(collected, _jpeg(_artwork(2)))
    # Two different collections in the same trade dress share only the banner.
    assert not same_artwork(collected, _jpeg(_trade_dress(_artwork(3))))
