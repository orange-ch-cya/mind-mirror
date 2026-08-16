"""API 蓝图注册中心。"""
from . import admin, auth, doctor, patient


def register_blueprints(app):
    for bp in (auth.bp, patient.bp, doctor.bp, admin.bp):
        app.register_blueprint(bp)
