import base64
import io

from PIL import Image, ImageDraw
import pytest

from app.reporting import visuals
from app.reporting.markdown_format import normalize_table_captions


SOURCES = [
    {"snippet": "2024年甲地区柑橘产量达125万吨，乙地区产量约87.5万吨。"},
    {"content": "项目第一阶段处理量为1,000吨，第二阶段处理量为2,000吨。"},
]
NUMERIC = """表1 地区柑橘产量

| 指标 | 数值 | 单位 | 统计口径 | 来源 |
| --- | --- | --- | --- | --- |
| 甲地区 | 125 | 万吨 | 2024年产量 | [1] |
| 乙地区 | 约87.5 | 万吨 | 2024年产量 | [1] |
"""
SCHEDULE = """| 阶段 | 示例周期 | 主要成果 |
| --- | --- | --- |
| 项目前期论证与市场验证 | 第1至2月 | 产品规格 |
| 小试与方案比选 | 第2—4月 | 小试报告 |
| 工程设计与许可准备 | 第4-6月 | 设备清单 |
| 采购施工与安装 | 第6至10月 | 设备安装 |
| 联动调试与试生产 | 第10至12月 | 客户样品 |
"""


@pytest.fixture
def fake_render(monkeypatch):
    """Keep parsing tests independent of fonts installed on a CI host."""
    monkeypatch.setattr(visuals, "_Fonts", lambda: object())
    for name in ("_bars", "_flow", "_gantt"):
        monkeypatch.setattr(visuals, name, lambda data, fonts: "test-image")


def test_numeric_chart_preserves_native_table_and_source_provenance(fake_render):
    markdown, figures = visuals.prepare_report_visuals(NUMERIC, sources=SOURCES)
    assert len(figures) == 1
    figure = figures[0]
    assert figure["kind"] == "bar"
    assert figure["caption"] == "图1 地区柑橘产量"
    assert [row["value"] for row in figure["data"]["rows"]] == [125, 87.5]
    assert figure["data"]["rows"][1]["display_value"] == "约87.5"
    assert "2024年产量" in figure["note"] and "[1]" in figure["note"]
    assert NUMERIC in markdown
    assert markdown.index("report-figure:") < markdown.index("表1")


def test_visual_planner_uses_trend_for_multi_year_series_and_semantic_theme():
    rows = [{"label": f"{year}年产量", "scope": "产量"} for year in (2021, 2022, 2023)]
    spec = visuals.plan_visual_spec("bar", {"rows": rows}, "区域产量趋势")
    assert spec["kind"] == "trend"
    assert spec["theme"] == "industry"
    assert "年份" in spec["reason"]


def test_visual_planner_uses_quality_theme_for_control_content():
    spec = visuals.plan_visual_spec(
        "bar",
        {"rows": [{"label": "合格率", "scope": "质量控制"}]},
        "关键质量控制点",
    )
    assert spec["kind"] == "bar"
    assert spec["theme"] == "quality"


def test_table_caption_numbering_remains_stable_when_visuals_are_inserted(fake_render):
    source = "## 产业分析\n\n" + NUMERIC + "\n\n## 实施计划\n\n" + SCHEDULE
    normalized = normalize_table_captions(source)
    markdown, figures = visuals.prepare_report_visuals(normalized, sources=SOURCES)
    assert [figure["kind"] for figure in figures] == ["bar", "gantt"]
    assert normalize_table_captions(markdown) == markdown
    for number, title in ((1, "地区柑橘产量"), (2, "实施计划")):
        caption = f"表{number} {title}"
        assert markdown.count(caption) == 1
        assert markdown.index(f"report-figure:{figures[number - 1]['id']}") < markdown.index(caption)
        assert markdown[markdown.index(caption) + len(caption):].lstrip().startswith("|")


@pytest.mark.parametrize("change", [
    ("[1]", "[9]"),
    ("[1]", "[0]"),
    ("[1]", "统计局"),
    ("125 | 万吨", "126 | 万吨"),
    ("125 | 万吨", "125 | 吨"),
    ("125 | 万吨", "NaN | 万吨"),
    ("125 | 万吨", "Infinity | 万吨"),
    ("125 | 万吨", "-125 | 万吨"),
    ("125 | 万吨", "1e2 | 万吨"),
    ("2024年产量", ""),
])
def test_numeric_chart_rejects_unverifiable_values_and_mixed_units(change, fake_render):
    markdown = NUMERIC.replace(*change, 1)
    result, figures = visuals.prepare_report_visuals(markdown, sources=SOURCES)
    assert figures == []
    assert result == markdown


