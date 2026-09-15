<#
.SYNOPSIS
    Varnostna kopija baze in slik strežnika (V3-R02).

.DESCRIPTION
    Iz živega projekta Compose `server` naredi mapo `<Cilj>\<datum_ura>` z:

      solski.dump    izpis baze (`pg_dump -Fc`), narejen v vsebniku baze
      slike.tar.gz   mapa `/data/images` iz vsebnika `api`, brez `.tmp`
      slike.sha256   SHA-256 vsake slike, za primerjavo ob obnovi
      stanje.json    revizija, števila vrstic, število slik, SHA-256 datotek
      PREBERI.md     isto za človeka

    Izpis nastane v vsebniku in gre ven z `docker cp`: preusmeritev `>` v
    PowerShellu binaren izpis pokvari.

    Števila vrstic in seznam slik se preberejo pred kopijo in po njej. Če se
    razlikujeta (med kopijo je prišla slika), kopija ne uspe in jo je treba
    pognati znova.

    `stanje.json` se zapiše zadnji in je znak, da je kopija cela. Po uspehu
    ostane zadnjih `-Ohrani` celih map; starejše se pobrišejo. Map z drugačnim
    imenom (ročne kopije) se ne dotakne. Neuspela kopija ne pobriše ničesar;
    njena mapa dobi pripono `-neuspela`.

    Kopija je na istem disku kot strežnik in okvare diska ne preživi
    (`docs/odlocitve/ADR-034` F). Obnovo preizkusi `obnova.ps1` v isti mapi.

.EXAMPLE
    pwsh -File apps/server/varnostna-kopija/kopija.ps1
#>
# `$PSNativeCommandUseErrorActionPreference` (napaka dockerja ustavi skripto)
# obstaja šele od PowerShell 7.3. Windows PowerShell 5.1 (`powershell.exe`) bi
# napake tiho prezrl, zato ga skripta zavrne. Dnevno opravilo naj kliče `pwsh`.
#Requires -Version 7.3
[CmdletBinding()]
param(
    [string] $Cilj = 'C:\varnostne-kopije\school_companion',

    [ValidateRange(1, 365)]
    [int] $Ohrani = 14
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$Projekt = 'server'
$Tabele = @('families', 'materials', 'questions', 'quizzes', 'quiz_items', 'question_attempts')
$ImeCeleKopije = '^\d{4}-\d{2}-\d{2}_\d{6}$'
$ImeNeuspele = '^\d{4}-\d{2}-\d{2}_\d{6}-neuspela$'
$SeznamSlik = 'cd /data && find images -type f ! -path "*/.tmp/*" -exec sha256sum {} + | LC_ALL=C sort -k 2'

function Get-Vsebnik([string] $Servis) {
    $id = docker ps -q `
        --filter "label=com.docker.compose.project=$Projekt" `
        --filter "label=com.docker.compose.service=$Servis"
    if (-not $id) {
        throw "Vsebnik '$Servis' projekta '$Projekt' ne teče. Zaženi strežnik in poženi kopijo znova."
    }
    return @($id)[0]
}

function Get-Stanje([string] $Baza, [string] $Api) {
    $sql = ($Tabele | ForEach-Object { "select '$_', count(*) from $_" }) -join ' union all '
    $prebrano = @{}
    docker exec $Baza psql -U solski -d solski -At -F '|' -c $sql | ForEach-Object {
        $ime, $stevilo = $_ -split '\|'
        $prebrano[$ime] = [int] $stevilo
    }
    $vrstice = [ordered]@{}
    foreach ($tabela in $Tabele) { $vrstice[$tabela] = $prebrano[$tabela] }

    return [pscustomobject]@{
        Revizija = (docker exec $Baza psql -U solski -d solski -At -c 'select version_num from alembic_version').Trim()
        Vrstice  = $vrstice
        Slike    = @(docker exec $Api sh -c $SeznamSlik)
    }
}

function Get-Sha256([string] $Pot) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Pot).Hash.ToLowerInvariant()
}

if (Test-Path -LiteralPath $Cilj) {
    # Neuspele kopije se ne štejejo med cele, a se tudi ne smejo kopičiti brez
    # meje, ko dnevno opravilo pada dan za dnem. Ohrani se jih največ `-Ohrani`;
    # čiščenje teče pred kopijo, da meja drži tudi ob naslednjem neuspehu.
    $neuspele = Get-ChildItem -LiteralPath $Cilj -Directory |
        Where-Object { $_.Name -match $ImeNeuspele } |
        Sort-Object Name -Descending
    foreach ($stara in ($neuspele | Select-Object -Skip $Ohrani)) {
        Remove-Item -LiteralPath $stara.FullName -Recurse -Force
        Write-Host "Pobrisana stara neuspela kopija: $($stara.Name)"
    }
}

