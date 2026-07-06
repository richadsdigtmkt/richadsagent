# RichAds Agent — Base de conocimiento

Pipeline automático de ingesta de novedades del sector (SEA / SEO / tracking)
y base de conocimiento destilada para RichAds Digital Marketing.

## Estructura

```
richadsagent/
├── scripts/
│   └── ingest_news.py          # Lee feeds, resume con Claude, escribe markdown
├── .github/workflows/
│   └── novedades-diarias.yml   # Cron diario a las 7:00 Madrid
├── conocimiento/
│   └── novedades/              # Un .md por día, generado automáticamente
├── requirements.txt
└── README.md
```

## Cómo funciona

Cada día a las 7:00 (hora de Madrid) GitHub Actions ejecuta el script, que:
1. Lee los feeds RSS de las fuentes configuradas.
2. Filtra las entradas de las últimas 26 horas.
3. Pasa cada una por la API de Claude (Haiku) para resumir y clasificar.
4. Escribe un documento markdown del día en `conocimiento/novedades/`.
5. Hace commit automático al repo.

No requiere que tu ordenador esté encendido: corre en los servidores de GitHub.

## Requisito único de configuración

La clave de API de Anthropic debe estar como **secreto del repo**:
`Settings > Secrets and variables > Actions > New repository secret`
- Nombre: `ANTHROPIC_API_KEY`
- Valor: tu clave (nunca se escribe en el código)

## Operación

**Probar ahora sin esperar al cron:** pestaña `Actions` > "Novedades diarias del
sector" > `Run workflow`. Útil para verificar que todo funciona en la primera vez.

**Ver el resultado:** carpeta `conocimiento/novedades/`, un archivo por día.

**Cambiar la hora:** editar las líneas `cron` en el workflow (están en UTC;
hay dos, una para horario de verano y otra de invierno de Madrid).

**Añadir o quitar fuentes:** editar la lista `FUENTES` en `scripts/ingest_news.py`.
Cada fuente necesita un feed RSS válido. Tras la primera ejecución, revisar que
todas devuelven entradas; si alguna sale con 0 de forma persistente, su feed
puede haber cambiado de URL.

**Cambiar el modelo:** variable `MODEL` en el script. Haiku es el recomendado
para el pipeline (barato). El diagnóstico de cuentas se hace aparte.

## Coste

El pipeline llama a la API de Claude una vez por novedad. Con las fuentes
actuales, unas pocas al día, el coste es de céntimos diarios. Vigilar el
consumo en console.anthropic.com.

## Base de conocimiento destilada (manual)

Además de las novedades automáticas, la carpeta `conocimiento/` alberga los
documentos destilados de sesiones de trabajo, con el formato definido en las
instrucciones del proyecto de Claude. Estos se generan a mano al cerrar cada
tarea importante y son el activo central: criterios de diagnóstico reutilizables.

Estructura recomendada:
```
conocimiento/
├── novedades/        # automático, diario
├── clientes/         # un .md por cliente con su histórico
└── criterios/        # reglas de diagnóstico transversales
```
