# PyInstaller onedir release build. User configuration and memory are deliberately
# excluded; they live under the user's NEBIX application-data directory.
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH).resolve()
optional_hiddenimports = []
optional_datas = []

if importlib.util.find_spec("openwakeword") is not None:
    optional_hiddenimports.extend(collect_submodules("openwakeword"))
    optional_datas.extend(collect_data_files("openwakeword"))

datas = [
    (str(ROOT / "interface"), "interface"),
    (str(ROOT / "dashboard" / "static"), "dashboard/static"),
    (str(ROOT / "core" / "prompt.txt"), "core"),
    (str(ROOT / "core" / "runtime_rules"), "core/runtime_rules"),
    (str(ROOT / "config" / "nebix.ico"), "config"),
    (str(ROOT / "config" / "nebix_identity.json"), "config"),
    (str(ROOT / "config" / "set_lnk_appid.ps1"), "config"),
]

for optional_dir in (ROOT / "assets",):
    if optional_dir.is_dir():
        datas.append((str(optional_dir), optional_dir.name))

for package_dir in (ROOT / "actions", ROOT / "plugins"):
    datas.extend(
        (str(path), package_dir.name)
        for path in sorted(package_dir.glob("*.py"))
        if path.name != "__init__.py"
    )

hiddenimports = sorted(
    set(
        collect_submodules("actions")
        + collect_submodules("plugins")
        + collect_submodules("tzdata")
        + collect_submodules("pywinauto")
        + collect_submodules(
            "google.genai",
            filter=lambda name: ".tests" not in name,
        )
        + optional_hiddenimports
        + [
            "webview.platforms.edgechromium",
            "webview.platforms.winforms",
            "webview.platforms.win32",
            "webview.platforms.mshtml",
            "win32timezone",
            "pythoncom",
            "win32com.client",
            "psutil",
            "cv2",
            "mss",
            "PIL.Image",
            "sounddevice",
            "numpy",
        ]
    )
)
datas.extend(collect_data_files("tzdata"))
datas.extend(optional_datas)

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NEBIX",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "config" / "nebix.ico"),
    version=str(ROOT / "config" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="NEBIX-Portable",
)
