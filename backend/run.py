"""应用入口：python run.py 启动开发服务器。"""
from app import create_app

app = create_app("development")

if __name__ == "__main__":
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=app.config["DEBUG"])
