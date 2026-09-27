"""数据传输业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "transmission"
REQUIRED_FIELDS = ["链路编号", "所属站点", "传输方式"]
STATUS_ORDER = ["待开通", "正常上报", "缺报告警", "已停用"]
ACTION_RULES = {"开通链路": "正常上报", "确认恢复": "缺报告警", "停用链路": "已停用"}
NEGATIVE_ACTIONS = ["停用链路"]

# 批量确认只允许这两种结论；已停用状态不参与批量确认。
CONFIRM_RESULTS = ["通过", "退回"]
DISABLED_STATUS = "已停用"
# 缺报链路的关键字段：为空时无法判断缺报情况，需要单独列出。
REPORT_FIELDS = ["上报频次", "最近上报时刻"]


def _missing_count(row: dict[str, Any]) -> int:
    """把「缺报次数」解析成整数；历史脏数据按 0 计，不拖垮合计。"""
    try:
        return int(str(row.get("缺报次数") or "0").strip())
    except ValueError:
        return 0


class TransmissionService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("链路编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
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
        return entry, f"传输链路已{action}"

    def stats(self) -> dict[str, int]:
        """列表页脚与统计卡片共用的缺报口径，保证两处数字对得上。"""
        rows = store.rows(MODULE)
        return {
            "在用链路": sum(1 for row in rows if row.get("status") != DISABLED_STATUS),
            "缺报链路": sum(1 for row in rows if row.get("status") == "缺报告警"),
            "缺报次数合计": sum(_missing_count(row) for row in rows),
        }

    def incomplete_entries(self) -> list[dict[str, Any]]:
        """上报频次或最近上报时刻为空的链路，逐条说明缺了什么。"""
        result = []
        for row in store.rows(MODULE):
            missing = [field for field in REPORT_FIELDS if not str(row.get(field) or "").strip()]
            if missing:
                result.append({**row, "缺失字段": missing})
        return result

    def duplicate_codes(self) -> list[dict[str, Any]]:
        """按链路编号分组，挑出重复编号的记录，方便值班室逐组点出来核对。"""
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in store.rows(MODULE):
            code = str(row.get("链路编号") or "").strip()
            if code:
                groups.setdefault(code, []).append(row)
        return [
            {"链路编号": code, "重复条数": len(rows), "记录ID": [int(row.get("id", 0)) for row in rows]}
            for code, rows in groups.items()
            if len(rows) > 1
        ]

    def batch_confirm(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """逐条确认缺报：通过或退回都写进链路记录；单条失败不影响其他条目。

        幂等口径：同一链路的缺报次数与确认结论和上一次完全一致时，视为重复提交，
        只回执不重复生效；缺报次数变化（新一轮缺报）后允许再次确认。
        """
        results: list[dict[str, Any]] = []
        for item in items:
            entry_id = item.get("id")
            conclusion = str(item.get("result") or "").strip()
            label = f"链路 {entry_id}"
            entry = None
            if isinstance(entry_id, int):
                entry = store.find(MODULE, entry_id)
            if entry is None:
                results.append({"id": entry_id, "ok": False, "message": f"{label} 不存在或已归档"})
                continue
            label = str(entry.get("链路编号") or label)
            if entry.get("status") == DISABLED_STATUS:
                results.append({"id": entry_id, "ok": False, "message": f"{label} 已停用，不参与批量确认"})
                continue
            if conclusion not in CONFIRM_RESULTS:
                results.append({"id": entry_id, "ok": False, "message": f"{label} 的确认结论「{conclusion}」无效，只能是通过或退回"})
                continue
            fingerprint = f"{_missing_count(entry)}:{conclusion}"
            if entry.get("confirm_fingerprint") == fingerprint:
                results.append({"id": entry_id, "ok": True, "message": f"{label} 已确认过相同结论，本次自动忽略，不重复生效"})
                continue
            entry["缺报确认结果"] = conclusion
            entry["确认时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry["confirm_fingerprint"] = fingerprint
            if conclusion == "通过":
                entry["status"] = "正常上报"
                entry["链路状态"] = "正常上报"
                entry["pending"] = False
                entry["abnormal"] = False
            else:
                entry["status"] = "缺报告警"
                entry["链路状态"] = "缺报告警"
                entry["pending"] = True
                entry["abnormal"] = True
            results.append({"id": entry_id, "ok": True, "message": f"{label} 缺报确认{conclusion}，已写入链路列表"})
        return results
