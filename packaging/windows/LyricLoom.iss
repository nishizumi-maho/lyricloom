; Inno Setup 6 script for the per-user LyricLoom installer.
;
; Build (normally through scripts/build-windows.ps1, which passes the version):
;   ISCC.exe /DMyAppVersion=2.1.1 packaging\windows\LyricLoom.iss
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
  #define MyAppVersion "2.1.1"
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
; Keep the task choices from an earlier version (for example the optional
; MusicBee plugin). A silent update passes /SKIPPLUGIN=1 to override it.
UsePreviousTasks=yes

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
; machine without MusicBee shows it unchecked and disabled. A silent update
; while MusicBee is open passes /SKIPPLUGIN=1 so MusicBee is never closed.
Name: "musicbeeplugin"; Description: "Install the Starry Karaoke plugin for MusicBee"; GroupDescription: "MusicBee"; Check: MusicBeeTaskAllowed

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
; Interactive install: the normal "Launch LyricLoom" checkbox on the finished
; page. Silent installs skip this entry (skipifsilent) and use the next one,
; which only starts the app when the updater passed /RELAUNCH=1.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: RelaunchAfterSilentInstall

; The uninstaller removes the installation directory and the plugin files recorded
; in its uninstall log. It then asks once (default No) whether to also delete
; the data LyricLoom created in its data folder. Only the entries LyricLoom itself
; creates there are deleted, never the folder as a whole. Custom work/vocals/models
; locations (settings.json or environment variables) are listed for manual removal;
; if one of them lies inside the data folder, or settings.json cannot be read,
; nothing is deleted.
; The user's music library and the .lrc files next to the music are never
; touched. The rest of the user's MusicBee Plugins folder is never touched.

[Code]
function RelaunchAfterSilentInstall: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

// Every LyricLoom process holds this mutex until it exits (lyricloom/updater.py). The app starts
// Setup as the last step of closing, but its process can live a little longer while background
// threads finish; installing then would hit files in use. A silent install (the in-app update)
// waits up to 60 seconds and gives up without changing anything; an interactive install waits
// briefly and then asks the user to close LyricLoom.
function LyricLoomRunning: Boolean;
begin
  Result := CheckForMutexes('LyricLoomAppRunning');
end;

function WaitForLyricLoomExit(const MaxMs: Integer): Boolean;
var
  Waited: Integer;
begin
  Waited := 0;
  while LyricLoomRunning and (Waited < MaxMs) do
  begin
    Sleep(500);
    Waited := Waited + 500;
  end;
  Result := not LyricLoomRunning;
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if WizardSilent then
  begin
    if not WaitForLyricLoomExit(60000) then
    begin
      Log('LyricLoom was still running after 60 seconds; the silent install was cancelled.');
      Result := False;
    end;
    Exit;
  end;
  if WaitForLyricLoomExit(15000) then
    Exit;
  while LyricLoomRunning do
  begin
    if MsgBox('LyricLoom is still running.' + #13#10#13#10 +
      'Close LyricLoom, then click OK to continue the installation.',
      mbInformation, MB_OKCANCEL) <> IDOK then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

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

function MusicBeeTaskAllowed: Boolean;
begin
  Result := MusicBeeDetected and (ExpandConstant('{param:SKIPPLUGIN|0}') <> '1');
end;

