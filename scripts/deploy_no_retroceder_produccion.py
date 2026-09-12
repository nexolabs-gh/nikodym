"""Decide si el Deploy de producción publica este commit, lo deja o se detiene.

Lo invoca `.github/workflows/deploy.yml` dos veces —antes de instalar nada y justo antes de
publicar— con `DEPLOY_SHA` en el entorno. Regla (pasadas 4, 6, 7 y 9 de la revisión adversarial
de la 1.14.0): **producción no retrocede, no pierde un commit verde y no se publica a ciegas.** Un
CI que termina después de que `main` avanzó no debe pisar un commit que producción ya dejó atrás;
saltarlo sólo porque la punta se movió perdía el último commit verde cuando el siguiente fallaba
su CI (A verde, B rojo: nadie desplegaba A). Por eso la regla mira lo que producción SIRVE —la
huella `build-sha.txt` que el propio Deploy sella en los DOS sitios— y decide:

- sin huella en ninguno (404: el sitio anterior al sello): se publica;
- huellas que no se pudieron leer, que discrepan entre docs y demo (una publicación a medias), un
  commit que `origin/main` no conoce, un historial divergente, o un `DEPLOY_SHA` que no está en
  `main`: el Deploy se DETIENE en rojo. Publicar a ciegas es exactamente el retroceso que este
  control existe para impedir; un `workflow_dispatch` con `forzar` publica a sabiendas;
- huella verificada: se salta sólo si ya es un descendiente de este commit (publicar
  retrocedería); el mismo commit se puede republicar y un ancestro se supera.
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

#: Dónde sirve cada sitio la huella del commit que lo construyó (`deploy.yml`, «Sellar …»).
SELLO_DOCS_URL = "https://docs.nikodym.cl/build-sha.txt"
SELLO_DEMO_URL = "https://demo.nikodym.cl/build-sha.txt"
_SHA = re.compile(r"[0-9a-f]{40}")

PUBLICAR = "publicar"
SALTAR = "saltar"
DETENER = "detener"


@dataclass(frozen=True)
class Sello:
    """Lo que un sitio respondió: `sha` si sirve una huella; `ausente` si no tiene ninguna (404).

    Sin `sha` y sin `ausente`, la huella no se pudo verificar.
    """

    sha: str | None = None
    ausente: bool = False

    @property
    def ilegible(self) -> bool:
        """Ni huella ni 404: el sitio no respondió algo verificable."""
        return self.sha is None and not self.ausente


def leer_sello(
    url: str, *, intentos: int = 3, espera: float = 10.0, timeout: float = 20.0
) -> Sello:
    """Lee la huella que sirve un sitio, reintentando; un 404 es «sin huella», no un fallo."""
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


def _huella_de_produccion(docs: Sello, demo: Sello) -> tuple[str | None, str | None]:
    """Reduce los dos sellos a una huella, o a un motivo para detenerse."""
    if docs.ilegible or demo.ilegible:
        cual = " y ".join(n for n, s in (("docs", docs), ("demo", demo)) if s.ilegible)
        return None, f"no se pudo leer la huella de {cual}: no se publica a ciegas"
    if docs.sha and demo.sha and docs.sha != demo.sha:
        return None, (
            f"producción está partida (docs {docs.sha[:7]}, demo {demo.sha[:7]}): "
            "no se publica encima; reejecuta el Deploy que quedó a medias"
        )
    return docs.sha or demo.sha, None


def decidir(deploy_sha: str, docs: Sello, demo: Sello, repo: Path) -> tuple[str, str]:
    """Devuelve (`publicar` | `saltar` | `detener`, motivo) para `deploy_sha` ante producción."""
    sello, motivo = _huella_de_produccion(docs, demo)
    if motivo is not None:
        return DETENER, motivo
    if not _git(repo, "fetch", "--quiet", "origin", "main"):
        return DETENER, "no se pudo traer origin/main para situar el commit: no se publica a ciegas"
    if not _git(repo, "merge-base", "--is-ancestor", deploy_sha, "origin/main"):
        return DETENER, f"{deploy_sha[:7]} no está en main: sólo main llega a producción sin forzar"
    if sello is None:
        return PUBLICAR, f"producción no tiene huella todavía: se publica {deploy_sha[:7]}"
    if sello == deploy_sha:
        return PUBLICAR, f"producción ya sirve {deploy_sha[:7]}: se vuelve a publicar"
    if not _git(repo, "cat-file", "-e", f"{sello}^{{commit}}"):
        return DETENER, (
            f"producción sirve {sello[:7]}, que origin/main no conoce: no se publica a ciegas"
        )
    if _git(repo, "merge-base", "--is-ancestor", deploy_sha, sello):
        return SALTAR, (
            f"producción ya sirve {sello[:7]}, posterior a {deploy_sha[:7]}: no se retrocede"
        )
    if _git(repo, "merge-base", "--is-ancestor", sello, deploy_sha):
        return PUBLICAR, f"producción sirve {sello[:7]}, anterior: se publica {deploy_sha[:7]}"
    return DETENER, (
        f"producción sirve {sello[:7]}, divergente de {deploy_sha[:7]}: no se publica a ciegas"
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
    docs = leer_sello(os.environ.get("SELLO_DOCS_URL", SELLO_DOCS_URL))
    demo = leer_sello(os.environ.get("SELLO_DEMO_URL", SELLO_DEMO_URL))
    decision, motivo = decidir(deploy_sha, docs, demo, Path.cwd())
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
