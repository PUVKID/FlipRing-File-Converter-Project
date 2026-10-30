$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath 'D:\2026\FilpRing Project').Path
$stageRoot = (Resolve-Path -LiteralPath "$projectRoot\work\enhancement-20261030\release-stage3").Path
$rollbackRoot = "$projectRoot\work\enhancement-20261030\previous-release-before17"
$reportPath = "$projectRoot\work\enhancement-20261030\실제설치-수리19.json"
if (Test-Path -LiteralPath $reportPath) { throw '기존 실제 설치 기록은 덮어쓰지 않습니다.' }
$installerPath = "$stageRoot\설치파일\FlipRing-Setup.exe"
$stageExe = "$stageRoot\프로그램\FlipRing\FlipRing.exe"
if ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash -ne '08699831c44df41a79556677d8baa85abf9825a55f677dcb06a619b072302468') { throw '설치 파일 해시 불일치' }
if ((Get-FileHash -LiteralPath $stageExe -Algorithm SHA256).Hash -ne '4b30939622b0b12fec0c195df95163d542fff0d7028f3f0edc10bd534ec2f0c1') { throw '실행 파일 해시 불일치' }
$record = [ordered]@{ started_kst=[DateTimeOffset]::Now.ToString('o'); task='workflow-enhancement-20261030'; repair_used=19; input_fix_used=2; old_processes=@(); installer_exit_code=$null; actual_launch_passed=$false }
try {
    $allowedExePaths = @("$projectRoot\프로그램\FlipRing\FlipRing.exe", "$env:LOCALAPPDATA\Programs\FlipRing\FlipRing.exe")
    Get-CimInstance Win32_Process -Filter "Name='FlipRing.exe'" | ForEach-Object {
        if ($allowedExePaths -notcontains $_.ExecutablePath) { throw "예상하지 못한 실행 경로: $($_.ExecutablePath)" }
        $record.old_processes += @{pid=$_.ProcessId; path=$_.ExecutablePath}
        Stop-Process -Id $_.ProcessId -Force
    }
    $installLog = "$projectRoot\work\enhancement-20261030\설치-수리19.log"
    $installArgs = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',"/LOG=`"$installLog`"")
    $record.installer = $installerPath
    $record.installer_arguments = $installArgs
    $setup = Start-Process -FilePath $installerPath -ArgumentList $installArgs -PassThru -Wait -WindowStyle Hidden
    $record.installer_exit_code = $setup.ExitCode
    if ($setup.ExitCode -ne 0) { throw "설치 종료 코드: $($setup.ExitCode)" }
    $installedExe = "$env:LOCALAPPDATA\Programs\FlipRing\FlipRing.exe"
    $record.installed_exe = $installedExe
    $record.installed_sha256 = (Get-FileHash -LiteralPath $installedExe -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($record.installed_sha256 -ne '4b30939622b0b12fec0c195df95163d542fff0d7028f3f0edc10bd534ec2f0c1') { throw '실제 설치 실행 파일 불일치' }
    if (Test-Path -LiteralPath $rollbackRoot) { throw '기존 롤백 자료는 덮어쓰지 않습니다.' }
    New-Item -ItemType Directory -Path $rollbackRoot | Out-Null
    foreach ($folderName in @('프로그램','설치파일')) {
        $existingPath = [IO.Path]::GetFullPath("$projectRoot\$folderName")
        $incomingPath = [IO.Path]::GetFullPath("$stageRoot\$folderName")
        if (-not $existingPath.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or -not $incomingPath.StartsWith($stageRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '이동 경로가 프로젝트 경계를 벗어났습니다.' }
        if (Test-Path -LiteralPath $existingPath) { Move-Item -LiteralPath $existingPath -Destination "$rollbackRoot\$folderName" }
        Move-Item -LiteralPath $incomingPath -Destination $projectRoot
    }
    Copy-Item -LiteralPath "$projectRoot\SHA256SUMS.txt" -Destination "$rollbackRoot\SHA256SUMS.txt"
    $appProcess = Start-Process -FilePath $installedExe -ArgumentList '--settings' -PassThru
    Start-Sleep -Seconds 4
    $appProcess.Refresh()
    $record.actual_launch_passed = (-not $appProcess.HasExited) -and ($appProcess.MainWindowHandle -ne 0)
    $record.new_process_id = $appProcess.Id
    $record.window_handle = $appProcess.MainWindowHandle.ToInt64()
    $record.window_title = $appProcess.MainWindowTitle
    $record.scope = '실제 Inno 설치 종료·설치 EXE 해시·Windows 프로세스 생존과 창 핸들. 화면 배치와 물리 Shift/OLE 조작은 별도 확인 필요.'
    if (-not $record.actual_launch_passed) { throw '새 설치 앱의 창 생성 확인 실패' }
} catch {
    $record.failure_original = $_.ToString()
    throw
} finally {
    $record.finished_kst = [DateTimeOffset]::Now.ToString('o')
    $record | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $reportPath -Encoding utf8
}
$record | ConvertTo-Json -Depth 10
