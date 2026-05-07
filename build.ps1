# build.ps1  -  Compile both tools into monolithic Windows executables
# Requires: pip install pyinstaller

$tools = @(
    @{ Name = "wpp-drive-mapper"; Script = "wpp-drive-mapper.py" },
    @{ Name = "wpp-clean-drives";  Script = "wpp-clean-drives.py"  }
)

foreach ($t in $tools) {
    Write-Host "=== Building $($t.Name) ===" -ForegroundColor Cyan
    python -m PyInstaller --onefile --windowed --name $t.Name --clean $t.Script
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: $($t.Name) build failed." -ForegroundColor Red
        exit 1
    }
    Write-Host ""
}

Write-Host "Build successful:" -ForegroundColor Green
Write-Host "  dist\wpp-drive-mapper.exe"
Write-Host "  dist\wpp-clean-drives.exe"
