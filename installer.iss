#define AppName "PulsePlay"
#define AppVersion "0.8.6"
#define AppPublisher "PulsePlay"
#define AppExeName "PulsePlay.exe"

[Setup]
AppId={{C56A61B3-B21E-4F77-AB4E-2CE41E148F2D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\PulsePlay
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=dist
OutputBaseFilename=PulsePlay-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=force
CloseApplicationsFilter=PulsePlay.exe
RestartApplications=no
Uninstallable=yes
UsePreviousAppDir=yes
UsePreviousGroup=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительные значки:"; Flags: unchecked

[Files]
Source: "dist\PulsePlay.exe"; DestDir: "{app}"; Flags: ignoreversion

; Clean loose files left by the earlier source-archive version if it was
; unpacked into this install folder. User settings live outside {app}.
[InstallDelete]
Type: files; Name: "{app}\app.py"
Type: files; Name: "{app}\core.py"
Type: files; Name: "{app}\help_ui.py"
Type: files; Name: "{app}\network.py"
Type: files; Name: "{app}\launch.pyw"
Type: files; Name: "{app}\Start.bat"
Type: files; Name: "{app}\START.cmd"
Type: files; Name: "{app}\ЗАПУСТИТЬ.cmd"

[Icons]
Name: "{group}\PulsePlay"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\PulsePlay"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Запустить PulsePlay"; Flags: nowait postinstall skipifsilent\n