"""Shared pytest fixtures."""

import pytest


def _make_pdf(pages: list[list[str]]) -> bytes:
    """Build a minimal PDF with one line of Helvetica text per string, per page.

    Hand-writing the PDF keeps the test free of binary fixtures and PDF-writing
    libraries. Each object's byte offset is recorded for the cross-reference table.
    """
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [%s] /Count %d >>"
        % (b" ".join(b"%d 0 R" % p for p in page_ids), len(pages)),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, lines in zip(page_ids, pages, strict=True):
        ops = b"BT /F1 12 Tf 72 720 Td 14 TL "
        ops += b"".join(b"(%s) Tj T* " % line.encode() for line in lines) + b"ET"
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
            % (page_id + 1)
        )
        objects[page_id + 1] = b"<< /Length %d >>\nstream\n%s\nendstream" % (
            len(ops),
            ops,
        )

    out = b"%PDF-1.4\n"
    offsets = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (obj_id, objects[obj_id])
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offsets[i] for i in sorted(objects))
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return out


@pytest.fixture
def make_pdf():
    """Build a small text-only PDF: make_pdf([["page 1 line", ...], ...]) -> bytes."""
    return _make_pdf
