# Soporte

Nikodym es software libre (Apache-2.0) mantenido por **Nexo Labs**. Esta página dice quién responde
qué, para que sepas a qué atenerte antes de apoyarte en la librería.

## Antes de preguntar

- **[Documentación](https://docs.nikodym.cl)** — guías, referencia de configuración y el detalle de
  cada dominio.
- **[Demo](https://demo.nikodym.cl)** — tres corridas reales del motor (scorecard, provisiones CMF,
  IFRS 9) con sus informes descargables.
- **[CHANGELOG](CHANGELOG.md)** — qué cambió en cada versión, incluidas las correcciones de cálculo.

## Canales

| Necesitas | Dónde | Qué esperar |
| --- | --- | --- |
| Reportar un bug | [Issues](https://github.com/nexolabs-gh/nikodym/issues) | Mejor esfuerzo. Incluye versión, config mínimo y traza completa. |
| Proponer una capacidad | [Issues](https://github.com/nexolabs-gh/nikodym/issues) | Se evalúa contra el roadmap; toda capacidad nueva pasa por un documento de diseño. |
| Reportar una vulnerabilidad | Ver [SECURITY.md](SECURITY.md) | **No uses issues públicos.** |
| Implantación, adaptación regulatoria o validación | [Nexo Labs](https://www.nikodym.cl/#contact) | Servicio comercial, con acuerdo y plazos por contrato. |

## Lo que este proyecto no promete

Preferimos decirlo antes de que dependas de ello:

- **No hay SLA en el canal abierto.** Los issues se atienden por mejor esfuerzo, sin garantía de
  tiempo de respuesta. Si necesitas compromisos de plazo, eso es el canal comercial.
- **No somos tu validador.** El informe entrega evidencia técnica y deja el veredicto como un
  bloque que debe firmar un validador humano. La responsabilidad regulatoria de usar estos números
  es de tu institución.
- **Las matrices normativas exigen validación humana.** Se publican con su fuente y su numeral para
  que las verifiques; están selladas y trazadas, pero no certificadas por el regulador.
- **Superficie estable vs. experimental.** El pipeline de scorecard (F1) está bajo garantía SemVer
  1.x. Las provisiones (CMF, IFRS 9), el stress, el forward-looking y survival están implementados
  y testeados, pero **marcados experimentales**: su API puede cambiar dentro de la serie 1.x. El
  propio informe declara qué superficie usó cada corrida.

## Compatibilidad

Python 3.11, 3.12 y 3.13, sobre macOS, Linux y Windows: la matriz completa se prueba en cada
cambio. Las dependencias base llevan techos deliberados (por ejemplo `pandas<3`) porque la versión
mayor siguiente aún no está probada contra el motor; se levantan cuando lo está, no antes.
