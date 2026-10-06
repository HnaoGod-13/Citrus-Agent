"""Create report figures from explicit, auditable report data.

The renderer never fetches images, executes chart descriptions, or guesses values.
The returned image manifest is the only source of images accepted by the export.
"""
from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageColor


WIDTH = 1800
INK = "#203247"
MUTED = "#54657A"
GRID = "#DFE7F0"
# A shared blue/gold palette keeps comparisons, process lanes and schedules
# visually consistent. Labels and positions carry meaning independently of hue.
PALETTE = (
    ("#2D679F", "#F0F5FB", "#8AB4DD"),
    ("#3B729F", "#F0F5F9", "#A2BED6"),
    ("#AB7115", "#FCF5E8", "#F0C16D"),
)
ACCENT = PALETTE[0][0]
BLUE = ("#2D679F", "#91BCE7", "#5F91C2")
GOLD = ("#A96C0C", "#F8D183", "#DBA33F")
_VISUAL_THEMES = {
    "industry": {"primary": "#1D7A63", "light": "#DDF3EA", "accent": "#D47B28", "ink": "#153A35"},
    "cold_chain": {"primary": "#2D679F", "light": "#E5F0FB", "accent": "#46A6A1", "ink": "#203247"},
    "quality": {"primary": "#167C80", "light": "#E1F3F1", "accent": "#D28A2E", "ink": "#173E43"},
    "market": {"primary": "#294C8C", "light": "#E7EDFA", "accent": "#D07A35", "ink": "#1F3152"},
    "default": {"primary": BLUE[0], "light": "#F0F5FB", "accent": GOLD[0], "ink": INK},
}
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_VALUE = re.compile(rf"^(?:约\s*)?({_NUMBER})$")
_REFERENCE = re.compile(r"\[(\d+)\]")
_FLOW = re.compile(r"^工艺流程\s*[：:]\s*(.+)$")
_PERIOD = re.compile(r"^第\s*(\d+)\s*(?:月\s*)?(?:至|到|—|–|-|~|～)\s*(?:第\s*)?(\d+)\s*(?:个)?月$")
_SINGLE_MONTH = re.compile(r"^第\s*(\d+)\s*(?:个)?月$")


