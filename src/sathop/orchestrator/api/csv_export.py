"""Shared CSV encoding and download headers for operator reports."""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterable, Iterable, Sequence
from urllib.parse import quote

from fastapi.responses import StreamingResponse

CsvRows = Iterable[Sequence[object]]


def encode_csv(rows: CsvRows) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    for row in rows:
        cells = []
        for value in row:
            text = "" if value is None else str(value)
            # Quoting alone does not stop spreadsheet formula evaluation.
            if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
                text = "'" + text
            cells.append(text)
        writer.writerow(cells)
    return buf.getvalue()


def csv_response(chunks: AsyncIterable[CsvRows], filename: str) -> StreamingResponse:
    async def stream():
        yield "\ufeff"  # Excel needs the BOM to recognize Chinese text as UTF-8.
        async for rows in chunks:
            yield encode_csv(rows)

    return StreamingResponse(
        stream(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "Cache-Control": "no-store",
        },
    )
