"""转型结果映射的候选模块名。"""
from app.services.value_cast import CastResultMapper, ValueCastService  # noqa: F401


def extract_cast_result(*args, **kwargs):
    return ValueCastService().extract_cast_result(*args, **kwargs)
