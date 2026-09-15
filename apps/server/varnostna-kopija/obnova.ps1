<#
.SYNOPSIS
    Preizkus obnove varnostne kopije na prazno namestitev (V3-R02).

.DESCRIPTION
    Kopijo iz `-Mapa` (narejeno s `kopija.ps1` v isti mapi) obnovi v nov vsebnik
    baze in dva prazna volumna ter jo primerja s `stanje.json`:

      - SHA-256 datotek kopije,
      - revizijo Alembic,
      - število vrstic po tabelah,
      - SHA-256 vsake slike posebej.

    Vsi viri se imenujejo `school-obnova*`. Živega projekta `server` se skripta
    ne dotakne. Obnova ne teče prek Compose: ta ob zagonu ustvari vsa omrežja iz
    datoteke, tudi `spredaj`, katerega stalno podomrežje že drži živi strežnik
    (`docs/odlocitve/ADR-034`, dopolnitev).

    Na koncu se viri `school-obnova*` pobrišejo, razen s stikalom `-Pusti`.
    Ostanki prejšnjega preizkusa se pobrišejo ob začetku.

    Izhodna koda 0: kopija se ujema. 1: razlika.

.EXAMPLE
    pwsh -File apps/server/varnostna-kopija/obnova.ps1 -Mapa C:\varnostne-kopije\school_companion\2026-09-16_020000
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $Mapa,

    [switch] $Pusti
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$Predpona = 'school-obnova'
$Vsebnik = "$Predpona-db"
$VolumenBaze = "${Predpona}_baza"
$VolumenSlik = "${Predpona}_slike"
# Ista slika kot servis `db` v `apps/server/docker-compose.yml`.
$SlikaBaze = 'pgvector/pgvector:pg17'
$SeznamSlik = 'cd /data && find images -type f ! -path "*/.tmp/*" -exec sha256sum {} + | LC_ALL=C sort -k 2'

foreach ($vir in $Vsebnik, $VolumenBaze, $VolumenSlik) {
    if (-not $vir.StartsWith($Predpona)) { throw "Vir '$vir' ni pod predpono '$Predpona'; skripta se ustavi." }
}

function Remove-Obnova {
    $PSNativeCommandUseErrorActionPreference = $false
    docker rm -f $Vsebnik 2>$null | Out-Null
    docker volume rm $VolumenBaze $VolumenSlik 2>$null | Out-Null
}

function Get-Sha256([string] $Pot) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Pot).Hash.ToLowerInvariant()
}

$razlike = [System.Collections.Generic.List[string]]::new()

function Compare-Vrednost([string] $Kaj, $Pricakovano, $Dejansko) {
    $p = "$Pricakovano"
    $d = "$Dejansko"
    $ok = $p -ceq $d
    # Primerja se celotna vrednost; skrajša se samo izpis.
    $kratko = { param($s) if ($s.Length -gt 16) { $s.Substring(0, 12) + '...' } else { $s } }
    $oznaka = if ($ok) { 'OK' } else { 'NE' }
    Write-Host ("  {0,-3} {1,-30} kopija: {2,-16} obnova: {3}" -f $oznaka, $Kaj, (& $kratko $p), (& $kratko $d))
    if (-not $ok) { $script:razlike.Add($Kaj) }
}

$Mapa = (Resolve-Path -LiteralPath $Mapa).Path
$potStanja = Join-Path $Mapa 'stanje.json'
if (-not (Test-Path -LiteralPath $potStanja)) {
    throw "V $Mapa ni stanje.json. Kopija ni cela ali ni narejena s kopija.ps1."
}
$stanje = Get-Content -LiteralPath $potStanja -Raw | ConvertFrom-Json

