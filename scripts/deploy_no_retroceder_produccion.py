"""Decide si el Deploy de producción publica este commit, lo deja o se detiene.

Lo invoca `.github/workflows/deploy.yml` dos veces —antes de instalar nada y justo antes de
publicar— con `DEPLOY_SHA` en el entorno. Regla (pasadas 4, 6, 7, 9 y 10 de la revisión
adversarial de la 1.14.0): **producción no retrocede, no pierde un commit verde y no se publica a
ciegas.** Un CI que termina después de que `main` avanzó no debe pisar un commit que producción ya
dejó atrás; saltarlo sólo porque la punta se movió perdía el último commit verde cuando el
siguiente fallaba su CI (A verde, B rojo: nadie desplegaba A). Por eso la regla mira lo que
producción SIRVE —la huella `build-sha.txt` que el propio Deploy sella en los DOS sitios— y decide:

- sin huella en ninguno (404: el sitio anterior al sello): se publica;
- las huellas presentes son este commit o ancestros suyos: se publica (el mismo commit se vuelve a
  publicar; un ancestro se supera; y una producción PARTIDA —docs en B, demo en A porque el
  segundo despliegue falló— la repara el rerun de B o cualquier descendiente, en los dos sitios);
- una huella ya es un descendiente de este commit: se salta si producción es coherente (publicar
  retrocedería); si está partida con un sitio adelante y otro atrás, se detiene —ni retroceder
  el primero ni dejar el segundo—: la repara el rerun del commit adelantado;
- huellas que no se pudieron leer, un commit que `origin/main` no conoce, un historial divergente
  o un `DEPLOY_SHA` que no está en `main`: el Deploy se DETIENE en rojo. Publicar a ciegas es
  exactamente el retroceso que este control existe para impedir; un `workflow_dispatch` con
  `forzar` publica a sabiendas.
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


def _es_ancestro(repo: Path, ancestro: str, descendiente: str) -> bool:
    return _git(repo, "merge-base", "--is-ancestor", ancestro, descendiente)


def _cortos(*shas: str) -> str:
    return "/".join(sha[:7] for sha in shas)


def decidir(deploy_sha: str, docs: Sello, demo: Sello, repo: Path) -> tuple[str, str]:
    """Devuelve (`publicar` | `saltar` | `detener`, motivo) para `deploy_sha` ante producción."""
    if docs.ilegible or demo.ilegible:
        cual = " y ".join(n for n, s in (("docs", docs), ("demo", demo)) if s.ilegible)
        return DETENER, f"no se pudo leer la huella de {cual}: no se publica a ciegas"
    if not _git(repo, "fetch", "--quiet", "origin", "main"):
        return DETENER, "no se pudo traer origin/main para situar el commit: no se publica a ciegas"
    if not _es_ancestro(repo, deploy_sha, "origin/main"):
        return DETENER, f"{deploy_sha[:7]} no está en main: sólo main llega a producción sin forzar"
    huellas = sorted({s.sha for s in (docs, demo) if s.sha})
    if not huellas:
        return PUBLICAR, f"producción no tiene huella todavía: se publica {deploy_sha[:7]}"
    for sha in huellas:
        if not _git(repo, "cat-file", "-e", f"{sha}^{{commit}}"):
            return DETENER, (
                f"producción sirve {sha[:7]}, que origin/main no conoce: no se publica a ciegas"
            )
    adelante = [s for s in huellas if s != deploy_sha and _es_ancestro(repo, deploy_sha, s)]
    if adelante:
        if len(huellas) == 1:
            return SALTAR, (
                f"producción ya sirve {huellas[0][:7]}, posterior a {deploy_sha[:7]}: "
                "no se retrocede"
            )
        return DETENER, (
            f"producción está partida ({_cortos(*huellas)}) y {_cortos(*adelante)} va delante de "
            f"{deploy_sha[:7]}: ni se retrocede ni se deja; "
            "reejecuta el Deploy del commit adelantado"
        )
    if all(s == deploy_sha or _es_ancestro(repo, s, deploy_sha) for s in huellas):
        if huellas == [deploy_sha]:
            return PUBLICAR, f"producción ya sirve {deploy_sha[:7]}: se vuelve a publicar"
        if len(huellas) > 1:
            return PUBLICAR, (
                f"producción está partida ({_cortos(*huellas)}), las dos iguales o anteriores: "
                f"se publica {deploy_sha[:7]} en los dos sitios"
            )
        return PUBLICAR, f"producción sirve {huellas[0][:7]}, anterior: se publica {deploy_sha[:7]}"
    return DETENER, (
        f"producción sirve {_cortos(*huellas)}, divergente de {deploy_sha[:7]}: "
        "no se publica a ciegas"
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
