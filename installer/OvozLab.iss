; OvozLab — Windows o'rnatuvchisi (Inno Setup 6)
; Yig'ish: powershell -ExecutionPolicy Bypass -File installer\build.ps1

#define AppName "OvozLab"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppPublisher "OvozLab contributors"
#define AppURL "https://github.com/uz4studiosuz/UzbekLabs"
#define AppId "{{8E3C2A51-6F0B-4C7D-9A1E-5B2F7D4C9E10}"
#define Root ".."

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=Output
OutputBaseFilename=OvozLab-Setup-{#AppVersion}
SetupIconFile=assets\ovozlab.ico
UninstallDisplayIcon={app}\assets\ovozlab.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardSizePercent=110
WizardImageFile=assets\wizard-1x.bmp,assets\wizard-2x.bmp
WizardSmallImageFile=assets\wizard-small-1x.bmp,assets\wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no
LicenseFile={#Root}\LICENSE
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup

[Languages]
Name: "uz"; MessagesFile: "compiler:Default.isl"

[Messages]
uz.SetupAppTitle=O'rnatish
uz.SetupWindowTitle=%1 — o'rnatish
uz.ButtonBack=< &Orqaga
uz.ButtonNext=&Keyingi >
uz.ButtonInstall=&O'rnatish
uz.ButtonOK=OK
uz.ButtonCancel=Bekor qilish
uz.ButtonYes=&Ha
uz.ButtonNo=&Yo'q
uz.ButtonFinish=&Tayyor
uz.ButtonBrowse=&Tanlash...
uz.ButtonWizardBrowse=T&anlash...
uz.ExitSetupTitle=O'rnatishdan chiqish
uz.ExitSetupMessage=O'rnatish tugallanmadi. Hozir chiqsangiz, dastur o'rnatilmaydi.%n%nKeyinroq qayta ishga tushirib, o'rnatishni yakunlashingiz mumkin.%n%nChiqasizmi?
uz.WelcomeLabel1=[name] o'rnatuvchisiga xush kelibsiz
uz.WelcomeLabel2=[name/ver] kompyuteringizga o'rnatiladi.%n%nO'rnatish ikki bosqichda bo'ladi:%n%n1. Hozir — dastur va asosiy komponentlar (~120 MB yuklanadi).%n2. Birinchi ishga tushirishda — AI modellar va qurilmangizga mos dvigatel. Ular nima ekani, hajmi va qayerga saqlanishi oldindan ko'rsatiladi.%n%nInternet aloqasi kerak.
uz.WizardLicense=Litsenziya
uz.LicenseLabel=Davom etishdan oldin quyidagi ma'lumotni o'qing.
uz.LicenseLabel3=OvozLab ochiq kodli dastur va Apache 2.0 litsenziyasi asosida tarqatiladi.
uz.LicenseAccepted=Litsenziya shartlarini &qabul qilaman
uz.LicenseNotAccepted=Qabul &qilmayman
uz.WizardSelectDir=O'rnatish joyini tanlang
uz.SelectDirDesc=[name] qayerga o'rnatilsin?
uz.SelectDirLabel3=Dastur va uning Python muhiti quyidagi papkaga o'rnatiladi.
uz.SelectDirBrowseLabel=Davom etish uchun "Keyingi" ni bosing. Boshqa papka tanlash uchun "Tanlash" ni bosing.
uz.DiskSpaceGBLabel=Kamida [gb] GB bo'sh joy kerak. Keyinchalik PyTorch uchun shu diskda yana ~4 GB kerak bo'ladi.
uz.DiskSpaceMBLabel=Hozir kamida [mb] MB bo'sh joy kerak. Keyinchalik PyTorch uchun shu diskda yana ~4 GB kerak bo'ladi (modellar joyini alohida tanlaysiz).
uz.DirExistsTitle=Papka mavjud
uz.DirExists=Bunday papka allaqachon bor:%n%n%1%n%nShu papkaga o'rnatilsinmi?
uz.WizardSelectTasks=Qo'shimcha vazifalar
uz.SelectTasksDesc=Qo'shimcha nimalar bajarilsin?
uz.SelectTasksLabel2=Kerakli bandlarni belgilang va "Keyingi" ni bosing.
uz.WizardReady=O'rnatishga tayyor
uz.ReadyLabel1=[name] o'rnatishga tayyor.
uz.ReadyLabel2a="O'rnatish" ni bosing. Sozlamalarni ko'rib chiqish uchun "Orqaga" ni bosing.
uz.ReadyLabel2b="O'rnatish" ni bosing.
uz.ReadyMemoDir=O'rnatish joyi:
uz.ReadyMemoTasks=Qo'shimcha vazifalar:
uz.WizardPreparing=Tayyorlanmoqda
uz.PreparingDesc=[name] o'rnatishga tayyorlanmoqda.
uz.ApplicationsFound=Quyidagi dasturlar yangilanadigan fayllardan foydalanmoqda. Ularni avtomatik yopishga ruxsat bering.
uz.ApplicationsFound2=Quyidagi dasturlar yangilanadigan fayllardan foydalanmoqda. Ularni avtomatik yopishga ruxsat bering.
uz.CloseApplications=Dasturlarni &avtomatik yopish
uz.DontCloseApplications=Dasturlarni &yopmaslik
uz.WizardInstalling=O'rnatilmoqda
uz.InstallingLabel=[name] o'rnatilmoqda, kuting...
uz.FinishedHeadingLabel=[name] o'rnatildi
uz.FinishedLabelNoIcons=[name] kompyuteringizga o'rnatildi.
uz.FinishedLabel=[name] kompyuteringizga o'rnatildi. Uni "Start" menyusidan ochishingiz mumkin.%n%nBirinchi ishga tushirishda o'rnatish ustasi qolgan komponentlarni yuklab oladi.
uz.ClickFinish=O'rnatuvchidan chiqish uchun "Tayyor" ni bosing.
uz.StatusExtractFiles=Fayllar nusxalanmoqda...
uz.StatusCreateIcons=Yorliqlar yaratilmoqda...
uz.StatusRollback=O'zgarishlar bekor qilinmoqda...
uz.StatusUninstalling=%1 o'chirilmoqda...
uz.ConfirmUninstall=%1 va uning barcha komponentlari o'chirilsinmi?
uz.UninstallStatusLabel=%1 kompyuteringizdan o'chirilmoqda, kuting...
uz.UninstalledAll=%1 kompyuteringizdan o'chirildi.
uz.UninstallAppTitle=O'chirish
uz.UninstallAppFullTitle=%1 — o'chirish
uz.SetupAlreadyRunning=O'rnatuvchi allaqachon ishlayapti.
uz.SelectLanguageTitle=Tilni tanlang

[CustomMessages]
uz.AdditionalIcons=Yorliqlar:
uz.CreateDesktopIcon=&Ish stolida yorliq yaratish
uz.LaunchProgram=%1 ni ochish
uz.BootstrapStatus=Python va asosiy komponentlar yuklanmoqda (~120 MB). Bu 1–3 daqiqa oladi...
uz.BootstrapFailed=Asosiy komponentlarni yuklab bo'lmadi (kod %1).%n%nInternet aloqasini tekshirib, o'rnatuvchini qayta ishga tushiring.%n%nBatafsil: %2
uz.RemoveDataTitle=Foydalanuvchi ma'lumotlari
uz.RemoveData=Klonlangan ovozlar, tarix va standart joydagi AI modellar ham o'chirilsinmi?%n%n%1%n%n(Agar modellarni boshqa papkaga saqlagan bo'lsangiz, ularni qo'lda o'chiring.)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Root}\ovozlab\*"; DestDir: "{app}\ovozlab"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"
Source: "{#Root}\omnivoice\*"; DestDir: "{app}\omnivoice"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"
Source: "{#Root}\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "build\bin\uv.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "files\bootstrap.cmd"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "files\bootstrap-run.ps1"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "assets\ovozlab.ico"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\runtime\Scripts\pythonw.exe"; Parameters: "-m ovozlab"; WorkingDir: "{app}"; IconFilename: "{app}\assets\ovozlab.ico"; AppUserModelID: "OvozLab.OvozLab"; Comment: "O'zbekcha nutq sintezi va ovoz klonlash"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\Scripts\pythonw.exe"; Parameters: "-m ovozlab"; WorkingDir: "{app}"; IconFilename: "{app}\assets\ovozlab.ico"; AppUserModelID: "OvozLab.OvozLab"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\Scripts\pythonw.exe"; Parameters: "-m ovozlab"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\ovozlab"
Type: filesandordirs; Name: "{app}\omnivoice"
Type: files; Name: "{app}\install.log"
Type: files; Name: "{app}\bootstrap.exitcode"

[Code]
procedure RunBootstrap;
var
  ResultCode: Integer;
  OldStyle: TNewProgressBarStyle;
begin
  WizardForm.StatusLabel.Caption := CustomMessage('BootstrapStatus');
  WizardForm.FilenameLabel.Caption := '';
  OldStyle := WizardForm.ProgressGauge.Style;
  WizardForm.ProgressGauge.Style := npbstMarquee;
  try
    // bootstrap-run.ps1 bootstrap.cmd ni WMI orqali (Setup'ning bolasi bo'lmagan jarayon sifatida) ishga
    // tushiradi: aks holda Setup'ning RedirectionGuard himoyasi uv yaratadigan junction'ni bloklaydi.
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
        '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + ExpandConstant('{app}\bin\bootstrap-run.ps1') + '" -App "' + ExpandConstant('{app}') + '"',
        ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      MsgBox(FmtMessage(CustomMessage('BootstrapFailed'), [IntToStr(ResultCode), ExpandConstant('{app}\install.log')]), mbError, MB_OK);
  finally
    WizardForm.ProgressGauge.Style := OldStyle;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RunBootstrap;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\OvozLab');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox(FmtMessage(CustomMessage('RemoveData'), [DataDir]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
