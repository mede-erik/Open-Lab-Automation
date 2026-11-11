; Copyright (C) 2025-2026 Erik Medeossi
; This file is part of Open Lab Automation.
; Licensed under the GNU General Public License v3.0; see the LICENSE file.
;
; Windows installer (Inno Setup 6.3 or newer) of the frozen bundle. Built by
; scripts/build_package.py (step "installer"), which passes these defines:
;   AppVersion, AppVersionNumeric (X.Y.Z.0), BundleDir, RepoRoot, OutDir, OutputBase

#ifndef AppVersion
  #error Build this script with scripts/build_package.py (AppVersion is not defined)
#endif

[Setup]
; Never change AppId: Windows uses it to recognise an older installation and upgrade it
AppId={{6B0B8A3E-5C2D-4E8E-9D5B-0F6A3C41B7A2}
AppName=Open Lab Automation
AppVersion={#AppVersion}
AppVerName=Open Lab Automation {#AppVersion}
AppPublisher=Erik Medeossi
AppPublisherURL=https://github.com/mede-erik/Open-Lab-Automation
AppSupportURL=https://github.com/mede-erik/Open-Lab-Automation/issues
VersionInfoVersion={#AppVersionNumeric}
DefaultDirName={autopf}\Open Lab Automation
DefaultGroupName=Open Lab Automation
DisableProgramGroupPage=yes
LicenseFile={#RepoRoot}\LICENSE
OutputDir={#OutDir}
OutputBaseFilename={#OutputBase}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install without a prompt; the user can choose "all users" (asks for administrator)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\OpenLabAutomation.exe
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Open Lab Automation"; Filename: "{app}\OpenLabAutomation.exe"
Name: "{group}\{cm:UninstallProgram,Open Lab Automation}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Open Lab Automation"; Filename: "{app}\OpenLabAutomation.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OpenLabAutomation.exe"; Description: "{cm:LaunchProgram,Open Lab Automation}"; Flags: nowait postinstall skipifsilent
