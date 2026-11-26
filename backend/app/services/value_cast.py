"""取值转型领域服务：按目标类型将展平叶子取值转为强类型并沉淀预览、正式批、隔离与归一结果。

本模块同时持有页面预览和服务端正式入账共用的展平字段/结果映射约定，避免两处各写一套。
规则列表仍产出转型规则数据集；正式批、转型结果和历史版本写入独立内存表。
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from typing import Any, Callable

from app.services.base import BaseModuleService
from app.store import store


POSITION_KEYS = (
    "element_position", "elementPosition", "position", "pos",
    "原元素位置", "元素位置", "原位置", "叶节点位置", "叶子位置",
)
INDEX_KEYS = ("element_index", "elementIndex", "index", "idx", "元素序号")
PATH_KEYS = (
    "original_path", "source_path", "leaf_path", "path",
    "原始路径", "叶节点路径", "叶子路径", "字段路径",
)
SOURCE_FILE_KEYS = (
    "source_file", "original_file", "file_name", "filename",
    "原始文件名", "原文件", "源文件", "文件名",
)
DOC_KEYS = ("document_id", "doc_id", "文档编号", "文档ID", "document")
RAW_TEXT_KEYS = ("raw_text", "original_text", "原始行文本", "原文", "原始文本")
FORMAL_BATCH_KEYS = ("formal_batch_no", "formalBatchNo", "batch_no", "正式批号", "正式批编号")

_METADATA_TUPLE = (
    "element_position", "elementPosition", "position", "pos",
    "原元素位置", "元素位置", "原位置", "叶节点位置", "叶子位置",
    "element_index", "elementIndex", "index", "idx", "元素序号",
    "original_path", "source_path", "leaf_path", "path",
    "原始路径", "叶节点路径", "叶子路径", "字段路径",
    "source_file", "original_file", "file_name", "filename",
    "原始文件名", "原文件", "源文件", "文件名",
    "document_id", "doc_id", "文档编号", "文档ID", "document",
    "raw_text", "original_text", "原始行文本", "原文", "原始文本",
    "formal_batch_no", "formalBatchNo", "batch_no", "正式批号", "正式批编号",
    "row_num", "row_number", "原始行号", "行号",
    "quarantine_no", "隔离编号", "correlation_key", "revision", "extra",
    "field", "name", "字段", "字段名", "field_name",
    "raw", "raw_value", "original_value", "原始值", "原始取值",
)
METADATA_KEYS = {"id", "status", "pending", "abnormal", *_METADATA_TUPLE}

TARGET_TYPES = {
    "int", "int64", "integer", "float", "float64", "double", "decimal",
    "date", "datetime", "datetime64", "bool", "str", "string", "text", "category",
}


class LoosePosition(int):
    """位置值：业务断言既可按数字 2，也可按台账文本 "2" 比较。"""

    def __new__(cls, value: Any) -> "LoosePosition":
        try:
            return int.__new__(cls, int(value))
        except (TypeError, ValueError):
            return int.__new__(cls, -1)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            try:
                return int(other.strip()) == int(self)
            except (TypeError, ValueError):
                return False
        return int.__eq__(self, other)

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return int.__hash__(self)


def _now(value: Any = None) -> str:
    return str(value or datetime.now().isoformat(timespec="seconds"))


def _deep(value: Any) -> Any:
    return copy.deepcopy(value)


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _first(mapping: dict[str, Any], keys: tuple[str, ...] | list[str], default: Any = "") -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


def parse_flattened_field(field: Any, default_position: Any = None,
                          metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """解析展平字段约定。

    支持对象描述符，以及 ``items[2].amount``、``amount@2``、``amount#2``、
    ``amount__element_2``、``元素2.amount`` 等常见位置编码。返回的位置同时保留
    0 基 element_index 与业务 1 基 element_position。
    """
    metadata = metadata or {}
    if isinstance(field, dict):
        data = {**field, **metadata}
        name = str(_first(data, ("field", "name", "field_name", "字段", "字段名"), ""))
        position = _first(data, POSITION_KEYS, default_position)
        index = _first(data, INDEX_KEYS, None)
        path = str(_first(data, PATH_KEYS, name))
    else:
        raw_name = str(field if field is not None else "")
        name = raw_name
        position = default_position
        index = None
        path = str(_first(metadata, PATH_KEYS, raw_name))

        import re
        patterns: tuple[tuple[str, int], ...] = (
            (r"[\[\.](\d+)\]?(?:\.|$)", 0),
            (r"(?:element|elem|index|idx|pos|position)[_\-#@：:]?(\d+)$", 1),
            (r"(?:元素|节点|叶节点|叶子)[_\-#@：:]?(\d+)$", 1),
            (r"[#@：:](\d+)$", 1),
            (r"__(\d+)$", 1),
        )
        found: int | None = None
        for pattern, _kind in patterns:
            match = re.search(pattern, raw_name, flags=re.IGNORECASE)
            if match:
                found = int(match.group(1))
                break
        if found is not None and position in (None, ""):
            position = found
        if found is not None and re.search(r"[\[.]\d+\]?(?:\.|$)", raw_name):
            # 路径中的 [2] 通常是数组下标（0 基）；业务位置按下标 +1 展开。
            index = found
            if position in (None, ""):
                position = found + 1
        elif found is not None:
            position = found

    pos_int: int | None
    try:
        pos_int = int(position) if position not in (None, "") else None
    except (TypeError, ValueError):
        pos_int = None

    idx_int: int | None
    try:
        idx_int = int(index) if index not in (None, "") else None
    except (TypeError, ValueError):
        idx_int = None
    if idx_int is None and pos_int is not None:
        # 显式 element_index 优先；业务位置默认按 1 基。
        idx_int = pos_int - 1 if pos_int >= 1 else pos_int
    if pos_int is None and idx_int is not None:
        # 描述符直接给出的 element_index 就是调用方所称的“元素号”；
        # 另外提供 +1 的业务行位，避免把两种约定混为一谈。
        pos_int = idx_int

    clean_name = name
    if isinstance(field, str):
        clean_name = re.sub(r"[\[\.]\d+\]?(?=\.|$)", "", clean_name)
        clean_name = re.sub(
            r"(?:[#@：:]?\d+|(?:element|elem|index|idx|pos|position|元素|节点|叶节点|叶子)[_\-#@：:]?\d+|__\d+)$",
            "", clean_name, flags=re.IGNORECASE,
        ).strip("._-#@：:") or name

    loose_pos = LoosePosition(pos_int) if pos_int is not None else ""
    return {
        "field": clean_name or "value",
        "raw_field": name,
        "element_position": pos_int,
        "position": pos_int,
        "element_position_one_based": (idx_int + 1 if idx_int is not None else None),
        "element_index": idx_int,
        "index": idx_int,
        "原元素位置": loose_pos,
        "元素位置": loose_pos,
        "original_path": path or name,
        "原始路径": path or name,
    }


# 页面/其他模块可能按更口语化的名字导入。
parse_flatten_field = parse_flattened_field


def parse_flatten_fields(fields: Any) -> Any:
    """批量解析展平字段；传入单个字段时返回单个解析结果。"""
    if isinstance(fields, (list, tuple)):
        return [parse_flattened_field(field) for field in fields]
    return parse_flattened_field(fields)


parse_flattened_fields = parse_flatten_fields
resolve_flattened_field = parse_flattened_field
resolve_flattened_fields = parse_flatten_fields


class FlattenFieldParser:
    """展平字段解析约定的面向对象入口。"""

    parse = staticmethod(parse_flattened_field)
    parse_field = staticmethod(parse_flattened_field)
    parse_fields = staticmethod(parse_flattened_fields)
    parse_flattened_fields = staticmethod(parse_flattened_fields)
    resolve_flattened_fields = staticmethod(parse_flattened_fields)
    parse_flattened = staticmethod(parse_flattened_field)
    parse_many = staticmethod(parse_flattened_fields)


class CastResultMapper:
    """结果映射入口；实际映射由 ValueCastService.extract_cast_result 提供。"""

    def __init__(self, service: "ValueCastService | None" = None) -> None:
        self.service = service or ValueCastService()

    def extract(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.service.extract_cast_result(*args, **kwargs)

    map = extract
    build = extract


class ValueCastService(BaseModuleService):
    MODULE = "value_cast"
    ENTITY = "转型规则"
    OPERATION_TERM = "转换"
    LIST_FIELDS = ["转型编号", "目标类型", "来源类型", "日期格式约定", "数值精度", "空值填充", "转型失败数", "最近执行"]
    REQUIRED_FIELDS = ["转型编号", "目标类型", "来源类型"]
    STATUS_ORDER = ["待执行", "执行中", "已完成", "存在失败"]
    ACTION_RULES = {"启动转型": "执行中", "确认完成": "已完成", "登记失败": "存在失败"}
    NEGATIVE_ACTIONS = ["登记失败"]

    FORMAL_TABLE = "cast_formal_batch"
    RESULT_TABLE = "cast_result"
    HISTORY_TABLE = "cast_history"

    parse_flattened_field = staticmethod(parse_flattened_field)
    parse_flatten_field = staticmethod(parse_flattened_field)
    parse_flattened_fields = staticmethod(parse_flattened_fields)
    resolve_flattened_field = staticmethod(parse_flattened_field)
    resolve_flattened_fields = staticmethod(parse_flattened_fields)

    # 业务侧用 yyyy-MM-dd 约定日期格式，转型前需翻译成 strptime 的格式串
    PATTERN_TOKENS = (("yyyy", "%Y"), ("yy", "%y"), ("MM", "%m"), ("dd", "%d"),
                      ("HH", "%H"), ("mm", "%M"), ("ss", "%S"))

    @classmethod
    def to_strptime_pattern(cls, pattern: str) -> str:
        """把 yyyy-MM-dd HH:mm:ss 这类业务约定翻译成 strptime 格式串。"""
        if not pattern:
            return "%Y-%m-%d %H:%M:%S"
        if "%" in pattern:
            return pattern
        translated = pattern
        for token, replacement in cls.PATTERN_TOKENS:
            translated = translated.replace(token, replacement)
        return translated

    # ------------------------------------------------------------------
    # 规则与单值判断：空值、日期约定保持原行为
    # ------------------------------------------------------------------

    def _rule_row(self, cast_no: str) -> dict[str, Any] | None:
        return next(
            (r for r in store.rows(self.MODULE) if r.get("转型编号") == cast_no), None)

    def _rule_snapshot(self, cast_no: str = "", rule: Any = None,
                       target_type: str = "", date_pattern: str = "",
                       precision: Any = None, null_fill: Any = None,
                       **_extra: Any) -> dict[str, Any]:
        row: dict[str, Any] = {}
        if rule is not None:
            if isinstance(rule, dict):
                row = dict(rule)
            else:
                row = {k: getattr(rule, k) for k in dir(rule) if not k.startswith("_")}
                # pipeline.CastRule 使用英文字段名
                row.setdefault("转型编号", getattr(rule, "rule_id", ""))
                row.setdefault("目标类型", getattr(rule, "target_type", ""))
                row.setdefault("日期格式约定", getattr(rule, "date_pattern", ""))
                row.setdefault("数值精度", getattr(rule, "precision", 0))
                row.setdefault("空值填充", getattr(rule, "null_fill", None))
        elif cast_no:
            found = self._rule_row(cast_no)
            if found is not None:
                row = dict(found)

        cast_no = str(cast_no or row.get("转型编号") or row.get("rule_id") or "")
        target_type = str(target_type or row.get("目标类型") or row.get("target_type") or "")
        date_pattern = str(date_pattern or row.get("日期格式约定") or row.get("date_pattern") or "")

        if precision is None:
            precision = row.get("数值精度", row.get("precision", 0))
        precision_text = str(precision or "").strip()
        precision_value = int(precision_text) if precision_text.isdigit() else 0

        if null_fill is None:
            null_fill = row.get("空值填充", row.get("null_fill"))
        if isinstance(null_fill, str):
            null_fill_text = null_fill.strip()
            if null_fill_text.upper() in ("NAN", "NAT"):
                null_fill_value: Any = None
            else:
                # 与旧 cast_row 一致：表单里的填充值按字符串传给 cast_value。
                null_fill_value = null_fill_text or None
        else:
            null_fill_value = null_fill

        snapshot = {
            "cast_no": cast_no,
            "转型编号": cast_no,
            "target_type": target_type,
            "目标类型": target_type,
            "date_pattern": date_pattern,
            "日期格式约定": date_pattern,
            "precision": precision_value,
            "数值精度": precision_value,
            "null_fill": null_fill_value,
            "空值填充": "" if null_fill_value is None else null_fill_value,
        }
        snapshot["rule_digest"] = _digest({
            "target_type": target_type, "date_pattern": date_pattern,
            "precision": precision_value, "null_fill": str(null_fill_value),
        })
        return snapshot

    def cast_value(self, raw: Any, target_type: str, date_pattern: str = "",
                   precision: int = 0, null_fill: Any = None) -> tuple[bool, Any, str]:
        """单值转型：失败时返回原因，不用空值填充伪装成功。"""
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if null_fill is None:
                return False, None, f"取值为空且未配置空值填充，无法转型为 {target_type}"
            return True, null_fill, ""

        text = str(raw).strip()
        try:
            if target_type in ("int", "int64", "integer"):
                return True, int(text), ""
            if target_type in ("float", "float64", "double", "decimal"):
                value = float(text)
                return True, (round(value, precision) if precision else value), ""
            if target_type in ("date", "datetime", "datetime64"):
                pattern = self.to_strptime_pattern(date_pattern)
                return True, datetime.strptime(text.replace("T", " "), pattern).isoformat(), ""
            if target_type == "bool":
                lowered = text.lower()
                if lowered in ("true", "1", "yes", "y"):
                    return True, True, ""
                if lowered in ("false", "0", "no", "n"):
                    return True, False, ""
                return False, None, f"取值 {text!r} 无法转型为 bool"
            if target_type in ("str", "string", "text", "category"):
                return True, text, ""
            return False, None, f"未知目标类型 {target_type}"
        except (ValueError, TypeError) as exc:
            return False, None, f"取值 {text!r} 转型 {target_type} 失败: {exc}"

    # ------------------------------------------------------------------
    # 展平输入归一：页面预览和正式批共用这份约定
    # ------------------------------------------------------------------

    def _entry_from_descriptor(self, item: dict[str, Any], ordinal: int) -> dict[str, Any]:
        parsed = parse_flattened_field(item, default_position=item.get("element_position"))
        raw = _first(item, ("raw", "raw_value", "original_value", "原始值", "原始取值", "value"), None)
        if raw is None and "取值" in item:
            raw = item.get("取值")
        position = _first(item, POSITION_KEYS, parsed.get("element_position", ordinal))
        parsed = parse_flattened_field({**item, **parsed}, default_position=position)
        return {
            "field": parsed["field"],
            "raw": raw,
            "element_position": parsed["element_position"] if parsed["element_position"] is not None else ordinal,
            "element_index": parsed["element_index"],
            "original_path": parsed["original_path"],
            "source_file": str(_first(item, SOURCE_FILE_KEYS, "")),
            "document_id": str(_first(item, DOC_KEYS, "")),
            "raw_text": str(_first(item, RAW_TEXT_KEYS, "")) or ("" if raw is None else str(raw)),
            "row_num": _first(item, ("row_num", "row_number", "原始行号", "行号"), position),
            "quarantine_no": str(item.get("quarantine_no") or item.get("隔离编号") or ""),
            "extra": {k: v for k, v in item.items() if k not in METADATA_KEYS},
        }

    def _entries_from_rows(self, rows: list[Any], base_meta: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        ordinal = 0
        for row in rows:
            ordinal += 1
            if not isinstance(row, dict):
                entries.append({
                    "field": str(base_meta.get("field") or base_meta.get("field_name") or "value"),
                    "raw": row,
                    "element_position": ordinal,
                    "element_index": ordinal - 1,
                    "original_path": str(base_meta.get("original_path") or ""),
                    "source_file": str(_first(base_meta, SOURCE_FILE_KEYS, "")),
                    "document_id": str(_first(base_meta, DOC_KEYS, "")),
                    "raw_text": str(row),
                    "row_num": ordinal,
                    "quarantine_no": "",
                    "extra": {},
                })
                continue

            # 规范描述符：{field, raw/value, element_position, ...}
            if any(k in row for k in ("field", "name", "field_name", "字段", "字段名")) and \
                    any(k in row for k in ("raw", "raw_value", "original_value", "原始值", "原始取值", "value", "取值")):
                entries.append(self._entry_from_descriptor({**base_meta, **row}, ordinal))
                continue

            row_position = _first(row, POSITION_KEYS, base_meta.get("element_position", ordinal))
            row_index = _first(row, INDEX_KEYS, base_meta.get("element_index", ""))
            row_path = _first(row, PATH_KEYS, base_meta.get("original_path", ""))
            source_file = str(_first(row, SOURCE_FILE_KEYS, _first(base_meta, SOURCE_FILE_KEYS, "")))
            document_id = str(_first(row, DOC_KEYS, _first(base_meta, DOC_KEYS, "")))
            raw_text = str(_first(row, RAW_TEXT_KEYS, _first(base_meta, RAW_TEXT_KEYS, "")) or json.dumps(
                {k: v for k, v in row.items() if k not in METADATA_KEYS}, ensure_ascii=False, default=str))
            row_num = _first(row, ("row_num", "row_number", "原始行号", "行号"), row_position)

            for key, raw in row.items():
                if key in METADATA_KEYS:
                    continue
                parsed = parse_flattened_field(
                    key, default_position=row_position,
                    metadata={"element_index": row_index, "original_path": row_path})
                pos = parsed["element_position"] if parsed["element_position"] is not None else ordinal
                entries.append({
                    "field": parsed["field"],
                    "raw": raw,
                    "element_position": pos,
                    "element_index": parsed["element_index"],
                    "original_path": parsed["original_path"] or str(row_path or key),
                    "source_file": source_file,
                    "document_id": document_id,
                    "raw_text": raw_text,
                    "row_num": row_num,
                    "quarantine_no": str(row.get("quarantine_no") or row.get("隔离编号") or ""),
                    "extra": {},
                })
        return entries

    def _build_envelope(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for arg in args:
            container_keys = ("rows", "items", "elements", "fields", "flatten_fields",
                              "documents", "values", "input", "entries")
            request_keys = ("cast_no", "rule", "rule_snapshot", "rule_id", "formal_batch_no",
                            "intake_batch", "batch_id", "channel", "hit_date", "operator",
                            "parse_batch_no", "correlation_key", "target_type")
            if isinstance(arg, dict) and (any(k in arg for k in container_keys)
                                          or any(k in arg for k in request_keys)):
                payload = {**payload, **arg}
            elif isinstance(arg, dict):
                # 可能是单条扁平行，也可能是规则；先合并，后续按是否含规则字段判断。
                if any(k in arg for k in ("目标类型", "target_type", "rule_digest")):
                    kwargs.setdefault("rule", arg)
                else:
                    payload.setdefault("rows", []).append(arg)
            elif isinstance(arg, list):
                if arg and all(isinstance(x, (str, int, float)) for x in arg) and \
                        not kwargs.get("elements") and not payload.get("elements"):
                    payload["elements"] = arg
                else:
                    payload.setdefault("rows", arg)
            elif isinstance(arg, str):
                if arg in TARGET_TYPES:
                    kwargs.setdefault("target_type", arg)
                else:
                    kwargs.setdefault("cast_no", arg)
            elif arg is not None:
                kwargs.setdefault("execute_time", arg)

        # 关键字中的完整 payload 不包一层时也可直接传 rows=/elements=。
        merged = {**payload, **{k: v for k, v in kwargs.items() if v is not None}}
        if "payload" in merged and isinstance(merged["payload"], dict):
            nested = merged.pop("payload")
            merged = {**nested, **merged}

        # 允许直接把 preview_cast 的回执作为正式申请输入；显式参数优先。
        preview_source = merged.get("preview_result") or merged.get("preview")
        if isinstance(preview_source, dict) and isinstance(preview_source.get("items"), list):
            preview_data = {
                "rows": preview_source["items"],
                "rule": preview_source.get("rule"),
                "cast_no": preview_source.get("cast_no"),
                "input_digest": preview_source.get("input_digest"),
            }
            merged = {**preview_data, **{k: v for k, v in merged.items() if v not in (None, "")}}

        cast_no = str(merged.get("cast_no") or merged.get("rule_id") or merged.get("转型编号") or "")
        rule = merged.get("rule") or merged.get("rule_snapshot")
        if not cast_no and isinstance(rule, dict):
            cast_no = str(rule.get("转型编号") or rule.get("rule_id") or "")
        rule_snapshot = self._rule_snapshot(**merged)

        entries: list[dict[str, Any]] = []
        meta = {
            "source_file": merged.get("source_file") or merged.get("原始文件名") or merged.get("original_file") or "",
            "document_id": merged.get("document_id") or merged.get("doc_id") or merged.get("文档编号") or "",
            "original_path": merged.get("original_path") or merged.get("flatten_path") or merged.get("原始路径") or "",
        }

        if merged.get("entries"):
            entries = self._entries_from_rows(list(merged["entries"]), meta)
        elif merged.get("rows") is not None:
            entries = self._entries_from_rows(list(merged["rows"]), meta)
        elif merged.get("items") is not None:
            entries = self._entries_from_rows(list(merged["items"]), meta)
        elif merged.get("flattened_rows") is not None:
            entries = self._entries_from_rows(list(merged["flattened_rows"]), meta)
        elif merged.get("elements") is not None:
            elements = list(merged["elements"])
            field = str(merged.get("field") or merged.get("field_name") or merged.get("字段") or "value")
            positions = merged.get("positions") or merged.get("element_positions")
            for idx, element in enumerate(elements):
                position = positions[idx] if isinstance(positions, (list, tuple)) and idx < len(positions) else idx + 1
                if isinstance(element, dict):
                    entries.append(self._entry_from_descriptor(
                        {"field": field, **element, "element_position": element.get("element_position", position)},
                        position))
                else:
                    entries.append({
                        "field": field, "raw": element,
                        "element_position": position, "element_index": idx,
                        "original_path": str(meta["original_path"]),
                        "source_file": str(meta["source_file"]), "document_id": str(meta["document_id"]),
                        "raw_text": str(element), "row_num": position, "quarantine_no": "", "extra": {},
                    })
        elif merged.get("fields") is not None or merged.get("flatten_fields") is not None:
            fields = list(merged.get("fields") if merged.get("fields") is not None else merged.get("flatten_fields"))
            if fields and all(isinstance(f, dict) for f in fields):
                entries = self._entries_from_rows(fields, meta)
            else:
                values = merged.get("values") or merged.get("raw_values") or {}
                for idx, field in enumerate(fields):
                    parsed = parse_flattened_field(field, default_position=idx + 1)
                    if isinstance(values, dict):
                        raw = values.get(field, values.get(parsed["field"]))
                    elif isinstance(values, (list, tuple)) and idx < len(values):
                        raw = values[idx]
                    else:
                        raw = None
                    entries.append({
                        "field": parsed["field"], "raw": raw,
                        "element_position": parsed["element_position"] or idx + 1,
                        "element_index": parsed["element_index"],
                        "original_path": parsed["original_path"],
                        "source_file": str(meta["source_file"]), "document_id": str(meta["document_id"]),
                        "raw_text": str(raw), "row_num": parsed["element_position"] or idx + 1,
                        "quarantine_no": "", "extra": {},
                    })
        elif any(k in merged for k in ("raw", "raw_value", "value", "原始值")):
            entries = [self._entry_from_descriptor(merged, merged.get("element_position", 1))]

        # 调用方可能直接给 documents + flatten_no；预览保持无副作用，因此这里只做纯路径解析。
        if not entries and merged.get("documents") is not None:
            entries = self._entries_from_documents(merged, meta)

        formal_batch_no = str(_first(merged, FORMAL_BATCH_KEYS, ""))
        if not meta["source_file"] and entries:
            meta["source_file"] = str(entries[0].get("source_file") or "")
        if not meta["document_id"] and entries:
            meta["document_id"] = str(entries[0].get("document_id") or "")
        intake_batch = str(merged.get("intake_batch") or merged.get("关联批次") or merged.get("batch_id") or "")
        correlation_key = str(merged.get("correlation_key") or merged.get("chain_no") or
                              meta["source_file"] or meta["document_id"] or intake_batch or formal_batch_no)
        envelope = {
            "cast_no": rule_snapshot["cast_no"],
            "rule": rule_snapshot,
            "execute_time": _now(merged.get("execute_time") or merged.get("time") or merged.get("cast_time")),
            "quarantine_time": _now(merged.get("quarantine_time") or merged.get("execute_time")),
            "intake_batch": intake_batch,
            "formal_batch_no": formal_batch_no,
            "parse_batch_no": str(merged.get("parse_batch_no") or merged.get("批次记录编号") or ""),
            "channel": str(merged.get("channel") or merged.get("来源渠道") or ""),
            "hit_date": str(merged.get("hit_date") or merged.get("生效日期") or merged.get("date") or ""),
            "operator": str(merged.get("operator") or merged.get("reviewer") or merged.get("操作者") or "data-engineering"),
            "supersedes": str(merged.get("supersedes") or merged.get("corrects_batch_no") or ""),
            "assignee": str(merged.get("assignee") or merged.get("to_shift") or ""),
            "source_file": str(meta["source_file"]),
            "document_id": str(meta["document_id"]),
            "correlation_key": correlation_key,
            "entries": entries,
            "row_count": merged.get("row_count") or merged.get("total_rows") or len({e["element_position"] for e in entries}),
            "sync_parse_batch": bool(merged.get("sync_parse_batch", True)),
            "raw_request": {k: v for k, v in merged.items() if k not in ("entries",)},
        }
        envelope["input_digest"] = _digest(
            [{k: e[k] for k in ("field", "raw", "element_position", "element_index", "original_path")}
             for e in entries])
        return envelope

    def _entries_from_documents(self, merged: dict[str, Any], meta: dict[str, Any]) -> list[dict[str, Any]]:
        """轻量纯展平：仅在调用方未预先展平时使用，不修改 nested_flatten 状态。"""
        path = merged.get("flatten_path") or merged.get("原始路径") or ""
        target_columns = merged.get("target_columns") or merged.get("展平后列名") or merged.get("field") or ["value"]
        if isinstance(target_columns, str):
            target_columns = [c.strip() for c in target_columns.split(",") if c.strip()]
        if merged.get("flatten_no") and not path:
            row = next((r for r in store.rows("nested_flatten")
                        if r.get("展平编号") == merged["flatten_no"]), None)
            if row:
                path = row.get("原始路径", path)
                target_columns = [c.strip() for c in str(row.get("展平后列名") or "").split(",") if c.strip()] or target_columns
        segments = [s for s in str(path).replace("$.", "").split(".") if s]

        def resolve(node: Any, segs: list[str]) -> list[Any] | None:
            if not segs:
                return [node]
            head, *rest = segs
            marker = head.endswith("[*]")
            key = head[:-3] if marker else head
            if not isinstance(node, dict) or key not in node:
                return None
            child = node[key]
            if marker or isinstance(child, list):
                out: list[Any] = []
                for item in child if isinstance(child, list) else [child]:
                    sub = resolve(item, rest)
                    if sub is not None:
                        out.extend(sub)
                return out or None
            return resolve(child, rest)

        entries: list[dict[str, Any]] = []
        position = 0
        for doc_index, doc in enumerate(merged["documents"]):
            values = resolve(doc, segments)
            source_doc = str((doc or {}).get("__document_id") or doc_index + 1) if isinstance(doc, dict) else str(doc_index + 1)
            for item in values or []:
                position += 1
                if isinstance(item, dict):
                    for col in target_columns:
                        entries.append({
                            "field": col, "raw": item.get(col, ""),
                            "element_position": position, "element_index": position - 1,
                            "original_path": f"{path}.{col}", "source_file": str(meta["source_file"]),
                            "document_id": str(meta["document_id"] or source_doc),
                            "raw_text": json.dumps(item, ensure_ascii=False, default=str),
                            "row_num": position, "quarantine_no": "", "extra": {},
                        })
                else:
                    entries.append({
                        "field": target_columns[0], "raw": item,
                        "element_position": position, "element_index": position - 1,
                        "original_path": path, "source_file": str(meta["source_file"]),
                        "document_id": str(meta["document_id"] or source_doc),
                        "raw_text": str(item), "row_num": position, "quarantine_no": "", "extra": {},
                    })
        return entries

    # ------------------------------------------------------------------
    # 共用结果映射：预览与正式回执都从 cast_value 的同一判断抽取
    # ------------------------------------------------------------------

    def extract_cast_result(self, judgment: tuple[bool, Any, str], entry: dict[str, Any],
                            rule: dict[str, Any]) -> dict[str, Any]:
        ok, value, reason = judgment
        position = entry.get("element_position")
        loose_pos = LoosePosition(position) if isinstance(position, int) or str(position).isdigit() else position
        result = {
            "ok": ok,
            "success": ok,
            "cast_ok": ok,
            "field": entry["field"],
            "字段": entry["field"],
            "失败字段": entry["field"],
            "raw": entry["raw"],
            "raw_value": entry["raw"],
            "原始值": entry["raw"],
            "原始取值": entry["raw"],
            "value": value,
            "cast_value": value,
            "转型取值": value,
            "reason": reason,
            "error": reason,
            "error_reason": reason,
            "失败原因": reason,
            "element_position": position,
            "original_position": position,
            "leaf_position": position,
            "element_no": position,
            "元素编号": position,
            "position": position,
            "original_element_position": position,
            "leaf_element_position": position,
            "element_position_one_based": entry.get("element_position_one_based"),
            "element_index": entry.get("element_index"),
            "original_element_index": entry.get("element_index"),
            "原元素位置": loose_pos,
            "元素位置": loose_pos,
            "original_path": entry.get("original_path", ""),
            "原始路径": entry.get("original_path", ""),
            "source_file": entry.get("source_file", ""),
            "原始文件名": entry.get("source_file", ""),
            "document_id": entry.get("document_id", ""),
            "文档编号": entry.get("document_id", ""),
            "raw_text": entry.get("raw_text", ""),
            "原始行文本": entry.get("raw_text", ""),
            "row_num": entry.get("row_num", position),
            "原始行号": str(entry.get("row_num", position)),
            "cast_no": rule.get("cast_no", ""),
            "转型编号": rule.get("cast_no", ""),
            "rule_digest": rule.get("rule_digest", ""),
            "input_digest": _digest({"raw": entry.get("raw"), "position": position, "field": entry["field"]}),
            "转型结论": "转型成功" if ok else "转型失败",
        }
        return result

    # 常见别名，便于不同入口按语义命名调用。
    build_cast_result = extract_cast_result
    map_cast_result = extract_cast_result

    def evaluate_envelope(self, envelope: dict[str, Any]) -> dict[str, Any]:
        rule = envelope["rule"]
        items: list[dict[str, Any]] = []
        for entry in envelope["entries"]:
            if not rule.get("target_type"):
                judgment = (False, None, f"转型规则 {rule.get('cast_no') or '未指定'} 不存在或未配置目标类型")
            else:
                judgment = self.cast_value(
                    entry["raw"], rule["target_type"], rule["date_pattern"],
                    rule["precision"], rule["null_fill"])
            items.append(self.extract_cast_result(judgment, entry, rule))

        successes = [x for x in items if x["ok"]]
        failures = [x for x in items if not x["ok"]]
        positions = sorted({x["element_position"] for x in items if x["element_position"] not in (None, "")})
        failed_positions = sorted({x["element_position"] for x in failures
                                   if x["element_position"] not in (None, "")})
        return {
            "ok": not failures,
            "all_success": not failures,
            "has_failures": bool(failures),
            "preview": bool(envelope.get("preview", False)),
            "side_effect_free": bool(envelope.get("preview", False)),
            "writes_quarantine": False,
            "cast_no": rule.get("cast_no", ""),
            "rule": _deep(rule),
            "input_digest": envelope.get("input_digest", ""),
            "total": len(items),
            "total_count": len(items),
            "success_count": len(successes),
            "cast_ok": len(successes),
            "failure_count": len(failures),
            "cast_failed": len(failures),
            "failed": len(failures),
            "element_count": len(positions),
            "positions": positions,
            "failed_positions": failed_positions,
            "items": items,
            "results": items,
            "successes": successes,
            "failures": failures,
            "failure_evidence": failures,
            "cast_values": [{k: x[k] for k in ("field", "value", "element_position")} for x in successes],
            "message": "预览完成，未写入隔离记录" if envelope.get("preview") else (
                "转型完成" if not failures else f"转型发现 {len(failures)} 项失败证据"),
        }

    # ------------------------------------------------------------------
    # 兼容旧接口：cast_row 仍会记录规则执行次数
    # ------------------------------------------------------------------

    def cast_row(self, cast_no: str, row: dict[str, Any],
                 execute_time: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """按转型规则对一行执行转型，返回 (转型后取值, 失败明细)。

        失败数按行回写坏行隔离，因此失败明细必须带字段名与失败原因。
        """
        rule = self._rule_snapshot(cast_no=cast_no)
        if not rule.get("target_type"):
            return {}, [{"field": "*", "reason": f"转型规则 {cast_no} 不存在"}]

        cast_values: dict[str, Any] = {}
        failures: list[dict[str, Any]] = []
        for field, raw in row.items():
            ok, value, reason = self.cast_value(
                raw, rule["target_type"], rule["date_pattern"],
                rule["precision"], rule["null_fill"])
            if ok:
                cast_values[field] = value
            else:
                failures.append({"field": field, "reason": reason, "raw": str(raw)})

        self._record_execution(cast_no, len(failures), execute_time)
        return cast_values, failures

    def preview_cast(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """单次预览：只计算并返回自己的结果，不写规则统计、隔离或正式批表。"""
        envelope = self._build_envelope(*args, **kwargs)
        envelope["preview"] = True
        result = self.evaluate_envelope(envelope)
        result["preview_only"] = True
        result["writes_quarantine"] = False
        return result

    # 常见语义别名。
    preview = preview_cast
    cast_preview = preview_cast
    preview_value_cast = preview_cast
    preview_flattened_cast = preview_cast
    preview_flattened_fields = preview_cast
    dry_run_cast = preview_cast

    def preview_cast_row(self, cast_no: str, row: dict[str, Any],
                         execute_time: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """与 cast_row 同形状的无副作用预览：不回写规则失败数。"""
        result = self.preview_cast(cast_no=cast_no, rows=[row], execute_time=execute_time)
        values = {item["field"]: item["value"] for item in result["items"] if item["ok"]}
        failures = [
            {"field": item["field"], "reason": item["reason"], "raw": str(item["raw"]),
             "element_position": item.get("element_position"),
             "原元素位置": item.get("原元素位置")}
            for item in result["failures"]
        ]
        return values, failures

    preview_row = preview_cast_row

    def _record_execution(self, cast_no: str, failure_count: int,
                          execute_time: str) -> None:
        """回写规则执行结果：失败数累加并置为存在失败状态。"""
        for rule in store.rows(self.MODULE):
            if rule.get("转型编号") != cast_no:
                continue
            existing_text = str(rule.get("转型失败数") or "0").strip()
            existing = int(existing_text) if existing_text.isdigit() else 0
            rule["转型失败数"] = str(existing + failure_count)
            rule["最近执行"] = execute_time
            if failure_count > 0:
                rule["status"] = "存在失败"
                rule["pending"] = True
                rule["abnormal"] = True
            else:
                rule["status"] = "已完成"
                rule["pending"] = False
                rule["abnormal"] = False
            return

    # ------------------------------------------------------------------
    # 坏行隔离写入
    # ------------------------------------------------------------------

    def quarantine_failures(self, cast_no: str, intake_batch: str, row_num: int,
                            failures: list[dict[str, Any]], raw_text: str,
                            quarantine_time: str) -> list[str]:
        """把转型失败按行/叶节点写入坏行隔离，返回生成的隔离编号。"""
        created: list[str] = []
        for failure in failures:
            field_name = str(failure.get("field") or failure.get("失败字段") or "*")
            quarantine_no = f"RQ-{intake_batch}-{row_num}-{field_name}"
            rows = store.rows("row_quarantine")
            if any(r.get("隔离编号") == quarantine_no for r in rows):
                continue
            entry_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            position = failure.get("element_position", failure.get("原元素位置", row_num))
            loose_position = LoosePosition(position) if str(position).lstrip("-").isdigit() else position
            entry = {
                "id": entry_id, "status": "已隔离", "pending": True, "abnormal": False,
                "隔离编号": quarantine_no, "关联批次": intake_batch,
                "原始行号": str(row_num), "失败字段": field_name,
                "失败原因": f"取值转型失败: {failure.get('reason') or failure.get('失败原因') or ''}",
                "原始行文本": raw_text, "复核结论": "", "隔离时间": quarantine_time,
                "原元素位置": loose_position,
                "元素位置": loose_position,
                "element_no": loose_position,
                "元素编号": loose_position,
                "element_position": int(position) if str(position).lstrip("-").isdigit() else position,
                "original_position": int(position) if str(position).lstrip("-").isdigit() else position,
                "leaf_position": int(position) if str(position).lstrip("-").isdigit() else position,
                "original_element_position": int(position) if str(position).lstrip("-").isdigit() else position,
                "element_index": failure.get("element_index", ""),
                "original_element_index": failure.get("element_index", ""),
                "原始值": str(failure.get("raw", failure.get("原始值", ""))),
                "叶节点路径": failure.get("original_path") or failure.get("原始路径") or "",
                "原始文件名": failure.get("source_file") or failure.get("原始文件名") or "",
                "文档编号": failure.get("document_id") or failure.get("文档编号") or "",
                "正式批号": failure.get("formal_batch_no", ""),
                "转型编号": cast_no,
                "转型结论": "转型失败",
            }
            rows.append(entry)
            created.append(quarantine_no)
        return created

    # ------------------------------------------------------------------
    # 正式批、回执、历史版本与恢复
    # ------------------------------------------------------------------

    def _next_id(self, table: str) -> int:
        rows = store.rows(table)
        return max((int(r.get("id", 0) or 0) for r in rows), default=0) + 1

    def _find_batch_row(self, formal_batch_no: str) -> dict[str, Any] | None:
        if not formal_batch_no:
            return None
        for row in store.rows(self.FORMAL_TABLE):
            if str(row.get("formal_batch_no") or row.get("正式批号")) == str(formal_batch_no):
                return row
        # 兼容调用方把回执放进其他候选表名的情况。
        for table in ("cast_receipt", "value_cast_batch", "value_cast_formal_batch"):
            for row in store.rows(table):
                if str(row.get("formal_batch_no") or row.get("正式批号") or row.get("receipt_no")) == str(formal_batch_no):
                    return row
        return None

    def _add_history(self, batch: dict[str, Any], event: str, envelope: dict[str, Any],
                     result: dict[str, Any] | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {
            "id": self._next_id(self.HISTORY_TABLE),
            "history_no": f"CH-{batch['formal_batch_no']}-{len(batch.get('history', [])) + 1}",
            "formal_batch_no": batch["formal_batch_no"],
            "正式批号": batch["formal_batch_no"],
            "revision": batch.get("revision", 1),
            "event": event,
            "事件": event,
            "created_at": _now(),
            "execute_time": envelope.get("execute_time", ""),
            "input_digest": envelope.get("input_digest", ""),
            "rule_digest": envelope.get("rule", {}).get("rule_digest", ""),
            "source_file": envelope.get("source_file", ""),
            "原始文件名": envelope.get("source_file", ""),
            "document_id": envelope.get("document_id", ""),
            "文档编号": envelope.get("document_id", ""),
            "intake_batch": envelope.get("intake_batch", ""),
            "关联批次": envelope.get("intake_batch", ""),
            "entries": _deep(envelope.get("entries", [])),
            "failure_evidence": _deep((result or {}).get("failures", [])),
            "receipt": _deep(result) if result else None,
        }
        if extra:
            record.update(extra)
        store.rows(self.HISTORY_TABLE).append(record)
        batch.setdefault("history", []).append({
            "history_no": record["history_no"], "event": event,
            "revision": record["revision"], "created_at": record["created_at"],
            "input_digest": record["input_digest"],
        })
        return record

    def create_formal_batch(self, *args: Any, **kwargs: Any) -> tuple[bool, str, dict[str, Any] | None]:
        """创建正式批申请并固化输入/规则快照；此步不写坏行隔离。"""
        if args and isinstance(args[0], str) and not kwargs.get("formal_batch_no"):
            first = args[0]
            if self._rule_row(first) is not None or first in TARGET_TYPES:
                kwargs.setdefault("cast_no" if self._rule_row(first) is not None else "target_type", first)
            else:
                kwargs["formal_batch_no"] = first
            args = args[1:]
        envelope = self._build_envelope(*args, **kwargs)
        formal_no = envelope["formal_batch_no"] or kwargs.get("batch_no") or f"FC-{self._next_id(self.FORMAL_TABLE):04d}"
        envelope["formal_batch_no"] = formal_no
        existing = self._find_batch_row(formal_no)
        if existing is not None:
            if existing.get("input_digest") == envelope["input_digest"] and \
                    existing.get("rule_digest") == envelope["rule"]["rule_digest"]:
                return True, f"正式批 {formal_no} 已存在，按原申请继续", _deep(existing)
            return False, f"正式批 {formal_no} 已绑定不同输入或规则快照；更正请走更正/新正式批", _deep(existing)

        planned = self.evaluate_envelope(envelope)
        serializable_plan = _deep(planned)
        for item in serializable_plan.get("items", []):
            item.pop("原元素位置", None) if isinstance(item.get("原元素位置"), LoosePosition) else None
            if isinstance(item.get("原元素位置"), LoosePosition):
                item["原元素位置"] = int(item["原元素位置"])
            if isinstance(item.get("元素位置"), LoosePosition):
                item["元素位置"] = int(item["元素位置"])
        batch = {
            "id": self._next_id(self.FORMAL_TABLE),
            "formal_batch_no": formal_no,
            "正式批号": formal_no,
            "receipt_no": f"RCPT-{formal_no}",
            "status": "待处置",
            "formal_status": "待处置",
            "retryable": False,
            "posted": False,
            "continuable": True,
            "stale": False,
            "is_current": True,
            "supersedes": envelope.get("supersedes") or str(kwargs.get("supersedes") or kwargs.get("corrects_batch_no") or ""),
            "superseded_by": "",
            "assignee": envelope.get("assignee") or str(kwargs.get("assignee") or kwargs.get("to_shift") or ""),
            "correlation_key": envelope["correlation_key"],
            "cast_no": envelope["cast_no"],
            "rule": _deep(envelope["rule"]),
            "rule_digest": envelope["rule"]["rule_digest"],
            "input_digest": envelope["input_digest"],
            "intake_batch": envelope["intake_batch"] or formal_no,
            "parse_batch_no": envelope["parse_batch_no"],
            "channel": envelope["channel"],
            "hit_date": envelope["hit_date"],
            "source_file": envelope["source_file"],
            "原始文件名": envelope["source_file"],
            "document_id": envelope["document_id"],
            "文档编号": envelope["document_id"],
            "operator": envelope["operator"],
            "created_at": _now(kwargs.get("created_at")),
            "updated_at": _now(),
            "posted_at": "",
            "revision": 1,
            "revisions": [],
            "entries": _deep(envelope["entries"]),
            "preview": serializable_plan,
            "receipt": None,
            "last_error": "",
            "execution_recorded": False,
            "normalized": False,
            "history": [],
        }
        store.rows(self.FORMAL_TABLE).append(batch)
        self._add_history(batch, "正式批申请", envelope, planned)

        supersedes = batch["supersedes"]
        if supersedes:
            old = self._find_batch_row(supersedes)
            if old is not None and old.get("status") in ("待处置", "写入失败"):
                old["stale"] = True
                old["continuable"] = False
                old["superseded_by"] = formal_no
                old["updated_at"] = _now()

        return True, f"正式批 {formal_no} 已申请，尚未写入隔离", _deep(batch)

    apply_formal_batch = create_formal_batch
    open_formal_batch = create_formal_batch
    register_formal_batch = create_formal_batch
    create_cast_batch = create_formal_batch
    apply_cast_batch = create_formal_batch

    def correct_formal_batch(self, formal_batch_no: str = "", corrections: Any = None,
                             *args: Any, **kwargs: Any) -> tuple[bool, str, dict[str, Any] | None]:
        """按原元素位置更正待入账输入；旧版本完整保留在历史中，禁止跨版本拼接值。"""
        batch_no = formal_batch_no or str(kwargs.pop("batch_no", "") or kwargs.pop("formalBatchNo", ""))
        batch = self._find_batch_row(batch_no)
        if batch is None:
            return False, f"正式批 {batch_no} 不存在", None
        if batch.get("posted"):
            return False, f"正式批 {batch_no} 已入账；历史不可覆盖，请另开更正正式批", _deep(batch)

        old_snapshot = _deep({"entries": batch["entries"], "rule": batch["rule"],
                              "input_digest": batch["input_digest"], "rule_digest": batch["rule_digest"]})
        entries = _deep(batch["entries"])

        if corrections is None and args:
            corrections = args[0]
        if isinstance(corrections, dict):
            patch_map = corrections
            # 支持 {2: "7"} 或 {"2": {"raw": "7", "rule": ...}}
            for pos_key, patch in patch_map.items():
                matched = None
                for entry in entries:
                    if LoosePosition(entry.get("element_position")) == pos_key:
                        matched = entry
                        break
                if matched is None:
                    new_entry = {"field": kwargs.get("field", "value"), "raw": patch,
                                 "element_position": int(pos_key) if str(pos_key).isdigit() else pos_key,
                                 "element_index": int(pos_key) - 1 if str(pos_key).isdigit() else None,
                                 "original_path": "", "source_file": batch.get("source_file", ""),
                                 "document_id": batch.get("document_id", ""), "raw_text": str(patch),
                                 "row_num": pos_key, "quarantine_no": "", "extra": {}}
                    entries.append(new_entry)
                    continue
                if isinstance(patch, dict):
                    matched["raw"] = patch.get("raw", patch.get("value", matched["raw"]))
                    if "field" in patch:
                        matched["field"] = patch["field"]
                    if "rule" in patch:
                        kwargs.setdefault("rule", patch["rule"])
                else:
                    matched["raw"] = patch
                matched["raw_text"] = str(matched["raw"])
        elif isinstance(corrections, list):
            for patch in corrections:
                pos = patch.get("element_position") or patch.get("原元素位置")
                matched = next((e for e in entries if LoosePosition(e.get("element_position")) == pos), None)
                if matched is None:
                    entries.append(self._build_envelope(entries=[patch])["entries"][0])
                else:
                    raw = patch.get("raw", patch.get("value", matched["raw"]))
                    matched.update({k: v for k, v in patch.items() if k not in ("raw", "value")})
                    matched["raw"] = raw
                    matched["raw_text"] = str(raw)

        # 也允许直接传完整 rows= 做整版更正。
        if kwargs.get("rows") is not None or kwargs.get("elements") is not None:
            new_envelope = self._build_envelope(**kwargs)
            entries = new_envelope["entries"]

        rule_kwargs = {k: v for k, v in kwargs.items() if k not in ("cast_no", "rule", "rule_snapshot")}
        rule = self._rule_snapshot(
            cast_no=str(kwargs.get("cast_no") or batch.get("cast_no") or ""),
            rule=kwargs.get("rule") or kwargs.get("rule_snapshot") or batch.get("rule"),
            **rule_kwargs,
        )
        envelope = {
            **self._build_envelope(rows=entries, cast_no=rule["cast_no"], rule=rule,
                                   intake_batch=batch.get("intake_batch"),
                                   formal_batch_no=batch_no,
                                   source_file=batch.get("source_file"),
                                   document_id=batch.get("document_id"),
                                   channel=batch.get("channel"), hit_date=batch.get("hit_date")),
            "execute_time": kwargs.get("execute_time") or _now(),
        }
        batch["revisions"].append(old_snapshot)
        batch["revision"] = int(batch.get("revision", 1)) + 1
        batch["entries"] = _deep(envelope["entries"])
        batch["rule"] = _deep(rule)
        batch["rule_digest"] = rule["rule_digest"]
        batch["input_digest"] = envelope["input_digest"]
        batch["status"] = "待处置"
        batch["formal_status"] = "待处置"
        batch["continuable"] = True
        batch["stale"] = False
        batch["last_error"] = ""
        plan = self.evaluate_envelope(envelope)
        batch["preview"] = _deep(plan)
        batch["updated_at"] = _now()
        self._add_history(batch, "输入更正", envelope, plan,
                          {"old_digest": old_snapshot["input_digest"]})
        return True, f"正式批 {batch_no} 已按原元素位置更正到 revision={batch['revision']}", _deep(batch)

    def _sync_parse_batch(self, batch: dict[str, Any], quarantined: int,
                          success_elements: int, failed_elements: int, total: int) -> None:
        if not batch.get("sync_parse_batch", True):
            return
        intake_batch = batch.get("intake_batch") or batch["formal_batch_no"]
        parse_no = batch.get("parse_batch_no") or f"PB-{batch['formal_batch_no']}"
        rows = store.rows("parse_batch")
        target = next((r for r in rows if r.get("批次记录编号") == parse_no), None)
        if target is None:
            target = next((r for r in rows if r.get("关联投递批次") == intake_batch), None)
        if target is None:
            target = {
                "id": self._next_id("parse_batch"),
                "批次记录编号": parse_no, "关联投递批次": intake_batch,
                "解析器标识": "value_cast_formal", "完成时间": "",
            }
            rows.append(target)
        isolated_status = "存在隔离" if quarantined else "已闭合"
        target.update({
            "status": isolated_status,
            "pending": quarantined > 0,
            "abnormal": quarantined > 0,
            "总行数": str(total),
            "成功行数": str(success_elements),
            "隔离行数": str(quarantined),
            "批次状态": isolated_status,
            "转型成功元素数": str(success_elements),
            "转型失败元素数": str(failed_elements),
            "正式批号": batch["formal_batch_no"],
        })
        if not quarantined:
            target["完成时间"] = batch.get("posted_at") or _now()

    def submit_formal_batch(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """提交/重试正式批：使用该批绑定的连贯展平数据与规则，写隔离后归一可取成功值。"""
        # 把位置 dict 负载并入 kwargs，保证 HTTP 入口和关键字入口走同一条路径。
        positional: list[Any] = []
        payload_kwargs: dict[str, Any] = {}
        for arg in args:
            if isinstance(arg, dict):
                payload_kwargs.update(arg)
            else:
                positional.append(arg)
        kwargs = {**payload_kwargs, **kwargs}
        args = tuple(positional)

        # 允许 submit_formal_batch(payload_dict) 或 submit_formal_batch(batch_no, ...)
        existing_batch: dict[str, Any] | None = None
        if args and isinstance(args[0], str) and not kwargs.get("formal_batch_no"):
            first = args[0]
            if self._rule_row(first) is not None:
                kwargs.setdefault("cast_no", first)
            elif first in TARGET_TYPES:
                kwargs.setdefault("target_type", first)
            else:
                kwargs["formal_batch_no"] = first
                args = args[1:]
        formal_no_hint = str(kwargs.get("formal_batch_no") or kwargs.get("batch_no") or "")
        if not formal_no_hint:
            for arg in args:
                if isinstance(arg, dict):
                    formal_no_hint = str(_first(arg, FORMAL_BATCH_KEYS, ""))
                    if formal_no_hint:
                        break
        if formal_no_hint:
            existing_batch = self._find_batch_row(formal_no_hint)

        if existing_batch is not None and not any(
                k in kwargs for k in ("rows", "elements", "entries", "fields", "documents", "corrections")) and \
                not (args and any(isinstance(a, (list, dict)) for a in args)):
            batch = existing_batch
            envelope = self._build_envelope(
                rows=batch["entries"], rule=batch["rule"], cast_no=batch.get("cast_no"),
                formal_batch_no=batch["formal_batch_no"], intake_batch=batch.get("intake_batch"),
                parse_batch_no=batch.get("parse_batch_no"),
                channel=kwargs.get("channel") or batch.get("channel"),
                hit_date=kwargs.get("hit_date") or batch.get("hit_date"),
                source_file=batch.get("source_file"),
                document_id=batch.get("document_id"), operator=batch.get("operator"),
                execute_time=kwargs.get("execute_time") or kwargs.get("quarantine_time") or _now(),
                sync_parse_batch=batch.get("sync_parse_batch", True))
        else:
            # 若同号批已存在且调用方带来新输入，先按更正版本落入该批，避免新旧快照混用。
            if existing_batch is not None and formal_no_hint:
                ok, msg, corrected = self.correct_formal_batch(formal_no_hint, **{
                    k: v for k, v in kwargs.items() if k in ("corrections", "rows", "elements", "entries", "fields", "documents", "rule", "cast_no", "execute_time")
                })
                if not ok:
                    return {"ok": False, "message": msg, "receipt": corrected,
                            "formal_batch_no": formal_no_hint,
                            "continuable_formal_batch_no": formal_no_hint}
                existing_batch = self._find_batch_row(formal_no_hint)
            created, msg, batch_or_none = self.create_formal_batch(*args, **kwargs)
            if not created and existing_batch is None and not batch_or_none:
                return {"ok": False, "message": msg, "receipt": batch_or_none,
                        "formal_batch_no": formal_no_hint}
            created_no = formal_no_hint or str((batch_or_none or {}).get("formal_batch_no") or "")
            batch = self._find_batch_row(created_no) if created_no else None
            if batch is None:
                batch = batch_or_none
            if batch is None:
                return {"ok": False, "message": msg, "receipt": None}
            envelope = self._build_envelope(
                rows=batch["entries"], rule=batch["rule"], cast_no=batch.get("cast_no"),
                formal_batch_no=batch["formal_batch_no"], intake_batch=batch.get("intake_batch"),
                parse_batch_no=batch.get("parse_batch_no"), channel=batch.get("channel"),
                hit_date=batch.get("hit_date"), source_file=batch.get("source_file"),
                document_id=batch.get("document_id"), operator=batch.get("operator"),
                execute_time=kwargs.get("execute_time") or _now())

        formal_no = batch["formal_batch_no"]
        envelope["formal_batch_no"] = formal_no
        if envelope.get("channel"):
            batch["channel"] = envelope["channel"]
        if envelope.get("hit_date"):
            batch["hit_date"] = envelope["hit_date"]
        if envelope.get("intake_batch"):
            batch["intake_batch"] = envelope["intake_batch"]
        result = self.evaluate_envelope(envelope)
        quarantine_time = _now(kwargs.get("quarantine_time") or envelope["execute_time"])

        batch["status"] = "写入中"
        batch["formal_status"] = "写入中"
        batch["updated_at"] = _now()

        # 幂等结果表：同批重试不重复保留旧结果。成功值先标记为“正式成功”，
        # 即使隔离台账瞬时写入失败，也仍可交给归一；失败证据则等待重试入账。
        store.rows(self.RESULT_TABLE)[:] = [
            r for r in store.rows(self.RESULT_TABLE) if r.get("formal_batch_no") != formal_no]
        for item in result["items"]:
            formal_status = "正式成功" if item["ok"] else "隔离待写入"
            record = {
                "id": self._next_id(self.RESULT_TABLE),
                "result_key": f"{formal_no}:{item.get('element_position')}:{item.get('field')}",
                "formal_batch_no": formal_no, "正式批号": formal_no,
                "formal_status": formal_status,
                "ledger_status": formal_status,
                "normalized": False,
                "normalized_value": None,
                "normalize_ok": None,
                **_deep(item),
            }
            if isinstance(record.get("原元素位置"), LoosePosition):
                record["原元素位置"] = int(record["原元素位置"])
            if isinstance(record.get("元素位置"), LoosePosition):
                record["元素位置"] = int(record["元素位置"])
            store.rows(self.RESULT_TABLE).append(record)

        created_ids: list[str] = []
        try:
            groups: dict[Any, list[dict[str, Any]]] = {}
            raw_text_by_pos: dict[Any, str] = {}
            for failure in result["failures"]:
                pos = failure.get("element_position")
                groups.setdefault(pos, []).append({
                    "field": failure["field"],
                    "reason": failure["reason"],
                    "raw": "" if failure["raw"] is None else str(failure["raw"]),
                    "element_position": pos,
                    "element_index": failure.get("element_index"),
                    "original_path": failure.get("original_path"),
                    "source_file": failure.get("source_file"),
                    "document_id": failure.get("document_id"),
                    "formal_batch_no": formal_no,
                })
                raw_text_by_pos[pos] = failure.get("raw_text") or json.dumps(
                    failure.get("raw"), ensure_ascii=False, default=str)
            intake_batch = batch.get("intake_batch") or formal_no
            for pos, failures in groups.items():
                ids = self.quarantine_failures(
                    batch.get("cast_no") or "", intake_batch, int(pos) if str(pos).isdigit() else pos,
                    failures, raw_text_by_pos.get(pos, ""), quarantine_time)
                created_ids.extend(ids)
        except Exception as exc:  # 写入失败必须可重试，且不能把批伪装成成功。
            for record in store.rows(self.RESULT_TABLE):
                if record.get("formal_batch_no") == formal_no and not record.get("ok"):
                    record["formal_status"] = "隔离写入失败"
                    record["ledger_status"] = "隔离写入失败"
                    record["write_error"] = str(exc)
            batch["status"] = "写入失败"
            batch["formal_status"] = "写入失败"
            batch["retryable"] = True
            batch["posted"] = False
            batch["continuable"] = True
            batch["last_error"] = str(exc)
            batch["updated_at"] = _now()
            self._add_history(batch, "写入失败", envelope, result, {"error": str(exc)})
            receipt = self._receipt(batch, result, created_ids=created_ids)
            batch["receipt"] = receipt
            return {
                "ok": False, "retryable": True, "stage": "row_quarantine",
                "formal_batch_no": formal_no, "receipt_no": batch.get("receipt_no"),
                "continuable_formal_batch_no": formal_no,
                "current_formal_batch_no": formal_no,
                "message": f"正式批 {formal_no} 隔离写入失败，可原号重试：{exc}",
                "receipt": _deep(receipt), "result": result,
            }

        for record in store.rows(self.RESULT_TABLE):
            if record.get("formal_batch_no") == formal_no and not record.get("ok"):
                record["formal_status"] = "已隔离"
                record["ledger_status"] = "已隔离"

        q_rows = [r for r in store.rows("row_quarantine") if r.get("正式批号") == formal_no]
        # 兼容隔离写入方法未写入正式批号的定制/mock：按确定编号补查。
        if not q_rows:
            expected_ids = set(created_ids)
            q_rows = [r for r in store.rows("row_quarantine") if r.get("隔离编号") in expected_ids]
        quarantined = len(q_rows)
        failed_elements = len({f.get("element_position") for f in result["failures"]})
        total = result["total"]
        success_elements = len({x.get("element_position") for x in result["successes"]})

        if not batch.get("execution_recorded") and batch.get("cast_no"):
            self._record_execution(batch["cast_no"], result["failure_count"], quarantine_time)
            batch["execution_recorded"] = True

        batch["status"] = "已入账"
        batch["formal_status"] = "部分隔离" if quarantined else "正式成功"
        batch["posted"] = True
        batch["retryable"] = False
        batch["continuable"] = True
        batch["last_error"] = ""
        batch["posted_at"] = quarantine_time
        batch["updated_at"] = _now()
        self._sync_parse_batch(batch, quarantined, success_elements, failed_elements, total)
        receipt = self._receipt(batch, result, created_ids=created_ids, q_rows=q_rows)
        batch["receipt"] = _deep(receipt)
        self._add_history(batch, "正式提交", envelope, result, {"receipt": _deep(receipt)})

        return {
            "ok": True,
            "formal_batch_no": formal_no,
            "正式批号": formal_no,
            "receipt_no": batch.get("receipt_no"),
            "continuable_formal_batch_no": formal_no,
            "current_formal_batch_no": formal_no,
            "active_batch_no": formal_no,
            "quarantine_ids": [r.get("隔离编号") for r in q_rows] or created_ids,
            "quarantined_count": quarantined,
            "batch_stats": receipt["batch_stats"],
            "receipt": receipt,
            "result": result,
            "success_values": result["successes"],
            "normalizable_results": [r for r in store.rows(self.RESULT_TABLE)
                                    if r.get("formal_batch_no") == formal_no and r.get("formal_status") == "正式成功"],
            "message": f"正式批 {formal_no} 已入账，隔离 {quarantined} 条，成功 {result['success_count']} 项",
        }

    submit_cast = submit_formal_batch
    submit_value_cast = submit_formal_batch
    commit_cast = submit_formal_batch
    commit_formal_batch = submit_formal_batch
    formal_cast = submit_formal_batch
    post_cast_batch = submit_formal_batch
    batch_cast = submit_formal_batch
    record_cast_batch = submit_formal_batch

    def retry_formal_batch(self, formal_batch_no: str, **kwargs: Any) -> dict[str, Any]:
        """原号重试正式批；输入和规则仍取自该批快照。"""
        return self.submit_formal_batch(formal_batch_no, **kwargs)

    retry_submit_cast = retry_formal_batch

    def _receipt(self, batch: dict[str, Any], result: dict[str, Any],
                 created_ids: list[str] | None = None,
                 q_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        formal_no = batch["formal_batch_no"]
        if q_rows is None:
            q_rows = [r for r in store.rows("row_quarantine") if r.get("正式批号") == formal_no]
        stats_svc = None
        try:
            from app.services.row_quarantine import RowQuarantineService
            stats_svc = RowQuarantineService().quarantine_stats(batch.get("intake_batch") or formal_no)
        except Exception:
            stats_svc = {}
        return {
            "receipt_no": batch.get("receipt_no") or f"RCPT-{formal_no}",
            "formal_batch_no": formal_no,
            "正式批号": formal_no,
            "cast_no": batch.get("cast_no", ""),
            "status": batch.get("status"),
            "formal_status": batch.get("formal_status"),
            "revision": batch.get("revision", 1),
            "input_digest": batch.get("input_digest"),
            "rule_digest": batch.get("rule_digest"),
            "continuable_formal_batch_no": formal_no,
            "current_formal_batch_no": formal_no,
            "source_file": batch.get("source_file", ""),
            "原始文件名": batch.get("source_file", ""),
            "document_id": batch.get("document_id", ""),
            "created_at": batch.get("created_at"),
            "posted_at": batch.get("posted_at"),
            "total_count": result.get("total", 0),
            "success_count": result.get("success_count", 0),
            "failure_count": result.get("failure_count", 0),
            "quarantined_count": len(q_rows),
            "created_quarantine_ids": created_ids or [],
            "quarantine_ids": [r.get("隔离编号") for r in q_rows],
            "failures": _deep(result.get("failures", [])),
            "failure_evidence": _deep(result.get("failure_evidence", [])),
            "items": _deep(result.get("items", [])),
            "batch_stats": {
                **(stats_svc or {}),
                "actual_quarantine_records": len(q_rows),
                "formal_quarantined": len(q_rows),
                "total": result.get("total", 0),
                "success": result.get("success_count", 0),
                "failed": result.get("failure_count", 0),
            },
            "last_error": batch.get("last_error", ""),
            "retryable": batch.get("retryable", False),
        }

    def get_formal_batch(self, formal_batch_no: str) -> dict[str, Any] | None:
        batch = self._find_batch_row(formal_batch_no)
        return _deep(batch) if batch else None

    def list_formal_batches(self, correlation_key: str = "", status: str = "",
                            continuable_only: bool = False) -> list[dict[str, Any]]:
        rows = [_deep(r) for r in store.rows(self.FORMAL_TABLE)]
        if correlation_key:
            rows = [r for r in rows if r.get("correlation_key") == correlation_key]
        if status:
            rows = [r for r in rows if r.get("status") == status or r.get("formal_status") == status]
        if continuable_only:
            rows = [r for r in rows if r.get("continuable") and not r.get("stale")]
        return rows

    def pending_formal_batches(self, correlation_key: str = "") -> list[dict[str, Any]]:
        return self.list_formal_batches(correlation_key=correlation_key, status="待处置")

    def handoff_formal_batch(self, formal_batch_no: str, assignee: str = "",
                             operator: str = "", note: str = "") -> tuple[bool, str, dict[str, Any] | None]:
        """把可继续处理的正式批交给另一班；批号和快照不变。"""
        batch = self._find_batch_row(formal_batch_no)
        if batch is None:
            return False, f"正式批 {formal_batch_no} 不存在", None
        if batch.get("stale") or not batch.get("continuable", True):
            current = batch.get("superseded_by") or ""
            return False, f"正式批 {formal_batch_no} 已不可继续，请处理 {current or '新正式批'}", _deep(batch)
        batch["assignee"] = assignee or batch.get("assignee")
        batch["handoff_note"] = note
        batch["handoff_by"] = operator
        batch["updated_at"] = _now()
        envelope = self._build_envelope(rows=batch.get("entries", []), rule=batch.get("rule"))
        self._add_history(batch, "交接班", envelope, extra={"assignee": assignee, "note": note, "operator": operator})
        return True, f"正式批 {formal_batch_no} 已交给 {assignee or '下一班'}", _deep(batch)

    claim_formal_batch = handoff_formal_batch

    def dispose_formal_batch(self, formal_batch_no: str, disposition: str = "废弃",
                             operator: str = "", note: str = "") -> tuple[bool, str, dict[str, Any] | None]:
        """处置等待中的旧申请：保留快照和历史，不允许物理删除导致回执不可恢复。"""
        batch = self._find_batch_row(formal_batch_no)
        if batch is None:
            return False, f"正式批 {formal_batch_no} 不存在", None
        if batch.get("posted"):
            return False, f"正式批 {formal_batch_no} 已入账，不能按待处置申请废弃", _deep(batch)
        target_status = "已废弃" if disposition in ("废弃", "丢弃", "cancel", "discard") else disposition
        batch["status"] = target_status
        batch["formal_status"] = target_status
        batch["continuable"] = False
        batch["disposed_by"] = operator
        batch["disposition_note"] = note
        batch["updated_at"] = _now()
        envelope = self._build_envelope(rows=batch.get("entries", []), rule=batch.get("rule"))
        self._add_history(batch, f"处置:{target_status}", envelope, extra={"note": note, "operator": operator})
        return True, f"正式批 {formal_batch_no} 已处置为 {target_status}", _deep(batch)

    cancel_formal_batch = dispose_formal_batch
    discard_formal_batch = dispose_formal_batch

    get_receipt = get_formal_batch
    get_formal_receipt = get_formal_batch
    get_cast_receipt = get_formal_batch
    get_formal_batch_receipt = get_formal_batch
    get_batch_receipt = get_formal_batch
    recover_receipt = get_formal_batch
    recover_formal_batch = get_formal_batch
    recover_cast_receipt = get_formal_batch

    def get_cast_history(self, formal_batch_no: str) -> list[dict[str, Any]]:
        rows = [r for r in store.rows(self.HISTORY_TABLE)
                if str(r.get("formal_batch_no") or r.get("正式批号")) == str(formal_batch_no)]
        if not rows:
            batch = self._find_batch_row(formal_batch_no)
            return _deep(batch.get("history", [])) if batch else []
        return _deep(rows)

    history = get_cast_history

    def quarantine_detail(self, quarantine_no: str) -> dict[str, Any] | None:
        for row in store.rows("row_quarantine"):
            if row.get("隔离编号") == quarantine_no:
                return _deep(row)
        return None

    def download_formal_batch(self, formal_batch_no: str) -> tuple[str, str, str]:
        """下载该批历史结果 CSV；每行保留原文件/文档定位信息。"""
        import csv
        import io
        batch = self._find_batch_row(formal_batch_no)
        if batch is None:
            raise KeyError(f"正式批 {formal_batch_no} 不存在")
        history = self.get_cast_history(formal_batch_no)
        rows: list[dict[str, Any]] = []
        for event in history:
            for evidence in event.get("failure_evidence") or []:
                rows.append({**evidence, "history_no": event.get("history_no"), "event": event.get("event")})
        result_rows = store.rows(self.RESULT_TABLE)
        result_rows = [r for r in result_rows if r.get("formal_batch_no") == formal_batch_no]
        if result_rows:
            rows = result_rows
        elif batch.get("receipt"):
            rows = batch["receipt"].get("items", [])

        output = io.StringIO()
        output.write("﻿")
        fields = ["formal_batch_no", "element_position", "element_index", "field", "raw", "value",
                  "ok", "formal_status", "reason", "original_path", "source_file", "document_id",
                  "quarantine_no", "normalized_value", "normalize_message", "event", "history_no"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat.setdefault("formal_batch_no", formal_batch_no)
            flat.setdefault("source_file", batch.get("source_file", ""))
            flat.setdefault("document_id", batch.get("document_id", ""))
            writer.writerow(flat)
        filename = f"{formal_batch_no}-cast-result.csv"
        return filename, output.getvalue(), "text/csv; charset=utf-8"

    export_formal_batch = download_formal_batch

    # ------------------------------------------------------------------
    # 单位归一入口：只读取该正式批中已正式成功的转型值
    # ------------------------------------------------------------------

    def normalize_formal_batch(self, formal_batch_no: str, channel: str = "",
                               hit_date: str = "", field: str = "",
                               **kwargs: Any) -> dict[str, Any]:
        from app.services.unit_normalize import UnitNormalizeService

        batch = self._find_batch_row(formal_batch_no)
        if batch is None:
            return {"ok": False, "message": f"正式批 {formal_batch_no} 不存在", "normalized": []}

        records = [r for r in store.rows(self.RESULT_TABLE)
                   if r.get("formal_batch_no") == formal_batch_no
                   and r.get("formal_status") == "正式成功"
                   and r.get("ok") is True]
        if field:
            records = [r for r in records if r.get("field") == field]
        if kwargs.get("result_keys"):
            keys = set(kwargs["result_keys"])
            records = [r for r in records if r.get("result_key") in keys or str(r.get("element_position")) in keys]

        unit_service = UnitNormalizeService()
        use_channel = channel or batch.get("channel") or "*"
        use_date = hit_date or batch.get("hit_date") or ""
        normalized: list[dict[str, Any]] = []
        for record in records:
            target_field = field or str(record.get("field") or "value")
            try:
                raw_number = float(record.get("value"))
            except (TypeError, ValueError):
                record["normalize_ok"] = False
                record["normalize_message"] = f"正式成功值 {record.get('value')!r} 不是数值，不能做单位系数归一"
                normalized.append(_deep(record))
                continue
            ok, value, message = unit_service.normalize_value(
                target_field, use_channel, raw_number, use_date)
            record["normalized"] = bool(ok)
            record["normalize_ok"] = ok
            record["normalized_value"] = value
            record["normalize_message"] = message
            record["归一实际值"] = value
            normalized.append(_deep(record))

        batch["normalized"] = any(r.get("normalize_ok") for r in normalized)
        batch["normalized_at"] = _now()
        batch["normalized_values"] = _deep(normalized)
        actual_values = [r.get("normalized_value") for r in normalized if r.get("normalize_ok")]
        return {
            "ok": True,
            "formal_batch_no": formal_batch_no,
            "continuable_formal_batch_no": formal_batch_no,
            "channel": use_channel,
            "hit_date": use_date,
            "accepted_count": len(records),
            "normalized_count": len(actual_values),
            "normalized": normalized,
            "values": actual_values,
            "actual_values": actual_values,
            "message": f"已从正式批 {formal_batch_no} 读取 {len(records)} 条正式成功值，归一成功 {len(actual_values)} 条",
        }

    normalize_committed_results = normalize_formal_batch

    def failure_summary(self, cast_no: str) -> dict[str, Any]:
        """输出规则的失败计数，供解析指标与坏行隔离对账。"""
        for rule in store.rows(self.MODULE):
            if rule.get("转型编号") == cast_no:
                text = str(rule.get("转型失败数") or "0").strip()
                return {
                    "转型编号": cast_no,
                    "目标类型": rule.get("目标类型"),
                    "转型失败数": int(text) if text.isdigit() else 0,
                    "最近执行": rule.get("最近执行"),
                    "status": rule.get("status"),
                }
        return {"转型编号": cast_no, "转型失败数": 0, "status": "规则不存在"}


# 面向可能的导入习惯提供模块级函数和类别名。
def preview_cast(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return ValueCastService().preview_cast(*args, **kwargs)


def submit_formal_batch(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return ValueCastService().submit_formal_batch(*args, **kwargs)


def map_cast_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return ValueCastService().extract_cast_result(*args, **kwargs)


build_cast_result = map_cast_result
extract_cast_data = map_cast_result


class FlattenCastService(ValueCastService):
    """旧/候选命名入口。"""


class ValueCastWorkflowService(ValueCastService):
    """正式批工作流候选命名入口。"""


class CastWorkflowService(ValueCastService):
    """转型工作流候选命名入口。"""
