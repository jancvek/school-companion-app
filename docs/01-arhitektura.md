# Arhitektura — trenutno stanje

> Ta dokument opisuje, kako je **zdaj**, ne kako naj bo.
> Model ga posodobi ob vsaki spremembi, ki ga naredi neaktualnega.

## Stack

| Plast | Tehnologija | Zakaj |
|---|---|---|
| Mobilna aplikacija | Expo (React Native, TypeScript) | EAS Build da APK brez Play Store-a in Android Studia; `expo-camera` / `expo-sqlite` / `expo-file-system` pokrijejo vse brez native kode |
| Lokalna baza (telefon) | SQLite (`expo-sqlite`) | Čakalna vrsta za offline-first delovanje |
| Strežnik | FastAPI (Python) | Naraven za AI/vision klice, lahek |
| Podatkovna baza (strežnik) | PostgreSQL + pgvector | Ena baza za metapodatke in (kasneje) vektorje, brez ločene vektorske baze |
| Povezljivost telefon ↔ strežnik | Tailscale | Dostop do domačega strežnika brez port-forwardinga |
| Vision / OCR | Cloud vision API (Claude ali Gemini — izbira odprta) | Klasični OCR (Tesseract) ne obvlada slovenskega rokopisa |
| Orkestracija strežnika | Docker Compose (`api` + `db`) | Brez Celery/Redis — obseg (5–25 slik/teden) tega ne potrebuje |

## Moduli

| Modul | Odgovornost | Datoteke |
|---|---|---|
| `apps/mobile` | Kamera, izbira predmeta, lokalna baza, zgodovina, upload worker | `apps/mobile/` (nastane v V1-R01) |
| `apps/server` | Upload endpoint, obdelava slik (worker), API | `apps/server/` (nastane v V1-R02) |

Ločena mapi namenoma ne delita orodij za monorepo (npr. Turborepo) — gre za
dva jezika (TypeScript / Python) brez skupne kode, zato vsaka živi s svojim
običajnim orodjem (`npm`/`package.json` v `apps/mobile`,
`pip`/`pyproject.toml` v `apps/server`).

## Podatkovni model

Še ne obstaja — nastane v V1-R02 (osnovne tabele) in V1-R03 (polja za
obdelavo). Načrt shem je v `docs/verzije/v1.md`.

## Zunanje odvisnosti

| Odvisnost | Namen | Kdaj dodana |
|---|---|---|
| — | — | — |

## Kako se poganja in testira

Se dopolni po V1-R01, ko `apps/mobile` in `apps/server` dejansko obstajata.
