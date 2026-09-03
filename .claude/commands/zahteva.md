---
description: Obdelaj zahtevo po procesu iz CLAUDE.md
argument-hint: <ID zahteve, npr. V1-R03>
---

Obdelaj zahtevo **$1** iz `docs/verzije/`.

Delaj strogo po fazah iz `CLAUDE.md`:

1. Preberi `docs/00-namen.md`, `docs/01-arhitektura.md`, vse v `docs/verzije/`,
   `docs/plan/` in `docs/odlocitve/`, preden karkoli rečeš.
2. Poglej dejansko kodo, ne samo dokumentacije — dokumentacija zaostaja.
3. Vsako fazo označi z naslovom (`# Faza 1 — Razumevanje` itd.).
4. Na vsaki 🛑 točki končaj obrat in počakaj name.
5. Faza 9 je konec. Brez merga.

Pred začetkom preveri stanje: `git status`, `git branch --show-current`,
`git log --oneline -5`. Če nisi na čistem `main`, se ustavi in povej, kaj si našel.

Če plan za $1 v `docs/plan/` že obstaja, ne začenjaj od faze 1 — povej mi, kje
smo obstali, in predlagaj, od katere faze naprej.
