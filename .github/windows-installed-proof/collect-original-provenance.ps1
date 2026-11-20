param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [Parameter(Mandatory)][string]$ProofRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$checkout = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$destination = Join-Path $checkout '.artifacts/registered-retest-transport'
$null = New-Item -ItemType Directory -Path $destination -Force
foreach ($name in 'registered-retest-provenance.json','verified-payload.json','verified-transport.json') {
    $old = Join-Path $ProofRoot "evidence/$name"
    if (Test-Path -LiteralPath $old -PathType Leaf) {
        $retained = Join-Path $destination $name
        Copy-Item -LiteralPath $old -Destination $retained
        if ((Get-FileHash -LiteralPath $old).Hash -cne (Get-FileHash -LiteralPath $retained).Hash) {
            throw "Verified provenance changed during collection: $name"
        }
    }
}
