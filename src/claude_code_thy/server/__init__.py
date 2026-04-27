from .context import WebAppContext


def create_app(*args, **kwargs):
    """懒加载 FastAPI app 工厂，避免非 Web 测试在未安装 fastapi 时提前 import。"""
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)


__all__ = ["WebAppContext", "create_app"]
