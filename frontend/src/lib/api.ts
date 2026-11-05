/**
 * Cliente HTTP del backend de 確定申告 2026.
 *
 * En dev, el proxy de Vite redirige `/api` al backend (`:8200`). Todas las
 * llamadas devuelven datos tipados y lanzan `ApiError` con un mensaje legible
 * (la UI nunca muestra "Error 500" crudo).
 */

const API_BASE = "/api/v1";

export interface YearEndProfile {
  name: string;
  name_kana: string | null;
  address: string | null;
}

export function fetchYearEndProfile(signal?: AbortSignal): Promise<YearEndProfile> {
  return request<YearEndProfile>("/year-end/2026/profile", { signal, cache: "no-store" });
}

/** Error de API con mensaje de dominio (japones) listo para mostrar. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface BackendErrorDetail {
  code?: string;
  message?: string;
  details?: Record<string, unknown>;
}

/** Mapea errores del backend a un mensaje claro en japones. */
function humanizeError(status: number, detail: BackendErrorDetail | string | undefined): ApiError {
  if (typeof detail === "object" && detail?.message) {
    return new ApiError(detail.message, status, detail.code ?? null);
  }
  const fallback: Record<number, string> = {
    400: "入力内容に問題があります。",
    401: "ログインが必要です。",
    403: "このアカウントはこのアプリを利用できません。",
    404: "対象が見つかりませんでした。",
    422: "年度の設定が必要です。",
    503: "OCRサービスが利用できません。",
    500: "サーバーで問題が発生しました。しばらくして再度お試しください。",
  };
  return new ApiError(
    fallback[status] ?? `通信に失敗しました（HTTP ${status}）。`,
    status,
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError("バックエンドに接続できません。", 0, "network");
  }
  if (!response.ok) {
    let detail: BackendErrorDetail | string | undefined;
    try {
      const body = (await response.json()) as { detail?: BackendErrorDetail | string };
      detail = body.detail;
    } catch {
      detail = undefined;
    }
    throw humanizeError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function createManualExpense(payload: {
  year: number; date: string; vendor: string; total_amount: number; account_code: string;
}): Promise<Transaction> {
  return request<Transaction>("/receipts/manual", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}

// --- Tipos del dominio (espejo de los schemas Pydantic) -------------------

export interface HealthStatus {
  status: string;
  service: string;
  version: string;
}

export type ConfidenceLevel = "high" | "low";
export type TransactionStatus = "pending" | "confirmed" | "rejected";

export interface TaxLine {
  base?: number;
  tax?: number;
  rate?: number;
}

export interface Transaction {
  id: string | null;
  date: string | null;
  vendor: string | null;
  total_amount: number | null;
  business_allocation?: { original_total: number; numerator: number; denominator: number; rationale: string } | null;
  registration_number: string | null;
  is_qualified_invoice: boolean;
  confidence: number | null;
  status: TransactionStatus;
  tax_lines: TaxLine[];
  evidence_id: string | null;
  /** 勘定科目 sugerido/elegido (editable en la bandeja). */
  account_code: string | null;
  /** Confianza por campo del OCR (date/vendor/total/...): guia que revisar. */
  field_confidences: Record<string, number> | null;
}

export interface JournalLine {
  side: "debit" | "credit";
  account_code: string;
  amount: number;
  tax_rate: number | null;
}

export interface JournalSuggestion {
  date: string | null;
  description: string;
  lines: JournalLine[];
  account_code: string;
  account_confidence: number;
}

export interface ReceiptResponse {
  transaction: Transaction;
  journal_suggestion: JournalSuggestion;
  confidence: number;
  confidence_level: ConfidenceLevel;
  provider_used: string;
  validation_errors: string[];
  /** La misma foto ya estaba archivada: se devolvio la transaccion existente. */
  duplicate: boolean;
  /** Transaccion que parece ser la misma compra (mismo hash o fecha+金額+取引先). */
  duplicate_of: string | null;
  /** Origen del 科目 propuesto: `learned` = regla aprendida del mismo 取引先. */
  account_source: "learned" | "rule" | "default";
}

/** Regla aprendida 取引先 -> 勘定科目 (memoria del clasificador). */
export interface VendorRule {
  id: string;
  vendor_key: string;
  vendor_sample: string | null;
  account_code: string;
  hits: number;
  last_used_at: string;
}

export interface EvidenceItem {
  id: string;
  transaction_id: string;
  date: string | null;
  amount: number | null;
  vendor: string | null;
  archived_at: string;
  retention_until: string | null;
  source: "ocr" | "csv" | "bank" | "manual";
  status: TransactionStatus;
  file_available: boolean;
}

export interface EvidenceList {
  year: number;
  total_count: number;
  total_amount: number;
  items: EvidenceItem[];
}

export interface EvidenceFilters {
  vendor?: string;
  dateFrom?: string;
  dateTo?: string;
  amountMin?: number;
  amountMax?: number;
}

export interface ProviderStatus {
  name: string;
  enabled: boolean;
  available: boolean;
  sends_data_externally: boolean;
  usable: boolean;
  reason: string | null;
}

export interface ProvidersResponse {
  allow_external_ocr: boolean;
  primary: string;
  fallback_chain: string[];
  providers: ProviderStatus[];
}

/** Uso diario de cuota de un proveedor cloud (free tier). */
export interface ProviderUsage {
  provider: string;
  used_today: number;
  daily_limit: number;
  /** Porcentaje usado (0-100, redondeado). */
  percent: number;
  /** `true` si alcanzo el limite (no-usable hoy). */
  over_limit: boolean;
  /** `true` si supero el umbral de aviso (>=80%) sin frenar aun. */
  warn: boolean;
  /** ISO (UTC) del proximo reseteo (medianoche US/Pacific). */
  resets_at: string;
}

/** Respuesta de `GET /ocr/usage`. */
export interface UsageResponse {
  providers: ProviderUsage[];
}

export interface DeductionBreakdown {
  kiso: number;
  social_insurance: number;
  medical: number;
  life_insurance: number;
  earthquake_insurance: number;
  dependents: number;
  spouse: number;
  ideco: number;
  furusato: number;
  other: number;
}

export interface TaxCalculationResult {
  year: number;
  income_breakdown: { kind: string; label: string | null; amount: number }[];
  total_income: number;
  deduction_breakdown: DeductionBreakdown;
  total_income_deductions: number;
  taxable_income: number;
  income_tax_base: number;
  tax_credits: number;
  income_tax_after_credits: number;
  reconstruction_tax: number;
  total_tax: number;
  withholding_total: number;
  final_amount: number;
}

export interface TaxCalculationInput {
  year: number;
  filing_type: string;
  incomes: { kind: string; revenue?: number; expenses?: number; amount?: number; label?: string }[];
  deductions: Partial<{
    social_insurance: number;
    medical_expenses: number;
    medical_reimbursement: number;
    life_insurance: number;
    earthquake_insurance: number;
    ideco: number;
    furusato: number;
    spouse_deduction: number;
  }>;
  withholding: { withholding_tax?: number; estimated_prepayment?: number };
  tax_credits?: number;
}

// --- Endpoints ------------------------------------------------------------

export function fetchHealth(signal?: AbortSignal): Promise<HealthStatus> {
  return request<HealthStatus>("/health", { signal });
}

export function fetchPendingReceipts(
  year: number,
  signal?: AbortSignal,
): Promise<Transaction[]> {
  return request<Transaction[]>(
    `/receipts?status=pending&year=${year}`,
    { signal },
  );
}

export function fetchReceipts(
  year: number,
  status?: TransactionStatus,
  signal?: AbortSignal,
): Promise<Transaction[]> {
  const params = new URLSearchParams({ year: String(year) });
  if (status) params.set("status", status);
  return request<Transaction[]>(`/receipts?${params.toString()}`, { signal });
}

export function fetchEvidence(
  year: number,
  filters: EvidenceFilters = {},
  signal?: AbortSignal,
): Promise<EvidenceList> {
  const params = new URLSearchParams({ year: String(year) });
  if (filters.vendor) params.set("vendor", filters.vendor);
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  if (filters.amountMin != null) params.set("amount_min", String(filters.amountMin));
  if (filters.amountMax != null) params.set("amount_max", String(filters.amountMax));
  return request<EvidenceList>(`/evidence?${params.toString()}`, { signal });
}

export function evidenceFileUrl(evidenceId: string): string {
  return `${API_BASE}/evidence/${evidenceId}/file`;
}

/** Correcciones opcionales aplicadas al confirmar (confirmacion de 1 toque). */
export interface ReceiptCorrections {
  date?: string;
  vendor?: string;
  total_amount?: number;
  account_code?: string;
}

export function confirmReceipt(
  id: string,
  corrections?: ReceiptCorrections,
): Promise<Transaction> {
  return request<Transaction>(`/receipts/${id}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corrections ?? {}),
  });
}

export function saveBusinessAllocation(
  id: string,
  payload: { expected_total: number; numerator: number; denominator: number; rationale: string },
): Promise<Transaction> {
  return request<Transaction>(`/receipts/${id}/business-allocation`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}

/** Reglas 取引先 -> 勘定科目 que la app aprendio de las confirmaciones. */
export function fetchVendorRules(signal?: AbortSignal): Promise<VendorRule[]> {
  return request<VendorRule[]>("/receipts/vendor-rules", { signal });
}

/** Borra una regla aprendida (el 取引先 vuelve al mapeo por defecto). */
export function deleteVendorRule(id: string): Promise<void> {
  return request<void>(`/receipts/vendor-rules/${id}`, { method: "DELETE" });
}

export function batchConfirmReceipts(ids: string[]): Promise<Transaction[]> {
  return request<Transaction[]>("/receipts/batch-confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transaction_ids: ids }),
  });
}

export function patchReceipt(
  id: string,
  patch: Partial<
    Pick<
      Transaction,
      "vendor" | "date" | "total_amount" | "account_code"
    >
  >,
): Promise<Transaction> {
  return request<Transaction>(`/receipts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function correctReceiptRegistration(id: string, expected: string | null, number: string): Promise<Transaction> {
  return request<Transaction>(`/receipts/${id}/registration-number`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_number: expected, number }),
  });
}

export function uploadReceipt(file: File, year: number): Promise<ReceiptResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("year", String(year));
  return request<ReceiptResponse>("/receipts", { method: "POST", body: form });
}

// --- Login con Google -----------------------------------------------------

/** Estado del login (lo que decide si se muestra la pantalla de acceso). */
export interface AuthStatus {
  /** `true` si el backend tiene el login con Google activo y configurado. */
  enabled: boolean;
  /** `true` si esta sesion esta autenticada (o si el login esta apagado). */
  authenticated: boolean;
  email: string | null;
}

export function fetchAuthStatus(signal?: AbortSignal): Promise<AuthStatus> {
  return request<AuthStatus>("/auth/status", { signal });
}

export function logout(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
}

/** URL a la que hay que navegar para entrar con Google (no es fetch: redirige). */
export const LOGIN_URL = `${API_BASE}/auth/login`;

export function fetchOcrProviders(signal?: AbortSignal): Promise<ProvidersResponse> {
  return request<ProvidersResponse>("/ocr/providers", { signal });
}

/** Uso diario de cuota por proveedor cloud (contador del free tier). */
export function fetchOcrUsage(signal?: AbortSignal): Promise<UsageResponse> {
  return request<UsageResponse>("/ocr/usage", { signal });
}

/** Cambios parciales de los toggles OCR (switch maestro + flags por proveedor). */
export interface OcrSettingsPatch {
  allow_external_ocr?: boolean;
  providers?: Record<string, boolean>;
  /** Limites diarios de cuota a ajustar (solo proveedores cloud). */
  daily_limits?: Record<string, number>;
}

export function patchOcrProviders(patch: OcrSettingsPatch): Promise<ProvidersResponse> {
  return request<ProvidersResponse>("/ocr/providers", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

// --- CSV import 取り込み (Fase 4-1) ----------------------------------------

/** Mapeo de columnas (indices 0-based; null = ausente). */
export interface CsvColumnMapping {
  date: number | null;
  vendor: number | null;
  amount: number | null;
  debit: number | null;
  credit: number | null;
}

/** Una fila del preview: datos parseados + 仕訳 propuesto + flags. */
export interface CsvPreviewRow {
  index: number;
  dedup_hash: string;
  date: string | null;
  vendor: string | null;
  total_amount: number | null;
  tax_lines: TaxLine[];
  account_code: string | null;
  is_expense: boolean;
  is_duplicate: boolean;
  importable: boolean;
  skipped_reason: string | null;
  journal_suggestion: JournalSuggestion | null;
}

/** Respuesta de `POST /import/csv/preview`. */
export interface CsvPreviewResponse {
  encoding: string;
  headers: string[];
  mapping: CsvColumnMapping;
  mapping_ok: boolean;
  total_rows: number;
  importable_count: number;
  duplicate_count: number;
  rows: CsvPreviewRow[];
}

/** Una fila a persistir en el commit (campos posiblemente editados). */
export interface CsvCommitRow {
  dedup_hash: string;
  date: string;
  vendor: string | null;
  total_amount: number;
  account_code: string | null;
  tax_lines: TaxLine[];
}

/** Respuesta de `POST /import/csv/commit`. */
export interface CsvCommitResponse {
  imported: number;
  skipped_duplicates: number;
  transaction_ids: string[];
}

/** Mapeo manual opcional (override de la auto-deteccion de columnas). */
export type CsvManualMapping = Partial<Omit<CsvColumnMapping, never>>;

/** Sube un CSV y devuelve el preview (filas + 仕訳 propuesto), sin persistir. */
export function previewCsvImport(
  file: File,
  mapping?: CsvManualMapping,
): Promise<CsvPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  if (mapping) form.append("mapping", JSON.stringify(mapping));
  return request<CsvPreviewResponse>("/import/csv/preview", {
    method: "POST",
    body: form,
  });
}

/** Persiste las filas seleccionadas como transacciones pending (a la bandeja). */
export function commitCsvImport(rows: CsvCommitRow[]): Promise<CsvCommitResponse> {
  return request<CsvCommitResponse>("/import/csv/commit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows }),
  });
}

export function calculateTax(input: TaxCalculationInput): Promise<TaxCalculationResult> {
  return request<TaxCalculationResult>("/tax/calculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

// --- 控除ウィザード (Fase 3B-1) --------------------------------------------

/** Tipo de 控除 (espejo del enum `DeductionType` del backend). */
export type DeductionType =
  | "kiso"
  | "shakai_hoken"
  | "iryohi"
  | "seimei_hoken"
  | "jishin_hoken"
  | "furusato"
  | "ideco"
  | "fuyo"
  | "haigusha"
  // 住宅借入金等特別控除 (住宅ローン控除) — 税額控除, no aparece como paso del
  // wizard pero el backend lo persiste y la lista 登録済み debe mostrarlo traducido.
  | "housing_loan"
  | "disability_self"
  | "other";

/** Una 控除 registrada (fila persistida). */
export interface Deduction {
  id: string;
  type: DeductionType;
  amount: number;
  meta: Record<string, unknown> | null;
  evidence_ref: string | null;
}

/** Respuesta de `GET /deductions`: filas + total efectivo (incl. 基礎控除). */
export interface DeductionList {
  year: number;
  deductions: Deduction[];
  applied_total: number;
}

/** Efecto de las 控除 sobre el impuesto (`GET /deductions/summary`). */
export interface DeductionSummary {
  year: number;
  applied_total: number;
  tax_with_deductions: number;
  tax_without_deductions: number;
  total_saving: number;
}

/** Sugerencia proactiva de una 控除 que el usuario podria estar perdiendo. */
export interface DeductionSuggestion {
  type: DeductionType;
  label: string;
  reason: string;
  estimated_saving: number | null;
  already_registered: boolean;
}

/** Cuerpo de creacion de una 控除. */
export interface DeductionCreate {
  type: DeductionType;
  amount: number;
  meta?: Record<string, unknown> | null;
  evidence_ref?: string | null;
}

export function fetchDeductions(
  year: number,
  signal?: AbortSignal,
): Promise<DeductionList> {
  return request<DeductionList>(`/deductions?year=${year}`, { signal });
}

export function fetchDeductionSummary(
  year: number,
  signal?: AbortSignal,
): Promise<DeductionSummary> {
  return request<DeductionSummary>(`/deductions/summary?year=${year}`, { signal });
}

export function fetchDeductionSuggestions(
  year: number,
  signal?: AbortSignal,
): Promise<DeductionSuggestion[]> {
  return request<DeductionSuggestion[]>(`/deductions/suggestions?year=${year}`, {
    signal,
  });
}

// --- 提案・アドバイス (motor de recomendaciones, plan 08) -------------------

/** Categoria de una recomendacion fiscal (節税 / 更正の請求 / aviso). */
export type RecommendationCategory = "setsuzei" | "kosei" | "info";

/** Prioridad de presentacion de una recomendacion. */
export type RecommendationPriority = "alta" | "media" | "baja";

/** Estado de una recomendacion (accionable / ya aplicada / requiere dato). */
export type RecommendationStatus = "actionable" | "applied" | "needs_info";

/** Una recomendacion fiscal accionable (calculada del estado real del owner). */
export interface Recommendation {
  id: string;
  category: RecommendationCategory;
  title_jp: string;
  body_jp: string;
  body_es: string;
  /** Ahorro estimado de 所得税 (+復興税) en yenes (概算). */
  income_tax_saving: number;
  /** Ahorro estimado de 住民税 en yenes (概算). */
  resident_tax_saving: number;
  /** Ahorro total estimado (所得税 + 住民税) en yenes (概算). */
  total_saving: number;
  priority: RecommendationPriority;
  status: RecommendationStatus;
  /** Etiqueta del boton de accion (japones). */
  action_label: string;
  /** Id del screen destino (atajo de navegacion) o null. */
  action_route: string | null;
  /** Siempre true: el ahorro es 概算 (no somos 税理士). */
  is_estimate: boolean;
}

/** Respuesta de `GET /recommendations/{year}`: lista priorizada + totales. */
export interface RecommendationReport {
  year: number;
  recommendations: Recommendation[];
  /** Σ del ahorro de las recomendaciones accionables (¥, 概算). */
  total_estimated_saving: number;
  actionable_count: number;
}

export function fetchRecommendations(
  year: number,
  signal?: AbortSignal,
): Promise<RecommendationReport> {
  return request<RecommendationReport>(`/recommendations/${year}`, { signal });
}

export function createDeduction(
  year: number,
  payload: DeductionCreate,
): Promise<Deduction> {
  return request<Deduction>(`/deductions?year=${year}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function patchDeduction(
  id: string,
  patch: { amount?: number; meta?: Record<string, unknown> | null },
): Promise<Deduction> {
  return request<Deduction>(`/deductions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function deleteDeduction(id: string): Promise<void> {
  return request<void>(`/deductions/${id}`, { method: "DELETE" });
}

// --- 控除証明書 XML import (Nivel 2 e-Tax) ---------------------------------

/** Desglose por categoría del 生命保険料控除 (一般/介護医療/個人年金). */
export interface KoujoSeimeiCategory {
  category: string;
  label: string;
  old_paid: number | null;
  new_paid: number | null;
  deduction: number;
}

/** Respuesta del preview de import XML de 控除証明書. */
export interface KoujoXmlPreview {
  /** Etiqueta japonesa del tipo de 控除 detectado. */
  koujo_type: string;
  /** Elemento raíz del XML (ej. "TEG850"). */
  root_element: string;
  /** Tipo de 控除 destino. */
  deduction_type: DeductionType;
  /** 控除額 propuesto (yenes) — el usuario lo confirma/edita. */
  amount: number;
  /** Emisor / 保険会社名 / 団体名 / 被保険者名. */
  issuer: string | null;
  /** Año 西暦 del certificado, o null. */
  year: number | null;
  /** true si el monto no es 100% determinable y requiere confirmación. */
  needs_confirmation: boolean;
  /** Aviso japonés (cómo se calculó / qué confirmar). */
  note: string | null;
  /** true si ya hay una 控除 del tipo registrada (el commit la suma). */
  already_registered: boolean;
  /** Desglose por categoría (solo 生命保険). */
  seimei_categories: KoujoSeimeiCategory[];
}

/** Cuerpo del commit del import XML (monto confirmado por el usuario). */
export interface KoujoXmlCommit {
  deduction_type: DeductionType;
  amount: number;
  issuer?: string | null;
  year?: number | null;
  koujo_type?: string | null;
}

/** Respuesta del commit del import XML. */
export interface KoujoXmlCommitResponse {
  id: string;
  type: DeductionType;
  amount: number;
  /** true si se creó; false si se sumó a una 控除 existente. */
  created: boolean;
}

/** Sube un XML de 控除証明書 y devuelve el preview (tipo + 控除額), sin persistir. */
export function previewKoujoXml(
  file: File,
  year: number,
): Promise<KoujoXmlPreview> {
  const form = new FormData();
  form.append("file", file);
  return request<KoujoXmlPreview>(
    `/deductions/import-xml/preview?year=${year}`,
    { method: "POST", body: form },
  );
}

/** Crea (o suma a) la 控除 con el monto confirmado del 控除証明書. */
export function commitKoujoXml(
  year: number,
  payload: KoujoXmlCommit,
): Promise<KoujoXmlCommitResponse> {
  return request<KoujoXmlCommitResponse>(
    `/deductions/import-xml/commit?year=${year}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

// --- 扶養家族 (扶養控除 detallado + 国外居住) — research 08 -----------------

/** Residencia del 扶養親族. */
export type Residence = "domestic" | "overseas";
/** Convivencia (define 同居老親 vs 老人別居). */
export type Cohabitation = "together" | "separate";
/** Motivo de excepcion para 国外居住 30-69. */
export type OverseasExemptionReason = "study" | "disability" | "remittance_380k";

/** Datos crudos de un 扶養親族 para clasificar (espejo de `DependentInput`). */
export interface DependentInput {
  name: string;
  relationship?: string | null;
  /** 生年月日 en ISO (YYYY-MM-DD). */
  birth_date?: string | null;
  /** 合計所得金額 del dependiente (vs umbral ¥580k 令和7). */
  goukei_shotoku?: number | null;
  is_jigyo_senju?: boolean;
  residence?: Residence;
  country?: string | null;
  cohabitation?: Cohabitation;
  eligible_cohabiting_ancestor?: boolean | null;
  overseas_exemption?: OverseasExemptionReason | null;
  annual_remittance?: number | null;
}

/** Un documento requerido para un 国外居住扶養親族. */
export interface DocumentRequirement {
  code: string;
  label: string;
  description: string;
}

/** Categoria resuelta de un 扶養親族. */
export type DependentKind =
  | "none"
  | "young"
  | "general"
  | "specific"
  | "elderly"
  | "elderly_cohabiting";

/** Resultado de clasificar un 扶養親族 (categoria + monto + 国外 docs). */
export interface DependentClassification {
  name: string;
  kind: DependentKind;
  kind_label: string;
  age: number | null;
  income_tax_amount: number;
  resident_tax_amount: number;
  qualifies: boolean;
  is_overseas: boolean;
  required_documents: DocumentRequirement[];
  needs_translation: boolean;
  disqualified_reason: string | null;
  disqualified_message: string | null;
}

/** Respuesta de `POST /dependents/classify`. */
export interface DependentsClassifyResult {
  year: number;
  dependents: DependentClassification[];
  total_income_tax_deduction: number;
  total_resident_tax_deduction: number;
  income_threshold: number;
}

/** Clasifica 扶養親族 (categoria + monto + 国外 docs) sin persistir. */
export function classifyDependents(
  year: number,
  dependents: DependentInput[],
): Promise<DependentsClassifyResult> {
  return request<DependentsClassifyResult>(
    `/dependents/classify?year=${year}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dependents),
    },
  );
}

// --- 収入 (IncomeSource) — ingresos editables del owner --------------------

/** Tipo de 所得 que el owner puede ingresar (espejo del enum `IncomeType`). */
export type IncomeType = "jigyo" | "kyuyo" | "zatsu" | "fudosan";

/** Una fuente de ingreso registrada (fila persistida). */
export interface IncomeSource {
  id: string;
  income_type: IncomeType;
  /** 収入金額 bruto (売上 para jigyo, 収入 para kyuyo, etc.). */
  gross: number;
  /** 源泉徴収税額 (del 源泉徴収票 / 支払調書). */
  withholding: number;
  /** 必要経費 (zatsu/fudosan). Para jigyo es informativo (経費 = 仕訳). */
  expenses: number;
  meta: Record<string, unknown> | null;
}

/** Respuesta de `GET /income-sources`: filas + totales del 年度. */
export interface IncomeSourceList {
  year: number;
  income_sources: IncomeSource[];
  /** 売上 del 事業 (Σ filas jigyo) — el que entra al PL. */
  sales_revenue: number;
  /** Σ源泉徴収税額 de todas las fuentes — el que descuenta el 納付額. */
  total_withholding: number;
}

/** Cuerpo de creacion de una fuente de ingreso. */
export interface IncomeSourceCreate {
  income_type: IncomeType;
  gross: number;
  withholding?: number;
  expenses?: number;
  meta?: Record<string, unknown> | null;
}

/** Cuerpo de edicion de una fuente (solo campos provistos). */
export interface IncomeSourcePatch {
  gross?: number;
  withholding?: number;
  expenses?: number;
  meta?: Record<string, unknown> | null;
}

export function fetchIncomeSources(
  year: number,
  signal?: AbortSignal,
): Promise<IncomeSourceList> {
  return request<IncomeSourceList>(`/income-sources?year=${year}`, { signal });
}

export function createIncomeSource(
  year: number,
  payload: IncomeSourceCreate,
): Promise<IncomeSource> {
  return request<IncomeSource>(`/income-sources?year=${year}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function patchIncomeSource(
  id: string,
  patch: IncomeSourcePatch,
): Promise<IncomeSource> {
  return request<IncomeSource>(`/income-sources/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function deleteIncomeSource(id: string): Promise<void> {
  return request<void>(`/income-sources/${id}`, { method: "DELETE" });
}

// --- 確定申告 (Fase 3B-2) --------------------------------------------------

/** Una linea del desglose de 所得 del 申告書. */
export interface FilingIncomeLine {
  kind: string;
  label: string | null;
  amount: number;
}

/** Una 控除 que entro al calculo del 申告書. */
export interface FilingDeductionLine {
  type: string;
  amount: number;
}

/** Item de la lista de prontitud del 確定申告. */
export interface FilingChecklistItem {
  key: string;
  label: string;
  done: boolean;
  detail: string | null;
}

/**
 * Estimacion del 住民税 (impuesto de residencia, pago futuro jun-may del año
 * siguiente). Espejo de `ResidentTaxOut`. NO es 還付: es un pago posterior, con
 * deducciones distintas al 所得税 (基礎控除 ¥430k, sin 復興特別税).
 */
export interface ResidentTaxEstimate {
  total_income: number;
  kiso_kojo: number;
  dependent_deduction: number;
  resident_deductions_total: number;
  taxable_income: number;
  /** 所得割 県民税 (4%). */
  shotokuwari_prefectural: number;
  /** 所得割 市民税 (6%). */
  shotokuwari_municipal: number;
  shotokuwari_total: number;
  kintowari_prefectural: number;
  kintowari_municipal: number;
  /** 森林環境税 (¥1,000 国税). */
  forest_environment_tax: number;
  kintowari_total: number;
  chosei_kojo: number;
  total: number;
}

/** Resumen estructurado del 確定申告 (`POST /filing/draft`, `GET .../summary`). */
export interface FilingSummary {
  draft_id: string;
  year: number;
  filing_type: string;
  taxpayer_name: string;
  sales_revenue: number;
  confirmed_expense_total: number;
  confirmed_count: number;
  pending_count: number;
  aoiro_deduction: number;
  business_income: number;
  income_breakdown: FilingIncomeLine[];
  total_income: number;
  total_income_deductions: number;
  taxable_income: number;
  income_tax_base: number;
  income_tax_after_credits: number;
  reconstruction_tax: number;
  total_tax: number;
  withholding_total: number;
  final_amount: number;
  is_refund: boolean;
  /** 住民税 estimado (pago futuro jun-may, NO 還付). */
  resident_tax: ResidentTaxEstimate;
  pl_net_income: number;
  bs_balanced: boolean;
  deductions_applied: FilingDeductionLine[];
  checklist: FilingChecklistItem[];
}

/** Formularios PDF disponibles. */
export type FilingPdfForm = "shinkokusho" | "kessansho" | "shiwakecho" | "motocho";

/** Arma el FilingDraft del 年度 (calculo completo) y devuelve el resumen. */
export function createFilingDraft(year: number): Promise<FilingSummary> {
  return request<FilingSummary>(`/filing/draft?year=${year}`, { method: "POST" });
}

/** Resumen de un draft ya creado (para revision). */
export function fetchFilingSummary(
  draftId: string,
  signal?: AbortSignal,
): Promise<FilingSummary> {
  return request<FilingSummary>(`/filing/${draftId}/summary`, { signal });
}

/** URL absoluta de descarga de un formulario PDF. */
export function filingPdfUrl(draftId: string, form: FilingPdfForm): string {
  return `${API_BASE}/filing/${draftId}/pdf?form=${form}`;
}

/** URL absoluta del ZIP con 申告書類一式. */
export function filingOfficialPackageUrl(draftId: string): string {
  return `${API_BASE}/filing/${draftId}/official-package`;
}

/** URL absoluta de descarga del .xtx (XML). */
export function filingXtxUrl(draftId: string): string {
  return `${API_BASE}/filing/${draftId}/xtx`;
}

/** URL absoluta de descarga del CSV (SHIFT-JIS). */
export function filingCsvUrl(draftId: string): string {
  return `${API_BASE}/filing/${draftId}/csv`;
}

// --- 消費税 (Consumption tax / インボイス) ---------------------------------

/** Metodo de calculo del 消費税 (clave del comparador). */
export type ConsumptionMethodKey = "honsoku" | "kani" | "tokurei";

/** Metodo configurado en el Taxpayer (espejo del enum `ConsumptionMethod`). */
export type ConsumptionMethodSetting = "honsoku" | "kani" | "tokurei_2wari";

/** Desglose del 売上税額 (区分経理 8% / 10%). */
export interface SalesTaxBreakdown {
  taxable_sales_8: number;
  taxable_sales_10: number;
  national_tax_8: number;
  national_tax_10: number;
  national_tax_total: number;
}

/** Desglose del 仕入税額控除 本則 (区分経理 8% / 10%). */
export interface PurchaseTaxBreakdown {
  qualified_purchases_8: number;
  qualified_purchases_10: number;
  national_tax_8: number;
  national_tax_10: number;
  national_tax_total: number;
  excluded_non_qualified: number;
}

/** Una opcion de calculo del 消費税 (本則 / 簡易 / 特例). */
export interface ConsumptionOption {
  method: ConsumptionMethodKey;
  label: string;
  eligible: boolean;
  eligibility_status: "unverified" | "unavailable";
  sales_tax: number;
  purchase_tax_credit: number;
  national_tax: number;
  local_tax: number;
  total_tax: number;
  note: string | null;
}

/** Resultado completo del calculo del 消費税 (`GET /consumption/calculate`). */
export interface ConsumptionResult {
  year: number;
  is_taxable: boolean;
  method_setting: ConsumptionMethodSetting | null;
  business_category: number | null;
  sales_breakdown: SalesTaxBreakdown;
  purchase_breakdown: PurchaseTaxBreakdown;
  honsoku: ConsumptionOption;
  kani: ConsumptionOption;
  tokurei: ConsumptionOption;
  recommended: ConsumptionMethodKey | null;
  recommended_saving: number;
  as_of: string;
}

/** Config del 消費税 del contribuyente (`GET/PATCH /taxpayer`). */
export interface TaxpayerConsumption {
  taxpayer_id: string;
  name: string;
  is_taxable_consumption: boolean;
  consumption_method: ConsumptionMethodSetting | null;
  consumption_business_category: number | null;
  business_category_labels: Record<string, string>;
  /** 税務署 (提出先) — clave del 税務署 (ej. "tsushima"). */
  filing_office: string | null;
  /** Si el onboarding guiado fue completado. */
  onboarded: boolean;
}

/** Cambios de la config del 消費税. */
export interface TaxpayerConsumptionPatch {
  is_taxable_consumption?: boolean;
  consumption_method?: ConsumptionMethodSetting;
  consumption_business_category?: number;
  filing_office?: string;
  /** Permite rehacer el onboarding (setear false desde el 設定). */
  onboarded?: boolean;
}

/** Calcula el 消費税 del 年度 (3 opciones + recomendacion). */
export function fetchConsumption(
  year: number,
  signal?: AbortSignal,
): Promise<ConsumptionResult> {
  return request<ConsumptionResult>(`/consumption/calculate?year=${year}`, {
    signal,
  });
}

/** URL absoluta del PDF del 消費税申告書. */
export function consumptionPdfUrl(year: number): string {
  return `${API_BASE}/consumption/${year}/pdf`;
}

/** Config actual del 消費税 del contribuyente. */
export function fetchTaxpayer(signal?: AbortSignal): Promise<TaxpayerConsumption> {
  return request<TaxpayerConsumption>("/taxpayer", { signal });
}

/** Actualiza la config del 消費税 (課税事業者 + metodo + 事業区分). */
export function patchTaxpayer(
  patch: TaxpayerConsumptionPatch,
): Promise<TaxpayerConsumption> {
  return request<TaxpayerConsumption>("/taxpayer", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

// --- Onboarding guiado (primera vez) ---------------------------------------

/** Estado del onboarding (`GET /onboarding/status`). */
export interface OnboardingStatus {
  /** `true` si el usuario ya completo la configuracion guiada. */
  onboarded: boolean;
  /** `true` si existe un Taxpayer registrado. */
  has_taxpayer: boolean;
  /** `true` si hay algun ingreso con monto/源泉 > 0. */
  has_income: boolean;
}

/** Un ingreso inicial declarado en el onboarding. */
export interface OnboardingIncome {
  income_type: IncomeType;
  gross?: number;
  withholding?: number;
  expenses?: number;
}

/** Perfil completo enviado al finalizar el onboarding (`POST .../complete`). */
export interface OnboardingComplete {
  name?: string;
  name_kana?: string;
  my_number?: string;
  postal_code?: string;
  address?: string;
  /** 生年月日 en formato ISO (YYYY-MM-DD). */
  birth_date?: string;
  business_type?: string;
  /** 申告区分: aoiro_65 / aoiro_55 / aoiro_10 / shiroiro. */
  filing_type?: string;
  is_taxable_consumption?: boolean;
  /** 税務署 (提出先) — clave (ej. "tsushima"). */
  filing_office?: string;
  incomes?: OnboardingIncome[];
}

/** Resultado del `POST /onboarding/complete`. */
export interface OnboardingCompleteResult {
  onboarded: boolean;
  taxpayer_id: string;
  year: number;
  income_count: number;
}

// --- 過去の申告 (archivo histórico de declaraciones anteriores) -------------

/** Una declaración histórica archivada (registro persistido). */
export interface PastFiling {
  id: string;
  year: number;
  original_filename: string | null;
  uploaded_at: string;
  /** 所得金額 (yenes), o null si no se extrajo. */
  total_income: number | null;
  /** 納付税額 (yenes), o null. */
  tax_paid: number | null;
  /** 還付金額 (yenes), o null. */
  tax_refund: number | null;
  /** 税務署 detectado, o null. */
  tax_office: string | null;
  /** 'auto' (extraído por el parser) | 'manual' (corregido por el usuario). */
  extraction_source: string;
  file_hash: string;
}

/** Un punto de la serie año a año (gráfico de comparación). */
export interface PastFilingPoint {
  year: number;
  total_income: number | null;
  tax_paid: number | null;
  tax_refund: number | null;
  /** Impuesto neto: 納付 positivo, 還付 negativo, o null. */
  net_tax: number | null;
}

/** Respuesta de `GET /past-filings`: registros + serie de comparación. */
export interface PastFilingList {
  filings: PastFiling[];
  comparison: PastFilingPoint[];
}

/** Resultado de `POST /past-filings`. */
export interface PastFilingUpload {
  filing: PastFiling;
  /** `true` si el PDF ya estaba archivado (mismo hash): no se duplicó. */
  duplicate: boolean;
  /** `true` si se extrajo al menos un monto del PDF. */
  extracted: boolean;
}

/** Campos editables de un registro histórico (corrección manual). */
export interface PastFilingPatch {
  year?: number;
  total_income?: number | null;
  tax_paid?: number | null;
  tax_refund?: number | null;
  tax_office?: string | null;
}

/** Lista las declaraciones históricas + la serie de comparación año a año. */
export function fetchPastFilings(signal?: AbortSignal): Promise<PastFilingList> {
  return request<PastFilingList>("/past-filings", { signal });
}

/** Sube un PDF de 確定申告 viejo (+ año opcional) y lo archiva/extrae. */
export function uploadPastFiling(
  file: File,
  year?: number,
): Promise<PastFilingUpload> {
  const form = new FormData();
  form.append("file", file);
  if (year !== undefined) form.append("year", String(year));
  return request<PastFilingUpload>("/past-filings", {
    method: "POST",
    body: form,
  });
}

/** Corrige los montos extraídos de un registro histórico. */
export function patchPastFiling(
  id: string,
  patch: PastFilingPatch,
): Promise<PastFiling> {
  return request<PastFiling>(`/past-filings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

/** Borra un registro histórico (y su PDF si queda huérfano). */
export function deletePastFiling(id: string): Promise<void> {
  return request<void>(`/past-filings/${id}`, { method: "DELETE" });
}

/** URL absoluta del PDF original archivado de un registro histórico. */
export function pastFilingPdfUrl(id: string): string {
  return `${API_BASE}/past-filings/${id}/pdf`;
}

// --- Onboarding ------------------------------------------------------------

/** Estado del onboarding del contribuyente. */
export function fetchOnboardingStatus(
  signal?: AbortSignal,
): Promise<OnboardingStatus> {
  return request<OnboardingStatus>("/onboarding/status", { signal });
}

/** Completa el onboarding con el perfil y marca onboarded=true. */
export function completeOnboarding(
  payload: OnboardingComplete,
  year: number,
): Promise<OnboardingCompleteResult> {
  return request<OnboardingCompleteResult>(`/onboarding/complete?year=${year}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// --- 年度 (ciclo multi-año fiscal) -----------------------------------------

/** Estado de un 年度 en el ciclo (espejo del enum `FiscalYearStatus`). */
export type FiscalYearStatus = "open" | "closed" | "filed";

/** Un 年度 del contribuyente (año + estado del ciclo). */
export interface FiscalYearItem {
  year: number;
  status: FiscalYearStatus;
  rules_available: boolean;
}

/** Respuesta de `GET /fiscal-years`: años + año activo por defecto. */
export interface FiscalYearList {
  years: FiscalYearItem[];
  /** Año OPEN más reciente (default del selector), o null si no hay años. */
  active_year: number | null;
}

/** Lista los 年度 del contribuyente (year + status), ordenados desc. */
export function fetchFiscalYears(signal?: AbortSignal): Promise<FiscalYearList> {
  return request<FiscalYearList>("/fiscal-years", { signal });
}

/** Crea (o devuelve, si ya existe) el 年度 de un año (abre un nuevo ciclo). */
export function createFiscalYear(year: number): Promise<FiscalYearItem> {
  return request<FiscalYearItem>("/fiscal-years", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ year }),
  });
}

/** Cambia el estado de un 年度 (open/closed/filed). */
export function patchFiscalYear(
  year: number,
  fyStatus: FiscalYearStatus,
): Promise<FiscalYearItem> {
  return request<FiscalYearItem>(`/fiscal-years/${year}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: fyStatus }),
  });
}

// --- 期首残高 (saldos de apertura manuales) -------------------------------

/** Categoria contable real del balance sheet. */
export type BalanceAccountCategory = "asset" | "liability" | "equity";

/** Una linea editable de saldo inicial por 勘定科目. */
export interface OpeningBalanceLineInput {
  account_code: string;
  amount: number;
}

/** Linea persistida de 期首残高. */
export interface OpeningBalanceLine {
  account_code: string;
  account_name: string;
  category: BalanceAccountCategory;
  amount: number;
}

/** Resumen contable de apertura devuelto por el backend. */
export interface OpeningBalanceSummary {
  year: number;
  balances: OpeningBalanceLine[];
  total_assets: number;
  total_liabilities: number;
  total_equity: number;
  imbalance: number;
  is_balanced: boolean;
  journal_entry_id: string | null;
}

/** Lee los saldos de apertura del 年度. */
export function fetchOpeningBalances(
  year: number,
  signal?: AbortSignal,
): Promise<OpeningBalanceSummary> {
  return request<OpeningBalanceSummary>(`/fiscal-years/${year}/opening-balances`, {
    signal,
  });
}

/** Reemplaza los saldos de apertura del 年度. */
export function upsertOpeningBalances(
  year: number,
  balances: OpeningBalanceLineInput[],
): Promise<OpeningBalanceSummary> {
  return request<OpeningBalanceSummary>(`/fiscal-years/${year}/opening-balances`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ balances }),
  });
}

// --- 家計簿 (libro de gastos personales, NO fiscal) ------------------------

/** Un gasto personal del 家計簿 (espejo de `HouseholdExpenseOut`). */
export interface HouseholdExpense {
  id: string;
  date: string;
  amount: number;
  category: string;
  memo: string | null;
  created_at: string;
}

/** Alta manual de un gasto personal. */
export interface HouseholdExpenseCreate {
  date: string;
  amount: number;
  category: string;
  memo?: string | null;
}

/** Campos editables de un gasto personal. */
export interface HouseholdExpensePatch {
  date?: string;
  amount?: number;
  category?: string;
  memo?: string | null;
}

/** Total de un 費目 dentro de un mes. */
export interface HouseholdCategoryTotal {
  category: string;
  total: number;
  count: number;
}

/** Resumen mensual del 家計簿: total + desglose por 費目. */
export interface HouseholdSummary {
  year: number;
  month: number;
  total: number;
  by_category: HouseholdCategoryTotal[];
}

/** Lista los gastos personales de un mes (más recientes primero). */
export function fetchHouseholdExpenses(
  year: number,
  month: number,
  signal?: AbortSignal,
): Promise<HouseholdExpense[]> {
  return request<HouseholdExpense[]>(
    `/household?year=${year}&month=${month}`,
    { signal },
  );
}

/** Resumen del mes (total + desglose por 費目). */
export function fetchHouseholdSummary(
  year: number,
  month: number,
  signal?: AbortSignal,
): Promise<HouseholdSummary> {
  return request<HouseholdSummary>(
    `/household/summary?year=${year}&month=${month}`,
    { signal },
  );
}

/** Crea un gasto personal manual. */
export function createHouseholdExpense(
  payload: HouseholdExpenseCreate,
): Promise<HouseholdExpense> {
  return request<HouseholdExpense>("/household", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Edita un gasto personal. */
export function patchHouseholdExpense(
  id: string,
  patch: HouseholdExpensePatch,
): Promise<HouseholdExpense> {
  return request<HouseholdExpense>(`/household/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

/** Borra un gasto personal. */
export function deleteHouseholdExpense(id: string): Promise<void> {
  return request<void>(`/household/${id}`, { method: "DELETE" });
}

/**
 * Mueve un ítem del 仕訳トレイ al 家計簿 (puente 事業→家計): lo crea como gasto
 * personal y marca la transacción como rechazada (la saca del flujo del negocio).
 */
export function householdFromTransaction(
  transactionId: string,
  category: string,
): Promise<HouseholdExpense> {
  return request<HouseholdExpense>(
    `/household/from-transaction/${transactionId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category }),
    },
  );
}

// --- 売上・請求 -----------------------------------------------------------

export type SalesDocumentType =
  | "estimate"
  | "delivery_note"
  | "invoice"
  | "receipt"
  | "purchase_order"
  | "order_acknowledgement"
  | "consolidated_invoice"
  | "corrected_invoice";

export type SalesDocumentStatus =
  | "draft"
  | "issued"
  | "sent"
  | "awaiting_payment"
  | "partially_paid"
  | "paid"
  | "voided";

export type SalesTaxCategory =
  | "standard_10"
  | "reduced_8"
  | "exempt"
  | "out_of_scope";
export type SalesPriceMode = "exclusive" | "inclusive";
export type TaxRoundingMode = "floor" | "round" | "ceil";
export type SalesPaymentMethod = "cash" | "bank_transfer" | "card" | "other";

export interface BusinessProfile {
  id: string;
  trade_name: string;
  legal_name: string | null;
  legal_name_kana: string | null;
  corporate_number: string | null;
  business_description: string | null;
  show_representative: boolean;
  representative_name: string | null;
  department_name: string | null;
  contact_person_name: string | null;
  postal_code: string | null;
  address: string | null;
  address_line1: string | null;
  address_line2: string | null;
  phone: string | null;
  fax: string | null;
  email: string | null;
  website_url: string | null;
  default_customer_honorific: string;
  payment_terms_days: number;
  bank_name: string | null;
  bank_branch: string | null;
  bank_account_type: string | null;
  bank_account_number: string | null;
  bank_account_holder: string | null;
  show_bank_details: boolean;
  logo_ref: string | null;
  seal_ref: string | null;
  show_stamp_box: boolean;
  show_logo: boolean;
  show_seal: boolean;
  seal_text: string | null;
  is_invoice_issuer: boolean;
  registration_number: string | null;
  show_registration_number: boolean;
  invoice_message: string | null;
  receipt_message: string | null;
  receipt_proviso: string | null;
  transfer_fee_note: string | null;
  document_footer_note: string | null;
  rounding_mode: TaxRoundingMode;
  price_mode: SalesPriceMode;
  updated_at: string;
}

export type BusinessProfilePatch = Partial<Omit<BusinessProfile, "id" | "updated_at">>;

export interface SalesCustomerSnapshot {
  name: string;
  honorific: string;
  postal_code?: string | null;
  address?: string | null;
  contact_name?: string | null;
  email?: string | null;
  phone?: string | null;
}

export interface SalesCustomer extends SalesCustomerSnapshot {
  id: string;
  payment_terms_days: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SalesLineInput {
  description: string;
  quantity: string;
  unit: string;
  unit_price: number;
  discount_amount?: number;
  tax_category: SalesTaxCategory;
}

export interface SalesLine extends SalesLineInput {
  id: string;
  position: number;
  amount: number;
}

export interface SalesPayment {
  id: string;
  payment_date: string;
  amount: number;
  method: SalesPaymentMethod;
  reference: string | null;
  receipt_document_id: string | null;
  created_at: string;
}

export interface SalesDocument {
  id: string;
  document_type: SalesDocumentType;
  status: SalesDocumentStatus;
  document_number: string | null;
  customer_id: string | null;
  source_document_id: string | null;
  subject: string | null;
  issue_date: string;
  due_date: string | null;
  notes: string | null;
  customer: SalesCustomerSnapshot;
  subtotal: number;
  tax_8: number;
  tax_10: number;
  total: number;
  amount_paid: number;
  outstanding: number;
  rounding_mode: TaxRoundingMode;
  price_mode: SalesPriceMode;
  is_qualified_invoice: boolean;
  revision: number;
  issued_at: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
  lines: SalesLine[];
  payments: SalesPayment[];
}

export interface SalesDocumentCreate {
  document_type: SalesDocumentType;
  customer_id?: string | null;
  customer?: SalesCustomerSnapshot;
  subject?: string | null;
  issue_date: string;
  due_date?: string | null;
  notes?: string | null;
  rounding_mode?: TaxRoundingMode;
  price_mode?: SalesPriceMode;
  is_qualified_invoice?: boolean;
  creation_key?: string;
  lines: SalesLineInput[];
}

export type SalesDocumentPatch = Partial<
  Omit<SalesDocumentCreate, "document_type" | "creation_key">
>;

export interface SalesPaymentCreate {
  payment_date: string;
  amount: number;
  method: SalesPaymentMethod;
  reference?: string | null;
  idempotency_key?: string;
  create_receipt?: boolean;
}

export function fetchBusinessProfile(signal?: AbortSignal): Promise<BusinessProfile> {
  return request<BusinessProfile>("/business-profile", { signal });
}

export function patchBusinessProfile(
  patch: BusinessProfilePatch,
): Promise<BusinessProfile> {
  return request<BusinessProfile>("/business-profile", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function fetchSalesCustomers(signal?: AbortSignal): Promise<SalesCustomer[]> {
  return request<SalesCustomer[]>("/customers", { signal });
}

export function createSalesCustomer(
  customer: SalesCustomerSnapshot,
): Promise<SalesCustomer> {
  return request<SalesCustomer>("/customers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...customer, payment_terms_days: 30, is_active: true }),
  });
}

export function fetchSalesDocuments(
  year?: number,
  signal?: AbortSignal,
): Promise<SalesDocument[]> {
  const query = year ? `?year=${year}` : "";
  return request<SalesDocument[]>(`/sales-documents${query}`, { signal });
}

export function createSalesDocument(
  payload: SalesDocumentCreate,
): Promise<SalesDocument> {
  return request<SalesDocument>("/sales-documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function patchSalesDocument(
  id: string,
  patch: SalesDocumentPatch,
): Promise<SalesDocument> {
  return request<SalesDocument>(`/sales-documents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function issueSalesDocument(id: string): Promise<SalesDocument> {
  return request<SalesDocument>(`/sales-documents/${id}/issue`, { method: "POST" });
}

export function convertSalesDocument(
  id: string,
  targetType: SalesDocumentType,
): Promise<SalesDocument> {
  return request<SalesDocument>(`/sales-documents/${id}/convert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_type: targetType }),
  });
}

export function duplicateSalesDocument(id: string): Promise<SalesDocument> {
  return request<SalesDocument>(`/sales-documents/${id}/duplicate`, { method: "POST" });
}

export function sendSalesDocument(id: string): Promise<SalesDocument> {
  return request<SalesDocument>(`/sales-documents/${id}/send`, { method: "POST" });
}

export function voidSalesDocument(id: string, reason?: string): Promise<SalesDocument> {
  return request<SalesDocument>(`/sales-documents/${id}/void`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

export function createSalesPayment(
  id: string,
  payload: SalesPaymentCreate,
): Promise<SalesPayment> {
  return request<SalesPayment>(`/sales-documents/${id}/payments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function salesDocumentPdfUrl(id: string): string {
  return `${API_BASE}/sales-documents/${id}/pdf`;
}
