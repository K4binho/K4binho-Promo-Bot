Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run Chr(34) & projectDir & "\run_bot.bat" & Chr(34), 0, False
