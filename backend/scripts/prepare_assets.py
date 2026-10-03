"""将两套静态前端整理到 Worker Assets 目录。"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "backend" / "public"


def main():
    PUBLIC.mkdir(exist_ok=True)
    for source, name in ((ROOT / "frontend-patient", "patient"),
                         (ROOT / "frontend-doctor", "doctor")):
        target = PUBLIC / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        shutil.copy2(source / "index.html", target / "index.html")
        # HTML 使用 /patient/static 和 /doctor/static；目录必须与引用一致。
        for folder in ("css", "js"):
            shutil.copytree(source / folder, target / "static" / folder)
        print(f"{source.name} -> {target}")


if __name__ == "__main__":
    main()