class _Fonts:
    """Use separate Chinese and Latin fonts, including on the chart canvas."""

    def __init__(self) -> None:
        self.cjk = self._find(
            "REPORT_CHART_CJK_FONT",
            ["C:/Windows/Fonts/simsun.ttc", "/usr/share/fonts/truetype/arphic/uming.ttc",
             "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"],
        )
        self.latin = self._find(
            "REPORT_CHART_LATIN_FONT",
            ["C:/Windows/Fonts/times.ttf", "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf",
             "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
        )
        self.cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
        self.ink_cache: dict[tuple[str, int], tuple[float, float, float, float]] = {}

    @staticmethod
    def _find(variable: str, candidates: list[str]) -> str:
        override = os.environ.get(variable)
        paths = [override] if override else candidates
        for candidate in paths:
            if candidate and Path(candidate).is_file():
                return candidate
        raise RuntimeError(f"报告图表缺少字体文件，请通过 {variable} 配置可用字体。")

    def get(self, character: str, size: int) -> ImageFont.FreeTypeFont:
        family = self.latin if ord(character) < 256 else self.cjk
        key = (family, size)
        if key not in self.cache:
            self.cache[key] = ImageFont.truetype(family, size=size)
        return self.cache[key]

    def measure(self, text: str, size: int) -> float:
        return sum(font.getlength(run) for run, font in self.runs(text, size))

    def runs(self, text: str, size: int) -> list[tuple[str, ImageFont.FreeTypeFont]]:
        runs: list[tuple[str, ImageFont.FreeTypeFont]] = []
        for char in text:
            # Use the Latin face for western punctuation as well as digits.
            font = self.get(char if char not in "—–−·" else "-", size)
            if runs and runs[-1][1] is font:
                runs[-1] = (runs[-1][0] + char, font)
            else:
                runs.append((char, font))
        return runs

    def bounds(self, text: str, size: int) -> tuple[float, float, float, float]:
        """Measure the union of mixed-font runs on one common baseline."""
        key = text, size
        if key in self.ink_cache:
            return self.ink_cache[key]
        x, boxes = 0.0, []
        for run, font in self.runs(text, size):
            mask, offset = font.getmask2(run, mode="L", anchor="ls")
            ink = mask.getbbox()
            if ink is not None:
                left, top, right, bottom = ink
                boxes.append((x + offset[0] + left, offset[1] + top, x + offset[0] + right, offset[1] + bottom))
            x += font.getlength(run)
        if not boxes:
            return 0, 0, 0, 0
        result = min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)
        self.ink_cache[key] = result
        return result

    def write(self, draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
              size: int = 44, fill: str = INK, align: str = "left",
              valign: str = "top") -> tuple[float, float, float, float]:
        x, y = xy
        left, top, right, bottom = self.bounds(text, size)
        if align == "center":
            x -= (left + right) / 2
        elif align == "right":
            x -= right
        else:
            x -= left
        baseline = y - ((top + bottom) / 2 if valign == "middle" else top)
        bounds = (x + left, baseline + top, x + right, baseline + bottom)
        for run, font in self.runs(text, size):
            draw.text((x, baseline), run, font=font, fill=fill, anchor="ls")
            x += font.getlength(run)
        return bounds

    def wrap(self, text: str, max_width: float, size: int = 44) -> list[str]:
        if "\n" in text:
            return [line for part in text.split("\n") for line in self.wrap(part, max_width, size)]
        if self.measure(text, size) <= max_width:
            return [text]
        greedy, current = [], ""
        for char in text:
            if current and self.measure(current + char, size) > max_width:
                greedy.append(current)
                current = ""
            current += char
        if current:
            greedy.append(current)
        target = self.measure(text, size) / len(greedy)

        @lru_cache(maxsize=None)
        def balanced(start: int, remaining: int):
            if remaining == 0:
                return (0.0, []) if start == len(text) else (math.inf, [])
            best = (math.inf, [])
            for end in range(start + 1, len(text) + 1):
                line = text[start:end]
                width = self.measure(line, size)
                if width > max_width:
                    break
                if end < len(text) and text[end - 1].isascii() and text[end - 1].isalnum() and text[end].isascii() and text[end].isalnum():
                    continue
                cost, tail = balanced(end, remaining - 1)
                cost += (width - target) ** 2
                if len(line.strip()) == 1:
                    cost += size ** 2 * 12
                if line[0] in "，。、：；）)]":
                    cost += size ** 2 * 20
                if end < len(text) and text[end] in "与及和或":
                    cost -= size ** 2 * .35
                if cost < best[0]:
                    best = cost, [line, *tail]
            return best

        cost, lines = balanced(0, len(greedy))
        return lines if math.isfinite(cost) else greedy


def _png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(300, 300), optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _cells(line: str) -> list[str]:
    return [re.sub(r"\*\*|__", "", cell.strip()) for cell in line.strip().strip("|").split("|")]


def _table(lines: list[str], start: int) -> tuple[list[str], list[list[str]], int] | None:
    if start + 1 >= len(lines) or not lines[start].lstrip().startswith("|"):
        return None
    header = _cells(lines[start])
    separators = _cells(lines[start + 1])
    if len(separators) != len(header) or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separators):
        return None
    end = start + 2
    rows = []
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        cells = _cells(lines[end])
        if len(cells) != len(header):
            return None
        rows.append(cells)
        end += 1
    return header, rows, end


def _source_supports(source: dict[str, Any], value: Decimal, unit: str,
                     *, approximate: bool, years: set[str]) -> bool:
    if not isinstance(source, dict):
        return False
    text = "\n".join(str(source.get(key) or "") for key in ("snippet", "content", "abstract"))
    pattern = re.compile(rf"(?<![\d.,+\-A-Za-z])({_NUMBER})\s*{re.escape(unit)}(?![A-Za-z])")
    for sentence in re.split(r"[。；;！？!?\n]", text):
        for match in pattern.finditer(sentence):
            if Decimal(match.group(1).replace(",", "")) != value:
                continue
            prefix = sentence[:match.start()].rstrip()
            if re.search(r"(?:超过|超|逾|不足|不超过|至少|不低于|近)$", prefix):
                continue
            if re.search(r"约$", prefix) and not approximate:
                continue
            if years:
                preceding = re.findall(r"((?:19|20)\d{2})\s*年", prefix)
                following = re.findall(r"((?:19|20)\d{2})\s*年", sentence[match.end():])
                linked_year = preceding[-1] if preceding else (following[0] if following else None)
                if years != {linked_year}:
                    continue
            return True
    return False


