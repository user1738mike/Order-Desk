"""Independent synthetic PDF authoring; no extraction implementation imports."""


def pdf_bytes(pages):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    page_ids = []
    for lines in pages:
        page_id = len(objects) + 1
        page_ids.append(page_id)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {page_id + 1} 0 R >>"
            ).encode()
        )
        commands = [b"BT /F1 10 Tf 14 TL 50 742 Td"]
        for index, line in enumerate(lines):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if index:
                commands.append(b"T*")
            commands.append(b"(" + escaped.encode("ascii") + b") Tj")
        commands.append(b"ET")
        stream = b"\n".join(commands)
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    objects[1] = (
        f"<< /Type /Pages /Count {len(page_ids)} /Kids "
        f"[{' '.join(f'{key} 0 R' for key in page_ids)}] >>"
    ).encode()
    result, offsets = b"%PDF-1.4\n", [0]
    for index, content in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + content + b"\nendobj\n"
    xref = len(result)
    result += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return (
        result
        + (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )


def supported_pdf():
    return pdf_bytes(
        [
            [
                "ORDER DESK TEXT PO v1",
                "SKU | QUANTITY | UNIT | DESCRIPTION",
                "0001.Mixed-Case | 1.234 | each | Synthetic widget",
                "END PAGE 1/1",
            ]
        ]
    )
