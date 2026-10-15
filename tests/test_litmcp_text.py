"""Tests for reading text, finding captions and rendering pages in litmcp/pdfs.py."""

import io

import pdfs
import pytest
from PIL import Image

# --- read_texts ---------------------------------------------------------------


def test_read_texts_feeds_find_captions(tmp_path, make_pdf):
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_pdf([["Body text."], ["Table 1: Results.", "More text."]]))

    captions = pdfs.find_captions(pdfs.read_texts(path))

    assert captions == [
        {"page": 2, "type": "Table", "number": "1", "caption": "Results."}
    ]


# --- find_captions ------------------------------------------------------------


def test_finds_figures_and_tables_with_1_based_pages():
    texts = [
        "Introduction\r\nSome text.",
        "Figure 1: The Transformer - model architecture.\r\nMore text.",
        "Table 2: BLEU scores.",
    ]

    assert pdfs.find_captions(texts) == [
        {
            "page": 2,
            "type": "Figure",
            "number": "1",
            "caption": "The Transformer - model architecture.",
        },
        {"page": 3, "type": "Table", "number": "2", "caption": "BLEU scores."},
    ]


def test_ignores_body_text_mentioning_a_table():
    # Real line from "Attention Is All You Need", p8: no ":" or "." after the number
    texts = ["Table 2 summarizes our results and compares our translation quality"]

    assert pdfs.find_captions(texts) == []


def test_normalises_label_styles():
    texts = ["FIG. 3. Loss curves.\r\nFIGURE 4: Accuracy.\r\nTABLE 5. Ablations."]

    found = [(c["type"], c["number"]) for c in pdfs.find_captions(texts)]

    assert found == [("Figure", "3"), ("Figure", "4"), ("Table", "5")]


# --- render_page --------------------------------------------------------------


def test_render_page_gives_png_of_requested_width(tmp_path, make_pdf):
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_pdf([["Page one"], ["Page two"]]))

    png = pdfs.render_page(path, 2, width=600)

    assert png.startswith(b"\x89PNG\r\n\x1a\n")  # the PNG file signature
    with Image.open(io.BytesIO(png)) as image:
        assert image.width == 600
        # US Letter is 612x792 points, so 600 px wide is ~776.5 px tall (rounded)
        assert abs(image.height - 792 * 600 / 612) <= 1


# --- render_page size limits: untrusted PDFs can declare any page size ----------


def render_size(tmp_path, make_pdf, size, rotate=0, **kwargs) -> tuple[int, int]:
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_pdf([["Text"]], size=size, rotate=rotate))
    with Image.open(io.BytesIO(pdfs.render_page(path, 1, **kwargs))) as image:
        return image.size


def assert_within_limits(width: int, height: int) -> None:
    assert width <= pdfs.PAGE_IMAGE_WIDTH
    assert height <= pdfs.MAX_PAGE_IMAGE_HEIGHT
    assert width * height <= pdfs.MAX_PAGE_IMAGE_PIXELS


def test_tall_thin_page_is_capped_in_height(tmp_path, make_pdf):
    # Fitting 100 x 14400 points to 1200 px wide would be 172,800 px tall
    width, height = render_size(tmp_path, make_pdf, (100, 14400))

    assert_within_limits(width, height)
    assert height >= pdfs.MAX_PAGE_IMAGE_HEIGHT - 1  # scaled to the height cap


def test_extreme_shapes_are_refused_not_rendered(tmp_path, make_pdf):
    with pytest.raises(ValueError, match="too extreme a shape"):
        render_size(tmp_path, make_pdf, (1, 14400))
