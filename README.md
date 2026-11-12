# Conciliación automática de pagos

Proyecto de portafolio que concilia los movimientos de una cuenta bancaria contra un registro contable interno. El motor aplica reglas en cascada, le pone una confianza a cada propuesta, manda las dudas a una cola de revisión humana y entrega un reporte en Excel con un registro de auditoría.

Es un caso genérico y sintético. Los datos los genera un script con semilla fija, y ni los formatos, ni las referencias, ni las reglas corresponden a un banco o a un sistema real. Cualquier parecido con un proceso de una institución es coincidencia de diseño.

## Qué hace

1. Genera dos fuentes: `datos/banco.csv` (movimientos bancarios) y `datos/contable.xlsx` (registro contable), con 137 y 152 filas.
2. Valida las entradas y calcula el SHA-256 de cada archivo.
3. Concilia con cuatro reglas, en este orden, y cada una solo ve lo que las anteriores dejaron libre:
   - R1, exacta: misma referencia normalizada, mismo monto y misma fecha. Confianza 1.00.
   - R2, tolerancia: misma referencia, monto a menos de 0.10 y fecha a máximo 3 días. La confianza baja con cada centavo y cada día de diferencia.
   - R2B, sin referencia: cuando falta la referencia en alguno de los lados, propone por monto igual y fecha cercana. Nunca pasa del 0.70, así que siempre queda para revisión.
   - R3, uno a muchos: un abono del banco contra varios documentos del mismo cliente cuya suma coincide (hasta 5 documentos).
4. Decide por umbral: 0.85 o más se concilia sola, de 0.50 a 0.85 va a la cola de revisión, y lo demás queda pendiente. Si dos candidatos distintos empatan, o una combinación de documentos admite varias soluciones, no elige: lo manda a revisión sin gastar los documentos.
5. Aparta los abonos repetidos del banco como posible duplicado, siempre que haya más abonos idénticos que documentos con esa referencia y monto.
6. Escribe `salidas/conciliacion_<clave>.xlsx` con las hojas Resumen, Conciliadas, Revision, Pendientes y Bitacora, y agrega una línea a `auditoria/registro_auditoria.jsonl`.

El diagrama de flujo está en [docs/flujo.md](docs/flujo.md) y las decisiones en [docs/bitacora.md](docs/bitacora.md).

## Casos que cubren los datos sintéticos

Coincidencia exacta (60), referencia con formato sucio como `fac-0001234 ` o `REF. 0001234` (20), diferencia de redondeo de uno a cinco centavos (10), fecha valor desfasada de uno a tres días (10), caso en el límite de ambas tolerancias (3), abono duplicado en el banco (6), un pago contra dos a cuatro facturas (8), un pago con dos combinaciones posibles de facturas (1), abonos sin referencia (4 y uno ambiguo), y partidas sin contraparte (8 del banco y 8 contables).

## Qué salió en la corrida de referencia

Cifras de `python src/ejecutar_todo.py` con la semilla 42:

- 114 conciliaciones automáticas (86 por R1, 20 por R2 y 8 por R3), 15 casos en la cola de revisión (6 duplicados, 5 sin referencia, 3 en el límite de tolerancias y 1 pago con combinaciones ambiguas), 8 movimientos bancarios y 14 registros contables pendientes.
- Contra la verdad de terreno que escribe el generador, las 285 partidas evaluadas terminan donde se esperaba y no hay conciliaciones automáticas incorrectas. Hay que leerlo con cuidado: el generador y el motor los escribí yo con las mismas ideas, así que esto confirma que el código hace lo que diseñé y no dice cómo se comportaría con datos reales, que traen casos que aquí no imaginé.
- El motor tarda unos 0.01 segundos en esta muestra. Es un tiempo medido.

## Tiempo manual contra automatizado

