# XTX R7: entrada transitoria y revisión

La pantalla de 確定申告 permite introducir 利用者識別番号, マイナンバー y 生年月日,
pagadores, retenciones, primas, donaciones municipales, período de actividad,
doce meses de 売上 y saldos iniciales explícitos. El nombre, dirección,
フリガナ, código postal, profesión y 税務署 se consultan en el perfil: corregirlos
allí evita usar una identidad distinta del borrador.

## Privacidad y contrato HTTP

- `GET /api/v1/filing/{draft_id}/xtx/context`: perfil sin identificadores completos.
- `POST /api/v1/filing/{draft_id}/xtx/review`: devuelve estado XSD y códigos de pendientes;
  no devuelve XML ni valores de identidad.
- `POST /api/v1/filing/{draft_id}/xtx`: recalcula y valida otra vez antes de descargar.
  Devuelve 409 mientras falte cualquier requisito o la revisión de presentación del generador.
- Los errores 422 no incluyen el cuerpo recibido. Respuestas del router con `Cache-Control: no-store`.
- La revisión usa proyección contable sin persistencia. Una prueba compara todas las
  tablas antes y después de revisar e intentar descargar.
- El formulario usa memoria/DOM durante su montaje: no localStorage, sessionStorage ni
  caché de consultas. Cerrar o cambiar de borrador lo vacía. Editar invalida el informe
  y aborta la solicitud anterior; una respuesta tardía no vuelve a habilitar la descarga.
- Vacío significa desconocido. Los ceros mensuales deben introducirse; el balance inicial
  cero exige marcar una confirmación explícita. No se cargan ejemplos ficticios en el producto.

## Casos fiscales añadidos

Las primas netas y su parte fuera de 年末調整 se emiten en las casillas oficiales
ABH00215–ABH00265, conservando el desglose antiguo/nuevo, 介護医療 y 個人年金.
La deducción calculada desde certificados debe coincidir con la ya contabilizada.
Se comprueban tramos, límites, fracciones de yen y elección de contratos antiguos.
La combinación de terremoto y daño antiguo requiere contratos distintos elegibles.

Cada 自治体 de ふるさと納税 se conserva en una continuación de 第二表; ABI00240
recibe una sola vez el total para 住民税. Se concilia el 控除 después del suelo de
2.000 yenes y del límite del 40% del ingreso. Incluir todas las donaciones, también
las declaradas previamente por ワンストップ特例.

Fuentes oficiales consultadas el 6 de noviembre de 2026:

- [NTA 1140: primas antiguas/nuevas](https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1140.htm).
- [Formulario R7 y redondeo de fracciones](https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2025bun_04.pdf).
- [NTA 1145: 地震保険料 y contratos antiguos](https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1145.htm).
- [NTA 1155: donaciones y casilla obligatoria de 住民税](https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/1155.htm).

## XSD, CI y Docker

Instalar `pip install -e ".[dev,etax]"`. Configurar `ETAX_OFFICIAL_XSD` con la ruta
local de `RKO0010-250.xsd` dentro del árbol oficial completo, manteniendo sus includes.
Sin árbol o sin validador, el informe deja constancia del fallo y no descarga.
La imagen Docker instala el extra `etax`. El árbol se monta en solo lectura;
no se incluye ninguna declaración ni base de datos en la imagen.

La acción `.github/actions/official-xsd` descarga el CAB público KSK2 y exige SHA-256
`48dc25a89a2b82a2b629f021e1779240cb2fe9f7e0c173e23239793feb4dfb55`.
Un cambio del proveedor requiere revisar el nuevo paquete, nunca saltar la comprobación.
El contenedor de los XSD se normaliza a un nombre ASCII antes de exportar rutas:
el CAB usa nombres Shift-JIS que no sobreviven intactos a `GITHUB_ENV` en Linux.
La primera ejecución de CI detectó este defecto de empaquetado y se corrigió sin
modificar el contenido de los esquemas.
CI valida el catálogo de 692 definiciones y los documentos sintéticos con lxml.
Docker smoke crea PostgreSQL y volúmenes exclusivos del run, aplica migraciones,
revisa el XTX sintético vía HTTP contra el XSD montado y exige 409 en la descarga.
También comprueba el proxy frontend y la persistencia tras recrear el backend.
El script rechaza una base con contribuyentes existentes y requiere activación explícita de CI.

## Límites que mantienen cerrada la descarga

El XSD verifica estructura, no todos los requisitos para presentar. La revisión visual
de casillas/importes en las páginas oficiales sigue pendiente. El reconocimiento previo
del XML base por el visor no valida las nuevas continuaciones de donaciones y seguros.
Ningún parámetro del navegador ni variable de entorno permite omitir este bloqueo.

Continúan pendientes los anexos de 医療費, 扶養, 配偶者 y otros 控除 personales;
depreciaciones, salarios, intereses y alquileres detallados del negocio; 白色申告;
otros ingresos y clasificación de 税額控除. Cuando corresponden, se enumeran como
pendientes; las pruebas exigen que no se trate la declaración como lista.
Las devoluciones requieren verificar la cuenta bancaria; pérdidas y compras de
mercancía señalan los anexos de compensación/existencias pendientes.
Todavía no se valida el checksum de マイナンバー: el formato de doce dígitos por sí solo
no acredita un identificador válido. Los números de prueba son exclusivamente sintéticos.

R8/2026 permanece bloqueado: la ampliación de 新生命保険料 de ese ejercicio no se aplica
al cálculo R7. [El aviso oficial](https://www.e-tax.nta.go.jp/topics/2026/topics_20261030_shiyo.htm)
prevé los XSD definitivos para el 25 de noviembre de 2026 y recepción desde el 4 de enero de 2027.

## Evidencia local

- Suite completa backend: 603 PASS, 4 SKIP; anterior a seis nuevos casos negativos y
  correcciones de texto de revisión. Los resultados posteriores dirigidos se registran
  por separado, sin sumar suites solapadas.
- Prueba dirigida posterior: 87 PASS y dos fallos del texto antiguo del aviso ZIP.
  Se corrigió el aviso sin debilitar la comprobación: el reintento de los dos casos
  y dos pruebas adicionales del paquete terminó con 4 PASS.
- Frontend: 104 PASS, lint y build correctos.
- UI real con base sintética aislada: identidad, pagador, dos primas, doce meses y
  balance cero; `XSD oficial: válido` y descarga bloqueada por revisión pendiente.
- Docker local: no hay motor activo. La evidencia Docker aplicable procede del
  workflow aislado del commit publicado, no de una ejecución en esta máquina.

Consultar los runs del commit en [GitHub Actions](https://github.com/jokken79/Kakuteishinkoku2026-public/actions).
