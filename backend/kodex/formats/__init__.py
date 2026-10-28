"""Archives (CBZ, CBR, CB7), EPUB, PDF and image folders: page extraction
with caching, ComicInfo/MetronInfo/OPF/series.json reading and writing,
and content identity. Replaces app/scanning/archive.py and parsers.
"""

from PIL import Image

# Pillow refuses images above this many pixels (a decompression bomb inside
# an otherwise small file). A two-page spread at 600 dpi is about 60 MP.
Image.MAX_IMAGE_PIXELS = 200_000_000
