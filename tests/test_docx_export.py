from docx import Document
from docx.shared import Cm, Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
import base64
from io import BytesIO
import pytest
from PIL import Image

from app.reporting.docx_export import markdown_to_docx
from app.reporting.markdown_format import normalize_table_captions


def test_generated_figures_embed_png_keep_editable_captions_and_survive_template_slots(tmp_path):
    png = BytesIO()
    Image.new("RGB", (900, 300), "white").save(png, format="PNG")
    figure = {"id": "flow-1", "caption": "图1 工艺流程", "note": "资料来源：[1]",
              "mime_type": "image/png", "image_base64": base64.b64encode(png.getvalue()).decode()}
    markdown = "## 工艺方案\n流程说明。\n![图1 工艺流程](report-figure:flow-1)\n实施要求。"
    for use_template in (False, True):
        template_path = tmp_path / "figure-template.docx"
        if use_template:
            template = Document()
            template.add_heading("工艺方案", level=1)
            template.add_paragraph("{{工艺方案}}")
            template.save(template_path)
        result = markdown_to_docx(markdown, tmp_path / f"figures-{use_template}.docx", figures=[figure],
                                  template_path=template_path if use_template else None)
        document = Document(result)
        assert len(document.inline_shapes) == 1
        assert document.inline_shapes[0].width <= document.sections[0].page_width - document.sections[0].left_margin - document.sections[0].right_margin
        text = "\n".join(p.text for p in document.paragraphs)
        assert "report-figure:" not in text and "{{" not in text
        assert text.index("流程说明") < text.index("图1 工艺流程") < text.index("实施要求")
        caption = next(p for p in document.paragraphs if p.text == figure["caption"])
        assert_typeface(caption._p, 21)
        assert caption.alignment == WD_ALIGN_PARAGRAPH.CENTER
        assert caption._p.getprevious().xpath(".//w:drawing")
        assert caption.paragraph_format.first_line_indent == 0
        assert document.element.body.xpath('.//w:r[w:rPr/w:vertAlign[@w:val="superscript"]]/w:t[text()="[1]"]')


def test_figure_export_rejects_unknown_ids_and_non_png_payloads(tmp_path):
    marker = "![图片](report-figure:unknown)"
    with pytest.raises(ValueError, match="缺少对应图表"):
        markdown_to_docx(marker, tmp_path / "missing.docx")
    with pytest.raises(ValueError, match="PNG"):
        markdown_to_docx(marker, tmp_path / "unsafe.docx", figures=[{
            "id": "unknown", "mime_type": "image/svg+xml", "image_base64": "PHN2Zz4="}])


def test_custom_word_template_preserves_layout_and_fills_section_placeholders(tmp_path):
    template_path = tmp_path / "unit-template.docx"
    template = Document()
    template.sections[0].top_margin = Cm(3)
    template.sections[0].header.paragraphs[0].text = "单位项目申报材料"
    title = template.add_paragraph()
    title.add_run("{{项目")
    title.add_run("名称}}")
    template.add_heading("摘要", level=1)
    template.add_paragraph("{{项目摘要}}")
    template.save(template_path)

    markdown = """# 武鸣沃柑项目

## 项目摘要
这是由批次事实和外部证据形成的摘要。

## 项目背景
这是需要追加到模板的项目背景。
"""
    output_path = tmp_path / "report.docx"
    markdown_to_docx(
        markdown,
        output_path,
        profile={"title": "武鸣沃柑项目"},
        template_path=template_path,
    )

    output = Document(output_path)
    text = "\n".join(paragraph.text for paragraph in output.paragraphs)
    assert "武鸣沃柑项目" in text
    assert "这是由批次事实和外部证据形成的摘要。" in text
    assert "这是需要追加到模板的项目背景。" in text
    assert "{{" not in text
    assert output.sections[0].header.paragraphs[0].text == "单位项目申报材料"
    assert round(output.sections[0].top_margin.cm, 1) == 3.0


def assert_typeface(element, half_points):
    runs = element.xpath(".//w:r")
    assert runs
    for run in runs:
        fonts = run.find(qn("w:rPr")).find(qn("w:rFonts"))
        assert fonts.get(qn("w:eastAsia")) == "宋体"
        assert fonts.get(qn("w:ascii")) == "Times New Roman"
        assert fonts.get(qn("w:hAnsi")) == "Times New Roman"
        assert not any("Theme" in key for key in fonts.attrib)
        assert run.xpath("./w:rPr/w:sz/@w:val") == [str(half_points)]


