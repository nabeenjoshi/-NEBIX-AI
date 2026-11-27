Option Explicit
Dim sh, fso, root, exePath
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
exePath = root & "\dist\NEBIX-Portable\NEBIX.exe"
If fso.FileExists(exePath) Then
  sh.Run """" & exePath & """", 0, False
Else
  MsgBox "Build NEBIX first with build_nebix.bat, then launch the standalone EXE.",  vbExclamation, "NEBIX"
End If