$baza = Get-Vsebnik 'db'
$api = Get-Vsebnik 'api'

$ime = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$mapa = Join-Path $Cilj $ime
if (Test-Path -LiteralPath $mapa) { throw "Mapa $mapa že obstaja. Počakaj sekundo in poženi znova." }
New-Item -ItemType Directory -Path $mapa | Out-Null

try {
    Write-Host "Kopija v $mapa"
    $prej = Get-Stanje $baza $api

    docker exec $baza pg_dump -U solski -Fc -f /tmp/kopija.dump solski
    docker cp "${baza}:/tmp/kopija.dump" (Join-Path $mapa 'solski.dump') | Out-Null

    docker exec $api tar czf /tmp/kopija-slike.tar.gz -C /data '--exclude=*/.tmp' images
    docker cp "${api}:/tmp/kopija-slike.tar.gz" (Join-Path $mapa 'slike.tar.gz') | Out-Null

    $potem = Get-Stanje $baza $api
    if (($prej | ConvertTo-Json -Depth 4) -ne ($potem | ConvertTo-Json -Depth 4)) {
        throw 'Med kopijo so se podatki spremenili (nova slika ali zapis). Poženi kopijo znova.'
    }

    $potSeznama = Join-Path $mapa 'slike.sha256'
    [IO.File]::WriteAllText($potSeznama, (($prej.Slike | ForEach-Object { "$_`n" }) -join ''))

    $datoteke = [ordered]@{}
    foreach ($datoteka in 'solski.dump', 'slike.tar.gz', 'slike.sha256') {
        $datoteke[$datoteka] = Get-Sha256 (Join-Path $mapa $datoteka)
    }

    $vrsticeTabele = ($prej.Vrstice.GetEnumerator() | ForEach-Object { "| ``$($_.Key)`` | $($_.Value) |" }) -join "`n"
    $vrsticeDatotek = ($datoteke.GetEnumerator() | ForEach-Object { "| ``$($_.Key)`` | ``$($_.Value)`` |" }) -join "`n"
    $preberi = @"
# Varnostna kopija $ime

Naredil ``apps/server/varnostna-kopija/kopija.ps1`` iz projekta Compose ``$Projekt``.

- Revizija Alembic: ``$($prej.Revizija)``
- Slik: $($prej.Slike.Count)

| Tabela | Vrstic |
|---|---|
$vrsticeTabele

| Datoteka | SHA-256 |
|---|---|
$vrsticeDatotek

Obnova na prazno namestitev in primerjava:

    pwsh -File apps/server/varnostna-kopija/obnova.ps1 -Mapa "$mapa"
"@
    [IO.File]::WriteAllText((Join-Path $mapa 'PREBERI.md'), $preberi)

    # Zadnji: brez te datoteke kopija ne šteje za celo.
    $stanje = [ordered]@{
        narejena = (Get-Date).ToString('o')
        projekt  = $Projekt
        revizija = $prej.Revizija
        vrstice  = $prej.Vrstice
        slike    = $prej.Slike.Count
        datoteke = $datoteke
    }
    [IO.File]::WriteAllText((Join-Path $mapa 'stanje.json'), ($stanje | ConvertTo-Json -Depth 4))
}
catch {
    if (Test-Path -LiteralPath $mapa) { Rename-Item -LiteralPath $mapa -NewName "$ime-neuspela" }
    Write-Host "Kopija NI uspela; mapa je preimenovana v $ime-neuspela." -ForegroundColor Red
    throw
}
finally {
    $PSNativeCommandUseErrorActionPreference = $false
    docker exec $baza rm -f /tmp/kopija.dump 2>$null | Out-Null
    docker exec $api rm -f /tmp/kopija-slike.tar.gz 2>$null | Out-Null
    $PSNativeCommandUseErrorActionPreference = $true
}

$cele = Get-ChildItem -LiteralPath $Cilj -Directory |
    Where-Object { $_.Name -match $ImeCeleKopije -and (Test-Path -LiteralPath (Join-Path $_.FullName 'stanje.json')) } |
    Sort-Object Name -Descending
foreach ($stara in ($cele | Select-Object -Skip $Ohrani)) {
    Remove-Item -LiteralPath $stara.FullName -Recurse -Force
    Write-Host "Pobrisana stara kopija: $($stara.Name)"
}

Write-Host ''
Write-Host "Kopija je uspela: revizija $($prej.Revizija), $($prej.Slike.Count) slik." -ForegroundColor Green
$prej.Vrstice.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-18} {1}" -f $_.Key, $_.Value) }
Write-Host "Mapa: $mapa"
