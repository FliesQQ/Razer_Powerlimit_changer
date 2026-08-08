# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for BladePower."""

from pathlib import Path

block_cipher = None
root = Path(SPECPATH)
icon_file = root / "Synapse.ico"

a = Analysis(
    [str(root / "run_app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "profiles.json"), "."),
        (str(icon_file), "."),
    ],
    hiddenimports=[
        "hid",
        "psutil",
        "keyboard",
        "pystray",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "app",
        "app.main",
        "app.gui",
        "app.admin",
        "app.hotkeys",
        "app.tray",
        "app.paths",
        "app.profile_manager",
        "app.backends",
        "app.backends.winring0",
        "app.backends.cpu_rapl",
        "app.backends.cpu_undervolt",
        "app.backends.synapse_gpu",
        "app.backends.synapse_guard",
        "app.backends.afterburner",
        "app.backends.monitor",
        "app.backends.gpu_nvapi_probe",
        "app.backends.fan_curve",
        "app.backends.temps",
        "app.backends.xtu_detect",
        "app.backends.razer_devices",
        "app.preflight",
        "app.preflight_dialog",
        "app.sensor_tray",
        "app.osd_overlay",
        "app.widgets",
        "app.widgets.hotkey_capture",
        "app.widgets.fan_curve_chart",
        "app.autostart",
        "app.power_events",
        "app.window_icon",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["customtkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="BladePower",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=str(icon_file) if icon_file.is_file() else None,
)
