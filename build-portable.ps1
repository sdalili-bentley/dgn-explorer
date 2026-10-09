param([string]$Python = "python", [string]$ApprovalManifest = "dependency-approvals.json")
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    & $Python -m dgn_explorer.policy $ApprovalManifest wheelhouse
    if ($LASTEXITCODE -ne 0) { throw "Development dependency admission fails" }
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Installed requirements are inconsistent" }
    & $Python write_build_receipt.py $ApprovalManifest build/receipt-check
    if ($LASTEXITCODE -ne 0) { throw "Installed build identities differ from reviewed inputs" }
    & $Python -m PyInstaller --noconfirm --clean portable.spec
    if ($LASTEXITCODE -ne 0) { throw "Portable build fails" }
    $bundle = Join-Path $PSScriptRoot "dist/DGN-Explorer"
    $notices = Join-Path $bundle "licenses"
    New-Item -ItemType Directory -Force $notices | Out-Null
    $archives = Get-ChildItem "$PSScriptRoot/wheelhouse/*.whl"
    foreach ($wheel in $archives) {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($wheel.FullName)
        try {
            foreach ($entry in $archive.Entries | Where-Object { $_.Length -gt 0 -and $_.FullName -match '(LICENSE|COPYING|licenses/)' }) {
                $safe = $entry.FullName -replace '[^a-zA-Z0-9._-]', '_'
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $notices "$($wheel.BaseName)-$safe"), $true)
            }
        } finally { $archive.Dispose() }
    }
    Copy-Item README.md, DEPENDENCY_CANDIDATES.md -Destination $bundle
    Copy-Item $ApprovalManifest -Destination (Join-Path $bundle "dependency-approvals.json")
    & $Python write_build_receipt.py $ApprovalManifest $bundle
    if ($LASTEXITCODE -ne 0) { throw "Build receipt/notices are incomplete" }
    "Development preview. Distribution license/notices review and signing are not approved. See DEPENDENCY_CANDIDATES.md. Python/Qt are bundled; run dgn-explorer-gui.exe." | Set-Content (Join-Path $bundle "BUILD-STATUS.txt") -Encoding utf8
    & $Python verify_portable.py $bundle --report build/portable-verification.json
    if ($LASTEXITCODE -ne 0) { throw "Actual packaged verification fails" }
    Copy-Item build/portable-inventory.json -Destination $bundle
    Compress-Archive -Path $bundle -DestinationPath "dist/DGN-Explorer-windows-x64.zip" -Force
    $hash = Get-FileHash "dist/DGN-Explorer-windows-x64.zip" -Algorithm SHA256
    @{file="DGN-Explorer-windows-x64.zip";sha256=$hash.Hash.ToLower()} | ConvertTo-Json | Set-Content dist/portable-output-sha256.json -Encoding utf8
    $hash
} finally { Pop-Location }