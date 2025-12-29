# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

def find_project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "manage.py").exists():
            return candidate
    return start


spec_path = globals().get("__file__")
if spec_path:
    project_root = Path(spec_path).resolve().parents[2]
elif os.environ.get("PYINSTALLER_PROJECT_ROOT"):
    project_root = Path(os.environ["PYINSTALLER_PROJECT_ROOT"]).resolve()
else:
    project_root = find_project_root(Path.cwd().resolve())

sys.path.insert(0, str(project_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "salary_tracker.settings")


datas = []


def add_data(path: Path, target: str) -> None:
    if path.exists():
        datas.append((str(path), target))


add_data(project_root / "templates", "templates")
add_data(project_root / "static", "static")
add_data(project_root / "tracker" / "templates", "tracker/templates")
add_data(project_root / "staticfiles", "staticfiles")

hiddenimports = []
for package_name in (
    "django",
    "rest_framework",
    "whitenoise",
    "salary_tracker",
    "tracker",
    "accounts",
):
    hiddenimports.extend(collect_submodules(package_name))

block_cipher = None

analysis = Analysis(
    [str(project_root / "desktop" / "backend" / "desktop_backend.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="salary-tracker-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=os.name != "nt",
)
