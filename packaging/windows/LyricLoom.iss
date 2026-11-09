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

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; The uninstaller removes the installation directory and the plugin files recorded
; in its uninstall log. It then asks once (default No) whether to also delete
; LyricLoom's own data folders. Custom work/vocals/models locations read from
; settings.json are only deleted when they are LyricLoom's defaults; anything
; else, and any environment-provided location, is listed for manual removal.
; The user's music library and the .lrc files next to the music are never
; touched. The rest of the user's MusicBee Plugins folder is never touched.

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

function ReadSettingString(const FileName, KeyName: String): String;
var
  Raw: AnsiString;
  Text, Needle: String;
  P, Q: Integer;
begin
  Result := '';
  if not LoadStringFromFile(FileName, Raw) then
    Exit;
  Text := String(Raw);
  Needle := '"' + KeyName + '"';
  P := Pos(Needle, Text);
  if P = 0 then
    Exit;
  P := P + Length(Needle);
  while (P <= Length(Text)) and (Text[P] <> '"') do
    Inc(P);
  if P > Length(Text) then
    Exit;
  Inc(P);
  Q := P;
  while (Q <= Length(Text)) and (Text[Q] <> '"') do
    Inc(Q);
  if Q > Length(Text) then
    Exit;
  Result := Copy(Text, P, Q - P);
  StringChangeEx(Result, '\\', '\', True);
  StringChangeEx(Result, '\/', '/', True);
end;

function NormalizedDir(const Value: String): String;
begin
  Result := Value;
  StringChangeEx(Result, '/', '\', True);
  while (Length(Result) > 3) and (Result[Length(Result)] = '\') do
    SetLength(Result, Length(Result) - 1);
end;

function SameDirectory(const A, B: String): Boolean;
begin
  Result := CompareText(NormalizedDir(A), NormalizedDir(B)) = 0;
end;

function IsInsideDirectory(const Child, Parent: String): Boolean;
var
  C, P: String;
begin
  C := NormalizedDir(Child);
  P := NormalizedDir(Parent);
  Result := (Length(C) > Length(P)) and (CompareText(Copy(C, 1, Length(P)), P) = 0)
            and (C[Length(P) + 1] = '\');
end;

function IsMusicFile(const Name: String): Boolean;
var
  Ext: String;
begin
  Ext := ExtractFileExt(Name);
  Result :=
    (CompareText(Ext, '.mp3') = 0) or (CompareText(Ext, '.flac') = 0) or
    (CompareText(Ext, '.m4a') = 0) or (CompareText(Ext, '.aac') = 0) or
    (CompareText(Ext, '.ogg') = 0) or (CompareText(Ext, '.opus') = 0) or
    (CompareText(Ext, '.wav') = 0) or (CompareText(Ext, '.aiff') = 0) or
    (CompareText(Ext, '.aif') = 0) or (CompareText(Ext, '.ape') = 0) or
    (CompareText(Ext, '.wma') = 0);
end;

function ContainsMusicOutsideCaches(const Dir: String): Boolean;
var
  FindRec: TFindRec;
  Sub: String;
begin
  Result := False;
  if not FindFirst(Dir + '\*', FindRec) then
    Exit;
  try
    repeat
      if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
      begin
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
        begin
          if (CompareText(FindRec.Name, 'work') <> 0) and
             (CompareText(FindRec.Name, 'vocals') <> 0) and
             (CompareText(FindRec.Name, 'models') <> 0) then
          begin
            Sub := Dir + '\' + FindRec.Name;
            if ContainsMusicOutsideCaches(Sub) then
            begin
              Result := True;
              Exit;
            end;
          end;
        end
        else if IsMusicFile(FindRec.Name) then
        begin
          Result := True;
          Exit;
        end;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, SettingsFile, ModelsDir, VocalsDir, WorkDir, LibraryDir, Manual, MessageText: String;
  CustomInside: Boolean;
  Answer: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if UninstallSilent then
    Exit;

  DataDir := ExpandConstant('{localappdata}\LyricLoom');
  SettingsFile := DataDir + '\settings.json';
  LibraryDir := ReadSettingString(SettingsFile, 'library');
  if (LibraryDir <> '') and (SameDirectory(LibraryDir, DataDir) or IsInsideDirectory(LibraryDir, DataDir)) then
  begin
    MsgBox('Your music library is inside LyricLoom''s data folder:' + #13#10 +
      '  ' + LibraryDir + #13#10#13#10 +
      'The uninstaller will not delete that folder, because doing so would delete your music.' + #13#10 +
      'Remove the LyricLoom data files by hand if you want to.', mbInformation, MB_OK);
    Exit;
  end;
  if ContainsMusicOutsideCaches(DataDir) then
  begin
    MsgBox('LyricLoom found music files inside its data folder:' + #13#10 +
      '  ' + DataDir + #13#10#13#10 +
      'The uninstaller will not delete that folder, because doing so could delete your music.' + #13#10 +
      'Remove the LyricLoom data files by hand if you want to.', mbInformation, MB_OK);
    Exit;
  end;

  ModelsDir := ReadSettingString(SettingsFile, 'models');
  VocalsDir := ReadSettingString(SettingsFile, 'vocals');
  WorkDir := ReadSettingString(SettingsFile, 'work');

  Manual := '';
  CustomInside := False;
  if (ModelsDir <> '') and not SameDirectory(ModelsDir, DataDir + '\models') then
  begin
    Manual := Manual + #13#10 + '  models: ' + ModelsDir;
    if IsInsideDirectory(ModelsDir, DataDir) then
      CustomInside := True;
    ModelsDir := '';
  end;
  if ModelsDir = '' then
    ModelsDir := DataDir + '\models';

  if (VocalsDir <> '') and not SameDirectory(VocalsDir, DataDir + '\vocals') then
  begin
    Manual := Manual + #13#10 + '  kept vocals: ' + VocalsDir;
    if IsInsideDirectory(VocalsDir, DataDir) then
      CustomInside := True;
    VocalsDir := '';
  end;
  if VocalsDir = '' then
    VocalsDir := DataDir + '\vocals';

  if (WorkDir <> '') and not SameDirectory(WorkDir, DataDir + '\work') then
  begin
    Manual := Manual + #13#10 + '  work cache: ' + WorkDir;
    if IsInsideDirectory(WorkDir, DataDir) then
      CustomInside := True;
    WorkDir := '';
  end;
  if WorkDir = '' then
    WorkDir := DataDir + '\work';

  if CustomInside then
  begin
    MsgBox('One of the configured models, vocals or work folders is inside LyricLoom''s data folder:' +
      Manual + #13#10#13#10 +
      'It is not a LyricLoom default location, so the uninstaller will not delete the data folder.' + #13#10 +
      'Remove the LyricLoom data files by hand if you want to.', mbInformation, MB_OK);
    Exit;
  end;

  if GetEnv('LYRICLOOM_DATA_DIR') <> '' then
  begin
    Manual := Manual + #13#10 + '  data (LYRICLOOM_DATA_DIR): ' + GetEnv('LYRICLOOM_DATA_DIR');
    if IsInsideDirectory(GetEnv('LYRICLOOM_DATA_DIR'), DataDir) then
      CustomInside := True;
  end;
  if GetEnv('LYRICLOOM_MODELS') <> '' then
  begin
    Manual := Manual + #13#10 + '  models (LYRICLOOM_MODELS): ' + GetEnv('LYRICLOOM_MODELS');
    if IsInsideDirectory(GetEnv('LYRICLOOM_MODELS'), DataDir) then
      CustomInside := True;
  end;
  if GetEnv('LYRICLOOM_WORK') <> '' then
  begin
    Manual := Manual + #13#10 + '  work cache (LYRICLOOM_WORK): ' + GetEnv('LYRICLOOM_WORK');
    if IsInsideDirectory(GetEnv('LYRICLOOM_WORK'), DataDir) then
      CustomInside := True;
  end;

  MessageText := 'LyricLoom can also delete its own data folders:' + #13#10 +
    '  settings, logs and scan cache: ' + DataDir + #13#10 +
    '  work cache: ' + WorkDir + #13#10 +
    '  kept vocals: ' + VocalsDir + #13#10 +
    '  models: ' + ModelsDir + #13#10 +
    '  AssemblyAI key: ' + DataDir + '\assemblyai.key';
  if Manual <> '' then
    MessageText := MessageText + #13#10#13#10 +
      'These custom or environment-provided folders are not LyricLoom default locations. ' +
      'Remove them by hand if you want to:' + Manual;
  MessageText := MessageText + #13#10#13#10 +
    'Your music library and the .lrc files next to your music are never deleted.' + #13#10#13#10 +
    'Delete LyricLoom''s data folders too?';

  Answer := MsgBox(MessageText, mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
  if Answer = IDYES then
    DelTree(DataDir, True, True, True);
end;
