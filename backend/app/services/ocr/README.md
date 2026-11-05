# Servicio OCR de recibos (Fase 2 + "OCR al limite")

Pipeline multi-proveedor que lee un recibo japones (レシート/領収書) y propone un
仕訳 (asiento contable) candidato. Arquitectura con on/off por proveedor y
consentimiento explicito para que el dato salga (o no) del equipo.

```
image_bytes
  -> preprocess_image()           (deskew/CLAHE/denoise/binarizacion/upscale; OpenCV, opt-out)
  -> provider.extract()           (cadena con fallback + consentimiento)
  -> parse_receipt()              (date / amount / tax_rate / reg_number / vendor)
  -> validate_receipt()           (cuadre aritmetico; 税≈base*rate; fecha; checksum; score)
  -> [post-correccion LLM]        (opt-in: si el cuadre falla, 1 reintento con el error)
  -> [ensemble / consensus]       (opt-in: 2do voto campo a campo si bloquea/baja confianza)
  -> 勘定科目 (classifier)         (reusa vendor_mapping del seed)
  -> Transaction + JournalEntry candidato  (status SIEMPRE pending; nunca auto-registra)
```

## Modulos

| Archivo | Rol |
|---|---|
| `base.py` | Contrato comun: `OcrRawResult`, `OCRProvider` (ABC), `sends_data_externally`. |
| `preprocess.py` | **Preproceso de imagen** (OpenCV+Pillow, import lazy): deskew, CLAHE, denoise, binarizacion (Otsu), upscale ×2 condicional. Degrada con gracia si falta OpenCV. |
| `structured.py` | **Structured output** compartido por los providers LLM: schema Pydantic `ReceiptStructured`, JSON-Schema para la API, prompt few-shot JP anti-alucinacion, parseo robusto y **confianza derivada** (no fija). |
| `ensemble.py` | **Voto campo a campo** entre dos parseos (consensus): campos que coinciden -> alta confianza; discrepan -> dudoso/pending. |
| `providers/` | `paddle`, `azure`, `google`, `gemini`, `glm`, `fake`. Imports **lazy**: el modulo carga aunque la lib no este instalada. |
| `parsers/` | Logica **pura** sobre `raw_text`: `date`, `amount`, `tax_rate`, `reg_number` (+checksum), `vendor`, y `parse_receipt`. |
| `classifier.py` | Sugiere 勘定科目 reusando `app.seed.vendor_mapping.classify_vendor`. Hook `MLAccountClassifier` para el ML futuro. |
| `registry.py` | Factory: resuelve proveedores segun `enabled` + disponibilidad + consentimiento. |
| `pipeline.py` | Orquesta preproceso -> extract -> parse -> validacion -> (post-correccion) -> (ensemble) -> 仕訳 candidato. |

## Proveedores y free tiers

| Proveedor | Local/Cloud | `sends_data_externally` | Free tier | Dependencia |
|---|---|---|---|---|
| **PaddleOCR PP-OCRv5** | Local | `false` | Gratis (Apache 2.0, datos no salen) | `paddlepaddle paddleocr` |
| **Azure Document Intelligence** | Cloud | `true` | **F0: 500 pag/mes** | `azure-ai-documentintelligence` |
| **Google Document AI** | Cloud | `true` | **~1000 pag/mes** | `google-cloud-documentai` |
| **Gemini Vision** (structured) | Cloud | `true` | **~1.500 req/dia gratis** (Gemini 3 Flash), alta precision JP | `google-genai` |
| **GLM-OCR (Z.AI)** | Cloud **o** Local | `true` (API) / `false` (Ollama) | API Z.AI (`ZAI_API_KEY`) o **Ollama local $0** | ninguna (HTTP) |
| **fake** | Local | `false` | — (solo tests/dev) | ninguna |

## "OCR al limite" — como exprimir la precision

El research `research/05-ocr-al-limite.md` ordena las palancas por impacto:

1. **Preproceso** (`preprocess.py`, mayor salto): se aplica a TODOS los providers
   antes de `extract()`. On por defecto (`OCR_PREPROCESS_ENABLED=true`). Si OpenCV
   no esta instalado, NO crashea: usa la imagen original y loggea el motivo.
2. **Structured output** (`structured.py`): los providers LLM (Gemini/GLM) piden un
   JSON tipado con few-shot JP (doble tasa 8/10%, インボイス T+13) e instrucciones
   anti-alucinacion ("null si no se lee, NO inventar; texto literal de respaldo").
   La confianza es **derivada** (penaliza notas dudosas y campos null), no 0.9 fija.
   El LLM **propone**; `parse_receipt` + el cuadre aritmetico **verifican**.
