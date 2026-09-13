"""Decide si el Deploy de producción publica este commit, lo deja o se detiene.

Lo invoca `.github/workflows/deploy.yml` dos veces —antes de instalar nada y justo antes de
publicar— con `DEPLOY_SHA` en el entorno. Regla (pasadas 4, 6, 7, 9, 10 y 11 de la revisión
adversarial de la 1.14.0): **producción no retrocede, no pierde un commit verde y no se publica a
ciegas.** Un CI que termina después de que `main` avanzó no debe pisar un commit que producción ya
dejó atrás; saltarlo sólo porque la punta se movió perdía el último commit verde cuando el
siguiente fallaba su CI (A verde, B rojo: nadie desplegaba A). Por eso la regla mira lo que
producción SIRVE —la huella `build-sha.txt` que el propio Deploy sella en los DOS sitios— y decide:

- las dos huellas son este commit o ancestros suyos: se publica (el mismo commit se vuelve a
  publicar; un ancestro se supera; y una producción PARTIDA —docs en B, demo en A porque el
  segundo despliegue falló— la repara el rerun de B o cualquier descendiente, en los dos sitios);
- una huella ya es un descendiente de este commit: se salta si producción es coherente (publicar
  retrocedería); si está partida con un sitio adelante y otro atrás, se detiene —ni retroceder
  el primero ni dejar el segundo—: la repara el rerun del commit adelantado;
- una huella que no se pudo leer —sin respuesta, cuerpo ilegible o 404: producción YA está
  sellada, así que un sitio sin huella no es un arranque sino un estado que no se puede
  verificar—, un commit que `origin/main` no conoce, un historial divergente o un `DEPLOY_SHA`
  que no está en `main`: el Deploy se DETIENE en rojo. Publicar a ciegas es exactamente el
  retroceso que este control existe para impedir; un `workflow_dispatch` con `forzar` publica a
  sabiendas (y es la única vía para volver a sellar un sitio que perdió su huella).

Y la vía MANUAL exige el CI del commit (pasada 12): el `if` del job sólo comprueba el CI verde
cuando lo dispara un `workflow_run`; un `workflow_dispatch` publicaba cualquier commit de `main`
sin mirar si su CI terminó, y en qué. Sin `forzar`, el script consulta por la API de Actions los
runs de `ci.yml` de `DEPLOY_SHA` **en `main`** —el verde de un tag o de otra rama sobre el mismo
commit es un CI reducido y no cuenta— y sólo sigue si alguno terminó en `success`: uno sin
terminar, ninguno en éxito, ninguno en absoluto o una API que no responde detienen el Deploy en
rojo. Con `forzar`, avisa y publica a sabiendas, como con el resto de la regla.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Dónde sirve cada sitio la huella del commit que lo construyó (`deploy.yml`, «Sellar …»).
SELLO_DOCS_URL = "https://docs.nikodym.cl/build-sha.txt"
SELLO_DEMO_URL = "https://demo.nikodym.cl/build-sha.txt"
_SHA = re.compile(r"[0-9a-f]{40}")

PUBLICAR = "publicar"
SALTAR = "saltar"
DETENER = "detener"

#: Veredictos de :func:`consultar_ci`; sólo :data:`CI_VERDE` deja seguir a un despacho manual.
CI_VERDE = "verde"
CI_PENDIENTE = "pendiente"
CI_ROJO = "rojo"
CI_SIN_RUNS = "sin_runs"
CI_NO_VERIFICABLE = "no_verificable"
#: Estados de un run que todavía no terminó (`status` de la API de Actions).
_RUN_EN_CURSO = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})
#: La única rama cuyo CI corre TODOS los gates (`test-all` sólo corre en PR o en `refs/heads/main`):
#: un run verde de un tag o de otra rama sobre el mismo commit es un CI reducido y no cuenta.
_RAMA_DE_PRODUCCION = "main"


@dataclass(frozen=True)
class Sello:
    """Lo que un sitio respondió: `sha` si sirve una huella; sin `sha`, no se pudo verificar."""

    sha: str | None = None

    @property
    def ilegible(self) -> bool:
        """Sin huella: el sitio no respondió un SHA (caído, cuerpo extraño o 404)."""
        return self.sha is None


def leer_sello(
    url: str, *, intentos: int = 3, espera: float = 10.0, timeout: float = 20.0
) -> Sello:
    """Lee la huella que sirve un sitio, reintentando; todo lo que no sea un SHA es ilegible."""
    for intento in range(1, intentos + 1):
        try:
            peticion = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
                texto = respuesta.read().decode("utf-8", errors="replace").strip()
        except (OSError, ValueError):
            pass
        else:
            if _SHA.fullmatch(texto):
                return Sello(sha=texto)
        if intento < intentos:
            time.sleep(espera)
    return Sello()


def consultar_ci(
    deploy_sha: str,
    *,
    repo: str,
    token: str | None,
    api_url: str = "https://api.github.com",
    intentos: int = 3,
    espera: float = 10.0,
    timeout: float = 20.0,
) -> tuple[str, str]:
    """Clasifica los runs de `ci.yml` de `deploy_sha` (pasada 12): (`verde` | … , motivo).

    Sólo cuentan los runs de `main` (`head_branch`): `ci.yml` corre en cualquier rama y en los
    tags, pero `test-all` sólo corre en PR o en `refs/heads/main`, así que el verde de un tag o de
    otra rama sobre el MISMO commit es un CI reducido que no habilita publicar un `main` rojo
    (pasada 1 de la revisión adversarial de esta serie). Verde si algún run de `main` terminó en
    `success` (un rerun verde de `main` cuenta; un rojo aislado del runner al lado no lo invalida);
    `pendiente` si alguno de `main` sigue corriendo y ninguno está en verde; `rojo` si todos los de
    `main` terminaron sin éxito; `sin_runs` si el commit no tiene CI de `main`; y `no_verificable`
    sin token o si la API no respondió algo legible tras `intentos`. Nunca fabrica un verde: la
    duda detiene.
    """
    corto = deploy_sha[:7]
    if not token:
        return CI_NO_VERIFICABLE, (
            f"sin GITHUB_TOKEN no se puede consultar el CI de {corto}: no se publica a ciegas"
        )
    consulta = urllib.parse.urlencode({"head_sha": deploy_sha, "per_page": 100})
    url = f"{api_url}/repos/{repo}/actions/workflows/ci.yml/runs?{consulta}"
    runs: list[dict[str, Any]] | None = None
    for intento in range(1, intentos + 1):
        try:
            peticion = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
                cuerpo = json.loads(respuesta.read().decode("utf-8"))
            candidatos = cuerpo.get("workflow_runs") if isinstance(cuerpo, dict) else None
            if isinstance(candidatos, list):
                runs = [run for run in candidatos if isinstance(run, dict)]
                break
        except (OSError, ValueError):
            pass
        if intento < intentos:
            time.sleep(espera)
    if runs is None:
        return CI_NO_VERIFICABLE, (
            f"no se pudo consultar el CI de {corto} por la API de Actions: no se publica a ciegas"
        )
    runs = [run for run in runs if run.get("head_branch") == _RAMA_DE_PRODUCCION]
    if not runs:
        return CI_SIN_RUNS, (
            f"no hay ningún run de ci.yml de {_RAMA_DE_PRODUCCION} para {corto} (los de otras "
            "ramas o tags no cuentan: no corren todos los gates): no se publica sin CI"
        )
    en_verde = [run for run in runs if run.get("conclusion") == "success"]
    if en_verde:
        return CI_VERDE, f"el CI de {corto} terminó en verde ({en_verde[0].get('html_url', '')})"
    en_curso = [run for run in runs if run.get("status") in _RUN_EN_CURSO]
    if en_curso:
        return CI_PENDIENTE, (
            f"el CI de {corto} todavía no terminó ({en_curso[0].get('html_url', '')}): "
            "espera su verde antes de publicar"
        )
    conclusiones = ", ".join(sorted({str(run.get("conclusion")) for run in runs}))
    return CI_ROJO, (
        f"el CI de {_RAMA_DE_PRODUCCION} para {corto} no terminó en success ({conclusiones}): "
        "no se publica"
    )


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
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        # La vía automática ya exige el CI verde en el `if` del job; la manual no lo miraba.
        veredicto, motivo = consultar_ci(
            deploy_sha,
            repo=os.environ.get("GITHUB_REPOSITORY", ""),
            token=os.environ.get("GITHUB_TOKEN"),
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        )
        if veredicto != CI_VERDE and forzar:
            print(f"::warning::{motivo}; se publica igual porque forzar=true")
        elif veredicto != CI_VERDE:
            print(f"::error::{motivo} (un workflow_dispatch con forzar=true publica a sabiendas)")
            return 1
        else:
            print(motivo)
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
