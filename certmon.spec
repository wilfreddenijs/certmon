# certmon.spec
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# Collect all flask/werkzeug data
flask_datas, flask_binaries, flask_hiddenimports = collect_all('flask')
jinja_datas, jinja_binaries, jinja_hiddenimports = collect_all('jinja2')
werkzeug_datas, werkzeug_binaries, werkzeug_hiddenimports = collect_all('werkzeug')

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=flask_binaries + jinja_binaries + werkzeug_binaries,
    datas=[
        ('templates', 'templates'),
        ('app.py', '.'),
    ] + flask_datas + jinja_datas + werkzeug_datas,
    hiddenimports=[
        'app',
        'flask', 'flask.templating', 'flask.json',
        'jinja2', 'jinja2.ext',
        'werkzeug', 'werkzeug.serving', 'werkzeug.routing',
        'werkzeug.middleware.shared_data',
        'cryptography', 'cryptography.hazmat.backends.openssl',
        'cryptography.hazmat.primitives', 'cryptography.x509',
        'cryptography.x509.oid',
        'openpyxl', 'openpyxl.styles', 'openpyxl.utils',
        'pystray', '_pystray_win32',
        'PIL', 'PIL.Image', 'PIL.ImageDraw',
        'pkg_resources', 'pkg_resources.py2_warn',
    ] + flask_hiddenimports + jinja_hiddenimports + werkzeug_hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
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
    console=False,
    windowed=True,
    icon=None,
)
