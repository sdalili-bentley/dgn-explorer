from pathlib import Path

root = Path(SPECPATH)
excluded = ["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtPrintSupport", "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtDesigner"]
cli = Analysis([str(root / "dgn_folder.py")], pathex=[str(root)], hiddenimports=["win32com.storagecon", "win32timezone"], excludes=["PySide6", "tkinter"], noarchive=False)
gui = Analysis([str(root / "gui_entry.py")], pathex=[str(root)], hiddenimports=["dgn_explorer.desktop", "dgn_explorer.portable", "test_support", "win32com.storagecon", "win32timezone"], excludes=excluded, noarchive=False)
def needed_native(entry):
	target = entry[0].replace("\\", "/")
	if target.endswith("/Qt6Svg.dll"):
		return False
	if "/plugins/" not in target:
		return True
	plugin = target.split("/plugins/", 1)[1]
	return plugin == "platforms/qwindows.dll" or plugin.startswith("styles/")

gui.binaries = [entry for entry in gui.binaries if needed_native(entry)]
gui.datas = [entry for entry in gui.datas if needed_native(entry)]
backend = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="dgn-explorer", console=True, upx=False, contents_directory="_internal")
desktop = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="dgn-explorer-gui", console=False, upx=False, contents_directory="_internal")
bundle = COLLECT(backend, desktop, cli.binaries, cli.datas, gui.binaries, gui.datas, strip=False, upx=False, name="DGN-Explorer")