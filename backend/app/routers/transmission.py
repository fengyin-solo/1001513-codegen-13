"""数据传输接口：维护传输链路，覆盖开通链路、确认恢复、停用链路等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchConfirmPayload, BatchConfirmResult, EntryPayload, PageResult
from app.services.transmission import TransmissionService

router = APIRouter(prefix="/api/transmission", tags=["数据传输"])

service = TransmissionService()

LIST_FIELDS = ["链路编号", "所属站点", "传输方式", "上报频次", "最近上报时刻", "缺报次数", "链路带宽", "链路状态"]
STATUSES = ["待开通", "正常上报", "缺报告警", "已停用"]


@router.get("/stats")
def stats() -> dict[str, int]:
    """缺报统计口径：列表页脚与统计卡片都从这儿取数，保证两边对得上。"""
    return service.stats()


@router.get("/incomplete")
def incomplete_entries() -> dict[str, Any]:
    """上报频次或最近上报时刻为空的链路单独列出，逐条说明缺了什么。"""
    items = service.incomplete_entries()
    return {"total": len(items), "items": items}


@router.get("/duplicates")
def duplicate_codes() -> dict[str, Any]:
    """链路编号重复的记录分组返回，前端按组点出来核对。"""
    items = service.duplicate_codes()
    return {"total": len(items), "items": items}


@router.post("/batch-confirm", response_model=BatchConfirmResult)
def batch_confirm(payload: BatchConfirmPayload) -> BatchConfirmResult:
    """批量确认缺报：逐条给出通过或退回；部分失败时保留已成功的条目。"""
    if not payload.items:
        return BatchConfirmResult(ok=False, message="请先勾选需要确认的传输链路", results=[])
    items = [{"id": item.id, "result": item.result} for item in payload.items]
    results = service.batch_confirm(items)
    succeeded = sum(1 for item in results if item["ok"])
    failed = len(results) - succeeded
    if failed:
        message = f"批量确认完成：成功 {succeeded} 条，失败 {failed} 条，已成功的条目不会回滚"
    else:
        message = f"批量确认完成：{succeeded} 条全部生效"
    return BatchConfirmResult(ok=failed == 0, message=message, results=results)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按链路编号检索"),
    status: str | None = Query(default=None, description="待开通、正常上报、缺报告警、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按链路编号与状态过滤数据传输列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条传输链路明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"传输链路 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条传输链路，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="传输链路已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条传输链路执行开通链路、确认恢复、停用链路；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据传输清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "transmission", "total": total, "items": items}
