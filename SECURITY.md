# Seguridad

## Cómo reportar un problema

Si encuentras una vulnerabilidad, repórtala de forma privada desde la pestaña Security de este repositorio, con la opción "Report a vulnerability". Por favor no abras un issue público con los detalles.

## Alcance

Es un proyecto de portafolio que corre en la computadora de quien lo usa. No tiene servidor, cuentas de usuario ni acceso a internet.

- Todos los datos son sintéticos y genéricos. No hay información de ningún banco ni de sus clientes.
- No hay credenciales en el código. Los parámetros se leen de variables de entorno `CONC_*`.
- Las entradas se validan: extensión permitida, tamaño máximo, número máximo de filas, columnas obligatorias y tipos de cada campo. Las filas inválidas se rechazan y se cuentan.
- No se usa `eval`, `exec` ni `subprocess`. Las rutas se manejan con `pathlib`.
- El reporte Excel antepone un apóstrofo a cualquier texto que empiece con `=`, `+`, `-` o `@`, para que no se interprete como fórmula.
- Los logs registran conteos y nombres de archivo, nunca rutas completas, montos ni referencias.
- El registro de auditoría encadena cada línea con el hash de la anterior para detectar ediciones.
- Las dependencias están fijadas a una versión y Dependabot las revisa cada semana. Las acciones de GitHub están fijadas a un commit.
