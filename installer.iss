; installer.iss
[Setup]
AppName=Нейро-фарм
AppVersion=1.0
DefaultDirName={pf}\NeuroPharm
DefaultGroupName=Нейро-фарм
UninstallDisplayIcon={app}\NeuroPharm.exe
Compression=lzma2
SolidCompression=yes
OutputDir=.
OutputBaseFilename=NeuroPharm_Setup
SetupIconFile=assets\icon.ico
WizardStyle=modern

[Files]
; Основной исполняемый файл
Source: "dist\NeuroPharm.exe"; DestDir: "{app}"; Flags: ignoreversion
; Дополнительные файлы (если есть)
Source: "prompt_templates.json"; DestDir: "{app}"; Flags: ignoreversion
; База данных (пустая папка или файл-заглушка)
; Source: "egk_extend306\*"; DestDir: "{app}\egk_extend306"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Нейро-фарм"; Filename: "{app}\NeuroPharm.exe"
Name: "{group}\Удалить Нейро-фарм"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Нейро-фарм"; Filename: "{app}\NeuroPharm.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительные значки:"; Flags: checkedonce

; -------- Добавляем галочку для открытия сайта Ollama --------
[Tasks]
Name: "openollama"; Description: "Открыть страницу установки Ollama после завершения"; GroupDescription: "Действия после установки:"; Flags: checkedonce

[Run]
; Эта секция выполняется после завершения установки, если выбран соответствующий task
Filename: "https://ollama.com/download"; Description: "Перейти на сайт Ollama"; Tasks: openollama; Flags: postinstall shellexec nowait

[UninstallDelete]
Type: filesandordirs; Name: "{app}\egk_extend306"