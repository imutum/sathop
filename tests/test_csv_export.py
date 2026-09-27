"""CSV transport behavior shared by both operator exports."""

import csv
import io
from urllib.parse import unquote

from sathop.orchestrator.api.csv_export import csv_response, encode_csv


def test_csv_round_trip_with_multiline_and_empty_cells():
    row = [None, 1024, '客户,"文件"\n第二行']
    assert list(csv.reader(io.StringIO(encode_csv([row])))) == [["", "1024", row[2]]]


async def test_csv_response_streams_lazily_with_one_bom_and_safe_filename():
    requested = []

    async def chunks():
        for index in range(3):
            requested.append(index)
            yield [[index, "客户"]]

    filename = '客户/交付\r\n".csv'
    response = csv_response(chunks(), filename)
    disposition = response.headers["content-disposition"]
    assert unquote(disposition.split("UTF-8''")[1]) == filename
    assert "\r" not in disposition and "\n" not in disposition
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    stream = response.body_iterator
    assert await anext(stream) == "\ufeff"
    assert requested == []
    assert await anext(stream) == "0,客户\r\n"
    assert requested == [0]
    assert "".join([chunk async for chunk in stream]) == "1,客户\r\n2,客户\r\n"
