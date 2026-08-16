"""pytest 公共夹具：内存 SQLite + 测试客户端。"""
import pytest

from app import create_app
from app.extensions import db


@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db_session(app):
    return db.session
