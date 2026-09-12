"""Decide si el Deploy de producción publica este commit, lo deja o se detiene.

Lo invoca `.github/workflows/deploy.yml` dos veces —antes de instalar nada y justo antes de
publicar— con `DEPLOY_SHA` en el entorno. Regla (pasadas 4, 6 y 7 de la revisión adversarial de
la 1.14.0): **producción no retrocede, no pierde un commit verde y no se publica a ciegas.** Un CI
que termina después de que `main` avanzó no debe pisar un commit que producción ya dejó atrás;
saltarlo sólo porque la punta se movió perdía el último commit verde cuando el siguiente fallaba
su CI (A verde, B rojo: nadie desplegaba A). Por eso la regla mira lo que producción SIRVE —la
huella `build-sha.txt` que el propio Deploy sella— y distingue tres estados:

- la huella responde y es un commit conocido: se salta sólo si ya es un descendiente de este
  commit (publicar retrocedería); el mismo commit se puede republicar;
- producción no tiene huella (404: el sitio anterior al sello, o un sitio roto): se publica;
- la huella no se pudo verificar (sin respuesta tras reintentar, cuerpo ilegible, o un commit que
  tampoco se pudo traer del remoto): el Deploy se DETIENE en rojo. Publicar a ciegas es
  exactamente el retroceso que este control existe para impedir; un `workflow_dispatch` con
  `forzar` lo publica a sabiendas.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

#: Dónde sirve producción la huella del commit que la construyó (`deploy.yml`, «Sellar el sitio»).
SELLO_URL = "https://docs.nikodym.cl/build-sha.txt"
_SHA = re.compile(r"[0-9a-f]{40}")

PUBLICAR = "publicar"
SALTAR = "saltar"
DETENER = "detener"


@dataclass(frozen=True)
class Sello:
    """Lo que producción respondió: `sha` si sirve una huella; `ausente` si no tiene ninguna (404).

    Sin `sha` y sin `ausente`, la huella no se pudo verificar.
    """

    sha: str | None = None
    ausente: bool = False


def leer_sello(
    url: str = SELLO_URL, *, intentos: int = 3, espera: float = 10.0, timeout: float = 20.0
) -> Sello:
    """Lee la huella que sirve producción, reintentando; un 404 es «sin huella», no un fallo."""
    for intento in range(1, intentos + 1):
        try:
            peticion = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
                texto = respuesta.read().decode("utf-8", errors="replace").strip()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return Sello(ausente=True)
        except (OSError, ValueError):
            pass
        else:
            if _SHA.fullmatch(texto):
                return Sello(sha=texto)
        if intento < intentos:
            time.sleep(espera)
    return Sello()


def _git(repo: Path, *args: str) -> bool:
    proceso = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    return proceso.returncode == 0


def decidir(deploy_sha: str, sello: Sello, repo: Path) -> tuple[str, str]:
    """Devuelve (`publicar` | `saltar` | `detener`, motivo) para `deploy_sha` frente a `sello`."""
    if sello.ausente:
        return PUBLICAR, f"producción no tiene huella todavía: se publica {deploy_sha[:7]}"
    if sello.sha is None:
        return DETENER, "no se pudo leer la huella de producción: no se publica a ciegas"
    if sello.sha == deploy_sha:
        return PUBLICAR, f"producción ya sirve {deploy_sha[:7]}: se vuelve a publicar"
    if not _git(repo, "cat-file", "-e", f"{sello.sha}^{{commit}}"):
        if not _git(repo, "fetch", "--quiet", "origin", "main"):
            return DETENER, (
                f"producción sirve {sello.sha[:7]} y no se pudo traer origin/main para situarlo"
            )
        if not _git(repo, "cat-file", "-e", f"{sello.sha}^{{commit}}"):
            return PUBLICAR, (
                f"producción sirve {sello.sha[:7]}, que no está en main: "
                f"se publica {deploy_sha[:7]}"
            )
    if _git(repo, "merge-base", "--is-ancestor", deploy_sha, sello.sha):
        return SALTAR, (
            f"producción ya sirve {sello.sha[:7]}, posterior a {deploy_sha[:7]}: no se retrocede"
        )
    return PUBLICAR, (
        f"producción sirve {sello.sha[:7]}, anterior o divergente: se publica {deploy_sha[:7]}"
    )


def _anotar_env(linea: str) -> None:
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as fh:
            fh.write(linea + "\n")


def main() -> int:
    """Punto de entrada del workflow: `SALTAR=1` en `GITHUB_ENV` si no publica; 1 si se detiene."""
    deploy_sha = os.environ["DEPLOY_SHA"]
    forzar = os.environ.get("FORZAR", "").strip().lower() == "true"
    sello = leer_sello(os.environ.get("SELLO_URL", SELLO_URL))
    decision, motivo = decidir(deploy_sha, sello, Path.cwd())
    if decision != PUBLICAR and forzar:
        print(f"::warning::{motivo}; se publica igual porque forzar=true")
        return 0
    if decision == SALTAR:
        print(f"::notice::{motivo}")
        _anotar_env("SALTAR=1")
        return 0
    if decision == DETENER:
        print(f"::error::{motivo} (un workflow_dispatch con forzar=true publica a sabiendas)")
        return 1
    print(motivo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
