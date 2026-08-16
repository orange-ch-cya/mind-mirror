"""系统配置服务（文档 5.6）：读取/写入配置表，进程内缓存 + 30 秒 TTL。

修改后立即生效（缓存自然过期），无需重启服务。
"""
import json
import time

from ..extensions import db
from ..models import SystemConfig

_cache = {}          # key -> (value, expire_at)
CACHE_TTL = 30       # 秒


def get_config(key, default=None):
    now = time.time()
    if key in _cache:
        value, expire_at = _cache[key]
        if now < expire_at:
            return value
        del _cache[key]

    row = SystemConfig.query.filter_by(key=key).first()
    if row is None:
        return default
    value = _decode(row.value_json, row.value_type)
    _cache[key] = (value, now + CACHE_TTL)
    return value


def set_config(key, value, value_type=None, description=None):
    row = SystemConfig.query.filter_by(key=key).first()
    if row is None:
        row = SystemConfig(key=key, value_json=json.dumps(value),
                           value_type=value_type or _infer_type(value),
                           description=description)
        db.session.add(row)
    else:
        row.value_json = json.dumps(value)
        if value_type:
            row.value_type = value_type
        if description is not None:
            row.description = description
    db.session.commit()
    _cache.pop(key, None)


def get_config_int(key, default=0):
    try:
        return int(get_config(key, default))
    except (TypeError, ValueError):
        return default


def get_config_bool(key, default=False):
    return bool(get_config(key, default))


def _decode(raw, value_type):
    try:
        if value_type == "int":
            return int(json.loads(raw))
        if value_type == "float":
            return float(json.loads(raw))
        if value_type == "bool":
            return bool(json.loads(raw))
        if value_type == "json":
            return json.loads(raw)
    except (ValueError, TypeError):
        pass
    return raw


def _infer_type(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, (dict, list)):
        return "json"
    return "str"
