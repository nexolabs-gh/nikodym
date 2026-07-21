# Política de seguridad

Nikodym se usa para calcular provisiones y evaluar riesgo de crédito en instituciones financieras.
Un defecto de seguridad —o un error de cálculo silencioso— puede tener consecuencias regulatorias
para quien lo usa. Tomamos los reportes en serio y agradecemos que nos los hagan llegar.

## Cómo reportar una vulnerabilidad

**No abras un issue público** para un problema de seguridad. Escríbenos a **admin@nxlabs.cl** con
el asunto `[seguridad] nikodym`, incluyendo:

- la versión de `nikodym` y de Python,
- qué observaste y cómo reproducirlo (idealmente un fragmento de código mínimo),
- por qué crees que tiene impacto de seguridad.

Si prefieres el canal de GitHub, este repositorio acepta
[reportes privados de vulnerabilidad](https://github.com/nexolabs-gh/nikodym/security/advisories/new).

## Qué puedes esperar

Somos un equipo pequeño, así que preferimos comprometernos con lo que podemos cumplir:

- **Acuse de recibo**: dentro de 5 días hábiles.
- **Diagnóstico inicial**: dentro de 15 días hábiles, con nuestra evaluación de impacto y, si
  corresponde, una mitigación provisional que puedas aplicar sin esperar la corrección.
- **Corrección**: publicamos un release en PyPI y una entrada en el `CHANGELOG.md`. Si el reporte
  lo amerita, emitimos un aviso de seguridad de GitHub.
- **Crédito**: te acreditamos en el aviso salvo que prefieras permanecer anónimo.

No tenemos un programa de recompensas.

## Versiones con soporte

Se corrigen problemas de seguridad sobre la **última versión menor publicada** de la serie 1.x. No
hay soporte retroactivo de versiones anteriores: la vía de corrección es actualizar.

| Versión | Soporte de seguridad |
| ------- | -------------------- |
| 1.4.x   | ✅                    |
| < 1.4   | ❌ (actualizar)       |

## Alcance

**Dentro de alcance**: ejecución de código no deseada al procesar un config, un dataset o un
artefacto de corrida; escritura fuera del `workdir` declarado; filtración de datos del usuario en
artefactos que se comparten (informe, export, logs); dependencias con vulnerabilidades conocidas
que Nikodym alcance en un flujo real.

**Fuera de alcance**: la capa opcional de narración por IA cuando el usuario la habilita y le
entrega su propia clave (esos datos salen hacia el proveedor que el usuario eligió; la prosa del
informe es determinista y no la escribe la IA); y las decisiones de negocio o regulatorias tomadas
a partir de los resultados, que requieren validación humana —el propio informe lo declara.

## Nota sobre datos

Nikodym es una librería: **corre dentro de tu infraestructura y no envía tus datos a ninguna
parte**. El paquete no contiene telemetría de ningún tipo, y el pipeline de cálculo no abre
conexiones de red por sí solo.

Sólo hay dos salidas posibles, y las dos las decides tú:

1. **La capa de narración por IA**, apagada por defecto: se activa explícitamente y con tu propia
   clave, y entonces envía el payload al proveedor que hayas elegido. La prosa del informe es
   determinista y no la escribe la IA, así que puedes dejarla apagada sin perder el entregable.
2. **El registro de experimentos (MLflow)**, cuyo destino por defecto es un directorio local
   (`./mlruns`). Si configuras un servidor de tracking remoto, los metadatos de tus corridas irán
   a ese servidor —el tuyo—, porque tú lo apuntaste ahí.

Si encuentras cualquier comportamiento que contradiga esto, trátalo como un reporte de seguridad y
escríbenos.
