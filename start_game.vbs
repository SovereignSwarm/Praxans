' Praxans launcher without an extra visible batch window.
Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

scriptPath = objFSO.GetParentFolderName(WScript.ScriptFullName)
launcher = """" & scriptPath & "\start_game.bat"""

objShell.Run launcher, 1, False
