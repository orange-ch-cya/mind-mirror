"""API 蓝图注册中心。"""
from . import admin, auth, doctor, pages, patient


def register_blueprints(app):
    for bp in (auth.bp, patient.bp, doctor.bp, admin.bp, pages.bp):
        app.register_blueprint(bp)
