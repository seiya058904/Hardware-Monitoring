!define APP_NAME "Hardware Monitoring"
!define APP_VERSION "1.0.9"
!define APP_EXE "Hardware Monitoring.exe"
!define DIST_DIR "dist\Hardware Monitoring"
!define INSTALL_DIR "$PROGRAMFILES\${APP_NAME}"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "HardwareMonitoring_Setup_v${APP_VERSION}.exe"
InstallDir "${INSTALL_DIR}"
InstallDirRegKey HKLM "${UNINSTALL_KEY}" "InstallLocation"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!include "MUI2.nsh"

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Section "程序文件 (必需)" SecCore
  SectionIn RO
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\payload"
  File "${DIST_DIR}\${APP_EXE}"
  File "用户须知.txt"
  SetOutPath "$PLUGINSDIR\payload\_internal"
  File /r "${DIST_DIR}\_internal\*.*"
  SetOutPath "$PLUGINSDIR\payload\licenses"
  File "THIRD_PARTY_NOTICES.md"
  File "third_party\licenses\*.txt"
  SetOutPath "$PLUGINSDIR"
  File "scripts\install-transaction.ps1"
  install_retry:
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\install-transaction.ps1" -Mode Install -InstallRoot "$INSTDIR" -SourceRoot "$PLUGINSDIR\payload"'
  Pop $0
  Pop $1
  StrCmp $0 "0" install_complete
  DetailPrint "$1"
  IfSilent install_cancel
  MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "安装未完成。请退出本安装目录的程序后重试。$\r$\n$1" IDRETRY install_retry
  install_cancel:
  SetErrorLevel 1
  Abort
  install_complete:
  SetOutPath "$INSTDIR"

  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoRepair" 1
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "开始菜单快捷方式" SecStartMenu
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section /o "桌面快捷方式" SecDesktop
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

Section /o "开机自启动" SecAutoRun
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${APP_NAME}" "$\"$INSTDIR\${APP_EXE}$\""
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecCore} "程序运行必需的核心文件。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "在开始菜单创建程序快捷方式。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "在桌面创建快捷方式。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAutoRun} "开机后自动启动硬件监控。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "scripts\install-transaction.ps1"
  uninstall_retry:
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\install-transaction.ps1" -Mode Uninstall -InstallRoot "$INSTDIR"'
  Pop $0
  Pop $1
  StrCmp $0 "0" uninstall_complete
  DetailPrint "$1"
  IfSilent uninstall_cancel
  MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "卸载未完成，恢复入口已保留。请退出程序后重试。$\r$\n$1" IDRETRY uninstall_retry
  uninstall_cancel:
  SetErrorLevel 1
  Abort
  uninstall_complete:
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${APP_NAME}"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "HardwareMonitorMini"
  DeleteRegKey HKLM "${UNINSTALL_KEY}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
