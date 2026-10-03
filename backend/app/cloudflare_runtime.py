"""将当前 Worker 请求的 D1 binding 交给 Flask-SQLAlchemy。"""
from contextvars import ContextVar

from sqlalchemy.pool import NullPool
from sqlalchemy_cloudflare_d1 import WorkerDBAPI


_current_env = ContextVar("mind_mirror_cloudflare_env")


class _BindingProxy:
    def prepare(self, sql):
        return _current_env.get().DB.prepare(sql)


def bind_env(env):
    return _current_env.set(env)


def reset_env(token):
    _current_env.reset(token)


def current_env():
    return _current_env.get()


def engine_options():
    # 每次连接都经当前请求的 binding；避免跨请求复用连接。
    return {"module": WorkerDBAPI(_BindingProxy()), "poolclass": NullPool}


def atomic_batch(statements):
    """把一组已参数化的 SQL 写入交给 D1 的原子 batch。"""
    from pyodide.ffi import run_sync

    async def execute():
        binding = current_env().DB
        prepared = []
        for sql, params in statements:
            statement = binding.prepare(sql)
            if params:
                statement = statement.bind(*params)
            prepared.append(statement)
        await binding.batch(prepared)

    run_sync(execute())