def assert_three_line_table(table):
    assert not table._tbl.xpath(".//w:shd | .//w:highlight")
    assert not table._tbl.xpath(".//w:tblHeader")
    visible = table._tbl.xpath("./w:tblPr/w:tblBorders/*[@w:val='single']")
    assert {node.tag for node in visible} == {qn("w:top"), qn("w:bottom")}
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            visible = cell._tc.xpath("./w:tcPr/w:tcBorders/*[@w:val='single']")
            expected = {qn("w:top"), qn("w:bottom")} if row_index == 0 else {qn("w:bottom")} if row_index == len(table.rows)-1 else set()
            assert {node.tag for node in visible} == expected
            assert_typeface(cell._tc, 21)
            for paragraph in cell.paragraphs:
                assert paragraph.alignment == WD_ALIGN_PARAGRAPH.LEFT
                assert paragraph.paragraph_format.first_line_indent == 0
                if row_index == 0:
                    assert paragraph.paragraph_format.keep_with_next is True
            assert cell._tc.xpath(".//w:rPr/w:color/@w:val") == ["000000"] * len(cell._tc.xpath(".//w:r"))


def test_generated_report_uses_requested_fonts_sizes_and_three_line_tables(tmp_path):
    output_path = tmp_path / "formatted.docx"
    markdown_to_docx(
        "# 示例报告\n\n## 项目摘要\n中文 NFC 12.8 °Brix 正文。[1]\n"
        "\n### 建设建议\n第二段正文 https://example.org/reference\n"
        "\n| 结论层级 | 当前结论 | 使用边界 |\n|---|---|---|\n"
        "| 已有批次事实 | 沃柑 20 吨 [2] | 检测复核 |\n"
        "| 系统建议 | NFC 果汁 | 需要小试 |\n"
        "| 投资决策 | 待测算 | 待询价 |\n",
        output_path, profile={"title": "示例报告"},
    )
    doc = Document(output_path)
    for paragraph in doc.paragraphs:
        if not paragraph.text:
            continue
        if paragraph.style.name.startswith("Heading"):
            assert_typeface(paragraph._p, 32)
            assert paragraph.alignment == WD_ALIGN_PARAGRAPH.LEFT
            assert paragraph.paragraph_format.first_line_indent == Pt(32)
            assert paragraph._p.xpath("./w:pPr/w:ind/@w:firstLineChars") == ["200"]
        elif paragraph.style.name == "Report TOC Title":
            assert_typeface(paragraph._p, 32)
            assert paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
            assert paragraph.paragraph_format.first_line_indent == 0
        elif paragraph.style.name == "Report TOC Entry":
            assert_typeface(paragraph._p, 28)
        elif paragraph.style.name == "Report Table Caption":
            assert_typeface(paragraph._p, 21)
            assert paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
            assert paragraph.paragraph_format.keep_with_next is True
            assert paragraph._p.getnext().tag == qn("w:tbl")
        elif paragraph.style.name != "Title":
            assert_typeface(paragraph._p, 24)
    toc = next(p for p in doc.paragraphs if p.text.startswith("01  "))
    assert_typeface(toc._p, 28)
    assert toc.paragraph_format.line_spacing == 1.3
    assert toc.paragraph_format.space_after >= Pt(3)
    assert_three_line_table(doc.tables[0])
    body_citations = [run for paragraph in doc.paragraphs for run in paragraph.runs if run.text == "[1]"]
    table_citations = [run for row in doc.tables[0].rows for cell in row.cells for paragraph in cell.paragraphs for run in paragraph.runs if run.text == "[2]"]
    assert body_citations and all(run._r.xpath("./w:rPr/w:vertAlign[@w:val='superscript']") for run in body_citations)
    assert table_citations and all(run._r.xpath("./w:rPr/w:vertAlign[@w:val='superscript']") for run in table_citations)
    assert_typeface(doc.sections[0].footer._element, 24)
    assert doc.sections[0].footer._element.xpath(".//w:instrText[contains(text(), 'PAGE')]")
    assert len([r for r in doc.part.rels.values() if r.reltype.endswith('/hyperlink')]) == 1


