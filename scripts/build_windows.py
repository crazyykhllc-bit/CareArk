"""Build the portable Windows zip with a double-clickable CareArk.exe."""

import os
import hashlib
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows 安装包必须在 Windows 上构建")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    separator = os.pathsep
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "CareArk", "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        "--add-data", f"{ROOT / 'app' / 'web'}{separator}app/web",
        "--add-data", f"{ROOT / 'alembic'}{separator}alembic",
        "--add-data", f"{ROOT / 'alembic.ini'}{separator}.",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "sqlalchemy.dialects.sqlite",
        "--collect-submodules", "aiosqlite",
        str(ROOT / "desktop_launcher.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    output = ROOT / "dist" / "CareArk"
    for name in ("LICENSE", "WINDOWS.md"):
        shutil.copy2(ROOT / name, output / name)
    archive = shutil.make_archive(str(ROOT / "dist" / f"CareArk-Windows-v{version}"), "zip",
                                  root_dir=ROOT / "dist", base_dir="CareArk")
    with open(archive, "rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    (ROOT / "dist" / "SHA256SUMS.txt").write_text(
        f"{digest}  {Path(archive).name}\n", encoding="ascii"
    )
    print(archive)


if __name__ == "__main__":
    main()
