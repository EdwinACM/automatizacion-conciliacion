# Bitácora de decisiones

Fecha de la corrida de referencia: 12 de noviembre de 2026. Semilla 42 en el generador.

## Datos

1. Los datos son sintéticos y genéricos. No se tomó ningún formato, nombre ni regla de un banco o sistema real. Los identificadores (`MOV-`, `DOC-`, `CLI`) y las referencias (`FAC-`) son inventados.
2. El banco va en CSV y el registro contable en Excel para probar los dos lectores. En el CSV algunos montos traen `$` y comas de miles, como pasa al exportar a mano.
3. El generador escribe además `verdad_terreno.csv` con el resultado esperado de cada partida. Solo lo usan `evaluar.py` y las pruebas, no el motor.

## Montos y fechas

4. Los montos se convierten a centavos enteros con `Decimal` para no arrastrar errores de punto flotante. Se redondea medio hacia arriba.
5. Solo se aceptan abonos con monto positivo. Un monto cero, negativo, vacío o no numérico rechaza la fila.

## Referencias

6. La normalización toma la corrida de dígitos más larga y quita ceros a la izquierda, después de retirar el código de cliente y el lote. Así `fac-0001234 `, `REF. 0001234` y `Pago FAC 1234` coinciden. Sin dígitos, se queda con las letras que no sean palabras de relleno (REF, FAC, PAGO...).
7. Si una referencia queda vacía tras normalizar, se considera sin referencia y solo puede entrar por R2B.

## Reglas

8. Orden de la cascada: exacta, tolerancia, sin referencia, uno a muchos. Se prefiere lo más estricto primero para que una coincidencia exacta no la gane un candidato aproximado.
9. Confianza de R2: 0.97, menos hasta 0.10 según la diferencia de monto respecto a la tolerancia, menos 0.03 por día. Con los valores por defecto, 3 días solos dan 0.88 y se concilian, y 3 días más 10 centavos dan 0.78 y van a revisión. Los pesos son una elección propia, sin calibración.
10. R2B nunca concilia sola: el máximo es 0.70. Un monto igual sin referencia puede ser coincidencia.
11. R3 usa el código de cliente del banco para limitar candidatos y prueba combinaciones de 2 a 5 documentos, con tope de 12 candidatos para acotar el cálculo. Confianza de 0.92 menos 0.02 por documento adicional al segundo y menos la penalización por diferencia de monto.
12. Empates: si dos candidatos con la misma puntuación son distintos entre sí, el caso va a revisión y no se consume ningún documento. Si son idénticos (misma referencia, monto, fecha y cliente) se toma el de menor identificador, porque da igual cuál se elija. Así dos pagos legítimos idénticos contra dos documentos idénticos no caen en revisión, y un empate real nunca lo decide el orden de los archivos.
13. Duplicados: se aparta el abono sobrante cuando hay más abonos idénticos en el banco que documentos con esa referencia y monto. Los abonos sin referencia no se evalúan como duplicado.

## Operación

14. Idempotencia: la clave de corrida es el hash de los dos archivos y de los parámetros de las reglas. Si la auditoría ya la tiene y el reporte existe con el mismo hash, la corrida se omite. Si el reporte falta, se regenera y se registra otra línea.
15. El modo de ensayo ejecuta todo el cálculo pero no escribe reporte ni auditoría.
16. Los reintentos son solo para errores de sistema de archivos, con tope de 5 intentos y espera exponencial de hasta 5 segundos. Un archivo inexistente o una entrada inválida no se reintentan.
17. El reporte se guarda con temporal y renombrado. Si todos los intentos fallan, no queda archivo ni línea de auditoría.
18. Los logs llevan prefijo de módulo, nombre de archivo sin ruta, conteos y números de fila. No llevan montos, referencias ni valores rechazados.

## Tiempo

19. Los minutos por partida (1.5) y por caso de revisión (3.0) son supuestos puestos por mí para tener un ejemplo de cuenta. No provienen de una medición. Solo el tiempo del motor es medido.
