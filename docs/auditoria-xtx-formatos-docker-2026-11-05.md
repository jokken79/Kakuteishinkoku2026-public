# Verificación e-Tax, formatos 2026 y Docker — 2026-11-05

## XTX

La especificación oficial [e-Tax: listado de esquemas](https://www.e-tax.nta.go.jp/shiyo/shiyo3.htm) ofrece `e-tax19.CAB` (XMLスキーマ, actualizado el 18 de mayo de 2026). El esquema del procedimiento `shotoku/RKO0010-250.xsd` declara `DATA` con namespace `http://xml.e-tax.nta.go.jp/XSD/shotoku`, `RKO0010` versión 25.0.0, `CATALOG` y `CONTENTS`; dentro de `CONTENTS` se requieren `IT` y el formulario. El `IT` requiere `ZEIMUSHO`, `NOZEISHA_ID`, `NOZEISHA_NM`, `NOZEISHA_ADR` y `TETSUZUKI`. El generador heredado no tiene ese sobre y emite referencias como valores planos; además, sus casillas deben anidarse según `KOA020-023.xsd`.

Se descargó el CAB oficial en una carpeta aislada, se compiló su esquema con lxml y se validó un borrador sintético creado en SQLite en memoria. Resultado: **FAIL**, raíz `DATA` sin namespace reconocido. Un control sintético vacío y un prototipo que anida los 16 importes del ejemplo pasan el mismo XSD. El prototipo usa identidad y código de oficina ficticios y omite datos y comprobaciones necesarios: no constituye una declaración presentable ni está conectado a las descargas. Una ejecución inicial del script cargó por error la semilla del proyecto privado por una instalación editable; solo se usó en SQLite en memoria, sin guardarla ni transmitirla. Se corrigió la prioridad de importación y se repitió con la semilla sintética. El validador interno anterior solo verifica una estructura propia, no conformidad XSD.

La descarga XTX y la validación que podría confundirse con conformidad están bloqueadas con `409 xtx_xsd_not_verified`; el ZIP no incluye XTX. El generador heredado se conserva para análisis y no debe emplearse para presentar. El CSV es un resumen de referencia, no un formato e-Tax validado. El esquema oficial contiene un grupo `KOA210` versión 11; no se ha comprobado su aplicabilidad para cada ejercicio.

Para reproducir: instale lxml en un entorno aislado, descargue y descomprima el CAB oficial conservando sus directorios y ejecute desde `backend`: `python ../tools/verify_official_xtx.py RUTA/shotoku/RKO0010-250.xsd`. Devuelve código 1 si falla.

Pendiente: implementar el sobre y sus referencias, capturar sin inventar la 利用者識別番号 y la oficina fiscal que requiere el esquema, verificar estructura y mapeo de cada casilla, y validar ejemplos sintéticos positivos y negativos contra el XSD completo. Conformidad XSD por sí sola no confirma aceptación o corrección tributaria.

## Formatos 令和8年分

La [página oficial de 国税庁](https://www.nta.go.jp/taxes/shiraberu/shinkoku/kakutei.htm) enlaza al [PDF 令和8年分](https://www.nta.go.jp/taxes/shiraberu/shinkoku/pdf/0026006-063.pdf) e indica que podría cambiar. La copia descargada el 5 de noviembre coincide con la referencia local (SHA-256 `490e198aaf9df19e676f7f387bd884798d153de7284baa864398a815bd6f8579`). Se revisó visualmente su portada de 32 páginas: está marcada 案 y anuncia uso desde enero de 2027. No se verificaron todos los campos, posiciones, decisiones fiscales o formatos electrónicos de 2026; la exportación de presentación para 2026 permanece bloqueada. Los formularios de 年末調整 2026 tienen funciones independientes y sus borradores siguen siendo parciales.

## Docker

El motor Docker de este equipo no respondió. En su lugar se ejecutó [un smoke aislado en GitHub Actions](https://github.com/jokken79/Kakuteishinkoku2026-public/actions/runs/41984169667): build de imágenes, inicio de PostgreSQL y servicios, migración Alembic de una base vacía, consulta de health y onboarding a través de nginx, y persistencia de un archivo sintético al recrear el backend. Resultado: **PASS**. El ejecutor y sus volúmenes temporales se eliminaron al terminar; no se usaron archivos ni bases personales.

La primera ejecución detectó que PostgreSQL rechazaba una asignación entera a un campo booleano; la migración se corrigió y volvió a pasar en SQLite y PostgreSQL. La configuración integra nginx como proxy `/api`, copia las migraciones y monta un volumen para `backend/data`. La migración se ejecuta explícitamente; haga un respaldo antes de aplicarla a una base existente. No se probó Docker Desktop en este equipo ni la recuperación de una copia de seguridad.


## Revisión adicional: generador XTX

- El esquema oficial `RKO0010-250.xsd` y sus dependencias se compilaron con `lxml`.
  Un control con datos sintéticos y las 28 constantes monetarias ABB del generador
  colocadas en las rutas y orden del XSD pasó la validación estructural. Esta
  comprobación no verifica que los importes, las casillas ni el documento sean
  correctos para una declaración. El catálogo RDF se ha ampliado en el control experimental.
- La salida real de `build_xtx` sigue fallando en la raíz: carece del namespace
  y del sobre `RKO0010`, `CATALOG`, `CONTENTS` e `IT`. El XSD también exige en
  `IT` el identificador `NOZEISHA_ID`; el perfil actual no lo proporciona.
- Según `データ形式等仕様書.docx` del CAB oficial `e-tax01.CAB`, el catálogo
  contiene metadatos RDF de los datos enviados y de los formularios. Pasar el
  XSD con un RDF vacío no acredita que e-Tax acepte el archivo.
- KOA210 figura en el esquema `RKO0010-250.xsd`; se eliminó la afirmación de
  que está retirado. Falta verificar su aplicabilidad y el mapeo completo del
  青色申告決算書, además del 第二表, las referencias, las casillas y las
  condiciones de obligatoriedad. No se ha validado la importación real.
- El validador heredado devuelve siempre `official_xsd_not_validated` como
  error: sus comprobaciones parciales no pueden certificar que un archivo sea
  apto para presentar. La descarga y el XTX en el ZIP siguen bloqueados.

Fuentes oficiales: [especificaciones e-Tax](https://www.e-tax.nta.go.jp/shiyo/shiyo3.htm),
[procedimientos de declaración](https://www.e-tax.nta.go.jp/tetsuzuki/shinkoku/shinkoku01.htm).


## Sobre experimental

El constructor experimental de RKO0010 recibe la identidad explícitamente y añade referencias RDF a IT y KOA020. La identidad no se persiste y las pruebas usan datos sintéticos. El XSD admite el sobre, pero esto no verifica la aceptación por e-Tax. La salida real de `build_xtx` todavía no lo utiliza y sigue bloqueada.

Pendientes: implementar las dos páginas, sus referencias y anexos, validar las reglas fiscales y la integración del identificador y verificar la importación oficial.

El control sintético también añadió un pagador, sus ingresos y retenciones en `KOA020-2`; pasó el XSD. Solo comprueba cuatro elementos estructurales, no la semántica fiscal ni el mapeo de la segunda página.
