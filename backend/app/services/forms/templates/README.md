# 様式 oficiales del NTA (令和7年分) — base del overlay

Estos PDF son los **formularios oficiales en blanco** del 国税庁 (NTA). El módulo
`overlay.py` estampa los valores calculados SOBRE ellos para producir el documento
oficial real (para 郵送), en vez de dibujar una réplica.

> ⚠️ Versionados a propósito: el overlay no funciona sin ellos. No borrar.

## Archivos

> ⚠️ Los códigos `FAxxxx` impresos en cada PDF son el identificador FIABLE del
> formulario (las etiquetas del índice HTML son ambiguas). Verificados por
> contenido renderizado, NO por el número de archivo del NTA.

| Archivo | Contenido | Código | Páginas | Rotación |
|---|---|---|---|---|
| `r07_01.pdf` | 確定申告書 第一表 (p0) + 第二表 (p1) + 控用 (p2,p3) | FA2205 | 4 | 0° |
| `r07_02.pdf` | 第三表 等 (分離課税) | — | 2 | — |
| `r07_kessansho.pdf` | **青色申告決算書（一般用）** P1損益(p0)〜P4貸借(p3) + 控用(p4-7) | FA3001 | 8 | 90° |
| `r07_05.pdf` | 収支内訳書（一般用, 白色） | FA7050 | 4 | 90° |
| `r07_09.pdf` | 収支内訳書（不動産所得用） | FA7200 | 4 | 90° |
| `r08_fuyo.pdf` | 令和8年分 給与所得者の扶養控除等（異動）申告書 | — | 2 | 0° |

`r08_fuyo.pdf` procede de [国税庁](https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_01_input.pdf).
Se retiraron los widgets de entrada vacíos para permitir la superposición; el contenido
impreso de la plantilla permanece. La app emite un borrador parcial para revisión,
no un formulario completamente validado ni presentado.

## Origen (descargados de nta.go.jp)

Índice: https://www.nta.go.jp/taxes/shiraberu/shinkoku/syotoku/r07.htm
Ruta: `.../yoshiki/01/shinkokusho/pdf/r07/NN.pdf`

- `r07_01.pdf` ← `01.pdf`
- `r07_02.pdf` ← `02.pdf`
- `r07_kessansho.pdf` ← `10.pdf` (青色申告決算書 一般用 — confirmado por FA3001)
- `r07_05.pdf` ← `05.pdf` (収支内訳書 一般用)
- `r07_09.pdf` ← `09.pdf` (収支内訳書 不動産用)

> Las etiquetas del WebFetch del índice salieron cruzadas; los archivos se
> re-identificaron descargando varios números y leyendo el código FA del PDF.

## Nota técnica (calibración de coordenadas)

**Cropbox desplazado (第一表):** el cropbox de `r07_01.pdf` NO está en el origen:
`[10.77, 6.29, 577.69, 808.50]`. PyMuPDF `get_text` normaliza al cropbox (origen
0,0 arriba-izq) pero el merge de pypdf usa el sistema nativo del mediabox.
`overlay._draw_layer` corrige ese offset (`crop_left`, `crop_top`). Sin eso, el
texto sale desplazado ~6–11pt.

**Páginas rotadas (決算書 / 収支内訳書):** tienen `/Rotate 90` (mediabox vertical
595×842, mostrado horizontal 842×595). `overlay._draw_field_rotated90` dibuja la
capa en el mediabox sin rotar aplicando `px=vy, py=vx` + `rotate(90)` para que el
texto salga derecho tras el giro de pantalla (verificado con esquinas+centro).
Las coords de los `Field` van en el espacio VISUAL (842×842 top-left, lo que se ve).
⚠️ OJO: `get_drawings` en estas páginas devuelve coords SIN rotar (595×842); al
mapear celdas desde la grilla, convertir a visual con `vx=842−uy, vy=ux`.

Casillas con ceros pre-impresos (se estampan sólo los dígitos significativos):
- 人的控除 ⑰⑲㉑㉓㉔㉕: `0000` (múltiplos de 万) → `monto // 10000`.
- ㉛ 課税所得: `000` (千円未満切り捨て) → `monto // 1000`.
- 52 納める税金: `00` (100円未満切り捨て) → `monto // 100`.

## Estado del mapeo

- `r08_kiso.pdf`: [基礎控除申告書 de 国税庁 2026](https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/gensen/pdf/2026bun_06.pdf), versión en blanco sin campos editables. El renderer `kiso_2026.py` solo rellena datos personales y estimaciones expresas; genera un borrador marcado para revisión. No cubre pérdidas de 副業, ajuste salarial especial ni las secciones de cónyuge y otros familiares.

- ✅ 第一表 (`r07_01.pdf` p0) — completo (`shinkokusho_official.py`).
- ✅ 第二表 (`r07_01.pdf` p1) — 氏名 + 所得の内訳 (事業 + 源泉徴収税額の合計).
  El desglose por póliza de seguros y el detalle de 配偶者・扶養 quedan para una
  pasada con datos por ítem (el 第一表 ya lleva cada importe de 控除).
- 青色申告決算書 一般用 (`r07_kessansho.pdf` FA3001) — se rellenan P1 y P4;
  se incluyen P2 y P3 sin rellenar para revisión manual. Página `/Rotate 90`.
- 収支内訳書 一般用 白色 (`r07_05.pdf` FA7050) — se rellena P1 y se incluye P2
  sin rellenar para revisión manual (`shushi_official.py`).
  Layout espejado (col1 科目|金額, col2 金額|科目). Página `/Rotate 90`.
- `.xtx`: descarga bloqueada; el generador heredado no cumple el XSD oficial.
  El esquema incluye KOA210; falta verificar su uso y generar el 決算書 completo.
