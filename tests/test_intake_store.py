import base64
from copy import deepcopy

import pytest

from app.intake_store import IntakeStore, validate_document


def supplier():
    return dict(side="supplier", fields={
        "profile.organization": "测试合作社", "profile.entityType": "合作社", "profile.address": "测试地址",
        "profile.contact": "测试联系人", "profile.recorder": "测试填报人", "profile.recordDate": "2026-09-07",
        "profile.source": "种植台账", "base.baseName": "测试基地", "base.plot": "P01", "base.origin": "重庆",
        "base.area": "12", "base.variety": "脐橙", "harvest.batch": "B-TEST-001", "harvest.date": "2026-09-07",
        "harvest.plots": "P01", "harvest.quantity": "2000", "harvest.unit": "kg", "harvest.operator": "测试负责人",
        "quality.grade": "一级", "quality.testStatus": "尚未检测", "consent.platformUse": True,
    }, declarations={"fertilizers": "未使用", "pesticides": "未使用"}, rows={}, attachments=[])


def test_empty_intake_does_not_inherit_example_facts():
    clean, audit = validate_document(dict(side="supplier"))
    assert not audit["valid"]
    assert clean["fields"]["base.origin"] == ""
    assert clean["fields"]["harvest.quantity"] == ""


def test_supplier_can_submit_without_processor_fields_and_without_inventing_tests():
    clean, audit = validate_document(supplier())
    assert audit["valid"], audit["errors"]
    assert clean["rows"]["tests"] == []
    assert "product.name" not in clean["fields"]


def test_normalizes_numbers_but_retains_detection_expressions():
    doc = supplier()
    doc["fields"]["harvest.quantity"] = " ２,０００ "
    doc["rows"]["tests"] = [dict(sample="B01",date="2026-09-07",item="检测项",result="＜0.01",unit="mg/kg",lab="实验室",reportNo="R01",conclusion="仅报告数值")]
    clean, audit = validate_document(doc)
    assert audit["valid"], audit["errors"]
    assert clean["fields"]["harvest.quantity"] == "2000"
    assert clean["rows"]["tests"][0]["result"] == "<0.01"


def test_conflicting_unused_statement_and_bad_values_are_blocked():
    doc = supplier()
    doc["rows"]["pesticides"] = [dict(name="已使用的农药")]
    doc["fields"]["quality.brix"] = "60"
    doc["fields"]["harvest.date"] = "2026-02-30"
    _, audit = validate_document(doc)
    assert any("冲突" in e["message"] for e in audit["errors"])
    assert any("数值" in e["message"] for e in audit["errors"])
    assert any("日期" in e["message"] for e in audit["errors"])


def test_processor_rejects_unlinked_parameters_and_conflicting_quality():
    doc = dict(side="processor", fields={"release.conclusion":"合格"}, rows={
        "steps": [dict(name="榨汁",start="2026-09-07T13:00",end="2026-09-07T12:00")],
        "parameters": [dict(step="不存在的工序",name="温度")],
        "tests": [dict(conclusion="不合格")],
        "materials": [dict(quantity="20",input="21",acceptance="拒收")],
    })
    _, audit = validate_document(doc)
    messages = " ".join(x["message"] for x in audit["errors"])
    for word in ("未关联", "冲突", "结束时间", "不能大于", "拒收"):
        assert word in messages


def test_server_save_restore_is_private_and_revision_checked(tmp_path):
    store = IntakeStore(tmp_path / "intake.db")
    saved = store.save("u1", "p1", supplier(), submit=True)
    assert saved["ok"] and saved["document"]["status"] == "submitted"
    doc = saved["document"]
    original_task_id = doc["task_id"]
    assert original_task_id.startswith("task_")
    assert IntakeStore(store.path).load("u1", "p1", doc["id"])["fields"]["base.variety"] == "脐橙"
    assert store.list("u2", "p1") == []
    assert store.list("u1", "p2") == []
    for scope in (("u2", "p1"), ("u1", "p2")):
        with pytest.raises(ValueError):
            store.load(*scope, doc["id"])
        with pytest.raises(ValueError):
            store.save(*scope, doc)
    updated = store.save("u1", "p1", doc)["document"]
    assert updated["revision"] == 2 and updated["status"] == "draft"
    assert updated["task_id"] == original_task_id
    resubmitted = store.save("u1", "p1", updated, submit=True)["document"]
    assert resubmitted["task_id"] == original_task_id
    with pytest.raises(ValueError, match="其他页面更新"):
        store.save("u1", "p1", doc)


def test_failed_submit_does_not_replace_saved_record(tmp_path):
    store = IntakeStore(tmp_path / "intake.db")
    saved = store.save("u", "p", supplier())["document"]
    invalid = deepcopy(saved)
    invalid["fields"]["consent.platformUse"] = False
    assert not store.save("u", "p", invalid, submit=True)["ok"]
    assert store.load("u", "p", saved["id"])["revision"] == 1


def test_attachments_store_contents_and_reject_fake_types(tmp_path):
    doc = supplier()
    raw = b"%PDF-1.7\n%%EOF"
    doc["attachments"] = [dict(name="test.pdf",content=base64.b64encode(raw).decode())]
    store = IntakeStore(tmp_path / "intake.db")
    saved = store.save("u", "p", doc)["document"]
    assert base64.b64decode(store.load("u", "p", saved["id"])["attachments"][0]["content"]) == raw
    doc["attachments"][0]["content"] = base64.b64encode(b"<script>alert(1)</script>").decode()
    with pytest.raises(ValueError, match="有效"):
        store.save("u", "p", doc)


def test_cannot_supply_owner_status_or_unknown_fields(tmp_path):
    doc = supplier()
    doc.update(user_id="admin", status="approved")
    doc["fields"]["isAdmin"] = True
    saved = IntakeStore(tmp_path / "intake.db").save("u", "p", doc)["document"]
    assert saved["status"] == "draft"
    assert "user_id" not in saved and "isAdmin" not in saved["fields"]


def test_attachment_and_repeat_limits_are_enforced():
    doc = supplier()
    doc["rows"]["tests"] = [{}] * 61
    with pytest.raises(ValueError, match="60"):
        validate_document(doc)
    with pytest.raises(ValueError):
        IntakeStore("unused.db").list("", "")


def test_private_analytics_use_saved_batch_values_without_attachments(tmp_path):
    store = IntakeStore(tmp_path / "intake.db")
    supply = supplier()
    supply["fields"]["quality.brix"] = "12.6"
    store.save("u", "p", supply, submit=True)
    store.save("u", "p", dict(
        side="processor",
        fields={
            "profile.organization": "测试加工厂",
            "product.date": "2026-09-07",
            "output.productMass": "500",
            "release.conclusion": "合格",
        },
        rows={"materials": [dict(input="1000", unit="kg")]},
        attachments=[],
    ))
    analytics = store.analytics("u", "p")
    assert analytics["recordCount"] == 2
    assert analytics["supplierCount"] == analytics["processorCount"] == 1
    assert analytics["submittedCount"] == 1
    assert analytics["supplyTons"] == 2
    assert analytics["inputTons"] == 1
    assert analytics["outputTons"] == .5
    assert analytics["averageBrix"] == 12.6
    assert analytics["origins"] == [{"label": "重庆", "value": 1}]
    assert analytics["quality"]["qualified"] == 1
    assert store.analytics("someone-else", "p")["recordCount"] == 0
    blank_store = IntakeStore(tmp_path / "blank.db")
    blank_store.save("u", "p", dict(side="supplier"))
    assert blank_store.analytics("u", "p")["timeline"] == []
