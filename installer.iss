; Installer di YGO Toolbox (Inno Setup 6).
;
; Compilazione — la versione arriva da FUORI, così resta UN solo posto da
; aggiornare (core/version.py, come per l'exe):
;   ISCC.exe /DAppVersion=1.0.24 installer.iss
;
; SCELTE DELIBERATE
; - PrivilegesRequired=lowest: si installa PER UTENTE in
;   %LocalAppData%\Programs, NIENTE prompt UAC. Su un'app condivisa fra amici
;   non c'è motivo di chiedere i permessi di amministratore, e ogni cartello
;   d'allarme in meno è un amico in meno che si blocca.
; - I dati (token, watchlist, catalogo) stanno in %UserProfile%\.ygo_toolbox e
;   NON si toccano: né installando né disinstallando. Aggiornare non deve
;   costare la watchlist.
; - Nessun download automatico dell'aggiornamento: l'app avvisa e apre la
;   pagina, il file lo prende l'utente.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "YGO Toolbox"
#define AppExe "YGO Toolbox.exe"
#define AppPublisher "Lorenzo"

[Setup]
; GUID fisso: identifica l'app fra le versioni. NON cambiarlo, o Windows
; considererebbe ogni versione un programma diverso e se ne accumulerebbero.
AppId={{8C5F1B42-3E7A-4D9C-9F21-A1B2C3D4E5F6}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=YGO Toolbox Setup v{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Se l'app è APERTA, chiudila prima di toccare i file. Senza questo,
; aggiornare con l'app in esecuzione lasciava l'exe vecchio al suo posto e
; disinstallare lasciava 44 MB orfani nella cartella (verificato dal vivo:
; l'eseguibile "onefile" di PyInstaller sopravvive alla chiusura della
; finestra e tiene il file bloccato). `force` chiude senza chiedere: non c'è
; niente da salvare, l'app scrive su SQLite a ogni modifica.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "LEGGIMI.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; CloseApplications=force chiude l'app quando si INSTALLA, ma sulla
; DISINSTALLAZIONE non basta: verificato dal vivo, i processi restavano vivi e
; l'exe da 44 MB rimaneva orfano nella cartella. Qui lo si chiude prima che
; parta la rimozione dei file (le voci [UninstallRun] girano per prime).
; Niente da salvare: l'app scrive su SQLite a ogni modifica.
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ""{#AppExe}"""; \
  Flags: runhidden skipifdoesntexist; RunOnceId: "chiudiApp"
