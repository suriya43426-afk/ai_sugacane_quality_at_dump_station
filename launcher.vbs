Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName) & "\ai_orchestration.bat"
' Run with 0 (vbHide)
WshShell.Run chr(34) & strPath & Chr(34), 0
Set WshShell = Nothing
