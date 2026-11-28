function Get-ReefVisionArtifactSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    # The Tauri build subprocess can lack the Get-FileHash cmdlet.
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            return ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
        } finally {
            $sha256.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}