def _numeric_data(header: list[str], rows: list[list[str]], sources: list[dict[str, Any]]) -> dict | None:
    if header != ["指标", "数值", "单位", "统计口径", "来源"] or not 2 <= len(rows) <= 8:
        return None
    data = []
    units: set[str] = set()
    for label, raw_value, unit, scope, citation in rows:
        parsed = _VALUE.fullmatch(raw_value)
        if not parsed or not label or not scope or not unit or len(label) > 50 or len(scope) > 80 or len(unit) > 16:
            return None
        try:
            value = Decimal(parsed.group(1).replace(",", ""))
        except InvalidOperation:
            return None
        if not value.is_finite() or value < 0 or not math.isfinite(float(value)):
            return None
        refs = [int(item) for item in _REFERENCE.findall(citation)]
        if not refs or any(ref < 1 or ref > len(sources) for ref in refs):
            return None
        years = set(re.findall(r"((?:19|20)\d{2})\s*年", label + " " + scope))
        if not any(_source_supports(sources[ref - 1], value, unit, approximate=raw_value.startswith("约"), years=years) for ref in refs):
            return None
        units.add(unit)
        data.append({"label": label, "value": float(value), "display_value": raw_value,
                     "unit": unit, "scope": scope, "references": sorted(set(refs))})
    if len(units) != 1:
        return None
    return {"unit": next(iter(units)), "rows": data}


def _gantt_data(header: list[str], rows: list[list[str]]) -> dict | None:
    if "阶段" not in header or not 2 <= len(rows) <= 10:
        return None
    period = next((name for name in ("计划周期", "示例周期") if name in header), None)
    if period is None:
        return None
    stage_index, period_index = header.index("阶段"), header.index(period)
    data = []
    for row in rows:
        stage, raw_period = row[stage_index], row[period_index]
        match = _PERIOD.fullmatch(raw_period)
        single = _SINGLE_MONTH.fullmatch(raw_period)
        if not stage or len(stage) > 60 or not (match or single):
            return None
        start, end = (int(match.group(1)), int(match.group(2))) if match else (int(single.group(1)), int(single.group(1)))
        if not 1 <= start <= end <= 60:
            return None
        data.append({"stage": stage, "start_month": start, "end_month": end})
    return {"rows": data, "period_label": period}


def _text_block(draw: ImageDraw.ImageDraw, fonts: _Fonts, lines: list[str],
                box: tuple[float, float, float, float], *, size: int = 44,
                fill: str = INK, align: str = "center") -> None:
    """Center a whole text block using its measured baseline bounds."""
    x0, y0, x1, y1 = box
    leading = size * 1.30
    bounds = [fonts.bounds(line, size) for line in lines]
    top = min(b[1] + i * leading for i, b in enumerate(bounds))
    bottom = max(b[3] + i * leading for i, b in enumerate(bounds))
    baseline = (y0 + y1 - top - bottom) / 2
    x = (x0 + x1) / 2 if align == "center" else x0
    for i, (line, bound) in enumerate(zip(lines, bounds)):
        fonts.write(draw, (x, baseline + i * leading + bound[1]), line, size=size, fill=fill, align=align)


def _scale(maximum: float) -> tuple[float, float]:
    target = (maximum or 1) / 4
    power = 10 ** math.floor(math.log10(target))
    step = next(value * power for value in (1, 2, 2.5, 5, 10) if value * power >= target)
    return math.ceil((maximum or 1) * 1.08 / step) * step, step


def _dashed(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float],
            *, fill: str = GRID, width: int = 2, dash: int = 10, gap: int = 7) -> None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if not length:
        return
    for offset in range(0, math.ceil(length), dash + gap):
        stop = min(offset + dash, length)
        draw.line((start[0] + dx * offset / length, start[1] + dy * offset / length,
                   start[0] + dx * stop / length, start[1] + dy * stop / length), fill=fill, width=width)


