"""Shared report labels for the web preview and Word export."""
from __future__ import annotations

import re


TABLE_CAPTION = re.compile(r"^表\s*\d+(?:\s+|[.．、:：]\s*)(.+)$")


def normalize_table_captions(markdown: str) -> str:
    """Keep table titles immediately above tables and number them in order."""
    lines = markdown.splitlines()
    output: list[str] = []
    section = "项目资料"
    count, index = 0, 0
    while index < len(lines):
        line = lines[index]
        heading = re.match(r"^#{2,3}\s+(.+)", line.strip())
        if heading:
            section = heading[1].strip()
        if line.lstrip().startswith("|") and index + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[index + 1]):
            count += 1
            previous = next((i for i in range(len(output) - 1, -1, -1) if output[i].strip()), None)
            caption = TABLE_CAPTION.fullmatch(output[previous].strip().strip("*")) if previous is not None else None
            title = caption[1] if caption else section
            if caption:
                del output[previous:]
            output.extend([f"表{count} {title}", ""])
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                output.append(lines[index])
                index += 1
            continue
        output.append(line)
        index += 1
    return "\n".join(output) + ("\n" if markdown.endswith("\n") else "")
