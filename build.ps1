# build.ps1  -  Compile wpp_drive_mapper.py into a monolithic Windows executable

$ExeName = "wpp-drive-mapper"
$Script  = "wpp_drive_mapper.py"

Write-Host "=== Building $ExeName ===" -ForegroundColor Cyan

python -m PyInstaller `
    --onefile `
    --windowed `
    --name $ExeName `
    --clean `
    $Script

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Build successful: dist\$ExeName.exe" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "ERROR: build failed." -ForegroundColor Red
    exit 1
}