def test_numeric_sources_require_the_correct_number_and_unit_together(fake_render):
    for snippet in ("125吨，87.5万吨", "125.9万吨，87.5万吨", "1125万吨，87.5万吨", "-125万吨，87.5万吨", "125，单位万吨；87.5万吨"):
        _, figures = visuals.prepare_report_visuals(NUMERIC, sources=[{"snippet": snippet}])
        assert figures == [], snippet
    assert visuals.prepare_report_visuals(NUMERIC)[1] == []


def test_numeric_chart_accepts_commas_and_abstract_evidence(fake_render):
    markdown = NUMERIC.replace("125 | 万吨", "1,000 | 吨").replace("约87.5 | 万吨", "2,000 | 吨")
    _, figures = visuals.prepare_report_visuals(markdown, sources=[{"abstract": "2024年规模为1000吨和2000吨。"}])
    assert [row["value"] for row in figures[0]["data"]["rows"]] == [1000, 2000]


def test_numeric_chart_rejects_wrong_year_or_lost_approximation(fake_render):
    markdown = NUMERIC.replace("2024年产量", "2023年产量", 1)
    assert visuals.prepare_report_visuals(markdown, sources=SOURCES)[1] == []
    markdown = NUMERIC.replace("约87.5", "87.5")
    assert visuals.prepare_report_visuals(markdown, sources=SOURCES)[1] == []


def test_numeric_chart_links_each_year_to_its_own_quantity(fake_render):
    markdown = NUMERIC.replace("甲地区 | 125", "2023年 | 约10").replace("乙地区 | 约87.5", "2024年 | 20").replace("2024年产量", "武鸣沃柑出口量")
    sources = [{"snippet": "2023年武鸣沃柑出口约10万吨，2024年增至20万吨。"}]
    _, figures = visuals.prepare_report_visuals(markdown, sources=sources)
    assert [row["value"] for row in figures[0]["data"]["rows"]] == [10, 20]
    swapped = markdown.replace("约10", "20").replace("2024年 | 20", "2024年 | 约10")
    assert visuals.prepare_report_visuals(swapped, sources=sources)[1] == []


def test_flow_uses_only_explicit_stages_in_order(fake_render):
    source = "前文\n\n工艺流程：原料验收 → 清洗 → 榨汁 → 杀菌 → 灌装。\n\n后文"
    markdown, figures = visuals.prepare_report_visuals(source)
    assert figures[0]["data"]["stages"] == ["原料验收", "清洗", "榨汁", "杀菌", "灌装"]
    assert "工艺流程：" not in markdown
    assert markdown.startswith("前文") and markdown.endswith("后文")
    assert "report-figure:" in markdown


@pytest.mark.parametrize("source", ["工艺流程：清洗", "工艺流程：清洗 → → 榨汁", "工艺流程：" + " → ".join(["清洗"] * 13)])
def test_flow_does_not_infer_missing_or_unbounded_stages(source, fake_render):
    assert visuals.prepare_report_visuals(source) == (source, [])


def test_schedule_retains_exact_inclusive_month_ranges(fake_render):
    markdown, figures = visuals.prepare_report_visuals(SCHEDULE)
    assert len(figures) == 1
    assert figures[0]["kind"] == "gantt"
    assert [(row["start_month"], row["end_month"]) for row in figures[0]["data"]["rows"]] == [(1, 2), (2, 4), (4, 6), (6, 10), (10, 12)]
    assert figures[0]["note"] == "相对项目启动月份，色块表示计划实施区间。"
    assert SCHEDULE in markdown


@pytest.mark.parametrize("period", ["第0至2月", "第4至2月", "第1至61月", "约两个月", "待定"])
def test_schedule_rejects_invalid_ranges_without_guessing(period, fake_render):
    markdown = SCHEDULE.replace("第1至2月", period)
    assert visuals.prepare_report_visuals(markdown) == (markdown, [])


def test_arbitrary_images_paths_code_and_unstructured_numbers_are_not_rendered(fake_render):
    markdown = "![图片](file:///secret.png)\n\n![图片](https://example.com/x.png)\n\n批次数量20吨，糖度12.8。\n\n```text\n工艺流程：清洗 → 灌装\n```\n"
    assert visuals.prepare_report_visuals(markdown) == (markdown, [])