def test_uploaded_template_direct_formatting_cannot_override_report_format(tmp_path):
    template_path = tmp_path / "colored-template.docx"
    template = Document()
    heading = template.add_heading("　　项目摘要", level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    heading.paragraph_format.first_line_indent = Cm(1)
    fonts = heading.runs[0]._r.get_or_add_rPr().get_or_add_rFonts()
    fonts.set(qn("w:asciiTheme"), "majorHAnsi")
    fonts.set(qn("w:eastAsiaTheme"), "majorEastAsia")
    template.add_paragraph("{{项目摘要}}")
    template.sections[0].header.paragraphs[0].text = "报告 Header 2026"
    template.sections[0].footer.paragraphs[0].text = "页脚 Footer"
    template.sections[0].different_first_page_header_footer = True
    template.sections[0].first_page_header.paragraphs[0].text = "首页 Header"
    template.sections[0].even_page_footer.paragraphs[0].text = "偶数页 Footer"
    table = template.add_table(rows=3, cols=2)
    table.style = "Light Shading Accent 1"
    template_header = OxmlElement("w:tblHeader")
    template_header.set(qn("w:val"), "true")
    table.rows[0]._tr.get_or_add_trPr().append(template_header)
    for row in table.rows:
        for cell in row.cells:
            cell.text = "中文 NFC 20"
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            cell.paragraphs[0].paragraph_format.keep_with_next = False
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), "1F4E78")
            cell._tc.get_or_add_tcPr().append(shading)
    template.save(template_path)
    output_path = tmp_path / "template-result.docx"
    markdown_to_docx("## 项目摘要\n模板正文。", output_path, template_path=template_path)
    doc = Document(output_path)
    heading = doc.paragraphs[0]
    assert heading.text == "项目摘要"
    assert_typeface(heading._p, 32)
    assert heading.alignment == WD_ALIGN_PARAGRAPH.LEFT
    assert heading.paragraph_format.first_line_indent == Pt(32)
    for name in ("header", "footer", "first_page_header", "even_page_footer"):
        assert_typeface(getattr(doc.sections[0], name)._element, 24)
    assert_three_line_table(doc.tables[0])


def test_table_titles_are_numbered_once_and_stay_above_their_tables(tmp_path):
    markdown = "## 原料条件\n\n| 品种 | 数量 |\n|---|---|\n| 沃柑 | 20 |\n\n## 市场分析\n\n**表9 出口量**\n\n| 年份 | 数值 |\n|---|---|\n| 2024 | 20 |\n"
    normalized = normalize_table_captions(markdown)
    assert normalized == normalize_table_captions(normalized)
    assert "表1 原料条件" in normalized and "表2 出口量" in normalized
    document = Document(markdown_to_docx(normalized, tmp_path / "tables.docx"))
    captions = [p for p in document.paragraphs if p.style.name == "Report Table Caption"]
    assert [p.text for p in captions] == ["表1 原料条件", "表2 出口量"]
    assert all(p._p.getnext().tag == qn("w:tbl") for p in captions)


def test_native_template_table_title_and_toc_use_requested_format(tmp_path):
    template = Document()
    template.add_heading("目 录", level=1)
    template.add_paragraph("表1 原料指标")
    table = template.add_table(rows=2, cols=1)
    table.cell(0, 0).text = "指标"
    table.cell(1, 0).text = "糖度"
    template_path = tmp_path / "native-captions.docx"
    template.save(template_path)
    document = Document(markdown_to_docx("", tmp_path / "native-result.docx", template_path=template_path))
    assert document.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert document.paragraphs[0].paragraph_format.first_line_indent == 0
    caption = document.paragraphs[1]
    assert_typeface(caption._p, 21)
    assert caption.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert caption.paragraph_format.keep_with_next is True


