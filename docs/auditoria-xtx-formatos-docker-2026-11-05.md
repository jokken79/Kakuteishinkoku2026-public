# Verificación e-Tax, formatos 2026 y Docker — 2026-11-05

## Estado del XTX

La descarga continúa bloqueada con `409 xtx_xsd_not_verified` y el ZIP no incluye
XTX. El generador real ahora usa `DATA/RKO0010/CATALOG/CONTENTS/IT`, referencias
ID/IDREF y RDF, KOA020 第一表・第二表 y KOA210 (cuatro páginas). Su salida de
prueba pasa el XSD oficial; esto no acredita aptitud fiscal general ni aceptación.
La integración de entrada de identidad/detalles en la interfaz de descarga sigue
pendiente: el constructor recibe esos datos de forma explícita y transitoria.

## Fuente oficial vigente

El [catálogo vigente](https://www.e-tax.nta.go.jp/shiyo/ksk2/ksk2_shiyo3.htm)
corresponde al sistema renovado el 24 de septiembre de 2026. Se descargó su
`e-tax19.CAB` del 28 de agosto de 2026, SHA-256
`48dc25a89a2b82a2b629f021e1779240cb2fe9f7e0c173e23239793feb4dfb55`.
Los XSD y documentos originales permanecen fuera del repositorio público.

`RKO0010-250.xsd` admite las versiones 25.0.0 y 25.0.1. Los esquemas de KOA020
23.0, KOA210 11.0, IT y el vocabulario general son idénticos a los del paquete
anterior comprobado. La prueba se repitió contra el paquete vigente completo.

`xtx_fields_r7.json` contiene 692 definiciones de las seis páginas utilizadas:
ruta, orden, tipo, etiqueta y límite de repetición. El verificador compara todas
con el XSD y comprueba sus hashes. Son metadatos estructurales, no 692 casos
fiscales ya implementados. Se prueban también las 28 constantes monetarias ABB
existentes en un control estructural independiente.

## Implementación y pruebas

- El identificador e-Tax, el マイナンバー y el nacimiento se suministran al
  constructor; no se recupera el número enmascarado ni se inventan datos. Los
  campos personales están excluidos de `repr` y la salida XML no se registra.
- La oficina se concilia con el perfil: la tabla oficial `zeimusho.xsd` asigna
  `06127` a 津島. Una oficina distinta se rechaza aunque su código pase el XSD.
- Las referencias de identidad se emiten desde IT. El RDF referencia IT, KOA020
  y KOA210 y se comprueba además del XSD (que permite RDF vacío).
- Los pagadores se distribuyen en grupos de cuatro por 第二表; sus ingresos y
  retenciones se concilian y el total global no se duplica en cada página.
- Se incluyen los detalles explícitos de 社会保険料 e iDeCo y el subtotal de
  deducciones. Un crédito fiscal agregado no se supone automáticamente de vivienda.
- KOA210 incluye período explícito, gastos por casilla o cuenta adicional con su
  nombre, ventas mensuales y clientes, y balance inicial/final. El 事業主貸 se
  reclasifica al activo con su signo fiscal y se comprueba el balance.
- `build_xtx_document` devuelve requisitos pendientes y mantiene
  `ready_for_submission=False`. Los casos no cubiertos se indican: otras
  deducciones/anexos, créditos sin distribución, detalles de depreciación,
  salarios, intereses y alquileres, cuentas no clasificadas, períodos parciales
  no conciliados y 収支内訳書 de 白色. No se autoriza su presentación.
- El validador XSD formal rechaza entidades, referencias rotas, RDF incompleto y
  esquemas/años no verificados. Sus mensajes no reproducen valores personales
  contenidos en errores de lxml.

Se usan únicamente fixtures sintéticas y SQLite en memoria. No se ha abierto
ninguna base ni documento personal durante esta implementación.

Reproducción, tras descargar y extraer el CAB conservando directorios:

```powershell
cd backend
pip install -e ".[dev,etax]"
python ../tools/verify_official_xtx.py RUTA/shotoku/RKO0010-250.xsd
$env:ETAX_OFFICIAL_XSD = "RUTA/shotoku/RKO0010-250.xsd"
pytest tests/test_xtx_document.py tests/test_xtx_envelope.py tests/test_etax_validator.py -q
```

El código 0 del verificador acredita sus comprobaciones estructurales; imprime
por separado que la presentación sigue bloqueada. La prueba XSD opcional de
pytest se omite cuando no se proporciona el árbol oficial local.

La suite completa del estado inicial terminó: 563 PASS, 4 SKIP, 582,23 s. Las
pausas largas proceden, entre otros casos, de comprobaciones de proveedores OCR;
las ejecuciones interrumpidas anteriores no demostraban un bloqueo. La suite
final terminó con 576 PASS, 4 SKIP y 8 avisos en 474,51 s. Tras el ajuste de
la oficina se repitieron 33 pruebas dirigidas con el XSD vigente: 33 PASS.
Ruff pasó y mypy no encontró problemas en 120 archivos.

## Comprobación del visor oficial

La [función oficial de visualización sin iniciar sesión](https://www.e-tax.nta.go.jp/e-taxsoftweb/e-taxsoftweb.htm)
se abrió desde el sitio oficial. El navegador de pruebas obtuvo una página sin
selector de archivo porque la web falla al cargar `dojo.nls.etaxweb_dlparts_es`.
No se cargó ni transmitió ningún archivo y no se inició sesión. La prueba de
apertura/importación sigue UNVERIFIED. Mostrar un documento tampoco equivale a
que una declaración haya sido aceptada.

## Formatos 令和8年分

El [aviso oficial del 30 de octubre](https://www.e-tax.nta.go.jp/topics/2026/topics_20261030_shiyo.htm)
indica que las especificaciones y el XSD definitivos para la recepción desde
el 4 de enero de 2027 se publicarán previsiblemente el 25 de noviembre de 2026.
A fecha de esta revisión, son borradores sujetos a cambios. No se utiliza el
esquema de 2025 para habilitar exportaciones del ejercicio 2026.

## Docker

El motor Docker de este equipo no respondió. En su lugar se ejecutó [un smoke aislado en GitHub Actions](https://github.com/jokken79/Kakuteishinkoku2026-public/actions/runs/41984169667): build de imágenes, inicio de PostgreSQL y servicios, migración Alembic de una base vacía, consulta de health y onboarding a través de nginx, y persistencia de un archivo sintético al recrear el backend. Resultado: **PASS**. El ejecutor y sus volúmenes temporales se eliminaron al terminar; no se usaron archivos ni bases personales.

La primera ejecución detectó que PostgreSQL rechazaba una asignación entera a un campo booleano; la migración se corrigió y volvió a pasar en SQLite y PostgreSQL. La configuración integra nginx como proxy `/api`, copia las migraciones y monta un volumen para `backend/data`. La migración se ejecuta explícitamente; haga un respaldo antes de aplicarla a una base existente. No se probó Docker Desktop en este equipo ni la recuperación de una copia de seguridad.
