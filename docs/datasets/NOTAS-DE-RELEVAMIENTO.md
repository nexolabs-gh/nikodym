# HANDOFF — Datasets para Nikodym

**Última sesión:** 2026-07-25
**Ubicación:** `/Users/camilogonzalez/Downloads/datasets-riesgo-credito` — **no es repo git**
**Estado:** cerrado y verificado. Nada a medias.

---

## Qué es esto

Catálogo de datasets públicos para desarrollar y validar **Nikodym** (librería de riesgo de
crédito). El criterio del catálogo no es "acá hay datos de crédito" sino **qué caso de prueba
cubre cada dataset que ningún otro cubre**.

Para retomar basta leer `README.md`. Este handoff sólo agrega el contexto de la sesión.

| Archivo | Rol |
|---|---|
| `README.md` | La referencia. Mapa de `raw/`, §0 sobre el ciclo efímero, y por cada dataset: fuente, ruta, y por qué testear con él |
| `catalogo.csv` | 42 datasets, 10 columnas. Verificado: 0 rutas rotas, 42/42 con justificación |
| `descargar.sh` | Gestor: `ls` `get` `rm` `nucleo` `espacio` `manual` `inventario` |
| `INVENTARIO.md` | Autogenerado. Qué hay en disco y qué falta, con el comando para recuperarlo |
| `raw/` | 117 archivos, 10 GB. **Efímeros** |

---

## Hecho

- Relevamiento de 42 datasets cubriendo: scorecard/PD retail, behavioral, PD corporativa,
  matrices de transición, LGD, EAD/CCF, IFRS 9, stress testing, Basilea/RWA, fairness, macro,
  Chile y fraude.
- Descargados 30 de 31 claves automatizables (10 GB).
- **Freddie Mac SFLLD completo**: 27 vintages 1999–2025 en versión sample (50.000 originaciones
  por año + performance mensual), 1,0 GB. Incluye las cosechas de crisis 2005–2007.
- Kaggle: cuenta verificada por SMS y reglas aceptadas en las 3 competencias
  (`GiveMeSomeCredit`, `home-credit-default-risk`, `home-credit-credit-risk-model-stability`).
- Limpieza: 3,2 GB de duplicados eliminados con verificación previa de equivalencia.
- Gates al cierre: sintaxis OK · catálogo sin rutas rotas · 5 datasets clave leídos con pandas.

## En curso

Nada. La sesión cerró sin trabajo a medias.

## Próximos pasos (en orden)

1. **Empezar por `raw/ifrs9/mortgage.csv`** (622.489 filas de panel). Da el ciclo IFRS 9
   completo sin depender de nada más. Prioridad: modelar `payoff_time` como riesgo competitivo
   — es donde falla la mayoría de las implementaciones de lifetime ECL.
2. Encadenar `raw/stress/fed/` sobre ese modelo: el House Price Index y el desempleo del
   escenario severely adverse enlazan directo con las columnas macro del panel.
3. Contrastar el staging resultante contra `raw/stress/eba/eba_st25_TRA_CRE_IRB.csv`, que trae
   exposiciones por `IFRS9_Stages` de 64 bancos europeos reales.
4. Cuando toque cada módulo, bajar su dataset y borrarlo después (ver Decisiones).

## Decisiones tomadas

- **Datasets efímeros.** El disco es escaso (93% usado) y los datasets son reproducibles.
  Lo permanente son los 4 archivos de documentación (~60 KB), no los datos. Ciclo:
  `get` → probar → `rm`. Decidido por Cami el 2026-07-25.
- **Núcleo permanente (~90 MB)** que no se borra: `hmeq`, `german`, `south_german`, `taiwan`,
  `credit_approval`, `australian`, `polish`, `taiwan_bank`, `ratings`, `adult`, `lgd`,
  `mortgage`, `fed`, `fred`, `cmf`. Cubren CI, IFRS 9, LGD y stress end-to-end.
- **Freddie Mac por samples, no vintages completos.** El muestreo de 50.000 préstamos/año lo
  hace Freddie Mac: es defendible ante un cliente sin justificar diseño muestral propio, y son
  1,0 GB en vez de ~200 GB.
- **Lending Club se conserva sólo comprimido.** Los `.csv` descomprimidos eran idénticos a sus
  `.csv.gz` (verificado: 2.260.702 y 27.648.742 filas en ambos). `pandas.read_csv` lee `.gz`
  nativo. Ahorro: 3,2 GB.
- **`raw/` se organiza por módulo de la librería, no por fuente.**

## Callejones sin salida (no repetir)

- **El portal "Datos Abiertos" de la CMF está vacío** — sólo navegación, sin archivos. Los datos
  reales están dispersos en páginas de estadísticas con URLs tipo
  `articles-NNNNNN_recurso_1.xlsx` que no se descubren desde el HTML ni aparecen como `<a href>`
  con extensión. Hay que extraerlos con JS desde el navegador. Las 12 URLs ya resueltas están
  en `descargar.sh`.
- **`mortgage.csv` no está listado en la página de datasets de creditriskanalytics.net.** Está
  en un `.rar` no enlazado: `uploads/1/9/5/1/19511601/mortgage_csv.rar`. El `tar` de macOS
  (libarchive) lo abre sin instalar nada.
- **El CLI de Kaggle 2.x no usa `kaggle.json`.** Autentica con `~/.kaggle/access_token` (OAuth).
  Además el binario puede no estar en el PATH aunque el módulo exista: usar `python3 -m kaggle`.
- **HMDA no se baja entero**: el data browser API exige filtros. Se baja por estado
  (`?years=2025&states=CA`).

## Bloqueos y pendientes

| Qué | Por qué | Acción |
|---|---|---|
| `amex` (50 GB) | No cabe: 15 GB libres | Buscar versión parquet reducida de la comunidad (3–10 GB) o liberar disco. `AMEX=1` no aplica al gestor nuevo: usar `./descargar.sh get amex` |
| EFH Chile | Requiere cuenta en efhweb.cl | **Sólo Cami.** Único microdato de deuda de hogares chilenos |
| Fannie Mae | Requiere cuenta | Baja prioridad: es validación cruzada de Freddie |
| S&P transiciones | Requiere cuenta; matrices vienen en PDF | Sólo si se hace rating corporativo. Tipear una vez y versionar |
| Descargas múltiples en Freddie Mac | Chrome las bloquea | Ya autorizado para ese dominio. El snippet de consola está en `./descargar.sh manual` |

## Nota sobre versionado

La carpeta vive en `~/Downloads` y **no está bajo git**. Si se quiere versionar, mover los 4
archivos de documentación (`README.md`, `catalogo.csv`, `descargar.sh`, `INVENTARIO.md`, ~60 KB)
al repo de Nikodym y dejar `raw/` fuera con `.gitignore`. Los datos se reconstruyen con
`./descargar.sh get`.