3. **Ensemble** (`OCR_ENSEMBLE_ENABLED=true`, opt-in): si la validacion bloquea o la
   confianza es baja, corre un 2do provider de la cadena y vota campo a campo.
   Discrepancias -> `pending`. Respeta el consentimiento (la cadena ya esta filtrada).
4. **Post-correccion** (`OCR_POSTCORRECTION_ENABLED=true`, opt-in): si el cuadre
   aritmetico falla con un provider LLM, un **solo** reintento mostrandole el error.

### Instalar el preproceso (OpenCV + Pillow)

Tienen wheels para Python 3.12-3.14 (probado con `opencv-python-headless 4.13` y
`numpy 2.4` en 3.14):

```powershell
.\.venv\Scripts\python.exe -m pip install opencv-python-headless pillow numpy
```

Si no se instala, el preproceso queda `off` y el pipeline sigue andando con la
imagen original (degradacion con gracia, sin romper nada).

## OCR local privado (datos NO salen) — venv Python 3.12/3.13

PaddlePaddle y los SDK de vision **no soportan Python 3.14**. Para el OCR local
(PaddleOCR), usar un **venv dedicado con Python 3.12 o 3.13**:

```powershell
# venv dedicado para el OCR local (Paddle no anda en 3.14)
py -3.12 -m venv .venv-ocr
.\.venv-ocr\Scripts\Activate.ps1
pip install paddlepaddle paddleocr pillow numpy opencv-python-headless
```

La primera ejecucion descarga los modelos PP-OCRv5 a la cache local (una vez).
`is_available()` solo chequea que `paddleocr` se pueda importar; si falta, reporta
el comando de instalacion sin crashear.

> **Nota**: el preproceso (`opencv-python-headless` + `pillow`) **si** anda en
> 3.14 — instalalo en el venv principal. Lo unico que exige venv 3.12/3.13 es
> PaddleOCR (y el modo GLM-via-Ollama no necesita Python: corre fuera del proceso).

## Activar Gemini (key gratis, ~1.500 req/dia)

1. Sacar la key gratis en https://aistudio.google.com/apikey (sin tarjeta).
2. `pip install google-genai`.
3. Config (env / `.env`):

```bash
ALLOW_EXTERNAL_OCR=true            # consentimiento (el dato sale del equipo)
OCR_GEMINI_ENABLED=true
OCR_GEMINI_API_KEY=<api-key>
OCR_GEMINI_MODEL=gemini-3-flash    # opcional (default gemini-3-flash)
```

Usa **structured output** (JSON tipado + few-shot JP + anti-alucinacion). En
cuanto la key este configurada, el provider opera; sin key, `is_available()` es
`false` con instrucciones.

## Activar GLM-OCR (Z.AI API o Ollama local)

GLM-OCR (Z.AI, 0.9B) es #1 en OmniDocBench / Receipt-KIE. **Dos modos**, auto-
detectados:

**Modo A — API Z.AI (cloud, el owner ya tiene `ZAI_API_KEY`)**: el dato sale del
equipo, requiere consentimiento.

```bash
ALLOW_EXTERNAL_OCR=true
OCR_GLM_ENABLED=true
OCR_GLM_API_KEY=<zai-key>          # o reutiliza ZAI_API_KEY del entorno (alias)
OCR_GLM_API_URL=https://api.z.ai/api/paas/v4/chat/completions   # opcional
OCR_GLM_MODEL=glm-ocr              # opcional
```

**Modo B — Ollama local (privado, $0, el dato NO sale)**:

```powershell
# 1. Instalar Ollama (https://ollama.com) y bajar el modelo
ollama pull glm-ocr        # o el tag GLM-OCR vigente
# 2. No hace falta API key; el provider detecta Ollama en :11434
```

```bash
OCR_GLM_ENABLED=true
OCR_GLM_OLLAMA_URL=http://localhost:11434   # opcional (default)
# (sin OCR_GLM_API_KEY -> usa Ollama; sends_data_externally=false)
```

Si hay `OCR_GLM_API_KEY`/`ZAI_API_KEY` se usa la **API Z.AI** (external=true); si
no, se intenta **Ollama local** (external=false). Tambien usa structured output.

## Modelos VLM afinados en recibos japoneses (opcional, local)

El provider `ollama` acepta **cualquier** VLM servido por Ollama, asi que se le
puede enchufar un modelo afinado especificamente en recibos japoneses de celular
en lugar de un VLM generalista:

```bash
OCR_OLLAMA_ENABLED=true
OCR_OLLAMA_MODEL=<tag-del-modelo-en-ollama>
```

De la linea de trabajo publicada sobre el dataset **Japanese-Mobile-Receipt-OCR**
(~1.300 recibos japoneses reales fotografiados con celular, 34.727 anotaciones de
texto) salieron dos modelos publicos en Hugging Face, ambos derivados de bases
Apache-2.0 y con salida JSON estructurada:

