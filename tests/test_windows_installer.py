import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcut and PowerShell integration")
def test_windows_installer_install_repeat_upgrade_and_bad_checksum(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for tag in ["v0.1.2", "v0.1.3"]:
        archive = tmp_path / f"CareArk-Windows-{tag}.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            for filename in ["CareArk.exe", "_internal/alembic/env.py", "_internal/app/web/index.html"]:
                bundle.writestr("CareArk/" + filename, "fixture " + tag)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (tmp_path / f"{tag}-SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(root / "tests/windows/install-windows.test.ps1"),
        "-InstallerPath", str(root / "scripts/install-windows.ps1"), "-FixtureRoot", str(tmp_path),
    ], text=True, errors="replace", capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INSTALLER_TESTS_OK" in result.stdout