def _gradient_shape(image: Image.Image, box: tuple[float, float, float, float],
                    light: str, dark: str, *, radius: int = 18,
                    square_base: str | None = None) -> None:
    """A true clipped gradient; a square zero-end preserves the numeric baseline."""
    x0, y0, x1, y1 = (round(value) for value in box)
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        return
    radius = min(radius, width // 2, height // 2)
    mask = Image.new("L", (width, height))
    pen = ImageDraw.Draw(mask)
    pen.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    if square_base == "bottom":
        pen.rectangle((0, max(0, height - radius - 1), width - 1, height - 1), fill=255)
    elif square_base == "left":
        pen.rectangle((0, 0, radius + 1, height - 1), fill=255)
    top, bottom = ImageColor.getrgb(light), ImageColor.getrgb(dark)
    gradient = Image.new("RGB", (1, height))
    gradient.putdata([tuple(round(a + (b - a) * y / max(1, height - 1)) for a, b in zip(top, bottom)) for y in range(height)])
    image.paste(gradient.resize((width, height)), (x0, y0), mask)


def _series_color(index: int, count: int) -> tuple[str, str, str]:
    # For a multi-period series, blue is the comparison baseline and gold
    # emphasizes the final observation, without implying extra data categories.
    return GOLD if count > 1 and index == count - 1 else BLUE


def _theme_for(data: dict[str, Any]) -> dict[str, str]:
    """Return the semantic theme selected by the content planner."""
    name = str(data.get("_theme") or "default")
    return _VISUAL_THEMES.get(name, _VISUAL_THEMES["default"])


def _year_labels(rows: list[dict[str, Any]]) -> list[str] | None:
    """Extract a comparable year axis without interpreting arbitrary labels."""
    years: list[str] = []
    for row in rows:
        match = re.fullmatch(r"\s*((?:19|20)\d{2})年(?:.*)?\s*", str(row.get("label") or ""))
        if not match:
            return None
        years.append(match.group(1))
    return years if len(years) >= 3 and len(set(years)) == len(years) else None


def _trend(data: dict, fonts: _Fonts) -> str:
    """Render a time series as a publication-style line chart.

    This is deliberately data-driven: the planner only selects this renderer
    when every row has a distinct year label. It never invents an interpolation
    or a missing observation.
    """
    rows = data["rows"]
    years = _year_labels(rows) or [str(row.get("label") or "") for row in rows]
    limit, step = _scale(max(row["value"] for row in rows))
    theme = _theme_for(data)
    image = Image.new("RGB", (WIDTH, 930), "white")
    draw = ImageDraw.Draw(image)
    x0, x1, y0, y1 = 165, 1715, 158, 735
    fonts.write(draw, (x0, 44), f'{data.get("metric") or "数值"}（{data["unit"]}）', size=50, fill=theme["ink"])
    for i in range(round(limit / step) + 1):
        value = i * step
        y = y1 - (y1 - y0) * value / limit
        _dashed(draw, (x0, y), (x1, y), fill=GRID)
        fonts.write(draw, (x0 - 28, y), format(value, ".6g"), size=38, fill=MUTED, align="right", valign="middle")
    points: list[tuple[float, float]] = []
    spacing = (x1 - x0) / max(1, len(rows) - 1)
    for i, row in enumerate(rows):
        x = x0 + i * spacing
        y = y1 - (y1 - y0) * row["value"] / limit
        points.append((x, y))
    if len(points) > 1:
        draw.line(points, fill=theme["primary"], width=8, joint="curve")
    for i, ((x, y), row) in enumerate(zip(points, rows)):
        draw.ellipse((x - 16, y - 16, x + 16, y + 16), fill="white", outline=theme["primary"], width=7)
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=theme["accent"])
        fonts.write(draw, (x, y - 46), row["display_value"], size=48, fill=theme["ink"], align="center", valign="middle")
        fonts.write(draw, (x, y1 + 56), f"{years[i]}年", size=44, fill=MUTED, align="center", valign="middle")
    draw.line((x0, y0, x0, y1, x1, y1), fill="#8593A5", width=2)
    return _png(image)