- `sabaridsnfuji/Japanese-Receipt-VL-3B-JSON` (base Qwen2.5-VL-3B)
- `sabaridsnfuji/Japanese-Receipt-VL-lfm2-450M` (chico, para CPU)

El **dataset en si no esta publicado como descarga**: el paper y las model cards
lo describen, pero lo que se puede bajar son los pesos, no las 1.300 imagenes.
Para usarlos aca hay que convertirlos a GGUF e importarlos a Ollama (`ollama
create`), o servirlos por un endpoint compatible. Sea cual sea el modelo, el
pipeline no le cree: `parse_receipt` + la validacion aritmetica siguen siendo el
arbitro anti-alucinacion, y el recibo igual nace `pending`.

## Aprendizaje 取引先 -> 勘定科目

`app/services/vendor_rules.py` guarda lo que el usuario confirma: al confirmar un
recibo (aceptando o corrigiendo el 科目), se refuerza una `VendorAccountRule` con
la clave normalizada del 取引先 (NFKC, sin espacios ni 株式会社), y la proxima foto
de esa misma tienda ya llega con el 科目 correcto propuesto
(`account_source == "learned"`).

El aprendizaje es visible y reversible: `GET /api/v1/receipts/vendor-rules` lista
las reglas y `DELETE /api/v1/receipts/vendor-rules/{id}` borra la que quedo mal.

## Configurar las otras nubes (Azure / Google)

```bash
# Azure (F0: 500 pag/mes)
OCR_AZURE_ENABLED=true
OCR_AZURE_ENDPOINT=https://<recurso>.cognitiveservices.azure.com/
OCR_AZURE_KEY=<api-key>

# Google Document AI (~1000 pag/mes)
OCR_GOOGLE_ENABLED=true
OCR_GOOGLE_PROJECT_ID=<gcp-project>
OCR_GOOGLE_LOCATION=us
OCR_GOOGLE_PROCESSOR_ID=<processor-id>
GOOGLE_APPLICATION_CREDENTIALS=<ruta-al-service-account.json>
```

## Prender/apagar proveedores y cadena de fallback

```bash
OCR_PADDLE_ENABLED=true            # flag on/off por proveedor
OCR_PRIMARY=paddle                 # proveedor primario
OCR_FALLBACK_CHAIN=["paddle","gemini"]   # JSON (orden de preferencia)
```

Reglas de resolucion (`registry.resolve_chain`):

1. Se respeta el flag `enabled` por proveedor.
2. Se exige `is_available()` (SDK instalado + credenciales presentes).
3. Si `allow_external_ocr=false`, se **excluyen** los proveedores cloud
   (`sends_data_externally=true`): el dato no sale del equipo sin consentimiento.

El endpoint `GET /api/v1/ocr/providers` expone el estado de cada proveedor
(`enabled` / `available` / `sends_data_externally` / `usable` / `reason`) para el
toggle on/off del frontend.

## Seguridad / 電帳法

- La imagen original se archiva como `Evidence` con **hash SHA-256**, timestamp y
  los indices de busqueda 日付/金額/取引先 (検索要件).
- **Nunca se auto-registra**: toda transaccion de OCR nace `pending`. Si el cuadre
  aritmetico falla o el 登録番号 no valida su checksum, queda bloqueada para
  revision humana (`validation.is_blocking = true`).

## Tests (sin dependencias externas)

`FakeOCRProvider` devuelve un recibo japones sintetico determinista (doble tasa
8%/10%, 登録番号 con checksum valido). Cubre parsers, clasificador, pipeline,
fallback chain, consentimiento y los endpoints.

```bash
pytest tests/test_ocr_parsers.py tests/test_ocr_pipeline.py tests/test_ocr_endpoint.py -v
pytest tests/ocr/ -v                      # "al limite": preprocess/structured/glm/ensemble
```

## Golden accuracy field-level (medir precision)

`tests/fixtures/ocr/golden/` tiene ~10 recibos sinteticos con ground truth
(`raw.txt` + `expected.json`): termico simple, doble tasa 8/10%, インボイス con/sin
登録番号, fecha 令和 (kanji y abreviada R6.7.20), seireki, 手書き simulado, checksum
invalido, una sola tasa 税込.

```bash
# Imprime la tabla field-level (date/金額/取引先/内訳/登録番号 % exact-match)
pytest tests/ocr/test_golden_accuracy.py -s -q
```

La tabla mide el techo de los **parsers de dominio** (la validacion cruzada del
LLM). Es el **harness para medir cualquier provider real** en cuanto haya key:
basta reemplazar la cadena `FakeOCRProvider` por el provider con credencial y
correr el mismo test. Hoy, sobre los sinteticos: **100%** en los 5 campos y
**100%** de cuadre aritmetico (10/10).
