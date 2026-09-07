"""Private, scoped intake records on the existing server data volume.

This module does not grant public marketplace access or implement account roles.
The caller supplies a server-established scope, never a scope from the browser.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.intake_schema import intake_schema

MAX_FILE = 3 * 1024 * 1024
MAX_TOTAL = 9 * 1024 * 1024


def _text(value):
    if not isinstance(value, (str, int, float, bool)):
        return ""
    result = unicodedata.normalize("NFKC", str(value)).strip()
    if len(result) > 4000:
        raise ValueError("单个字段最多4000字，请把长记录作为附件保存。")
    return result


def validate_document(value):
    if not isinstance(value, dict) or value.get("side") not in ("supplier", "processor"):
        raise ValueError("请选择供应端或生产端。")
    schema = intake_schema()["sides"][value["side"]]
    clean = {"schemaVersion": 1, "side": value["side"], "fields": {}, "rows": {}, "declarations": {}, "attachments": []}
    errors = []
    total = complete = 0
    fields = value.get("fields") if isinstance(value.get("fields"), dict) else {}
    rows = value.get("rows") if isinstance(value.get("rows"), dict) else {}
    declarations = value.get("declarations") if isinstance(value.get("declarations"), dict) else {}

    def check(spec, raw, path, step):
        nonlocal total, complete
        result = raw is True if spec["type"] == "checkbox" else _text(raw if raw is not None else "")
        present = result is True if spec["type"] == "checkbox" else result != ""
        if spec["required"]:
            total += 1
            complete += bool(present)
            if not present:
                errors.append({"step": step, "message": f"{path}：请填写{spec['label']}"})
        if present and spec["type"] == "number":
            try:
                number = float(result.replace(",", ""))
                if not math.isfinite(number) or number < spec.get("min", -math.inf) or number > spec.get("max", math.inf):
                    raise ValueError
                result = format(number, ".12g")
            except (ValueError, TypeError):
                errors.append({"step": step, "message": f"{path}：{spec['label']}数值不在有效范围内"})
        if present and spec["type"] in ("date", "datetime-local"):
            try:
                datetime.strptime(result, "%Y-%m-%d" if spec["type"] == "date" else "%Y-%m-%dT%H:%M")
            except ValueError:
                errors.append({"step": step, "message": f"{path}：{spec['label']}日期格式无效"})
        if present and spec.get("options") and result not in spec["options"]:
            errors.append({"step": step, "message": f"{path}：{spec['label']}选项无效"})
        return result

    for step, part in enumerate(schema["steps"]):
        for g in part["groups"]:
            key = g["key"]
            if not g["repeat"]:
                for spec in g["fields"]:
                    path = f"{key}.{spec['key']}"
                    clean["fields"][path] = check(spec, fields.get(path), g["title"], step)
                continue
            raw_rows = rows.get(key, [])
            if not isinstance(raw_rows, list) or len(raw_rows) > 60:
                raise ValueError("单项明细最多60条，请分批记录。")
            active = [r for r in raw_rows if isinstance(r, dict) and any(_text(r.get(s["key"], "")) for s in g["fields"])]
            declared = declarations.get(key, "")
            clean["declarations"][key] = declared if declared in ("已使用", "未使用") else ""
            if g["declaration"]:
                total += 1
                complete += declared in ("已使用", "未使用")
                if declared not in ("已使用", "未使用"):
                    errors.append({"step": step, "message": f"{g['title']}：请选择已使用或未使用"})
                if declared == "未使用" and active:
                    errors.append({"step": step, "message": f"{g['title']}：未使用声明与明细冲突，请核对"})
            if (g["required"] or declared == "已使用") and not active:
                total += 1
                errors.append({"step": step, "message": f"{g['title']}：至少添加一条完整记录"})
            clean["rows"][key] = [
                {s["key"]: check(s, r.get(s["key"]), f"{g['title']}第{i+1}条", step) for s in g["fields"]}
                for i, r in enumerate(raw_rows) if isinstance(r, dict)
            ]

    def error(step, message):
        errors.append(dict(step=step, message=message))

    d = clean["fields"]
    if clean["side"] == "supplier":
        if d["harvest.quantity"] and float_or_none(d["harvest.quantity"]) is not None and float(d["harvest.quantity"]) <= 0:
            error(3, "本批采收量应大于0。")
        if d["supply.from"] and d["supply.until"] and d["supply.until"] < d["supply.from"]:
            error(5, "供应结束日期不能早于开始日期。")
        if d["quality.testStatus"] == "已有检测资料" and not clean["rows"]["tests"]:
            error(4, "请选择新增检测项目，填写已有检测资料。")
        for key in ("fertilizers", "pesticides"):
            for row in clean["rows"][key]:
                if row["date"] and row["stopDate"] and row["stopDate"] < row["date"]:
                    error(2, "投入品停用日期不能早于使用日期。")
                if row["stopDate"] and d["harvest.date"] and row["stopDate"] > d["harvest.date"]:
                    error(2, "投入品停用日期晚于本批采收日期，请核对关联地块和批次。")
    else:
        if not d["profile.license"] and not d["profile.licenseReason"]:
            error(0, "请填写食品生产许可信息，或说明无需许可的适用业务情形。")
        names = {r["name"] for r in clean["rows"]["steps"] if r["name"]}
        for r in clean["rows"]["parameters"]:
            if r["step"] and r["step"] not in names:
                error(3, f"参数“{r['name']}”未关联已登记的工序名称。")
        for r in clean["rows"]["steps"]:
            if r["start"] and r["end"] and r["end"] < r["start"]:
                error(3, "工序结束时间不能早于开始时间。")
        for r in clean["rows"]["materials"]:
            quantity, used = float_or_none(r["quantity"]), float_or_none(r["input"])
            if quantity is not None and quantity <= 0:
                error(1, "原料到货数量应大于0。")
            if quantity is not None and used is not None and used > quantity:
                error(1, "实际投料量不能大于该条原料到货数量。")
            if r["acceptance"] in ("待验", "拒收") and used is not None and used > 0:
                error(1, "存在待验或拒收原料的投料记录，请核对。")
        if d["release.conclusion"] == "合格":
            if any(r["conclusion"] == "不合格" for r in clean["rows"]["tests"]):
                error(4, "检测项目不合格与成品合格结论冲突。")
            if not d["release.reviewer"] or not d["release.date"]:
                error(4, "合格结论请补齐质量负责人和判定日期。")

    supplied_files = value.get("attachments", [])
    if not isinstance(supplied_files, list) or len(supplied_files) > 8:
        raise ValueError("每份采集记录最多附8个文件。")
    total_bytes = 0
    for item in supplied_files:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str) or len(item["content"]) > MAX_FILE * 1.4:
            raise ValueError("附件内容无效或超过3MB。")
        try:
            raw = base64.b64decode(item["content"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("附件编码无效。") from exc
        name = _text(item.get("name", "")).replace("\\", "/").split("/")[-1][:180]
        suffix = Path(name).suffix.lower()
        signatures = {".pdf": b"%PDF", ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}
        if suffix not in signatures or not raw.startswith(signatures[suffix]) or len(raw) > MAX_FILE:
            raise ValueError("仅接收有效的 PDF、PNG、JPEG 原件，每个不超过3MB。")
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL:
            raise ValueError("单份记录附件合计不能超过9MB。")
        clean["attachments"].append(dict(name=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), content=item["content"]))
    audit = dict(errors=errors, required=total, completed=complete, valid=not errors,
                 score=round(100 * complete / max(total, 1)))
    return clean, audit


def float_or_none(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


class IntakeStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS intake_records (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL,
            side TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
            revision INTEGER NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS intake_scope ON intake_records(user_id, project_id, updated_at)")
        return db

    @staticmethod
    def scope(user, project):
        if not user or not project:
            raise ValueError("当前访问身份尚未初始化，请刷新页面后保存。")

    def list(self, user, project):
        self.scope(user, project)
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,side,title,status,revision,updated_at FROM intake_records WHERE user_id=? AND project_id=? ORDER BY updated_at DESC LIMIT 100",
                (user, project))]

    def analytics(self, user, project):
        """Return attachment-free aggregates for the current private scope."""
        self.scope(user, project)
        with self.connect() as db:
            records = db.execute(
                "SELECT side,status,updated_at,payload FROM intake_records WHERE user_id=? AND project_id=? ORDER BY updated_at",
                (user, project),
            ).fetchall()
        timeline = defaultdict(lambda: {"supply": 0.0, "output": 0.0})
        origins = Counter()
        quality = Counter()
        supply_tons = input_tons = output_tons = 0.0
        brix_values = []
        supplier_count = processor_count = submitted_count = 0

        def amount(value, unit="kg"):
            number = float_or_none(value)
            if number is None:
                return 0.0
            return number if unit == "吨" else number / 1000

        for record in records:
            try:
                document = json.loads(record["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            fields = document.get("fields", {})
            rows = document.get("rows", {})
            if record["status"] == "submitted":
                submitted_count += 1
            if record["side"] == "supplier":
                supplier_count += 1
                quantity = amount(fields.get("harvest.quantity"), fields.get("harvest.unit"))
                supply_tons += quantity
                date = fields.get("harvest.date") or record["updated_at"][:10]
                if quantity > 0:
                    timeline[str(date)[:7]]["supply"] += quantity
                origin = str(fields.get("base.origin") or "").strip()
                if origin:
                    origins[origin] += 1
                brix = float_or_none(fields.get("quality.brix"))
                if brix is not None:
                    brix_values.append(brix)
            else:
                processor_count += 1
                date = fields.get("product.date") or record["updated_at"][:10]
                output = amount(fields.get("output.productMass"), "kg")
                output_tons += output
                if output > 0:
                    timeline[str(date)[:7]]["output"] += output
                for material in rows.get("materials", []):
                    input_tons += amount(material.get("input"), material.get("unit"))
                release = fields.get("release.conclusion")
                if release == "合格":
                    quality["qualified"] += 1
                elif release == "不合格":
                    quality["unqualified"] += 1
                elif release:
                    quality["pending"] += 1
            for test in rows.get("tests", []):
                conclusion = test.get("conclusion")
                if conclusion == "合格":
                    quality["qualified"] += 1
                elif conclusion == "不合格":
                    quality["unqualified"] += 1
                elif conclusion:
                    quality["pending"] += 1

        points = [
            {"label": month, "supply": round(values["supply"], 3), "output": round(values["output"], 3)}
            for month, values in sorted(timeline.items())[-12:]
        ]
        return {
            "source": "当前账号产业数据采集记录",
            "recordCount": len(records),
            "supplierCount": supplier_count,
            "processorCount": processor_count,
            "submittedCount": submitted_count,
            "draftCount": len(records) - submitted_count,
            "supplyTons": round(supply_tons, 3),
            "inputTons": round(input_tons, 3),
            "outputTons": round(output_tons, 3),
            "averageBrix": round(sum(brix_values) / len(brix_values), 2) if brix_values else None,
            "timeline": points,
            "origins": [{"label": label, "value": value} for label, value in origins.most_common(8)],
            "quality": dict(qualified=quality["qualified"], pending=quality["pending"], unqualified=quality["unqualified"]),
            "updatedAt": records[-1]["updated_at"] if records else "",
        }

    def load(self, user, project, record_id):
        self.scope(user, project)
        with self.connect() as db:
            row = db.execute("SELECT * FROM intake_records WHERE id=? AND user_id=? AND project_id=?", (record_id, user, project)).fetchone()
        if row is None:
            raise ValueError("未找到此采集记录，或当前访问身份无权读取。")
        return {**json.loads(row["payload"]), **{k: row[k] for k in ("id", "status", "revision", "updated_at")}}

    def save(self, user, project, value, submit=False):
        self.scope(user, project)
        if not isinstance(value, dict):
            raise ValueError("采集记录格式无效。")
        if len(json.dumps(value, ensure_ascii=False)) > 14 * 1024 * 1024:
            raise ValueError("采集记录过大，请拆分批次。")
        clean, audit = validate_document(value)
        if submit and not audit["valid"]:
            return dict(ok=False, message="记录尚有待补或异常项，请按检查结果完善后提交。", audit=audit)
        identifier = _text(value.get("id"))
        if identifier and not re.fullmatch(r"ic_[a-f0-9]{32}", identifier):
            raise ValueError("采集记录编号无效。")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        title = clean["fields"].get("harvest.batch") or clean["fields"].get("product.batch") or "未命名批次"
        title = f"{clean['fields'].get('profile.organization') or '未填写主体'} · {title}"
        payload = json.dumps(clean, ensure_ascii=False)
        status = "submitted" if submit else "draft"
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if identifier:
                row = db.execute("SELECT user_id,project_id,revision,side FROM intake_records WHERE id=?", (identifier,)).fetchone()
                if row is None or (row["user_id"], row["project_id"]) != (user, project):
                    raise ValueError("无权修改此采集记录。")
                if value.get("revision") != row["revision"]:
                    raise ValueError("此记录已在其他页面更新，请从采集记录重新打开；当前内容可先导出备份。")
                if clean["side"] != row["side"]:
                    raise ValueError("已保存记录不能改为另一端，请新建对应端的记录。")
                revision = row["revision"] + 1
                db.execute("UPDATE intake_records SET title=?,status=?,revision=?,updated_at=?,payload=? WHERE id=?", (title, status, revision, now, payload, identifier))
            else:
                count, size = db.execute("SELECT COUNT(*),COALESCE(SUM(LENGTH(payload)),0) FROM intake_records WHERE user_id=? AND project_id=?", (user, project)).fetchone()
                if count >= 100 or size + len(payload) > 250 * 1024 * 1024:
                    raise ValueError("当前访问身份的采集容量已达上限，请联系平台维护人员。")
                identifier, revision = "ic_" + uuid4().hex, 1
                db.execute("INSERT INTO intake_records VALUES (?,?,?,?,?,?,?,?,?)", (identifier, user, project, clean["side"], title, status, revision, now, payload))
        document = dict(clean, id=identifier, status=status, revision=revision, updated_at=now)
        return dict(ok=True, message="已提交采集记录，当前状态：待复核。" if submit else "采集草稿已保存。", document=document, audit=audit)
