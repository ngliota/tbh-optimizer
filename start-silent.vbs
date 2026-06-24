' TBH Optimizer — silent background launcher (no console window).
' Starts the uvicorn server hidden if it isn't already running. Does NOT open a browser,
' so it's unobtrusive on login. Open http://localhost:8000 yourself, or use start.bat.
Dim shell, fso, here
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here
' 0 = hidden window, False = don't wait for it to exit.
shell.Run """" & here & "\.venv\Scripts\python.exe"" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level warning", 0, False