Write-Host "Datoteke kopije v $Mapa"
foreach ($datoteka in $stanje.datoteke.PSObject.Properties) {
    $pot = Join-Path $Mapa $datoteka.Name
    $dejansko = if (Test-Path -LiteralPath $pot) { Get-Sha256 $pot } else { '(ni datoteke)' }
    Compare-Vrednost "sha256 $($datoteka.Name)" $datoteka.Value $dejansko
}
if ($razlike.Count -gt 0) {
    Write-Host 'Datoteke kopije so poškodovane ali spremenjene; obnove ne poskušam.' -ForegroundColor Red
    exit 1
}

Remove-Obnova
try {
    docker volume create $VolumenBaze | Out-Null
    docker volume create $VolumenSlik | Out-Null
    docker run -d --name $Vsebnik `
        -e POSTGRES_USER=solski -e POSTGRES_PASSWORD=obnova -e POSTGRES_DB=solski `
        -v "${VolumenBaze}:/var/lib/postgresql/data" `
        -v "${VolumenSlik}:/data" `
        -v "${Mapa}:/kopija:ro" `
        $SlikaBaze | Out-Null

    # Prek TCP in ne prek vtičnice: med prvo inicializacijo baza teče le na
    # vtičnici in se nato ponovno zažene; obnova v tem oknu bi padla.
    Write-Host 'Čakam na prazno bazo ...'
    $pripravljena = $false
    for ($i = 0; $i -lt 60 -and -not $pripravljena; $i++) {
        $PSNativeCommandUseErrorActionPreference = $false
        docker exec $Vsebnik pg_isready -h 127.0.0.1 -U solski -d solski 2>$null | Out-Null
        $pripravljena = $LASTEXITCODE -eq 0
        $PSNativeCommandUseErrorActionPreference = $true
        if (-not $pripravljena) { Start-Sleep -Seconds 1 }
    }
    if (-not $pripravljena) { throw 'Prazna baza v 60 sekundah ni bila pripravljena.' }

    Write-Host 'Obnavljam bazo in slike ...'
    docker exec $Vsebnik pg_restore -U solski -d solski --no-owner --exit-on-error /kopija/solski.dump
    docker exec $Vsebnik tar xzf /kopija/slike.tar.gz -C /data

    Write-Host 'Primerjava s kopijo'
    $revizija = (docker exec $Vsebnik psql -U solski -d solski -At -c 'select version_num from alembic_version').Trim()
    Compare-Vrednost 'revizija' $stanje.revizija $revizija

    foreach ($tabela in $stanje.vrstice.PSObject.Properties) {
        $stevilo = (docker exec $Vsebnik psql -U solski -d solski -At -c "select count(*) from $($tabela.Name)").Trim()
        Compare-Vrednost "vrstice $($tabela.Name)" $tabela.Value $stevilo
    }

    $obnovljene = @(docker exec $Vsebnik sh -c $SeznamSlik | Where-Object { $_ })
    $vKopiji = @(Get-Content -LiteralPath (Join-Path $Mapa 'slike.sha256') | Where-Object { $_ })
    Compare-Vrednost 'število slik' $stanje.slike $obnovljene.Count

    if ($vKopiji.Count -eq 0 -or $obnovljene.Count -eq 0) {
        $neujemanja = @($vKopiji) + @($obnovljene)
    }
    else {
        $neujemanja = @(Compare-Object -ReferenceObject $vKopiji -DifferenceObject $obnovljene -CaseSensitive)
    }
    Compare-Vrednost 'sha256 vsake slike (razlik)' 0 $neujemanja.Count
    foreach ($n in ($neujemanja | Select-Object -First 5)) { Write-Host "       $n" }
}
finally {
    if ($Pusti) {
        Write-Host "Viri ostanejo za pregled: vsebnik $Vsebnik, volumna $VolumenBaze in $VolumenSlik."
    }
    else {
        Remove-Obnova
    }
}

Write-Host ''
if ($razlike.Count -eq 0) {
    Write-Host 'Obnova na prazno namestitev se ujema s kopijo.' -ForegroundColor Green
    exit 0
}
Write-Host "Obnova se NE ujema s kopijo: $($razlike -join ', ')" -ForegroundColor Red
exit 1
