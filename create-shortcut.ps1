$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$pythonwPath = Join-Path $projectPath '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath -PathType Leaf)) {
    throw 'Create the Python 3.13 .venv using README.md before creating the shortcut.'
}
$desktopPath = [Environment]::GetFolderPath('DesktopDirectory')
$shortcutPath = Join-Path $desktopPath 'InvestResearch.lnk'
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($shortcutPath)
if ((Test-Path -LiteralPath $shortcutPath) -and (
    $shortcut.TargetPath -ne $pythonwPath -or $shortcut.Arguments -ne '-m app')) {
    throw 'An unrelated InvestResearch shortcut already exists. Rename it before continuing.'
}
# COM stores the target and working directory separately, including paths with spaces.
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '-m app'
$shortcut.WorkingDirectory = $projectPath
$shortcut.Description = 'Open Investment Research'
$shortcut.Save()
Write-Output "Created $shortcutPath"
