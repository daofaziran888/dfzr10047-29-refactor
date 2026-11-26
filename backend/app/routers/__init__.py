"""业务路由汇总：专用工作流路由先注册，随后是所有模块共用的资源路由。"""
from __future__ import annotations

from app.routers import resource, value_cast_workflow

ROUTERS = [value_cast_workflow, resource]
