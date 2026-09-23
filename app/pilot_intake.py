"""Tenant-scoped intake adapter with immutable versions and review transitions."""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
import json

from sqlalchemy import and_, delete, func, or_, select, update
from app import platform_db as t
from app.blob_store import BlobStore
from app.intake_store import validate_document, float_or_none
from app.platform_store import Actor, PlatformStore, identifier, now

REVIEW_STATUSES = {"submitted", "approved", "needs_changes", "rejected", "archived"}


class PilotIntakeStore:
    def __init__(self, platform: PlatformStore, actor: Actor, blobs=None):
        self.platform, self.actor = platform, actor
        self.engine = platform.engine
        self.blobs = blobs or BlobStore()

    def _permission(self, db, *, manage=False):
        return self.platform.authorize(db, self.actor, {"owner", "admin", "reviewer"} if manage else ())

    def _scope(self, user, project):
        if (user, project) != (self.actor.user_id, self.actor.organization_id):
            raise ValueError("资料访问身份已变化，请重新打开页面。")

    def _filter(self, permission):
        expression = t.records.c.organization_id == self.actor.organization_id
        # Drafts remain private to their creator; review staff see submitted records.
        if permission["role"] == "member":
            return and_(expression, t.records.c.created_by == self.actor.user_id)
        return and_(expression, or_(t.records.c.created_by == self.actor.user_id,
            t.records.c.status != "draft"))

    def _record(self, db, rid, *, lock=False):
        permission = self._permission(db)
        query = select(t.records).where(t.records.c.id == rid, self._filter(permission))
        if lock:
            query = query.with_for_update()
        row = db.execute(query).mappings().first()
        if not row:
            raise ValueError("未找到记录，或当前账号无权查看。")
        return dict(row)

    def _document(self, row, *, files=True):
        result = json.loads(row["payload"])
        result.update({k:row[k] for k in ("id", "status", "revision", "updated_at", "task_id",
            "review_note", "reviewed_revision", "reviewed_by", "created_by")})
        if files:
            result["attachments"] = [{k:v for k,v in a.items() if k != "key"} |
                {"content":base64.b64encode(self.blobs.read(a)).decode()} for a in result["attachments"]]
        return result

    def list(self, user, project):
        self._scope(user, project)
        with self.engine.connect() as db:
            permission = self._permission(db)
            columns = [t.records.c[k] for k in ("id", "side", "title", "status", "revision", "updated_at", "task_id", "review_note", "created_by")]
            return [dict(r) for r in db.execute(select(*columns).where(self._filter(permission))
                .order_by(t.records.c.updated_at.desc()).limit(500)).mappings()]

    def load(self, user, project, record_id):
        self._scope(user, project)
        with self.engine.begin() as db:
            row = self._record(db, record_id)
            result = self._document(row)
            self.platform.audit(db, self.actor, "record_opened", record_id)
            return result

    def save(self, user, project, value, submit=False):
        self._scope(user, project)
        if len(json.dumps(value, ensure_ascii=False)) > 14 * 1024 * 1024:
            raise ValueError("记录过大，请拆分批次。")
        with self.engine.begin() as db:
            permission = self._permission(db)
            if permission["role"] == "reviewer":
                raise ValueError("审核员只能查看和审核资料，请使用填报成员账号填写。")
            rid = value.get("id")
            previous = self._record(db, rid, lock=True) if rid else None
            if previous:
                if previous["created_by"] != user:
                    raise ValueError("仅填报人可修改原始资料；审核人员可填写审核意见。")
                if previous["status"] == "archived":
                    raise ValueError("归档记录不可修改，请新建批次。")
                if previous["revision"] != value.get("revision"):
                    raise ValueError("记录已在其他页面更新，请重新打开后修改。")
                if previous["side"] != value.get("side"):
                    raise ValueError("不能更换已保存记录的采集类型。")
            clean, audit = validate_document(value)
            if submit and not audit["valid"]:
                return {"ok":False, "message":"资料存在待补项目，请完善后提交。", "audit":audit}
            # Bound the pilot until an explicit capacity plan is chosen.
            if not previous:
                count = db.scalar(select(func.count()).select_from(t.records).where(t.records.c.organization_id == project))
                if count >= 500:
                    raise ValueError("企业试点容量已达500份，请联系管理员。")
            clean["attachments"] = [self.blobs.put(project, item["name"], base64.b64decode(item["content"]))
                for item in clean["attachments"]]
            timestamp, rid = now(), rid or identifier("ic")
            revision = previous["revision"] + 1 if previous else 1
            payload = json.dumps(clean, ensure_ascii=False)
            status = "submitted" if submit else "draft"
            task_id = (previous or {}).get("task_id") or (identifier("task") if submit else "")
            title = " · ".join([str(clean["fields"].get("profile.organization") or "未填写主体"),
                str(clean["fields"].get("harvest.batch") or clean["fields"].get("product.batch") or "未命名批次")])[:500]
            values = dict(updated_by=user, side=clean["side"], title=title, status=status, revision=revision,
                payload=payload, task_id=task_id, review_note="", reviewed_by="", reviewed_revision=None, updated_at=timestamp)
            if previous:
                changed = db.execute(update(t.records).where(t.records.c.id == rid,
                    t.records.c.revision == previous["revision"]).values(**values))
                if changed.rowcount != 1:
                    raise ValueError("记录已在其他页面更新，请重新打开后修改。")
            else:
                db.execute(t.records.insert().values(id=rid, organization_id=project,
                    created_by=user, created_at=timestamp, **values))
            db.execute(t.versions.insert().values(record_id=rid, revision=revision, payload=payload,
                status=status, actor=user, created_at=timestamp))
            self.platform.audit(db, self.actor, "record_submitted" if submit else "record_saved", rid, revision=revision)
            row = db.execute(select(t.records).where(t.records.c.id == rid)).mappings().one()
            return dict(ok=True, message="已提交，等待资料审核。" if submit else "资料草稿已保存。",
                document=self._document(row), audit=audit)

    def review(self, rid, revision, decision, note):
        if decision not in {"approved", "needs_changes", "rejected"}:
            raise ValueError("审核决定无效。")
        note = str(note).strip()
        if not note or len(note) > 2000:
            raise ValueError("请填写2000字以内的审核意见。")
        with self.engine.begin() as db:
            self._permission(db, manage=True)
            row = self._record(db, rid, lock=True)
            if row["created_by"] == self.actor.user_id:
                raise ValueError("不能审核自己填报的资料，请由另一位审核人员处理。")
            if row["status"] != "submitted" or row["revision"] != revision:
                raise ValueError("资料已更新或已审核，请刷新后复核。")
            changed = db.execute(update(t.records).where(t.records.c.id == rid,
                t.records.c.revision == revision, t.records.c.status == "submitted").values(status=decision,
                review_note=note, reviewed_by=self.actor.user_id, reviewed_revision=revision, updated_at=now()))
            if changed.rowcount != 1:
                raise ValueError("资料审核状态已变化，请刷新。")
            self.platform.audit(db, self.actor, "record_reviewed", rid, revision=revision, decision=decision, note=note)

    def history(self, rid):
        with self.engine.begin() as db:
            self._record(db, rid)
            rows = db.execute(select(t.versions).where(t.versions.c.record_id == rid)
                .order_by(t.versions.c.revision.desc())).mappings().all()
            self.platform.audit(db, self.actor, "history_opened", rid)
            return [dict(r) for r in rows]

    def export(self, rid):
        doc = self.load(self.actor.user_id, self.actor.organization_id, rid)
        with self.engine.begin() as db:
            self._record(db, rid)
            self.platform.audit(db, self.actor, "record_exported", rid)
        return json.dumps(doc, ensure_ascii=False, indent=2)

    def export_all(self):
        """Export every record visible to the current enterprise reviewer."""
        with self.engine.begin() as db:
            permission = self._permission(db, manage=True)
            rows = db.execute(select(t.records).where(self._filter(permission))
                              .order_by(t.records.c.updated_at.desc()).limit(500)).mappings().all()
            documents = [self._document(row) for row in rows]
            self.platform.audit(db, self.actor, "organization_exported", self.actor.organization_id,
                                record_count=len(documents))
        return json.dumps({"exportVersion": 1, "organizationId": self.actor.organization_id,
                           "exportedAt": now(), "records": documents}, ensure_ascii=False, indent=2)

    def archive(self, rid, revision):
        with self.engine.begin() as db:
            self._permission(db, manage=True)
            row = self._record(db, rid, lock=True)
            if row["revision"] != revision or row["status"] not in {"approved", "rejected"}:
                raise ValueError("只能归档当前版本已审核的资料。")
            db.execute(update(t.records).where(t.records.c.id == rid).values(status="archived", updated_at=now()))
            self.platform.audit(db, self.actor, "record_archived", rid)

    def delete(self, rid, revision):
        with self.engine.begin() as db:
            row = self._record(db, rid, lock=True)
            permission = self._permission(db)
            if permission["role"] != "platform_admin" and (row["created_by"] != self.actor.user_id or row["status"] != "draft"):
                raise ValueError("仅可删除自己的草稿；已提交记录请联系平台管理员。")
            if row["revision"] != revision:
                raise ValueError("资料已修改，请刷新后操作。")
            db.execute(delete(t.versions).where(t.versions.c.record_id == rid))
            db.execute(delete(t.records).where(t.records.c.id == rid))
            self.platform.audit(db, self.actor, "record_deleted", rid)
        # Immutable orphan files are retained for the configured backup window.

    def analytics(self, user, project):
        self._scope(user, project)
        with self.engine.connect() as db:
            permission = self._permission(db)
            rows = db.execute(select(t.records).where(self._filter(permission))).mappings().all()
        origins, quality = Counter(), Counter()
        timeline = defaultdict(lambda: {"supply":0.0, "output":0.0})
        supply = inputs = output = 0.0
        brix, supplier_count, processor_count = [], 0, 0
        def amount(value, unit="kg"):
            num = float_or_none(value) or 0
            return num if unit == "吨" else num / 1000
        for row in rows:
            doc = json.loads(row["payload"])
            f, r = doc["fields"], doc["rows"]
            if row["side"] == "supplier":
                supplier_count += 1
                q = amount(f.get("harvest.quantity"), f.get("harvest.unit"))
                supply += q
                timeline[(f.get("harvest.date") or row["updated_at"])[:7]]["supply"] += q
                if f.get("base.origin"):
                    origins[f["base.origin"]] += 1
                num = float_or_none(f.get("quality.brix"))
                if num is not None:
                    brix.append(num)
            else:
                processor_count += 1
                q = amount(f.get("output.productMass"))
                output += q
                timeline[(f.get("product.date") or row["updated_at"])[:7]]["output"] += q
                inputs += sum(amount(m.get("input"), m.get("unit")) for m in r.get("materials", []))
            for item in r.get("tests", []):
                quality[{"合格":"qualified", "不合格":"unqualified"}.get(item.get("conclusion"), "pending")] += 1
        return dict(source="当前企业授权范围内的采集记录", recordCount=len(rows), supplierCount=supplier_count,
            processorCount=processor_count, submittedCount=sum(r["status"] != "draft" for r in rows),
            draftCount=sum(r["status"] == "draft" for r in rows), supplyTons=round(supply,3), inputTons=round(inputs,3),
            outputTons=round(output,3), averageBrix=round(sum(brix)/len(brix),2) if brix else None,
            timeline=[dict(label=m, **timeline[m]) for m in sorted(timeline)[-12:]],
            origins=[dict(label=k,value=v) for k,v in origins.most_common(8)],
            quality={k:quality[k] for k in ("qualified", "unqualified", "pending")},
            updatedAt=max((r["updated_at"] for r in rows), default=""))
