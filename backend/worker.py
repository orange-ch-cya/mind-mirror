from workers import Response, WorkerEntrypoint, wsgi
from js import URL
from reportlab.lib import colors, pagesizes, styles, units
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

from app import create_app
from app.cloudflare_runtime import bind_env, reset_env


_application = create_app("cloudflare")


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = URL.new(request.url).pathname
        if path in ("/", "/patient"):
            return await self.env.ASSETS.fetch("https://assets.local/patient/index.html")
        if path in ("/doctor", "/doctor/login", "/admin", "/admin/login"):
            return await self.env.ASSETS.fetch("https://assets.local/doctor/index.html")
        if path.startswith(("/patient/static/", "/doctor/static/")):
            return await self.env.ASSETS.fetch(request)
        if path.startswith(("/doctor/", "/admin/")):
            return await self.env.ASSETS.fetch("https://assets.local/doctor/index.html")

        jwt_secret = str(self.env.JWT_SECRET)
        password_pepper = str(self.env.PASSWORD_PEPPER)
        if len(jwt_secret) < 32 or len(password_pepper) < 32:
            return Response("Worker secrets are not configured", status=503)
        _application.config["SECRET_KEY"] = jwt_secret
        token = bind_env(self.env)
        try:
            return await wsgi.fetch(_application, request, self.env)
        finally:
            reset_env(token)