El reporte incluye una comparación, pero casi toda se basa en supuestos que declaro en `src/config.py`: 1.5 minutos para conciliar a mano cada partida y 3 minutos para que una persona resuelva cada caso de la cola. Con esos supuestos, las 289 partidas serían unos 433 minutos a mano y unos 45 minutos con el motor más la revisión de los 15 casos. Son cuentas de ejemplo, no un ahorro medido en ningún proceso real, y no deben citarse como resultado.

## Límites

- Solo concilia abonos (montos positivos), en una moneda y una cuenta. No maneja cargos, comisiones ni conversión de divisas.
- No resuelve el caso inverso de varios abonos del banco contra un solo documento.
- La agrupación uno a muchos necesita el código de cliente en la referencia o la descripción del banco, y combina como máximo 12 candidatos y 5 documentos para acotar el cálculo.
- Si dos pagos legítimos son idénticos en referencia, monto y fecha, y el registro contable tiene un solo documento, el motor marca el segundo como posible duplicado. Es lo que se busca, pero es una sospecha y no una conclusión.
- Los candidatos que se muestran en la cola de revisión se calculan al momento de la corrida. Si alguien concilia a mano un documento y vuelve a correr, el resultado cambia, y por eso la clave de idempotencia depende solo de los archivos y de las reglas.
- Los pesos de la confianza (0.97, 0.03 por día, 0.10 por la tolerancia de monto) son una elección mía y no se calibraron con datos reales.

## Cómo correrlo

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/ejecutar_todo.py      # genera datos, ensaya, concilia, repite y evalúa
python -m pytest
```

Por separado:

```bash
python src/generar_datos.py
python src/conciliar.py --dry-run      # calcula y muestra el resumen sin escribir nada
python src/conciliar.py                # corrida real
python src/conciliar.py --banco otro.csv --contable otro.xlsx
```

Correr dos veces con los mismos archivos y las mismas reglas no duplica nada: la segunda vez avisa que ya se procesó y no escribe. Si cambia un archivo o una regla, se genera un reporte nuevo y una línea nueva en la auditoría.

## Configuración

Todo por variables de entorno, con valores por defecto: `CONC_TOL_MONTO` (0.10), `CONC_TOL_DIAS` (3), `CONC_DIAS_GRUPO` (5), `CONC_UMBRAL_AUTO` (0.85), `CONC_UMBRAL_REVISION` (0.50), `CONC_MAX_CANDIDATOS` (12), `CONC_MAX_DOCS_GRUPO` (5), `CONC_REINTENTOS` (3), `CONC_MAX_FILAS`, `CONC_MAX_MB` y las carpetas `CONC_DIR_DATOS`, `CONC_DIR_SALIDAS` y `CONC_DIR_AUDITORIA`. Un valor fuera de rango detiene la corrida con código de salida 2.

## Errores y reintentos

Las lecturas y escrituras de archivos se reintentan hasta 3 veces por defecto (tope de 5) con espera creciente, solo ante errores de sistema de archivos transitorios. Un archivo inexistente o una entrada inválida fallan de inmediato. El reporte se escribe a un temporal y luego se renombra, así que un fallo no deja un Excel a medias, y la auditoría solo se escribe cuando el reporte quedó completo.

## Auditoría

Cada corrida real agrega una línea JSON con el nombre (sin ruta), tamaño y SHA-256 de cada archivo de entrada, el hash de las reglas, el hash del reporte y los conteos. Cada línea incluye el hash de la anterior, de modo que editar o borrar una línea intermedia se detecta con `auditoria.verificar_cadena`.

## Pruebas

Las 98 pruebas de `tests/` cubren cada regla y sus bordes (tolerancias exactas y excedidas, empates, documentos intercambiables, duplicados legítimos y sospechosos, topes de agrupación), la validación de entradas, la idempotencia, el modo de ensayo, los reintentos, la protección contra fórmulas en Excel, la ausencia de rutas y datos en los logs, y la integridad de la cadena de auditoría. Una acción de GitHub las corre en cada cambio.

Licencia MIT.
