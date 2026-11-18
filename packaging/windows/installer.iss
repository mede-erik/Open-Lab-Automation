; Copyright (C) 2025-2026 Erik Medeossi
; This file is part of Open Lab Automation.
; Licensed under the GNU General Public License v3.0; see the LICENSE file.
;
; Windows installer (Inno Setup 6.3 or newer) of the frozen bundle. Built by
; scripts/build_package.py (step "installer"), which passes these defines:
;   AppVersion, AppVersionNumeric (X.Y.Z.0), BundleDir, RepoRoot, OutDir, OutputBase
;
; The file is saved as UTF-8 with a BOM: the texts of the languages below have accents.
;
; What the installer does, besides copying the files:
;   * languages: the same as frontend/lang (en, it, fr, es, de); a test keeps them equal
;   * requirements: Windows 10 1809 or later (64 bit); Setup checks the free disk space itself
;   * a previous installation (same user or all-users mode) is found, and Setup asks
;       Update : the old uninstaller runs first and removes the program files of the old
;                version (only the files it installed), then the new ones are installed: no
;                file of the old version is left behind
;       Repair : the files of this version are installed again over the existing ones; the
;                missing ones come back, nothing is removed
;     Projects, measurements and settings are not in the installation folder: never touched.
;     A silent installation takes /MODE=UPDATE or /MODE=REPAIR; without it: Repair when the
;     installed version is the same, Update otherwise.

#ifndef AppVersion
  #error Build this script with scripts/build_package.py (AppVersion is not defined)
#endif

[Setup]
; Never change AppId: Windows uses it to recognise an older installation and upgrade it.
; The same GUID is in AppGuid of the [Code] section (a test checks that they are equal).
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
; Windows 10 1809 (build 17763) is the oldest Windows that Qt 6 and Python 3.12 support
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install without a prompt; the user can choose "all users" (asks for administrator)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\OpenLabAutomation.exe
CloseApplications=yes
; Ask for the language only when the language of Windows is not one of ours
ShowLanguageDialog=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
ExistingTitle=Existing installation
ExistingSubtitle=Open Lab Automation %1 is already installed.
ExistingPrompt=What do you want to do? Your projects, measurements and settings are not touched.
OptUpdate=Update to version %1: the files of the old version are removed first, then the new ones are installed
OptRepair=Repair: install the files of version %1 again over the existing ones, restoring any that are missing
RemovingOld=Removing the previous version...

italian.ExistingTitle=Installazione esistente
italian.ExistingSubtitle=Open Lab Automation %1 è già installato.
italian.ExistingPrompt=Cosa vuoi fare? I tuoi progetti, le misure e le impostazioni non vengono toccati.
italian.OptUpdate=Aggiorna alla versione %1: prima si rimuovono i file della versione precedente, poi si installano quelli nuovi
italian.OptRepair=Ripara: reinstalla i file della versione %1 sopra quelli esistenti, ripristinando quelli mancanti
italian.RemovingOld=Rimozione della versione precedente...

french.ExistingTitle=Installation existante
french.ExistingSubtitle=Open Lab Automation %1 est déjà installé.
french.ExistingPrompt=Que voulez-vous faire ? Vos projets, mesures et paramètres ne sont pas modifiés.
french.OptUpdate=Mettre à jour vers la version %1 : les fichiers de l'ancienne version sont d'abord supprimés, puis les nouveaux sont installés
french.OptRepair=Réparer : réinstaller les fichiers de la version %1 par-dessus les fichiers existants, en restaurant ceux qui manquent
french.RemovingOld=Suppression de la version précédente...

spanish.ExistingTitle=Instalación existente
spanish.ExistingSubtitle=Open Lab Automation %1 ya está instalado.
spanish.ExistingPrompt=¿Qué quieres hacer? Tus proyectos, mediciones y ajustes no se tocan.
spanish.OptUpdate=Actualizar a la versión %1: primero se eliminan los archivos de la versión anterior y después se instalan los nuevos
spanish.OptRepair=Reparar: volver a instalar los archivos de la versión %1 sobre los existentes, restaurando los que falten
spanish.RemovingOld=Eliminando la versión anterior...

german.ExistingTitle=Vorhandene Installation
german.ExistingSubtitle=Open Lab Automation %1 ist bereits installiert.
german.ExistingPrompt=Was möchten Sie tun? Ihre Projekte, Messungen und Einstellungen bleiben unberührt.
german.OptUpdate=Auf Version %1 aktualisieren: Zuerst werden die Dateien der alten Version entfernt, dann die neuen installiert
german.OptRepair=Reparieren: Die Dateien der Version %1 über die vorhandenen installieren und fehlende wiederherstellen
german.RemovingOld=Vorherige Version wird entfernt...

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

[Code]
const
  // The AppId of the [Setup] section: Inno Setup writes the uninstall entry under it
  AppGuid = '{6B0B8A3E-5C2D-4E8E-9D5B-0F6A3C41B7A2}';

var
  ModePage: TInputOptionWizardPage;
  PreviousVersion: String;
  PreviousUninstaller: String;

function UninstallKey: String;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + AppGuid + '_is1';
end;

// True when this program is installed in the mode of this run (this user, or all users)
function FindPreviousInstall: Boolean;
var
  Root: Integer;
  Uninstall: String;
begin
  if IsAdminInstallMode then
    Root := HKLM
  else
    Root := HKCU;
  Result := RegQueryStringValue(Root, UninstallKey, 'DisplayVersion', PreviousVersion)
    and RegQueryStringValue(Root, UninstallKey, 'UninstallString', Uninstall);
  if Result then
    PreviousUninstaller := RemoveQuotes(Uninstall);
end;

procedure InitializeWizard;
var
  Requested: String;
begin
  if not FindPreviousInstall then
    Exit;   // first installation: no question, Setup goes on as usual

  ModePage := CreateInputOptionPage(wpWelcome,
    CustomMessage('ExistingTitle'),
    FmtMessage(CustomMessage('ExistingSubtitle'), [PreviousVersion]),
    CustomMessage('ExistingPrompt'), True, False);
  ModePage.Add(FmtMessage(CustomMessage('OptUpdate'), ['{#AppVersion}']));
  ModePage.Add(FmtMessage(CustomMessage('OptRepair'), ['{#AppVersion}']));

  // The default answer; /MODE=UPDATE or /MODE=REPAIR on the command line decides a silent run
  Requested := Uppercase(ExpandConstant('{param:MODE|}'));
  if Requested = 'REPAIR' then
    ModePage.Values[1] := True
  else if Requested = 'UPDATE' then
    ModePage.Values[0] := True
  else if PreviousVersion = '{#AppVersion}' then
    ModePage.Values[1] := True
  else
    ModePage.Values[0] := True;
end;

function WantsUpdate: Boolean;
begin
  Result := (ModePage <> nil) and ModePage.Values[0];
end;

// Update: the old uninstaller removes the old program files before the new ones are copied.
// It removes only what the old Setup installed, so a folder shared with other files is safe.
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep <> ssInstall) or (not WantsUpdate) then
    Exit;
  if not WizardSilent then
    WizardForm.StatusLabel.Caption := CustomMessage('RemovingOld');
  if not FileExists(PreviousUninstaller) then
    Log('Previous uninstaller not found, the files are replaced in place: ' + PreviousUninstaller)
  else if Exec(PreviousUninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log('Previous version removed, exit code ' + IntToStr(ResultCode))
  else
    Log('Could not run the previous uninstaller: ' + SysErrorMessage(ResultCode));
end;
