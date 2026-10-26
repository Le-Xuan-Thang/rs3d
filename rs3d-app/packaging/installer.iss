; Inno Setup script: builds dist\RS3D-Setup-<version>.exe from dist\RS3D\ (see build_windows.ps1).
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6F0B7C3E-5A52-4E5B-9E0F-3D0000000001}
AppName=RS3D
AppVersion={#AppVersion}
AppPublisher=RS3D
DefaultDirName={autopf}\RS3D
DefaultGroupName=RS3D
OutputDir=..\dist
OutputBaseFilename=RS3D-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\RS3D.exe
SetupIconFile=rs3d.ico

[Files]
Source: "..\dist\RS3D\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\RS3D"; Filename: "{app}\RS3D.exe"
Name: "{autodesktop}\RS3D"; Filename: "{app}\RS3D.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\RS3D.exe"; Description: "Start RS3D"; Flags: postinstall nowait skipifsilent
