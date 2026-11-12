# Diagrama de flujo

```mermaid
flowchart TD
    A[Archivos de entrada: banco.csv y contable.xlsx] --> B[Validar extensión, tamaño y columnas]
    B --> C[Calcular SHA-256 de cada archivo y clave de corrida]
    C --> D{¿La clave ya está en la auditoría<br/>y el reporte existe?}
    D -- Sí --> Z[Omitir: no se duplica nada]
    D -- No --> E[Leer filas y rechazar las inválidas]
    E --> F[Apartar abonos duplicados del banco]
    F --> G[R1 exacta: referencia, monto y fecha]
    G --> H[R2 tolerancia: monto y fecha dentro de rango]
    H --> I[R2B sin referencia: monto igual, fecha cercana]
    I --> J[R3 uno a muchos: suma de documentos del mismo cliente]
    J --> K{Confianza de cada propuesta}
    K -- "mayor o igual al umbral automático" --> L[Conciliada]
    K -- "entre umbrales, empate o duplicado" --> M[Cola de revisión humana]
    K -- "sin propuesta" --> N[Pendiente]
    L --> O{¿Ensayo?}
    M --> O
    N --> O
    O -- Sí --> P[Mostrar resumen, no escribir nada]
    O -- No --> Q[Escribir reporte Excel de forma atómica,<br/>con reintentos acotados]
    Q --> R[Agregar línea encadenada al registro de auditoría]
```

Cada regla trabaja solo con las partidas que las anteriores dejaron libres. Un documento nunca se usa dos veces. Cuando dos candidatos distintos empatan, el motor no elige: manda el caso a la cola de revisión y deja libres los documentos.
