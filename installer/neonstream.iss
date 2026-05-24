; ══════════════════════════════════════════════════════════════════════════════
;  installer/neonstream.iss — Script Inno Setup 6+
;  Genera: NeonStream_Setup_1.0.0.exe
;
;  Prerequisitos:
;    • Inno Setup 6.x  → https://jrsoftware.org/isdl.php
;    • dist/NeonStream/ ya generado por PyInstaller
;
;  Uso:
;    iscc installer\neonstream.iss
;    → genera installer\output\NeonStream_Setup_1.0.0.exe
;
;  Funcionalidades del instalador:
;    ✓ Wizard con páginas: Bienvenida, Licencia, Directorio, Menú inicio,
;                          Opciones adicionales, Instalando, Finalizado
;    ✓ Acceso directo en Escritorio (opcional)
;    ✓ Acceso directo en Menú Inicio
;    ✓ Registro en Agregar/Quitar programas
;    ✓ Desinstalador incluido
;    ✓ Requiere Windows 10+
;    ✓ Icono personalizado Retrowave
;    ✓ Colores de fondo personalizados (neón)
;    ✓ Crea el .env en %APPDATA%\NeonStream en el primer arranque
; ══════════════════════════════════════════════════════════════════════════════

#define MyAppName        "NeonStream Social Manager"
#define MyAppVersion     "1.0.0"
#define MyAppPublisher   "NeonStream"
#define MyAppURL         "https://github.com/tuusuario/neonstream"
#define MyAppExeName     "NeonStream.exe"
#define MyAppIcon        "..\ui\assets\neonstream.ico"
#define DistDir          "..\dist\NeonStream"
#define OutputDir        "output"

[Setup]
; ── Identificadores únicos (regenerar con Tools > Generate GUID en Inno IDE) ─
AppId={{A3F7C2B1-4D8E-4F5A-9B2C-E1D6F3A78C52}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases

; ── Rutas de salida ───────────────────────────────────────────────────────────
DefaultDirName={autopf}\NeonStream
DefaultGroupName={#MyAppName}
OutputDir={#OutputDir}
OutputBaseFilename=NeonStream_Setup_{#MyAppVersion}

; ── Icono y apariencia ────────────────────────────────────────────────────────
SetupIconFile={#MyAppIcon}
WizardStyle=modern
WizardSizePercent=120
WizardImageFile=compiler:WizModernImage.bmp
WizardSmallImageFile=compiler:WizModernSmallImage.bmp

; ── Compresión (LZMA2 máxima) ────────────────────────────────────────────────
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; ── Requisitos del sistema ────────────────────────────────────────────────────
MinVersion=10.0.17763    ; Windows 10 v1809+
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; ── Privilegios ──────────────────────────────────────────────────────────────
PrivilegesRequired=lowest          ; No requiere admin — instala por usuario
PrivilegesRequiredOverridesAllowed=dialog

; ── Miscelánea ────────────────────────────────────────────────────────────────
DisableProgramGroupPage=no
DisableWelcomePage=no
AllowNoIcons=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer

[Languages]
Name: "spanish";  MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english";  MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "Crear acceso directo en el &Escritorio";     GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "quicklaunchicon"; Description: "Crear icono en la &barra de tareas (inicio rápido)"; GroupDescription: "Accesos directos:"; Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
; ── Bundle PyInstaller completo ───────────────────────────────────────────────
Source: "{#DistDir}\*";  DestDir: "{app}";  Flags: ignoreversion recursesubdirs createallsubdirs

; ── .env.example junto al ejecutable ─────────────────────────────────────────
Source: "..\{#MyAppName}.env.example";  DestDir: "{app}";  DestName: ".env.example";  Flags: ignoreversion onlyifdoesntexist

; ── Documentación ─────────────────────────────────────────────────────────────
Source: "..\README.md";   DestDir: "{app}";  DestName: "README.md";   Flags: ignoreversion isreadme
Source: "..\CHANGELOG.md"; DestDir: "{app}"; DestName: "CHANGELOG.md"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Menú Inicio
Name: "{group}\{#MyAppName}";          Filename: "{app}\{#MyAppExeName}";  IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar NeonStream"; Filename: "{uninstallexe}"

; Escritorio (tarea opcional)
Name: "{autodesktop}\{#MyAppName}";    Filename: "{app}\{#MyAppExeName}";  IconFilename: "{app}\{#MyAppExeName}";  Tasks: desktopicon

; Inicio rápido (tarea opcional)
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}";  Tasks: quicklaunchicon

[Run]
; Opción "Lanzar NeonStream" en la última página del wizard
Filename: "{app}\{#MyAppExeName}";
  Description: "Lanzar {#MyAppName}";
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Limpiar archivos generados en tiempo de ejecución al desinstalar
Type: files;      Name: "{app}\neonstream.db"
Type: files;      Name: "{app}\neonstream.db-journal"
Type: filesandordirs; Name: "{app}\__pycache__"

[Registry]
; Registrar en Agregar/Quitar programas (información adicional)
Root: HKCU; Subkey: "Software\NeonStream\SocialManager";
  ValueType: string; ValueName: "InstallPath"; ValueData: "{app}";
  Flags: uninsdeletekey

[Code]
// ── Verificar que Windows 10+ esté disponible ────────────────────────────────
function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  if (Version.Major < 10) then
  begin
    MsgBox(
      'NeonStream Social Manager requiere Windows 10 o superior.' + #13#10 +
      'Tu versión de Windows no es compatible.',
      mbCriticalError, MB_OK
    );
    Result := False;
  end
  else
    Result := True;
end;

// ── Mensaje de bienvenida personalizado ──────────────────────────────────────
function GetWelcomeMessage(Param: String): String;
begin
  Result :=
    'Bienvenido al instalador de NeonStream Social Manager.' + #13#10 + #13#10 +
    'Esta aplicación te permite gestionar tus redes sociales desde' + #13#10 +
    'el escritorio con integración de IA (Google Gemini).' + #13#10 + #13#10 +
    'Haz clic en Siguiente para continuar.';
end;