def test_visual_count_is_bounded_and_ids_are_deterministic(fake_render):
    markdown = "\n\n".join(["工艺流程：清洗 → 榨汁"] * 6)
    result, figures = visuals.prepare_report_visuals(markdown)
    assert len(figures) == 4
    assert result.count("工艺流程：") == 2
    assert len({figure["id"] for figure in figures}) == 4
    assert visuals.prepare_report_visuals(markdown) == (result, figures)


def test_real_renderer_outputs_valid_png_for_long_chinese_labels():
    try:
        visuals._Fonts()
    except RuntimeError:
        pytest.skip("Rendering smoke test requires installed CJK and Latin fonts")
    long_schedule = SCHEDULE.replace("采购施工与安装", "原料处理设备采购与厂房配套公用工程施工安装")
    markdown = NUMERIC + "\n工艺流程：原料接收与质量安全检查 → 清洗分选 → 榨汁及果汁精制 → 热处理与灌装 → 冷链储运\n\n" + long_schedule
    result, figures = visuals.prepare_report_visuals(markdown, sources=SOURCES)
    assert len(figures) == 3
    assert result.count("report-figure:") == 3
    for figure in figures:
        image = Image.open(io.BytesIO(base64.b64decode(figure["image_base64"], validate=True)))
        image.load()
        assert image.format == "PNG"
        assert image.width == 1800
        assert 250 <= image.height <= 2500
        assert image.getpixel((0, 0)) == (255, 255, 255)
        assert round(image.info["dpi"][0]) == 300


@pytest.fixture
def real_fonts():
    try:
        return visuals._Fonts()
    except RuntimeError:
        pytest.skip("Layout regression tests require installed CJK and Latin fonts")


@pytest.mark.parametrize("size", [38, 46, 58])
def test_mixed_script_labels_share_a_baseline_and_are_visually_centered(real_fonts, monkeypatch, size):
    """The original per-glyph top anchor made month ranges jump vertically."""
    image = Image.new("L", (1200, 400), 0)
    draw = ImageDraw.Draw(image)
    paint = draw.text
    calls = []

    def record_text(xy, text, *args, **kwargs):
        calls.append((xy, text, kwargs.get("anchor")))
        return paint(xy, text, *args, **kwargs)

    monkeypatch.setattr(draw, "text", record_text)
    text = "第1—2月 · NFC 12.8 °Brix"
    predicted = real_fonts.write(draw, (600, 200), text, size=size,
                                 fill="white", align="center", valign="middle")
    assert "".join(call[1] for call in calls) == text
    assert len(calls) > 1  # Exercise Chinese/Latin transitions in one label.
    assert {call[2] for call in calls} == {"ls"}
    assert max(call[0][1] for call in calls) - min(call[0][1] for call in calls) < 0.01

    ink = image.getbbox()
    assert ink is not None
    assert abs((ink[0] + ink[2]) / 2 - 600) <= 2
    assert abs((ink[1] + ink[3]) / 2 - 200) <= 2
    assert all(abs(actual - measured) <= 2 for actual, measured in zip(ink, predicted))


def _ink_line_boxes(image):
    """Find actual painted text rows without using the renderer's measurements."""
    start = None
    boxes = []
    for y in range(image.height + 1):
        occupied = y < image.height and image.crop((0, y, image.width, y + 1)).getbbox() is not None
        if occupied and start is None:
            start = y
        elif not occupied and start is not None:
            local = image.crop((0, start, image.width, y)).getbbox()
            boxes.append((local[0], start, local[2], y))
            start = None
    return boxes


@pytest.mark.parametrize("align", ["left", "center"])
def test_multiline_text_is_centered_as_a_block_and_fits_its_box(real_fonts, align):
    image = Image.new("L", (1200, 600), 0)
    box = (100, 100, 1100, 500)
    lines = ["项目启动后第1—2月", "NFC质量控制12.8 °Brix", "原料验收与分选清洗"]
    visuals._text_block(ImageDraw.Draw(image), real_fonts, lines, box,
                        size=46, fill="white", align=align)
    ink = image.getbbox()
    assert ink is not None
    assert abs((ink[1] + ink[3]) / 2 - (box[1] + box[3]) / 2) <= 2
    assert box[0] <= ink[0] < ink[2] <= box[2]
    assert box[1] <= ink[1] < ink[3] <= box[3]
    painted_lines = _ink_line_boxes(image)
    assert len(painted_lines) == len(lines)
    for left, _, right, _ in painted_lines:
        if align == "center":
            assert abs((left + right) / 2 - (box[0] + box[2]) / 2) <= 2
        else:
            assert abs(left - box[0]) <= 2


