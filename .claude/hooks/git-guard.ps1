# PreToolUse hook za Bash in PowerShell.
# Izhod 2 = klic orodja je blokiran, stderr gre modelu kot razlog.
#
# Ograja stoji na treh stvareh:
#   1. gate datoteka je ZUNAJ repozitorija, da je model ne more ustvariti mimogrede
#   2. vsak ukaz, ki omenja pot do gate mape, je blokiran
#   3. merge zahteva ZELEN verify za TOČNO ta HEAD commit
#
# To ni trdna varnostna meja. Vse teče pod istim uporabnikom in dovolj
# iznajdljiv obhod je mogoč. Trdna meja je zaščita veje na oddaljenem
# repozitoriju. To tukaj ustavi nesreče in zdrs, ne odločenega nasprotnika.

$ErrorActionPreference = 'Stop'

function Deny([string]$Reason) {
    [Console]::Error.WriteLine("BLOKIRANO (git-guard.ps1): $Reason")
    [Console]::Error.WriteLine("Ukaz: $script:Norm")
    exit 2
}

# --- Vhod ---
try {
    $raw = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }
    $payload = $raw | ConvertFrom-Json
} catch { exit 0 }

$cmd = $payload.tool_input.command
if ([string]::IsNullOrWhiteSpace($cmd)) { exit 0 }

# Zlepi vrstice in skrči presledke, da se blokade ne da obiti z novo vrstico.
$script:Norm = ($cmd -replace "`r?`n", ' ') -replace '\s+', ' '
$n = $script:Norm

# --- Poti ---
$repo = $env:CLAUDE_PROJECT_DIR
if ([string]::IsNullOrWhiteSpace($repo)) { $repo = (Get-Location).Path }
$projectName = Split-Path -Leaf $repo
$gateDir  = Join-Path $env:USERPROFILE ".claude-gates\$projectName"
$gateFile = Join-Path $gateDir 'dovoli-merge'
$verFile  = Join-Path $gateDir 'verify.json'

# ============================================================
# 1. Poskusi poseganja v samo ograjo
# ============================================================
if ($n -match '(?i)\.claude-gates') {
    Deny 'Gate mapa je moja, ne tvoja. Ograje ne odpiraš sam.'
}
if ($n -match '(?i)\.claude[\\/](hooks|settings\.json|agents)') {
    Deny 'Spreminjanje ograje ali nastavitev ni dovoljeno. Predlagaj spremembo meni.'
}
if ($n -match '(?i)[\\/]?scripts[\\/]verify\.ps1') {
    Deny 'Skripta verify.ps1 se ne spreminja. Če je narobe, mi povej.'
}

# ============================================================
# 2. Vedno prepovedano, brez izjem
# ============================================================
$vedno = @(
    @{ p = '(?i)git\s+push\b.*(--force|--force-with-lease|\s-f\b)'; r = 'force push ni dovoljen.' },
    @{ p = '(?i)git\s+reset\s+--hard';                              r = 'git reset --hard lahko izgubi moje delo.' },
    @{ p = '(?i)git\s+clean\s+-\w*[df]';                            r = 'git clean briše nesledene datoteke.' },
    @{ p = '(?i)git\s+checkout\s+--\s';                             r = 'razveljavljanje sprememb je moja odločitev.' },
    @{ p = '(?i)git\s+restore\s+\.';                                r = 'razveljavljanje sprememb je moja odločitev.' },
    @{ p = '(?i)git\s+branch\s+-\w*[dD]\b';                         r = 'brisanje branchev je moja odločitev.' },
    @{ p = '(?i)git\s+rebase\b';                                    r = 'rebase ni del tega procesa.' },
    @{ p = '(?i)git\s+config\b.*user\.';                            r = 'spreminjanje git identitete ni dovoljeno.' },
    @{ p = '(?i)git\s+worktree\s+remove';                           r = 'odstranjevanje worktreejev je moja odločitev.' }
)
foreach ($v in $vedno) { if ($n -match $v.p) { Deny $v.r } }

# ============================================================
# 3. Delo na main
# ============================================================
$veja = ''
try { $veja = (git -C "$repo" branch --show-current 2>$null | Out-String).Trim() } catch { }

if ($veja -eq 'main' -or $veja -eq 'master') {
    if ($n -match '(?i)git\s+commit\b') {
        Deny "commit neposredno na '$veja'. Najprej naredi feature branch (faza 3)."
    }
}

# ============================================================
# 4. Merge / push / tag
# ============================================================
if ($n -match '(?i)git\s+(merge|push|tag)\b') {

    if (-not (Test-Path $gateFile)) {
        Deny @"
merge/push/tag zahteva mojo izrecno odobritev.
Napiši poročilo faze 9 in počakaj. Gate odprem jaz z:
  New-Item -ItemType Directory -Force '$gateDir' | Out-Null
  New-Item -ItemType File -Force '$gateFile'     | Out-Null
"@
    }

    # Gate je odprt. Zdaj mora biti verify zelen za TOČNO ta commit.
    if (-not (Test-Path $verFile)) {
        Deny "gate je odprt, ampak verify ni bil pognan. Poženi: pwsh -File scripts/verify.ps1"
    }

    $head = ''
    try { $head = (git -C "$repo" rev-parse HEAD 2>$null | Out-String).Trim() } catch { }

    try { $ver = Get-Content $verFile -Raw | ConvertFrom-Json } catch {
        Deny 'verify.json je pokvarjen. Poženi verify.ps1 znova.'
    }

    if ($ver.status -ne 'pass') {
        Deny "zadnji verify ni bil uspešen (status=$($ver.status)). Popravi in poženi znova."
    }
    if ($ver.head -ne $head) {
        Deny "verify je bil pognan na commitu $($ver.head), HEAD pa je $head. Poženi verify.ps1 znova."
    }
}

exit 0
