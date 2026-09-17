from docx import Document
from docx.shared import Cm

from app.reporting.docx_export import markdown_to_docx


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
