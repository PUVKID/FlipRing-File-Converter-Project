; PUVKID 무료 배포판 설치 구성
[Setup]
AppId=PUVKID.FlipRing19
AppName=FlipRing
AppVersion=1.14.0
AppPublisher=PUVKID
DefaultDirName={localappdata}\Programs\FlipRing19
DefaultGroupName=FlipRing
UsePreviousAppDir=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#GetEnv('FLIPRING_INSTALLER')}
OutputBaseFilename=FlipRing-Setup
SetupIconFile={#GetEnv('FLIPRING_SOURCE')}\assets\app.ico
UninstallDisplayIcon={app}\FlipRing.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile={#GetEnv('FLIPRING_SOURCE')}\LICENSE.txt
InfoAfterFile={#GetEnv('FLIPRING_PROGRAM')}\사용안내.txt
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
[Files]
Source: "{#GetEnv('FLIPRING_PROGRAM')}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "FlipRing19"; Flags: uninsdeletevalue
[Run]
Filename: "{app}\FlipRing.exe"; Description: "FlipRing"; Flags: nowait postinstall skipifsilent
