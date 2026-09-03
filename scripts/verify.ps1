# Lokalni nadomestek za CI.
# Požene vse preverbe in zapiše rezultat, vezan na TRENUTNI HEAD commit.
# Hook brez zelenega rezultata za ta commit ne pusti merga.
#
# TO PRILAGODI SVOJEMU STACKU. Spodaj je primer za Node/TypeScript.
# Kar ne uporabljaš, zakomentiraj.
#
# Korak s poljem 'mapa' se PRESKOČI, če te mape ni. Tako verify preživi
# obdobje, ko del projekta še ne obstaja (npr. apps/server pred V1-R02).
# Preskočen korak šteje kot uspešen, zato se zabeleži s 'preskocen = true'
# v verify.json — ob mergu je vidno, kaj se dejansko ni izvedlo.
#
# Te datoteke model ne sme spreminjati (blokira jo git-guard.ps1).

$ErrorActionPreference = 'Continue'

$repo = if ($env:CLAUDE_PROJECT_DIR) { $env:CLAUDE_PROJECT_DIR } else { (Get-Location).Path }
Set-Location $repo

$projectName = Split-Path -Leaf $repo
$gateDir = Join-Path $env:USERPROFILE ".claude-gates\$projectName"
New-Item -ItemType Directory -Force $gateDir | Out-Null
$verFile = Join-Path $gateDir 'verify.json'

$head = (git rev-parse HEAD | Out-String).Trim()

$koraki = @(
    @{ ime = 'mobile-lint';      mapa = 'apps/mobile'; ukaz = 'npm --prefix apps/mobile run lint' },
    @{ ime = 'mobile-typecheck'; mapa = 'apps/mobile'; ukaz = 'npm --prefix apps/mobile run typecheck' },
    @{ ime = 'mobile-test';      mapa = 'apps/mobile'; ukaz = 'npm --prefix apps/mobile test -- --watchAll=false' },
    @{ ime = 'server-lint';      mapa = 'apps/server'; ukaz = 'ruff check apps/server' },
    @{ ime = 'server-typecheck'; mapa = 'apps/server'; ukaz = 'mypy apps/server' },
    @{ ime = 'server-test';      mapa = 'apps/server'; ukaz = 'pytest apps/server' }
)

$izidi = @()
$vsiOk = $true
$stPreskocenih = 0

foreach ($k in $koraki) {

    if ($k.mapa -and -not (Test-Path (Join-Path $repo $k.mapa))) {
        Write-Host "`n=== $($k.ime): PRESKOCEN (ni mape $($k.mapa)) ===" -ForegroundColor DarkGray
        $izidi += [pscustomobject]@{ korak = $k.ime; ukaz = $k.ukaz; ok = $true; exit = 0; preskocen = $true }
        $stPreskocenih++
        continue
    }

    Write-Host "`n=== $($k.ime): $($k.ukaz) ===" -ForegroundColor Cyan
    & cmd /c $k.ukaz
    $ok = ($LASTEXITCODE -eq 0)
    if (-not $ok) { $vsiOk = $false }
    $izidi += [pscustomobject]@{ korak = $k.ime; ukaz = $k.ukaz; ok = $ok; exit = $LASTEXITCODE; preskocen = $false }
    Write-Host ("--- $($k.ime): " + $(if ($ok) { 'OK' } else { 'PADEL' })) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
}

# Umazan delovni imenik pomeni, da verify ne velja za noben commit.
$umazano = (git status --porcelain | Out-String).Trim()
if ($umazano) {
    Write-Host "`nOPOZORILO: delovni imenik ni čist. Verify velja samo za commitano stanje." -ForegroundColor Yellow
    $vsiOk = $false
    $izidi += [pscustomobject]@{ korak = 'čist imenik'; ukaz = 'git status --porcelain'; ok = $false; exit = 1; preskocen = $false }
}

[pscustomobject]@{
    status = $(if ($vsiOk) { 'pass' } else { 'fail' })
    head   = $head
    veja   = (git branch --show-current | Out-String).Trim()
    cas    = (Get-Date).ToString('s')
    koraki = $izidi
} | ConvertTo-Json -Depth 4 | Set-Content $verFile -Encoding UTF8

Write-Host "`n================================"
if ($stPreskocenih -gt 0) {
    Write-Host "Preskocenih korakov: $stPreskocenih (glej verify.json)" -ForegroundColor DarkGray
}
if ($vsiOk) {
    Write-Host "VERIFY ZELEN za $head" -ForegroundColor Green
    exit 0
} else {
    Write-Host "VERIFY PADEL. Merge bo blokiran." -ForegroundColor Red
    exit 1
}