function IsJsonSpace(const C: Char): Boolean;
begin
  Result := (C = ' ') or (C = #9) or (C = #13) or (C = #10);
end;

// Reads one string value of settings.json, which LyricLoom writes as UTF-8 JSON with the
// non-ASCII characters of a path stored as they are (C:\Users\Jose with an accent, for example).
// Returns True with Value = '' when the key is absent or null, True with the folder when it was
// read, and False when the key is there but cannot be understood: the caller must then refuse to
// delete anything, because it cannot know where that folder is.
function ReadSetting(const FileName, KeyName: String; var Value: String): Boolean;
var
  Raw: AnsiString;
  Text, Needle: String;
  P, Q: Integer;
begin
  Value := '';
  Result := True;
  if not FileExists(FileName) then
    Exit;
  if not LoadStringFromFile(FileName, Raw) then
  begin
    Result := False;
    Exit;
  end;
  Text := UTF8Decode(Raw);
  Needle := '"' + KeyName + '"';
  P := Pos(Needle, Text);
  if P = 0 then
    Exit;
  Result := False;
  P := P + Length(Needle);
  while (P <= Length(Text)) and IsJsonSpace(Text[P]) do
    Inc(P);
  if (P > Length(Text)) or (Text[P] <> ':') then
    Exit;
  Inc(P);
  while (P <= Length(Text)) and IsJsonSpace(Text[P]) do
    Inc(P);
  if Copy(Text, P, 4) = 'null' then
  begin
    Result := True;
    Exit;
  end;
  if (P > Length(Text)) or (Text[P] <> '"') then
    Exit;
  Inc(P);
  Q := P;
  while (Q <= Length(Text)) and (Text[Q] <> '"') do
    Inc(Q);
  if Q > Length(Text) then
    Exit;
  Value := Copy(Text, P, Q - P);
  // "\\" is a backslash and "\/" a slash; any other escape (\uXXXX, \n ...) is not expected in
  // a folder LyricLoom saved, so it is treated as unreadable rather than guessed.
  StringChangeEx(Value, '\\', #1, True);
  StringChangeEx(Value, '\/', '/', True);
  if Pos('\', Value) > 0 then
  begin
    Value := '';
    Exit;
  end;
  StringChangeEx(Value, #1, '\', True);
  Result := True;
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
          // A junction or symlink can point back to an ancestor; following it would loop.
          if (FindRec.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) = 0 then
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

// Adds a configured folder that is not LyricLoom's default to the "remove by hand" list and
// reports whether it lies inside the data folder (then nothing in the data folder is deleted).
procedure NoteCustomFolder(const Caption, Dir, DefaultDir, DataDir: String;
  var Manual: String; var CustomInside: Boolean);
begin
  if (Dir = '') or SameDirectory(Dir, DefaultDir) then
    Exit;
  Manual := Manual + #13#10 + '  ' + Caption + ': ' + Dir;
  if SameDirectory(Dir, DataDir) or IsInsideDirectory(Dir, DataDir) then
    CustomInside := True;
end;

// Deletes only what LyricLoom itself creates in its data folder. The folder itself is removed
// only when that leaves it empty, so a file the user put there is never deleted.
procedure DeleteOwnData(const DataDir: String);
var
  FindRec: TFindRec;
begin
  DelTree(DataDir + '\work', True, True, True);
  DelTree(DataDir + '\vocals', True, True, True);
  DelTree(DataDir + '\models', True, True, True);
  DelTree(DataDir + '\logs', True, True, True);
  DelTree(DataDir + '\bin', True, True, True);
  DeleteFile(DataDir + '\settings.json');
  DeleteFile(DataDir + '\settings.json.tmp');
  DeleteFile(DataDir + '\assemblyai.key');
  if FindFirst(DataDir + '\scan-*.json', FindRec) then
  begin
    try
      repeat
        DeleteFile(DataDir + '\' + FindRec.Name);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
  RemoveDir(DataDir);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, SettingsFile, ModelsDir, VocalsDir, WorkDir, LibraryDir, Manual, MessageText: String;
  CustomInside, Readable: Boolean;
  Answer: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if UninstallSilent then
    Exit;

  DataDir := ExpandConstant('{localappdata}\LyricLoom');
  if not DirExists(DataDir) then
    Exit;
  SettingsFile := DataDir + '\settings.json';
  Readable := ReadSetting(SettingsFile, 'library', LibraryDir);
  if not ReadSetting(SettingsFile, 'models', ModelsDir) then
    Readable := False;
  if not ReadSetting(SettingsFile, 'vocals', VocalsDir) then
    Readable := False;
  if not ReadSetting(SettingsFile, 'work', WorkDir) then
    Readable := False;
  if not Readable then
  begin
    MsgBox('The uninstaller could not read the folders saved in:' + #13#10 +
      '  ' + SettingsFile + #13#10#13#10 +
      'It cannot tell where your library, models, vocals and work folders are, so it will not ' +
      'delete anything in LyricLoom''s data folder.' + #13#10 +
      'Remove the LyricLoom data files by hand if you want to.', mbInformation, MB_OK);
    Exit;
  end;

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

  // Every configured folder, from settings.json and from the environment, is read before the
  // decision: one that is not a default and lies inside the data folder stops the deletion.
  Manual := '';
  CustomInside := False;
  NoteCustomFolder('models', ModelsDir, DataDir + '\models', DataDir, Manual, CustomInside);
  NoteCustomFolder('kept vocals', VocalsDir, DataDir + '\vocals', DataDir, Manual, CustomInside);
  NoteCustomFolder('work cache', WorkDir, DataDir + '\work', DataDir, Manual, CustomInside);
  NoteCustomFolder('data (LYRICLOOM_DATA_DIR)', GetEnv('LYRICLOOM_DATA_DIR'), DataDir, DataDir,
    Manual, CustomInside);
  NoteCustomFolder('models (LYRICLOOM_MODELS)', GetEnv('LYRICLOOM_MODELS'), DataDir + '\models',
    DataDir, Manual, CustomInside);
  NoteCustomFolder('work cache (LYRICLOOM_WORK)', GetEnv('LYRICLOOM_WORK'), DataDir + '\work',
    DataDir, Manual, CustomInside);

  if CustomInside then
  begin
    MsgBox('A configured models, vocals, work or data folder is inside LyricLoom''s data folder ' +
      'and is not a LyricLoom default location:' + Manual + #13#10#13#10 +
      'The uninstaller will not delete anything in the data folder.' + #13#10 +
      'Remove the LyricLoom data files by hand if you want to.', mbInformation, MB_OK);
    Exit;
  end;

  MessageText := 'LyricLoom can also delete the data it created in:' + #13#10 +
    '  ' + DataDir + #13#10 +
    '  (settings, the AssemblyAI key, logs, the scan and work caches, kept vocals, models' + #13#10 +
    '  and a downloaded whisper build; any other file there is kept)';
  if Manual <> '' then
    MessageText := MessageText + #13#10#13#10 +
      'These custom or environment-provided folders are not LyricLoom default locations. ' +
      'Remove them by hand if you want to:' + Manual;
  MessageText := MessageText + #13#10#13#10 +
    'Your music library and the .lrc files next to your music are never deleted.' + #13#10#13#10 +
    'Delete LyricLoom''s data too?';

  Answer := MsgBox(MessageText, mbConfirmation, MB_YESNO or MB_DEFBUTTON2);
  if Answer = IDYES then
  begin
    DeleteOwnData(DataDir);
    if DirExists(DataDir) then
      MsgBox('Files that LyricLoom did not create were kept in:' + #13#10 + '  ' + DataDir,
        mbInformation, MB_OK);
  end;
end;