def test_two_month_gantt_periods_keep_a_shared_size_and_stay_inside_bars(real_fonts, monkeypatch):
    periods = [(1, 2), (3, 4), (5, 8), (9, 10), (11, 12)]
    labels = {f"{start}—{end}月" for start, end in periods}
    bars, painted = [], []
    gradient, write = visuals._gradient_shape, visuals._Fonts.write

    def record_bar(image, box, *args, **kwargs):
        bars.append(box)
        return gradient(image, box, *args, **kwargs)

    def record_label(self, draw, xy, text, *args, **kwargs):
        bounds = write(self, draw, xy, text, *args, **kwargs)
        if text in labels:
            painted.append((bounds, kwargs["size"]))
        return bounds

    monkeypatch.setattr(visuals, "_gradient_shape", record_bar)
    monkeypatch.setattr(visuals._Fonts, "write", record_label)
    visuals._gantt({"rows": [{"stage": "阶段", "start_month": start, "end_month": end}
                             for start, end in periods]}, real_fonts)
    assert len(painted) == len(bars) == 5
    assert len({size for _, size in painted}) == 1
    for (x0, y0, x1, y1), ((left, top, right, bottom), _) in zip(bars, painted):
        assert x0 < left < right < x1 and y0 < top < bottom < y1
        assert abs((top + bottom) / 2 - (y0 + y1) / 2) <= 2


@pytest.mark.parametrize("kind,data", [
    ("flow", {"stages": ["原料批次质量安全检查与设备公用工程设施验收及试运行条件确认和质量记录复核" for _ in range(12)]}),
    ("gantt", {"rows": [
        {"stage": "原料处理设备采购与厂房配套公用工程施工安装以及质量控制体系建设与验收与试生产准备以及生产人员操作规程培训和项目验收资料归档"[:60],
         "start_month": month, "end_month": month}
        for month in (1, 2, 10, 20, 30, 40, 50, 58, 59, 60)
    ], "period_label": "计划周期"}),
    ("bars", {"unit": "万吨", "rows": [
        {"label": "柑橘原料加工与综合利用项目第一阶段全年处理总量",
         "scope": "广西南宁武鸣地区项目建设完成后的年度计划加工规模",
         "value": 87.5, "display_value": "约87.5"},
        {"label": "柑橘原料加工与综合利用项目第二阶段全年处理总量",
         "scope": "项目二期设备投产及生产能力提升后的年度计划加工规模",
         "value": 125, "display_value": "125"},
    ]}),
])
def test_long_labels_and_largest_supported_plans_keep_text_inside_canvas_and_boxes(
        real_fonts, monkeypatch, kind, data):
    """Check layout at boundary inputs, including a narrow month-60 bar label."""
    original_write = visuals._Fonts.write
    original_block = visuals._text_block
    text_bounds = []

    def checked_write(self, draw, xy, text, *args, **kwargs):
        bounds = original_write(self, draw, xy, text, *args, **kwargs)
        width, height = draw._image.size
        assert -2 <= bounds[0] <= bounds[2] <= width + 2, (text, bounds, (width, height))
        assert -2 <= bounds[1] <= bounds[3] <= height + 2, (text, bounds, (width, height))
        text_bounds.append((text, bounds))
        return bounds

    def checked_block(draw, fonts, lines, box, **kwargs):
        first = len(text_bounds)
        original_block(draw, fonts, lines, box, **kwargs)
        for text, bounds in text_bounds[first:]:
            assert box[0] - 2 <= bounds[0] <= bounds[2] <= box[2] + 2, (text, bounds, box)
            assert box[1] - 2 <= bounds[1] <= bounds[3] <= box[3] + 2, (text, bounds, box)

    monkeypatch.setattr(visuals._Fonts, "write", checked_write)
    monkeypatch.setattr(visuals, "_text_block", checked_block)
    encoded = getattr(visuals, "_" + kind)(data, real_fonts)
    image = Image.open(io.BytesIO(base64.b64decode(encoded, validate=True)))
    image.load()
    assert image.width == 1800
    assert text_bounds