def _bars(data: dict, fonts: _Fonts) -> str:
    rows = data["rows"]
    theme = _theme_for(data)
    same_scope = len({row["scope"] for row in rows}) == 1
    limit, step = _scale(max(row["value"] for row in rows))
    # Short, directly comparable series use a spacious scientific column plot.
    if same_scope and len(rows) <= 4 and all(fonts.measure(row["label"], 46) <= 460 for row in rows):
        image = Image.new("RGB", (WIDTH, 870), "white")
        draw = ImageDraw.Draw(image)
        x0, x1, y0, y1 = 165, 1720, 142, 730
        years = [re.fullmatch(r"((?:19|20)\d{2}年)(.+)", row["label"]) for row in rows]
        metric = years[0][2] if all(years) and len({item[2] for item in years}) == 1 else "数值"
        fonts.write(draw, (x0, 39), f'{metric}（{data["unit"]}）', size=50, fill=theme["ink"])
        for i in range(round(limit / step) + 1):
            value = i * step
            y = y1 - (y1 - y0) * value / limit
            _dashed(draw, (x0, y), (x1, y))
            draw.line((x0 - 12, y, x0, y), fill="#8593A5", width=2)
            fonts.write(draw, (x0 - 28, y), format(value, ".6g"), align="right", valign="middle")
        spacing = (x1 - x0) / len(rows)
        width = min(292, spacing * .44)
        for i, row in enumerate(rows):
            dark = theme["ink"]
            light, color = theme["light"], theme["primary"]
            center = x0 + spacing * (i + .5)
            top = y1 - (y1 - y0) * row["value"] / limit
            if row["value"] > 0:
                _gradient_shape(image, (center - width / 2, top, center + width / 2, y1), light, color,
                                radius=22, square_base="bottom")
            fonts.write(draw, (center, top - 46), row["display_value"], size=62, fill=dark,
                        align="center", valign="middle")
            label = years[i][1] if all(years) and metric != "数值" else row["label"]
            _text_block(draw, fonts, fonts.wrap(label, spacing - 45, 46),
                        (center - spacing / 2 + 20, y1 + 31, center + spacing / 2 - 20, 827), size=46)
        draw.line((x0, y0, x0, y1, x1, y1), fill="#8593A5", width=2)
        return _png(image)

    labels = [fonts.wrap(row["label"] if same_scope else f'{row["label"]}（{row["scope"]}）', 525) for row in rows]
    heights = [max(144, len(label) * 58 + 40) for label in labels]
    image = Image.new("RGB", (WIDTH, sum(heights) + 180), "white")
    draw = ImageDraw.Draw(image)
    x0, x1 = 640, 1580
    fonts.write(draw, (x0, 35), f'数值（{data["unit"]}）', size=46)
    for i in range(round(limit / step) + 1):
        value = i * step
        x = x0 + (x1 - x0) * value / limit
        _dashed(draw, (x, 112), (x, image.height - 75))
        fonts.write(draw, (x, image.height - 43), format(value, ".6g"), align="center", valign="middle")
    top = 110
    for i, (row, label_lines, height) in enumerate(zip(rows, labels, heights)):
        dark = theme["ink"]
        light, color = theme["light"], theme["primary"]
        center = top + height / 2
        _text_block(draw, fonts, label_lines, (55, top, 580, top + height), align="left")
        end = x0 + (x1 - x0) * row["value"] / limit
        if row["value"] > 0:
            _gradient_shape(image, (x0, center - 32, end, center + 32), light, color,
                            radius=14, square_base="left")
        fonts.write(draw, (end + 22, center), row["display_value"], size=46, fill=dark, valign="middle")
        top += height
    draw.line((x0, 112, x0, image.height - 75), fill="#8593A5", width=2)
    return _png(image)


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float], *, color: str = ACCENT) -> None:
    draw.line((*start, *end), fill=color, width=4)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    points = [end]
    for offset in (-0.48, 0.48):
        points.append((end[0] - 18 * math.cos(angle + offset), end[1] - 18 * math.sin(angle + offset)))
    draw.polygon(points, fill=color)


def _phase_name(stages: list[str], number: int) -> str:
    terms = "、".join(stages)
    if any(word in terms for word in ("冷链", "集配", "配送", "发运")):
        return "贮运交付"
    if "包装" in terms and any(word in terms for word in ("分选", "分级", "预冷")):
        return "分级包装"
    if any(word in terms for word in ("灌装", "放行", "成品")):
        return "成品控制"
    if any(word in terms for word in ("精制", "脱气", "杀菌")):
        return "精制处理"
    if any(word in terms for word in ("原料", "验收", "清洗", "分选")):
        return "原料处理"
    return f"工艺阶段 {number}"


