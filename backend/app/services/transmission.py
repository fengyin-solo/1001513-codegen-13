"""数据传输业务规则：状态流转、字段校验、缺报批量确认与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "transmission"
REQUIRED_FIELDS = ["链路编号", "所属站点", "传输方式"]
STATUS_ORDER = ["待开通", "正常上报", "缺报告警", "已停用"]
STOPPED_STATUS = "已停用"
ALARM_STATUS = "缺报告警"
ACTION_RULES = {"开通链路": "正常上报", "确认恢复": "缺报告警", "停用链路": "已停用"}
NEGATIVE_ACTIONS = ["停用链路"]

# 批量确认前必须能说明“按什么频次、最近什么时候上报”，缺一个都不允许参与
CONFIRM_REQUIRED_FIELDS = ["上报频次", "最近上报时刻"]
CONFIRM_DECISIONS = ["通过", "退回"]


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _missing_count(row: dict[str, Any]) -> int:
    """缺报次数按整数解析；占位脏数据或空值按 0 计，绝不让统计口径炸掉。"""
    try:
        return max(int(float(row.get("缺报次数"))), 0)
    except (TypeError, ValueError):
        return 0


class TransmissionService:
    def __init__(self) -> None:
        # 已生效的批量确认令牌：同一批连续提交两次只生效一次
        self._used_tokens: set[str] = set()

    def _filter_rows(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("链路编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filter_rows(keyword=keyword, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"传输链路 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据传输可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        entry["链路状态"] = target
        return entry, f"传输链路已{action}"

    # ---- 缺报批量确认 -------------------------------------------------

    def _incomplete_reason(self, row: dict[str, Any]) -> list[str]:
        """缺报告警链路参与批量确认时，逐字段说明缺了什么。"""
        return [field for field in CONFIRM_REQUIRED_FIELDS if _is_blank(row.get(field))]

    def list_incomplete(self) -> list[dict[str, Any]]:
        """上报频次或最近上报时刻为空的链路（按全量口径），单独列出并说明缺了什么。"""
        result = []
        for row in store.rows(MODULE):
            missing = [
                field for field in CONFIRM_REQUIRED_FIELDS if _is_blank(row.get(field))
            ]
            if missing:
                result.append({
                    "id": row.get("id"),
                    "链路编号": row.get("链路编号", ""),
                    "所属站点": row.get("所属站点", ""),
                    "链路状态": row.get("status", ""),
                    "missing_fields": missing,
                    "reason": f"缺少{'、'.join(missing)}",
                })
        return result

    def list_duplicates(self) -> list[dict[str, Any]]:
        """链路编号重复的记录成组点出来，供列表上做高亮定位。"""
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in store.rows(MODULE):
            code = str(row.get("链路编号", "")).strip()
            if not code:
                continue
            groups.setdefault(code, []).append(row)
        duplicates = []
        for code, rows in groups.items():
            if len(rows) > 1:
                duplicates.append({
                    "链路编号": code,
                    "ids": [row.get("id") for row in rows],
                    "count": len(rows),
                })
        return sorted(duplicates, key=lambda item: item["链路编号"])

    def get_stats(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """统计口径与列表筛选保持一致；缺报次数合计供页脚与卡片共用一个数。"""
        rows = self._filter_rows(keyword=keyword, status=status)
        return {
            "active_count": sum(1 for row in rows if row.get("status") != STOPPED_STATUS),
            "alarm_count": sum(1 for row in rows if row.get("status") == ALARM_STATUS),
            "missing_total": sum(_missing_count(row) for row in rows),
            "incomplete": self.list_incomplete(),
            "duplicates": self.list_duplicates(),
        }

    def batch_confirm_missing(
        self,
        items: list[dict[str, Any]],
        token: str | None = None,
    ) -> dict[str, Any]:
        """批量确认缺报：逐条校验逐条生效，已停用/信息不全/非缺报告警均拦下；
        同批重复 id 与同一令牌重复提交只生效一次；部分失败不影响已成功条目。"""
        if not items:
            return {
                "ok": False,
                "message": "未选择任何传输链路",
                "success_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "token": token,
                "results": [],
            }

        repeated_submit = bool(token) and token in self._used_tokens
        results: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        success = failed = skipped = 0

        for item in items:
            entry_id = item.get("id")
            decision = str(item.get("decision") or "").strip()

            if entry_id in seen_ids:
                skipped += 1
                results.append({
                    "id": entry_id,
                    "status": "skipped",
                    "decision": decision or None,
                    "message": "同一链路在本次提交中重复出现，只生效一次",
                    "entry": None,
                })
                continue
            seen_ids.add(entry_id)

            if repeated_submit:
                skipped += 1
                results.append({
                    "id": entry_id,
                    "status": "skipped",
                    "decision": decision or None,
                    "message": "该批确认已连续提交过，本次不再重复生效",
                    "entry": None,
                })
                continue

            row = store.find(MODULE, entry_id) if isinstance(entry_id, int) else None
            if row is None:
                failed += 1
                results.append({
                    "id": entry_id,
                    "status": "failed",
                    "decision": decision or None,
                    "message": f"传输链路 {entry_id} 不存在或已归档",
                    "entry": None,
                })
                continue

            if decision not in CONFIRM_DECISIONS:
                failed += 1
                results.append({
                    "id": entry_id,
                    "status": "failed",
                    "decision": decision or None,
                    "message": "确认意见只能是「通过」或「退回」",
                    "entry": None,
                })
                continue

            if row.get("status") == STOPPED_STATUS:
                failed += 1
                results.append({
                    "id": entry_id,
                    "status": "failed",
                    "decision": decision,
                    "message": "已停用链路不参与缺报批量确认",
                    "entry": None,
                })
                continue

            missing_fields = self._incomplete_reason(row)
            if missing_fields:
                failed += 1
                results.append({
                    "id": entry_id,
                    "status": "failed",
                    "decision": decision,
                    "message": f"缺少{'、'.join(missing_fields)}，请先补全链路信息",
                    "entry": None,
                })
                continue

            if row.get("status") != ALARM_STATUS:
                failed += 1
                results.append({
                    "id": entry_id,
                    "status": "failed",
                    "decision": decision,
                    "message": f"链路当前为「{row.get('status')}」，只有缺报告警链路需要确认",
                    "entry": None,
                })
                continue

            # 校验全部通过才写状态：通过即恢复正常上报并清零缺报；退回维持缺报告警
            if decision == "通过":
                row["status"] = "正常上报"
                row["链路状态"] = "正常上报"
                row["缺报次数"] = 0
                row["abnormal"] = False
            else:
                row["status"] = ALARM_STATUS
                row["链路状态"] = ALARM_STATUS
                row["abnormal"] = True
            row["pending"] = True
            row["确认结果"] = decision
            success += 1
            results.append({
                "id": entry_id,
                "status": "success",
                "decision": decision,
                "message": f"缺报确认{decision}已写入链路",
                "entry": dict(row),
            })

        if token and not repeated_submit:
            self._used_tokens.add(token)

        if success:
            message = f"批量确认完成：成功 {success} 条"
            if failed:
                message += f"，失败 {failed} 条（已保留成功结果）"
            if skipped:
                message += f"，跳过 {skipped} 条"
        elif skipped and not failed:
            message = f"本次提交未生效：{skipped} 条均为重复提交"
        else:
            message = f"批量确认未通过：失败 {failed} 条"
            if skipped:
                message += f"，跳过 {skipped} 条"

        return {
            "ok": success > 0,
            "message": message,
            "success_count": success,
            "failed_count": failed,
            "skipped_count": skipped,
            "token": token,
            "results": results,
        }
