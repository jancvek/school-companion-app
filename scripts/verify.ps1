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
# NAČIN "SAMO DOKUMENTACIJA": če se veja od main (merge-base) razlikuje
# SAMO v datotekah *.md, teče samo korak 'server-test'. Ta ostane, ker
# nekateri strežniški testi berejo docs/ (ADR-066, POC-01, 00-namen,
# 01-arhitektura) in primerjajo besedilo s kodo. Ostali koraki se
# preskočijo z razlogom 'samo .md'. Prazna razlika (npr. na samem main),
# neuspel merge-base ali katerakoli ne-.md datoteka pomeni POLN verify.
# Preimenovanja se štejejo kot brisanje + dodajanje (--no-renames), da
# preimenovanje kode v .md ne izgleda kot sprememba samo v dokumentaciji.
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

# --- Ali se veja od main razlikuje samo v .md? ---
$samoDok = $false
$spremenjene = @()
$baza = (git merge-base main HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -eq 0 -and $baza -and $baza -ne $head) {
    $spremenjene = @(git -c core.quotepath=false diff --name-only --no-renames $baza HEAD | Where-Object { $_ })
    if ($LASTEXITCODE -eq 0 -and $spremenjene.Count -gt 0) {
        $neDok = @($spremenjene | Where-Object { $_ -notmatch '(?i)\.md$' })
        $samoDok = ($neDok.Count -eq 0)
    }
}
if ($samoDok) {
    Write-Host "`nSAMO DOKUMENTACIJA: $($spremenjene.Count) datotek .md od main - tece samo server-test." -ForegroundColor DarkGray
    $spremenjene | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
}

$koraki = @(
    @{ ime = 'mobile-lint';      mapa = 'apps/mobile'; ukaz = 'npm --prefix apps/mobile run lint' },
    @{ ime = 'mobile-typecheck'; mapa = 'apps/mobile'; ukaz = 'npm --prefix apps/mobile run typecheck' },
    @{ ime = 'mobile-test';      mapa = 'apps/mobile'; ukaz = 'npm --prefix apps/mobile test -- --watchAll=false' },
    @{ ime = 'server-lint';      mapa = 'apps/server'; ukaz = 'ruff check apps/server' },
    @{ ime = 'server-typecheck'; mapa = 'apps/server'; ukaz = 'mypy apps/server' },
    @{ ime = 'server-test';      mapa = 'apps/server'; ukaz = 'pytest apps/server'; tudiZaDok = $true }
)

$izidi = @()
$vsiOk = $true
$stPreskocenih = 0

foreach ($k in $koraki) {

    if ($samoDok -and -not $k.tudiZaDok) {
        Write-Host "`n=== $($k.ime): PRESKOCEN (samo .md) ===" -ForegroundColor DarkGray
        $izidi += [pscustomobject]@{ korak = $k.ime; ukaz = $k.ukaz; ok = $true; exit = 0; preskocen = $true; razlog = 'samo .md' }
        $stPreskocenih++
        continue
    }

    if ($k.mapa -and -not (Test-Path (Join-Path $repo $k.mapa))) {
        Write-Host "`n=== $($k.ime): PRESKOCEN (ni mape $($k.mapa)) ===" -ForegroundColor DarkGray
        $izidi += [pscustomobject]@{ korak = $k.ime; ukaz = $k.ukaz; ok = $true; exit = 0; preskocen = $true; razlog = "ni mape $($k.mapa)" }
        $stPreskocenih++
        continue
    }

    Write-Host "`n=== $($k.ime): $($k.ukaz) ===" -ForegroundColor Cyan
    & cmd /c $k.ukaz
    $ok = ($LASTEXITCODE -eq 0)
    if (-not $ok) { $vsiOk = $false }
    $izidi += [pscustomobject]@{ korak = $k.ime; ukaz = $k.ukaz; ok = $ok; exit = $LASTEXITCODE; preskocen = $false; razlog = '' }
    Write-Host ("--- $($k.ime): " + $(if ($ok) { 'OK' } else { 'PADEL' })) -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
}

# Umazan delovni imenik pomeni, da verify ne velja za noben commit.
$umazano = (git status --porcelain | Out-String).Trim()
if ($umazano) {
    Write-Host "`nOPOZORILO: delovni imenik ni čist. Verify velja samo za commitano stanje." -ForegroundColor Yellow
    $vsiOk = $false
    $izidi += [pscustomobject]@{ korak = 'čist imenik'; ukaz = 'git status --porcelain'; ok = $false; exit = 1; preskocen = $false; razlog = '' }
}

[pscustomobject]@{
    status      = $(if ($vsiOk) { 'pass' } else { 'fail' })
    head        = $head
    veja        = (git branch --show-current | Out-String).Trim()
    cas         = (Get-Date).ToString('s')
    nacin       = $(if ($samoDok) { 'samo-dokumentacija' } else { 'poln' })
    baza        = $baza
    spremenjene = @($(if ($samoDok) { $spremenjene }))
    koraki      = $izidi
} | ConvertTo-Json -Depth 4 | Set-Content $verFile -Encoding UTF8

Write-Host "`n================================"
if ($samoDok) {
    Write-Host "Nacin: SAMO DOKUMENTACIJA (od main se razlikujejo samo .md)" -ForegroundColor DarkGray
}
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