def _flow(data: dict, fonts: _Fonts) -> str:
    stages = data["stages"]
    columns = min(3, len(stages))
    box_width = (1380 - (columns - 1) * 60) / columns
    labels = [fonts.wrap(stage, box_width - 130, 44) for stage in stages]
    box_height = max(150, max(len(label) for label in labels) * 60 + 45)
    row_count = math.ceil(len(stages) / columns)
    lane_height, gap = box_height + 100, 76
    image = Image.new("RGB", (WIDTH, int(60 + row_count * lane_height + (row_count - 1) * gap)), "white")
    draw = ImageDraw.Draw(image)
    boxes = []
    for row in range(row_count):
        dark, pale, color = PALETTE[2 if row == row_count - 1 else 0]
        y = 30 + row * (lane_height + gap)
        draw.rounded_rectangle((40, y, 1760, y + lane_height), radius=22, fill=pale)
        draw.rounded_rectangle((40, y, 49, y + lane_height), radius=4, fill=color)
        part = stages[row * columns:(row + 1) * columns]
        title = _phase_name(part, row + 1)
        _text_block(draw, fonts, fonts.wrap(title, 235, 46), (78, y + 45, 316, y + lane_height - 90), size=46, fill=dark)
        first, last = row * columns + 1, min(len(stages), (row + 1) * columns)
        fonts.write(draw, (197, y + lane_height - 64), f"{first:02d}—{last:02d}", fill=dark, align="center", valign="middle")
    for index, label_lines in enumerate(labels):
        row, column = divmod(index, columns)
        dark, pale, color = PALETTE[2 if row == row_count - 1 else 0]
        x = 360 + column * (box_width + 60)
        y = 80 + row * (lane_height + gap)
        boxes.append((x, y, x + box_width, y + box_height))
        draw.rounded_rectangle((x + 2, y + 6, x + box_width + 2, y + box_height + 6),
                               radius=18, fill="#E8E4DA" if row == row_count - 1 else "#E0E9F2")
        draw.rounded_rectangle(boxes[-1], radius=18, outline=color, fill="white", width=2)
        center = y + box_height / 2
        draw.ellipse((x + 17, center - 28, x + 73, center + 28), fill=pale, outline=color, width=2)
        fonts.write(draw, (x + 45, center), f"{index + 1:02d}", size=36, fill=dark, align="center", valign="middle")
        _text_block(draw, fonts, label_lines, (x + 94, y + 24, x + box_width - 36, y + box_height - 24), size=44)
    for index in range(len(boxes) - 1):
        current, following = boxes[index], boxes[index + 1]
        color = PALETTE[2 if index // columns == row_count - 1 else 0][0]
        if following[1] > current[1]:
            start_x, end_x = (current[0] + current[2]) / 2, (following[0] + following[2]) / 2
            middle_y = (current[3] + following[1]) / 2
            draw.line((start_x, current[3] + 4, start_x, middle_y, end_x, middle_y), fill=color, width=4, joint="curve")
            draw.ellipse((start_x - 5, current[3] - 1, start_x + 5, current[3] + 9), fill=color)
            _arrow(draw, (end_x, middle_y), (end_x, following[1] - 6), color=color)
        else:
            _arrow(draw, (current[2] + 7, (current[1] + current[3]) / 2), (following[0] - 7, (following[1] + following[3]) / 2), color=color)
    return _png(image)


def _gantt(data: dict, fonts: _Fonts) -> str:
    rows = data["rows"]
    labels = [fonts.wrap(row["stage"], 465) for row in rows]
    row_height = max(146, max(len(label) for label in labels) * 58 + 40)
    top = 206
    image = Image.new("RGB", (WIDTH, top + len(rows) * row_height + 35), "white")
    draw = ImageDraw.Draw(image)
    x0, x1 = 655, 1750
    months = max(row["end_month"] for row in rows)
    unit_width = (x1 - x0) / months
    tick_step = max(1, math.ceil(months / 12))
    label_sizes = []
    for row in rows:
        start, end = row["start_month"], row["end_month"]
        label = f"{start}—{end}月" if start != end else f"{start}月"
        label_sizes.append(math.floor(((end - start + 1) * unit_width - 32) * 42 / fonts.measure(label, 42)))
    # Use one shared type size when all periods can fit inside their bars.
    # Very short spans on long schedules retain the legible outside-label path.
    period_size = min(42, min(label_sizes)) if min(label_sizes) >= 34 else 42
    fonts.write(draw, (52, 58), "实施阶段", size=48, valign="middle")
    fonts.write(draw, (x0, 58), "项目启动后月份", size=48, valign="middle")
    group_width = 3 if months <= 12 else max(3, math.ceil(months / 4))
    for start in range(1, months + 1, group_width):
        end = min(months, start + group_width - 1)
        left, right = x0 + (start - 1) * unit_width, x0 + end * unit_width
        draw.rounded_rectangle((left + 2, 102, right - 2, 148), radius=6, fill="#EDF3F9")
        if right - left >= 180:
            fonts.write(draw, ((left + right) / 2, 125), f"{start}—{end}月", size=37, fill=MUTED, align="center", valign="middle")
    for i in range(len(rows)):
        y = top + i * row_height
        if i % 2 == 0:
            draw.rectangle((40, y, x1, y + row_height), fill="#F8FAFD")
        draw.line((40, y + row_height, x1, y + row_height), fill=GRID, width=2)
    for month in range(1, months + 1):
        x = x0 + (month - 1) * unit_width
        draw.line((x, top, x, image.height - 35), fill=GRID, width=2)
        if month == 1 or month == months or month % tick_step == 0:
            fonts.write(draw, (x + unit_width / 2, 180), str(month), align="center", valign="middle")
    draw.line((x1, top, x1, image.height - 35), fill=GRID, width=2)
    for i, (row, label_lines) in enumerate(zip(rows, labels)):
        dark, pale, color = PALETTE[2 if i == len(rows) - 1 else 0]
        center = top + row_height / 2
        draw.rounded_rectangle((52, center - 28, 110, center + 28), radius=8, fill=pale, outline=color, width=2)
        fonts.write(draw, (81, center), f"{i + 1:02d}", size=38, fill=dark, align="center", valign="middle")
        _text_block(draw, fonts, label_lines, (140, top + 12, 605, top + row_height - 12), align="left")
        start, end = row["start_month"], row["end_month"]
        period = f"{start}—{end}月" if start != end else f"{start}月"
        left, right = x0 + (start - 1) * unit_width + 2, x0 + end * unit_width - 2
        inside = fonts.measure(period, period_size) + 28 <= right - left
        bar_y = center if inside else center + 26
        _gradient_shape(image, (left, bar_y - 32, right, bar_y + 32),
                        "#FCE9BE" if i == len(rows) - 1 else "#E2EEFA",
                        "#F0CA7D" if i == len(rows) - 1 else "#BAD1E8", radius=10)
        draw.rounded_rectangle((left, bar_y - 32, right, bar_y + 32), radius=min(10, (right - left) / 2), outline=color, width=2)
        draw.line((left + 1, bar_y - 22, left + 1, bar_y + 22), fill=dark, width=4)
        label_x = min(x1 - fonts.measure(period, period_size) / 2, max(x0 + fonts.measure(period, period_size) / 2, (left + right) / 2))
        fonts.write(draw, (label_x, center if inside else center - 31), period, size=period_size, fill=dark, align="center", valign="middle")
        top += row_height
    return _png(image)


def plan_visual_spec(kind: str, data: dict[str, Any], title: str = "") -> dict[str, Any]:
    """Choose a chart form and visual language from the report semantics.

    The report model supplies facts and tables; this planner decides how those
    facts should be read. The result is serializable and is included in the
    figure manifest so the web and Word renderers can expose the same decision.
    """
    text = " ".join([str(title or ""), *[str(row.get("label") or "") for row in data.get("rows", [])],
                     *[str(row.get("scope") or "") for row in data.get("rows", [])],
                     *[str(item) for item in data.get("stages", [])]]).lower()
    if any(term in text for term in ("冷链", "预冷", "运输", "集配", "配送")):
        theme = "cold_chain"
    elif any(term in text for term in ("质量", "检测", "控制点", "安全", "合规")):
        theme = "quality"
    elif any(term in text for term in ("市场", "需求", "出口", "销售", "投资")):
        theme = "market"
    elif any(term in text for term in ("产量", "产业", "种植", "原料", "品种", "加工")):
        theme = "industry"
    else:
        theme = "default"

    selected = kind
    reason = {
        "bar": "多个同口径指标横向比较，使用柱状图突出差异。",
        "flow": "内容包含明确先后关系，使用流程图表达工艺路径。",
        "gantt": "内容包含相对月份区间，使用时间计划图表达实施节奏。",
    }.get(kind, "根据结构化事实选择最合适的图表。")
    metric = ""
    years = _year_labels(data.get("rows", [])) if kind == "bar" else None
    if years:
        selected = "trend"
        first_label = str(data["rows"][0].get("label") or "")
        metric = re.sub(r"^(?:19|20)\d{2}年", "", first_label).strip() or "数值"
        reason = "同一指标按年份连续变化，使用趋势图表达变化方向和年度节点。"
    elif kind == "bar" and title:
        # Carry the report table's business wording into the axis label so a
        # standalone figure remains understandable outside the document.
        metric = re.sub(r"^(?:表\s*\d+[.．、:\：-]?\s*)", "", str(title).strip())[:24] or "数值"
    return {"kind": selected, "theme": theme, "reason": reason, "metric": metric}


def prepare_report_visuals(markdown: str, *, sources: list[dict[str, Any]] | None = None) -> tuple[str, list[dict]]:
    """Add up to four trusted figure markers and their PNG image manifest.

    Supported inputs are explicit arrow process lines, relative-month schedules,
    and five-column numeric tables whose quantities are corroborated by sources.
    A content planner chooses between a comparison bar chart and a year trend
    chart, then assigns a semantic theme. Original tables remain editable;
    unsupported content is left untouched.
    """
    lines = markdown.splitlines()
    result: list[str] = []
    figures: list[dict] = []
    fonts: _Fonts | None = None
    index = 0
    fence: str | None = None

    def add(kind: str, data: dict, title: str, note: str) -> str:
        nonlocal fonts
        if fonts is None:
            fonts = _Fonts()
        number = len(figures) + 1
        spec = plan_visual_spec(kind, data, title)
        render_kind = str(spec["kind"])
        render_data = dict(data)
        render_data["_theme"] = spec["theme"]
        if spec.get("metric"):
            render_data["metric"] = spec["metric"]
        identity = hashlib.sha256(json.dumps({"kind": render_kind, "data": render_data}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        figure_id = f"figure-{number}-{identity}"
        title = title.replace("[", "（").replace("]", "）")[:100]
        caption = f"图{number} {title}"
        render = {"bar": _bars, "trend": _trend, "flow": _flow, "gantt": _gantt}[render_kind]
        figures.append({"id": figure_id, "caption": caption, "note": note, "kind": render_kind,
                        "visual_spec": spec, "data": data, "image_base64": render(render_data, fonts), "mime_type": "image/png"})
        return f"![{caption}](report-figure:{figure_id})"

    while index < len(lines):
        line = lines[index]
        fence_match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            result.append(line)
            index += 1
            continue
        if fence is not None:
            result.append(line)
            index += 1
            continue
        if len(figures) < 4:
            flow = _FLOW.fullmatch(line.strip())
            if flow:
                stages = [stage.strip().rstrip("。；") for stage in flow.group(1).split("→")]
                if 2 <= len(stages) <= 12 and all(0 < len(stage) <= 36 for stage in stages):
                    result.extend([add("flow", {"stages": stages}, "项目工艺流程", ""), ""])
                    index += 1
                    continue
            table = _table(lines, index)
            if table:
                header, rows, end = table
                numeric = _numeric_data(header, rows, sources or [])
                gantt = _gantt_data(header, rows)
                figure_marker = None
                if numeric:
                    preceding = next((entry.strip() for entry in reversed(result) if entry.strip()), "")
                    match = re.fullmatch(r"(?:\*\*)?表\s*\d+[.．、\s]*(.+?)(?:\*\*)?", preceding)
                    title = match.group(1).rstrip("*").strip() if match else "相关指标数据比较"
                    scopes = list(dict.fromkeys(row["scope"] for row in numeric["rows"]))
                    refs = sorted({ref for row in numeric["rows"] for ref in row["references"]})
                    note = "统计口径：" + "；".join(scopes) + "。数据来源：" + "".join(f"[{ref}]" for ref in refs) + "。"
                    figure_marker = add("bar", numeric, title, note)
                elif gantt:
                    figure_marker = add("gantt", gantt, "项目实施进度计划", "相对项目启动月份，色块表示计划实施区间。")
                if figure_marker:
                    caption_index = next((position for position in range(len(result) - 1, -1, -1) if result[position].strip()), None)
                    if caption_index is not None and re.match(r"^(?:\*\*)?表\s*\d+", result[caption_index].strip()):
                        result[caption_index:caption_index] = [figure_marker, ""]
                    else:
                        result.extend([figure_marker, ""])
                result.extend(lines[index:end])
                index = end
                continue
        result.append(line)
        index += 1
    suffix = "\n" if markdown.endswith("\n") else ""
    return "\n".join(result) + suffix, figures
