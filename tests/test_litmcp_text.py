"""Tests for reading text, finding captions and rendering pages in litmcp/pdfs.py."""

import io

import pdfs
import pytest
from PIL import Image

# --- read_texts ---------------------------------------------------------------


def test_read_texts_returns_one_string_per_page(tmp_path, make_pdf):
    path = tmp_path / "paper.pdf"
    path.write_bytes(
        make_pdf([["Introduction", "Some text."], ["Figure 1: A diagram."]])
    )

    texts = pdfs.read_texts(path)

    assert len(texts) == 2
    assert "Introduction" in texts[0]
    assert "Figure 1: A diagram." in texts[1]


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


def test_ignores_mentions_mid_line():
    texts = ["As shown in Figure 3: the loss decreases."]

    assert pdfs.find_captions(texts) == []


def test_normalises_label_styles():
    texts = ["FIG. 3. Loss curves.\r\nFIGURE 4: Accuracy.\r\nTABLE 5. Ablations."]

    found = [(c["type"], c["number"]) for c in pdfs.find_captions(texts)]

    assert found == [("Figure", "3"), ("Figure", "4"), ("Table", "5")]


def test_supplementary_numbers():
    texts = ["Figure S1: Extra results.\r\nfigure s2. More."]

    assert [c["number"] for c in pdfs.find_captions(texts)] == ["S1", "S2"]


def test_no_carriage_returns_or_padding_in_captions():
    texts = ["  Figure 1:   Spaced out caption.   \r\nNext line."]

    assert pdfs.find_captions(texts)[0]["caption"] == "Spaced out caption."


def test_repeated_caption_keeps_first_page():
    texts = ["Table 2: Results.", "Table 2: Results (continued)."]

    captions = pdfs.find_captions(texts)

    assert len(captions) == 1
    assert captions[0]["page"] == 1


def test_fig_and_figure_are_the_same_figure():
    texts = ["Fig. 1. Overview.", "Figure 1: Overview, repeated."]

    assert len(pdfs.find_captions(texts)) == 1


def test_long_captions_are_capped():
    texts = ["Figure 1: " + "word " * 100]

    caption = pdfs.find_captions(texts)[0]["caption"]

    assert len(caption) <= pdfs.MAX_CAPTION_CHARS


def test_no_text_gives_no_captions():
    # Scanned PDFs have no text layer, so every page is empty
    assert pdfs.find_captions(["", ""]) == []


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


def test_render_page_rejects_pages_outside_document(tmp_path, make_pdf):
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_pdf([["Only page"]]))

    for page in (0, 2):
        with pytest.raises(ValueError, match="this paper has 1 pages"):
            pdfs.render_page(path, page)
