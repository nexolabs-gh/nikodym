# SDD-NN — <Nombre del módulo>

> **Plantilla.** Copiar a `docs/design/NN-<modulo>.md` y completar todas las secciones.
> Un SDD por módulo del árbol `src/nikodym/`. **Objetivo: que el módulo quede 100% especificado antes de escribir código** — quien implemente (persona o agente) no debe tener que tomar decisiones de diseño pendientes, solo traducir esta especificación a código.
> Regla: este documento describe **qué** y **cómo se comporta**, no la implementación. Las firmas de API son contratos (ilustrativas), no código final.

| Campo | Valor |
|---|---|
| **SDD** | NN |
| **Módulo** | `nikodym.<paquete>` |
| **Fase** | F0 / F1 / … |
| **Tanda de producción** | T1 / T2 / … |
| **Estado** | Borrador / En revisión / Aprobado |
| **Depende de** | SDD-XX, SDD-YY |
| **Lo consumen** | SDD-ZZ, … |
| **Autor / Fecha** | |

---

## 1. Propósito y responsabilidad
- Qué resuelve este módulo en una frase.
- **Responsabilidad única**: qué SÍ hace.
- **Límites explícitos**: qué NO hace (y qué módulo lo hace en su lugar).

## 2. Contexto y ubicación en la arquitectura
- Dónde encaja (capa, dominio).
- Quién lo invoca y a quién invoca (diagrama de dependencias si ayuda).
- Cómo interactúa con el `Study` y el config declarativo.

## 3. Conceptos y fundamentos
- Definiciones de dominio (riesgo de crédito / estadística) necesarias.
- **Fórmulas** explícitas (con notación), referencias normativas (CMF/IFRS 9) y académicas.
- Enlaces a la síntesis de investigación o normativa relevante (`docs/`).

## 4. API pública (contrato)
- Clases y funciones expuestas, con **firmas ilustrativas** (nombres, parámetros, tipos, retorno).
- Patrón **scikit-learn** (`fit/transform/predict`, `get_params/set_params`) donde aplique; señalar dónde se usa una clase base propia y por qué.
- Atributos resultantes (convención `_` final para los fiteados).
- Ejemplo de uso de extremo a extremo (pseudocódigo, no implementación).

## 5. Configuración (schema Pydantic)
- Modelo(s) Pydantic v2 que parametrizan el módulo: campos, tipos, **defaults defendibles**, validaciones, rangos.
- Cómo se serializa a/desde YAML (round-trip) y cómo lo edita la UI.

## 6. Contratos de datos (I/O)
- **Input**: esquema esperado (columnas, tipos, supuestos), validaciones de entrada.
- **Output**: estructura producida (tablas, objetos, artefactos) y formato.
- Invariantes que deben cumplirse antes/después.

## 7. Algoritmos y flujo
- Pasos del procesamiento (numerados), en **pseudocódigo de alto nivel**.
- Decisiones algorítmicas y alternativas descartadas (con motivo).
- Complejidad / consideraciones de rendimiento si son relevantes.

## 8. Casos borde y manejo de errores
- Missing / special values / clases vacías / datos degenerados.
- Excepciones propias y mensajes (qué se valida y qué se levanta).
- Comportamiento ante configuración inválida.

## 9. Reproducibilidad y auditoría
- Componentes estocásticos y cómo se siembran (semilla).
- Qué registra en el **audit-trail / lineage / model card** (decisiones, umbrales gatillados).
- Garantía de determinismo y caveats (p.ej. GBDT multihilo).

## 10. Dependencias
- **Internas**: módulos `nikodym` de los que depende.
- **Externas**: librerías + versión mínima + **licencia** (vetar copyleft en el core).
- Si es un *extra* opcional, declararlo (import perezoso, mensaje al usuario).

## 11. Estrategia de tests
- Casos canónicos con resultado conocido (p.ej. fórmulas verificables a mano).
- Tests de propiedades (Hypothesis) e invariantes.
- Test de reproducibilidad (misma semilla → mismo resultado).
- Fixtures / datasets de prueba.

## 12. Decisiones abiertas y riesgos
- Lo que queda por decidir (con responsable sugerido).
- Riesgos técnicos/metodológicos y mitigación.
