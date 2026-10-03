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
        shutil.copytree(source, target)
        print(f"{source.name} -> {target}")


if __name__ == "__main__":
    main()
