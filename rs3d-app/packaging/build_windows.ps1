# Build the Windows portable zip and installer. Run from rs3d-app\ on Windows.
# Needs: uv, and Inno Setup 6 (iscc) on PATH for the installer. Output goes to dist\.
$ErrorActionPreference = "Stop"
uv sync --extra desktop
uv run pyinstaller packaging/rs3d.spec --noconfirm --distpath dist --workpath build

$ver = (uv run python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])").Trim()

# Portable: the same folder plus a marker, so data stays in .\data next to RS3D.exe
$port = "dist\RS3D-Portable-$ver"
if (Test-Path $port) { Remove-Item $port -Recurse -Force }
Copy-Item dist\RS3D $port -Recurse
New-Item "$port\portable.txt" -ItemType File | Out-Null
Compress-Archive "$port\*" "dist\RS3D-Portable-$ver.zip" -Force
Remove-Item $port -Recurse -Force

if (Get-Command iscc -ErrorAction SilentlyContinue) {
    iscc /DAppVersion=$ver packaging\installer.iss
} else {
    Write-Warning "Inno Setup (iscc) not found: skipped the installer."
}
