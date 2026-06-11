# certmon.spec
# Build with: pyinstaller certmon.spec

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates', 'templates'),
    ],
    hiddenimports=[
        'app',
        'flask',
        'flask.templating',
        'jinja2',
        'werkzeug',
        'cryptography',
        'cryptography.hazmat.backends.openssl',
        'cryptography.hazmat.primitives',
        'cryptography.x509',
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'engineio',
        'pkg_resources',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
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
    name='CertMon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # No console window
    windowed=True,
    icon=None,              # Add .ico file path here if you have one
)