@pytest.mark.parametrize("with_figure", [False, True])
def test_template_section_slots_keep_editable_tables_and_separate_captions(tmp_path, with_figure):
    template = Document()
    template.add_paragraph("模板前文")
    template.add_heading("实施计划", level=1)
    slot = template.add_paragraph()
    slot.add_run("{{实施")
    slot.add_run("计划}}")
    template.add_paragraph("模板后文")
    template_path = tmp_path / "table-slot.docx"
    template.save(template_path)
    png = BytesIO()
    Image.new("RGB", (900, 300), "white").save(png, format="PNG")
    figure = {"id": "schedule-1", "caption": "图1 实施计划", "note": "",
              "mime_type": "image/png", "image_base64": base64.b64encode(png.getvalue()).decode()}
    marker = "![图1 实施计划](report-figure:schedule-1)\n\n" if with_figure else ""
    markdown = ("## 实施计划\n前期准备说明。[1]\n\n" + marker
                + "表1 阶段计划\n\n| 阶段 | 计划 |\n|---|---|\n| 前期 | 第1月 |\n| 建设 | 第2月 [2] |\n"
                + "\n### 验收要求\n完成验收。\n")
    document = Document(markdown_to_docx(markdown, tmp_path / "table-slot-result.docx",
                                       template_path=template_path, figures=[figure] if with_figure else []))
    assert len(document.tables) == 1
    assert_three_line_table(document.tables[0])
    caption = next(p for p in document.paragraphs if p.text == "表1 阶段计划")
    assert caption._p.getnext() == document.tables[0]._tbl
    assert caption.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert caption.paragraph_format.keep_with_next is True
    assert_typeface(caption._p, 21)
    text = "\n".join(p.text for p in document.paragraphs)
    assert text.index("模板前文") < text.index("前期准备说明") < text.index("表1 阶段计划") < text.index("完成验收") < text.index("模板后文")
    assert text.count("前期准备说明") == 1 and "{{" not in text and "｜" not in text
    subheading = next(p for p in document.paragraphs if p.text == "验收要求")
    assert subheading.style.name == "Heading 2"
    assert subheading.paragraph_format.first_line_indent == Pt(32)
    assert document.tables[0]._tbl.xpath('.//w:r[w:rPr/w:vertAlign[@w:val="superscript"]]/w:t[text()="[2]"]')
    assert len(document.inline_shapes) == int(with_figure)
    if with_figure:
        figure_caption = next(p for p in document.paragraphs if p.text == "图1 实施计划")
        assert figure_caption._p.getprevious().xpath(".//w:drawing")
        assert figure_caption._p.getnext() == caption._p
        assert figure_caption.alignment == WD_ALIGN_PARAGRAPH.CENTER
        assert_typeface(figure_caption._p, 21)


def test_table_cell_section_slot_preserves_existing_template_grid(tmp_path):
    template = Document()
    table = template.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "章节"
    table.cell(0, 1).text = "内容"
    table.cell(1, 0).text = "实施计划"
    table.cell(1, 1).text = "{{实施计划}}"
    template_path = tmp_path / "cell-slot.docx"
    template.save(template_path)
    markdown = "## 实施计划\n\n| 阶段 | 计划 |\n|---|---|\n| 前期 | 第1月 |\n"
    document = Document(markdown_to_docx(markdown, tmp_path / "cell-result.docx", template_path=template_path))
    assert len(document.tables) == 1 and len(document.tables[0].rows) == 2
    cell = document.tables[0].cell(1, 1)
    assert "第1月" in cell.text and "{{" not in cell.text
    assert len(cell.tables) == 0 and cell._tc[-1].tag == qn("w:p")
    assert_three_line_table(document.tables[0])


@pytest.mark.parametrize("caption_style", ["Normal", "Caption"])
def test_existing_template_image_caption_uses_requested_format(tmp_path, caption_style):
    template = Document()
    png = BytesIO()
    Image.new("RGB", (900, 300), "white").save(png, format="PNG")
    png.seek(0)
    template.add_picture(png, width=Cm(12))
    template.add_paragraph()
    caption = template.add_paragraph("图1 已有工艺图", style=caption_style)
    caption.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    caption.paragraph_format.first_line_indent = Cm(1)
    template.add_paragraph("正文说明。")
    template.add_paragraph("图1 的详细说明见正文。")
    template_path = tmp_path / "image-caption.docx"
    template.save(template_path)
    document = Document(markdown_to_docx("", tmp_path / "image-result.docx", template_path=template_path))
    caption = next(p for p in document.paragraphs if p.text == "图1 已有工艺图")
    assert caption.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert caption.paragraph_format.first_line_indent == 0
    assert_typeface(caption._p, 21)
    mention = next(p for p in document.paragraphs if p.text == "图1 的详细说明见正文。")
    assert_typeface(mention._p, 24)
