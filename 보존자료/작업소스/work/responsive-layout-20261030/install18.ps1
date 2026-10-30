$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath 'D:\2026\FilpRing Project').Path
$taskWork = Join-Path $taskRoot 'work\responsive-layout-20261030'
$taskStage = Join-Path $taskWork 'release-stage1'
$taskCheck = Get-Content -LiteralPath (Join-Path $taskRoot 'evidence\1.8-실행파일소스대조.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $taskCheck.passed) { throw '새 실행 파일의 소스 대조가 통과하지 않았습니다.' }
$taskExe = Join-Path $taskStage '프로그램\FlipRing\FlipRing.exe'
if ((Get-FileHash -LiteralPath $taskExe -Algorithm SHA256).Hash.ToLower() -ne $taskCheck.exe_sha256) { throw '검증 후 실행 파일이 바뀌었습니다.' }
$taskInstalled = Join-Path $env:LOCALAPPDATA 'Programs\FlipRing\FlipRing.exe'
Get-Process -Name FlipRing -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Path -eq $taskInstalled) { Stop-Process -Id $_.Id }
}
$taskInstaller = Join-Path $taskStage '설치파일\FlipRing-Setup.exe'
$taskStart = Get-Date -Format o
$taskProcess = Start-Process -FilePath $taskInstaller -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-' -WindowStyle Hidden -PassThru -Wait
$taskRecord = [ordered]@{started_kst=$taskStart;finished_kst=(Get-Date -Format o);installer=$taskInstaller;installer_exit_code=$taskProcess.ExitCode;actual_launch_passed=$false}
$taskRecord | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskWork 'actual-install.json') -Encoding utf8
if ($taskProcess.ExitCode -ne 0) { throw '설치 파일 실행이 실패했습니다. 원문 종료 코드를 보존했습니다.' }
$taskApp = Start-Process -FilePath $taskInstalled -ArgumentList '--settings' -PassThru
$taskDeadline = (Get-Date).AddSeconds(20)
do {
    Start-Sleep -Milliseconds 500
    $taskApp.Refresh()
    if ($taskApp.HasExited) { break }
} while ($taskApp.MainWindowHandle -eq 0 -and (Get-Date) -lt $taskDeadline)
$taskRecord['pid']=$taskApp.Id
$taskRecord['exe']=$taskInstalled
$taskRecord['window_handle']=$taskApp.MainWindowHandle.ToInt64()
$taskRecord['window_title']=$taskApp.MainWindowTitle
$taskRecord['responding']=$taskApp.Responding
$taskRecord['actual_launch_passed']=(-not $taskApp.HasExited -and $taskApp.MainWindowHandle -ne 0 -and $taskApp.Responding)
$taskRecord | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskWork 'actual-install.json') -Encoding utf8
if (-not $taskRecord.actual_launch_passed) { throw '새 설치본의 응답 창을 확인하지 못했습니다.' }
$taskRecord | ConvertTo-Json -Depth 5
