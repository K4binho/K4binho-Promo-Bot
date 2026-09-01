Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Mata bot atual pela porta do single-instance lock
shell.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr ""127.0.0.1:47591""') do taskkill /F /PID %a", 0, True
WScript.Sleep 2000

' Inicia novo bot invisivel
shell.Run Chr(34) & projectDir & "\run_bot.bat" & Chr(34), 0, False
