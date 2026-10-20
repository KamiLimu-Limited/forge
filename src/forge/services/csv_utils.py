"""CSV rendering for exports."""

import csv
import io
from collections.abc import Iterable


def to_csv(header: list[str], rows: Iterable[Iterable[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()
