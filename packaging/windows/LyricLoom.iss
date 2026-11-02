; Inno Setup 6 script for the per-user LyricLoom installer.
;
; Build (normally through scripts/build-windows.ps1, which passes the version):
;   ISCC.exe /DMyAppVersion=2.0.0 packaging\windows\LyricLoom.iss
;
; Expected input:
;   dist\LyricLoom\  (PyInstaller one-folder output)
;
; Output:
;   dist\LyricLoom-Setup-<version>.exe
;
; This is a per-user install: no elevation, no Program Files, no machine-wide
; registry keys and no file associations.  Models are downloaded by the app at
; runtime and are deliberately not part of the installer.

#ifndef MyAppVersion
  #define MyAppVersion "2.0.0"
#endif

#define MyAppName "LyricLoom"
#define MyAppPublisher "LyricLoom contributors"
#define MyAppURL "https://github.com/nishizumi-maho/lyricloom"
#define MyAppExeName "LyricLoom.exe"
#define MyIconFile AddBackslash(SourcePath) + "LyricLoom.ico"

[Setup]
; Stable AppId: changing it would make Windows treat a new version as a
; different product and leave the old uninstall entry behind.
AppId={{30B45883-3E91-4D7B-A462-5B4EA3BF1D2B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}

DefaultDirName={localappdata}\Programs\LyricLoom
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir=..\..\dist
OutputBaseFilename=LyricLoom-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern

UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesAssociations=no

#if FileExists(MyIconFile)
SetupIconFile={#MyIconFile}
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\LyricLoom\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; The uninstaller removes only the installation directory.  User settings,
; logs, cached vocals and downloaded models under %LOCALAPPDATA%\LyricLoom are
; intentionally left in place (there is deliberately no [UninstallDelete]).
