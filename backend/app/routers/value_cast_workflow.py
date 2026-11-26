"""取值转型专用工作流接口：预览、正式批回执/恢复、更正、下载与正式成功值归一。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.services import service_for

router = APIRouter(prefix="/api/value_cast", tags=["取值转型工作流"])


def _service():
    service = service_for("value_cast")
    assert service is not None
    return service


async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        data = {}
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    return {"payload": data}


@router.post("/preview")
@router.post("/preview_cast")
@router.post("/cast-preview")
@router.post("/cast/preview")
@router.post("/actions/preview")
async def preview_cast(request: Request) -> dict[str, Any]:
    data = await _body(request)
    return _service().preview_cast(data)


@router.get("/formal-batches")
async def list_formal_batches(correlation_key: str = "", status: str = "") -> dict[str, Any]:
    items = _service().list_formal_batches(correlation_key=correlation_key, status=status)
    return {"ok": True, "items": items, "total": len(items)}


@router.post("/formal-batches")
@router.post("/formal_batches")
@router.post("/apply")
@router.post("/apply_formal_batch")
async def create_formal_batch(request: Request) -> dict[str, Any]:
    data = await _body(request)
    ok, message, batch = _service().create_formal_batch(data)
    return {"ok": ok, "message": message, "entry": batch, "batch": batch, "receipt": batch}


@router.post("/submit")
@router.post("/submit_cast")
@router.post("/commit")
@router.post("/commit_cast")
@router.post("/formal")
@router.post("/formal/submit")
@router.post("/formal-batches/submit")
async def submit_formal_batch(request: Request) -> dict[str, Any]:
    data = await _body(request)
    return _service().submit_formal_batch(data)


@router.post("/formal-batches/{formal_batch_no}/submit")
@router.post("/formal-batches/{formal_batch_no}/retry")
@router.post("/receipts/{formal_batch_no}/retry")
async def retry_formal_batch(formal_batch_no: str, request: Request) -> dict[str, Any]:
    data = await _body(request)
    data.setdefault("formal_batch_no", formal_batch_no)
    return _service().submit_formal_batch(data)


@router.post("/formal-batches/{formal_batch_no}/correct")
@router.post("/correct/{formal_batch_no}")
async def correct_formal_batch(formal_batch_no: str, request: Request) -> dict[str, Any]:
    data = await _body(request)
    data.pop("formal_batch_no", None)
    data.pop("batch_no", None)
    ok, message, batch = _service().correct_formal_batch(formal_batch_no, **data)
    return {"ok": ok, "message": message, "batch": batch, "receipt": batch}


@router.post("/formal-batches/{formal_batch_no}/handoff")
async def handoff_formal_batch(formal_batch_no: str, request: Request) -> dict[str, Any]:
    data = await _body(request)
    data.pop("formal_batch_no", None)
    ok, message, batch = _service().handoff_formal_batch(formal_batch_no, **data)
    return {"ok": ok, "message": message, "batch": batch}


@router.post("/formal-batches/{formal_batch_no}/dispose")
@router.post("/formal-batches/{formal_batch_no}/cancel")
async def dispose_formal_batch(formal_batch_no: str, request: Request) -> dict[str, Any]:
    data = await _body(request)
    data.pop("formal_batch_no", None)
    ok, message, batch = _service().dispose_formal_batch(formal_batch_no, **data)
    return {"ok": ok, "message": message, "batch": batch, "receipt": batch}


@router.post("/normalize")
@router.post("/normalize_formal_batch")
@router.post("/unit-normalize")
async def normalize_formal_batch(request: Request) -> dict[str, Any]:
    data = await _body(request)
    batch_no = str(data.get("formal_batch_no") or data.get("batch_no") or "")
    return _service().normalize_formal_batch(batch_no, **{k: v for k, v in data.items()
                                                           if k not in ("formal_batch_no", "batch_no")})


@router.get("/formal-batches/{formal_batch_no}")
@router.get("/formal_batches/{formal_batch_no}")
@router.get("/receipts/{formal_batch_no}")
@router.get("/receipt/{formal_batch_no}")
@router.get("/recovery/{formal_batch_no}")
async def get_receipt(formal_batch_no: str) -> dict[str, Any]:
    batch = _service().get_formal_batch(formal_batch_no)
    return {"ok": batch is not None, "entry": batch, "batch": batch, "receipt": batch}


@router.get("/formal-batches/{formal_batch_no}/history")
@router.get("/history/{formal_batch_no}")
async def get_history(formal_batch_no: str) -> dict[str, Any]:
    rows = _service().get_cast_history(formal_batch_no)
    return {"ok": True, "items": rows, "total": len(rows)}


@router.get("/formal-batches/{formal_batch_no}/download")
@router.get("/receipts/{formal_batch_no}/download")
@router.get("/download/{formal_batch_no}")
async def download(formal_batch_no: str) -> Response:
    filename, content, media_type = _service().download_formal_batch(formal_batch_no)
    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
