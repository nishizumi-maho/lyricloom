; Inno Setup 6 script for the per-user LyricLoom installer.
;
; Build (normally through scripts/build-windows.ps1, which passes the version):
;   ISCC.exe /DMyAppVersion=2.1.0 packaging\windows\LyricLoom.iss
;
; Expected input:
;   dist\LyricLoom\        (PyInstaller one-folder output)
;   dist\MusicBeePlugin\   (Starry Karaoke plugin files, optional installer task)
;
; Output:
;   dist\LyricLoom-Setup-<version>.exe
;
; This is a per-user install: no elevation, no Program Files, no machine-wide
; registry keys and no file associations.  Models are downloaded by the app at
; runtime and are deliberately not part of the installer.

#ifndef MyAppVersion
  #define MyAppVersion "2.1.0"
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

; If MusicBee (or anything else) has the plugin files open, Restart Manager
; lists the programs and asks the user to close them before Setup continues.
; MusicBee is not restarted automatically; the user starts it again.
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll
RestartApplications=no

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
; Check makes this task checked by default only when MusicBee is installed; a
; machine without MusicBee shows it unchecked and disabled.
Name: "musicbeeplugin"; Description: "Install the Starry Karaoke plugin for MusicBee"; GroupDescription: "MusicBee"; Check: MusicBeeDetected

[Files]
Source: "..\..\dist\LyricLoom\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The plugin zip's contents belong directly in MusicBee's per-user Plugins
; folder.  No admin rights are needed.  Inno Setup records these files in its
; uninstall log, so the uninstaller removes only the files it installed here.
Source: "..\..\dist\MusicBeePlugin\*"; Excludes: "\RomajiCore.dll,\LibNMeCab.dll,\RomajiLyrics\*"; DestDir: "{userappdata}\MusicBee\Plugins"; Flags: ignoreversion recursesubdirs createallsubdirs; Tasks: musicbeeplugin; Check: MusicBeeDetected
; The romaji engine, MeCab and its dictionary are shared with the Desktop Lyrics
; (Romaji) plugin.  They are replaced only by a newer version (no ignoreversion),
; the dictionary only when it is missing, and the uninstaller never removes them,
; so installing or removing LyricLoom cannot break the other plugin.
Source: "..\..\dist\MusicBeePlugin\RomajiCore.dll"; DestDir: "{userappdata}\MusicBee\Plugins"; Flags: uninsneveruninstall; Tasks: musicbeeplugin; Check: MusicBeeDetected
Source: "..\..\dist\MusicBeePlugin\LibNMeCab.dll"; DestDir: "{userappdata}\MusicBee\Plugins"; Flags: uninsneveruninstall; Tasks: musicbeeplugin; Check: MusicBeeDetected
Source: "..\..\dist\MusicBeePlugin\RomajiLyrics\*"; DestDir: "{userappdata}\MusicBee\Plugins\RomajiLyrics"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs; Tasks: musicbeeplugin; Check: MusicBeeDetected

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Other programs (for example the Starry Karaoke MusicBee plugin) can find the
; installed executable without guessing the per-user install directory.
; The whole key is removed by the uninstaller.
Root: HKCU; Subkey: "Software\LyricLoom"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\LyricLoom"; ValueType: string; ValueName: "Executable"; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; The uninstaller removes only the installation directory and the plugin files
; recorded in its uninstall log.  User settings, logs, cached vocals and
; downloaded models under %LOCALAPPDATA%\LyricLoom are intentionally left in
; place (there is deliberately no [UninstallDelete]).  The rest of the user's
; MusicBee Plugins folder is never touched.

[Code]
function MusicBeeDetected: Boolean;
begin
  Result :=
    DirExists(ExpandConstant('{userappdata}\MusicBee\Plugins')) or
    DirExists(ExpandConstant('{userappdata}\MusicBee')) or
    RegKeyExists(HKEY_CURRENT_USER, 'Software\MusicBee') or
    RegKeyExists(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicBee') or
    RegKeyExists(HKEY_LOCAL_MACHINE, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicBee') or
    RegKeyExists(HKEY_LOCAL_MACHINE, 'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\MusicBee') or
    FileExists(ExpandConstant('{pf}\MusicBee\MusicBee.exe')) or
    FileExists(ExpandConstant('{pf32}\MusicBee\MusicBee.exe'));
end;
