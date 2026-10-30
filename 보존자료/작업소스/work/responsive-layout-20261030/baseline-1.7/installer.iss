; PUVKID 무료 배포판 설치 구성
[Setup]
AppId=PUVKID.FlipRing
AppName=FlipRing
AppVersion=1.7.0
AppPublisher=PUVKID
DefaultDirName={localappdata}\Programs\FlipRing
DefaultGroupName=FlipRing
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=D:\2026\FilpRing Project\work\enhancement-20261030\release-stage3\설치파일
OutputBaseFilename=FlipRing-Setup
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\FlipRing.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=LICENSE.txt
InfoAfterFile=사용안내.txt
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
[Files]
Source: "D:\2026\FilpRing Project\work\enhancement-20261030\release-stage3\프로그램\FlipRing\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
[Icons]
Name: "{group}\FlipRing"; Filename: "{app}\FlipRing.exe"
Name: "{autodesktop}\FlipRing"; Filename: "{app}\FlipRing.exe"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "FlipRing"; Flags: uninsdeletevalue
