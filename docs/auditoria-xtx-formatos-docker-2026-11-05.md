# Verificación e-Tax, formatos 2026 y Docker — 2026-11-05

## XTX

La especificación oficial [e-Tax: listado de esquemas](https://www.e-tax.nta.go.jp/shiyo/shiyo3.htm) ofrece `e-tax19.CAB` (XMLスキーマ, actualizado el 18 de mayo de 2026). El esquema del procedimiento `shotoku/RKO0010-250.xsd` declara `DATA` con namespace `http://xml.e-tax.nta.go.jp/XSD/shotoku`, `RKO0010` versión 25.0.0, `CATALOG` y `CONTENTS`; dentro de `CONTENTS` se requieren `IT` y el formulario. El `IT` requiere `ZEIMUSHO`, `NOZEISHA_ID`, `NOZEISHA_NM`, `NOZEISHA_ADR` y `TETSUZUKI`. El generador heredado no tiene ese sobre y emite referencias como valores planos; además, sus casillas deben anidarse según `KOA020-023.xsd`.

Se descargó el CAB oficial en una carpeta aislada, se compiló su esquema con lxml y se validó un borrador sintético creado en SQLite en memoria. Resultado: **FAIL**, raíz `DATA` sin namespace reconocido. Un XML sintético vacío con el sobre requerido pasó el mismo XSD como control; no contiene importes y no representa una declaración presentable. Una ejecución inicial del script cargó por error la semilla del proyecto privado por una instalación editable; solo se usó en SQLite en memoria, sin guardarla ni transmitirla. Se corrigió la prioridad de importación y se repitió con la semilla sintética. El validador interno anterior solo verifica una estructura propia, no conformidad XSD.

La descarga XTX y la validación que podría confundirse con conformidad están bloqueadas con `409 xtx_xsd_not_verified`; el ZIP no incluye XTX. El generador heredado se conserva para análisis y no debe emplearse para presentar. El CSV es un resumen de referencia, no un formato e-Tax validado. El esquema oficial contiene un grupo `KOA210` versión 11; no se ha comprobado su aplicabilidad para cada ejercicio.

Para reproducir: instale lxml en un entorno aislado, descargue y descomprima el CAB oficial conservando sus directorios y ejecute desde `backend`: `python ../tools/verify_official_xtx.py RUTA/shotoku/RKO0010-250.xsd`. Devuelve código 1 si falla.

Pendiente: implementar el sobre y sus referencias, capturar sin inventar la 利用者識別番号 y la oficina fiscal que requiere el esquema, verificar estructura y mapeo de cada casilla, y validar ejemplos sintéticos positivos y negativos contra el XSD completo. Conformidad XSD por sí sola no confirma aceptación o corrección tributaria.

## Formatos 令和8年分

La [página oficial de 国税庁](https://www.nta.go.jp/taxes/shiraberu/shinkoku/kakutei.htm) enlaza al [PDF 令和8年分](https://www.nta.go.jp/taxes/shiraberu/shinkoku/pdf/0026006-063.pdf) e indica que podría cambiar. La copia descargada el 5 de noviembre coincide con la referencia local (SHA-256 `490e198aaf9df19e676f7f387bd884798d153de7284baa864398a815bd6f8579`). Se revisó visualmente su portada de 32 páginas: está marcada 案 y anuncia uso desde enero de 2027. No se verificaron todos los campos, posiciones, decisiones fiscales o formatos electrónicos de 2026; la exportación de presentación para 2026 permanece bloqueada. Los formularios de 年末調整 2026 tienen funciones independientes y sus borradores siguen siendo parciales.

## Docker

`docker compose config --quiet` pasó. Docker Desktop no ofreció un motor disponible después del intento de inicio; por lo tanto, no se ejecutaron contenedores, migraciones en PostgreSQL ni pruebas de red o persistencia de Docker. La configuración debe probarse en un proyecto y volúmenes aislados antes de declararse operativa.

La revisión estática detectó que el contenedor backend no copia ni ejecuta migraciones Alembic; el servicio frontend utiliza `vite preview` sin configuración de proxy `/api`; y `backend/data` no está montado como volumen persistente. Estos puntos no se han comprobado en ejecución y requieren corrección y prueba aislada.
