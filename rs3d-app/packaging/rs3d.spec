# PyInstaller spec: `pyinstaller packaging/rs3d.spec` (run on Windows for the Windows build).
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
for pkg in ("rs3d", "nicegui", "obspy", "webview", "keyring", "matplotlib"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
# keyring picks its backend by entry point; obspy loads format readers by name
hiddenimports += collect_submodules("keyring.backends") + collect_submodules("obspy.io.mseed")
hiddenimports += ["scipy.special._cdflib"]

a = Analysis(
    ["../src/rs3d/desktop.py"],
    pathex=["../src"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "playwright"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="RS3D", console=False, icon="rs3d.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="RS3D")
