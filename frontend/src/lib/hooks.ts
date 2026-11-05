/** Hooks de React Query (server state) + derivacion del impuesto estimado. */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  batchConfirmReceipts,
  commitCsvImport,
  commitKoujoXml,
  confirmReceipt,
  createDeduction,
  type KoujoXmlCommit,
  type KoujoXmlCommitResponse,
  type KoujoXmlPreview,
  previewKoujoXml,
  createFilingDraft,
  type CsvCommitRow,
  type CsvManualMapping,
  type DeductionCreate,
  type DeductionList,
  type DeductionSummary,
  type DeductionSuggestion,
  createIncomeSource,
  deleteDeduction,
  deleteIncomeSource,
  fetchDeductions,
  fetchEvidence,
  fetchDeductionSuggestions,
  fetchDeductionSummary,
  fetchIncomeSources,
  type FilingSummary,
  type EvidenceFilters,
  type EvidenceList,
  type IncomeSourceCreate,
  type IncomeSourceList,
  type IncomeSourcePatch,
  type ConsumptionResult,
  fetchConsumption,
  fetchTaxpayer,
  fetchYearEndProfile,
  type YearEndProfile,
  patchTaxpayer,
  type TaxpayerConsumption,
  type TaxpayerConsumptionPatch,
  completeOnboarding,
  fetchOnboardingStatus,
  type OnboardingComplete,
  type OnboardingCompleteResult,
  type OnboardingStatus,
  createHouseholdExpense,
  deleteHouseholdExpense,
  fetchHouseholdExpenses,
  fetchHouseholdSummary,
  householdFromTransaction,
  patchHouseholdExpense,
  type HouseholdExpense,
  type HouseholdExpenseCreate,
  type HouseholdExpensePatch,
  type HouseholdSummary,
  fetchOcrProviders,
  fetchOcrUsage,
  fetchPastFilings,
  fetchPendingReceipts,
  fetchRecommendations,
  type RecommendationReport,
  type OcrSettingsPatch,
  type PastFilingList,
  type PastFilingPatch,
  type PastFilingUpload,
  deletePastFiling,
  patchPastFiling,
  uploadPastFiling,
  patchDeduction,
  patchIncomeSource,
  patchOcrProviders,
  patchReceipt,
  previewCsvImport,
  type ProvidersResponse,
  type Transaction,
  uploadReceipt,
  type UsageResponse,
  createSalesDocument,
  createSalesCustomer,
  createSalesPayment,
  convertSalesDocument,
  duplicateSalesDocument,
  fetchBusinessProfile,
  fetchSalesCustomers,
  fetchSalesDocuments,
  issueSalesDocument,
  patchBusinessProfile,
  patchSalesDocument,
  sendSalesDocument,
  voidSalesDocument,
  type BusinessProfile,
  type BusinessProfilePatch,
  type SalesDocument,
  type SalesDocumentCreate,
  type SalesDocumentPatch,
  type SalesDocumentType,
  type SalesPaymentCreate,
  type SalesCustomerSnapshot,
} from "./api";
import {
  type ReceiptCorrections,
  type FiscalYearItem,
  type FiscalYearList,
  type OpeningBalanceLineInput,
  type OpeningBalanceSummary,
  createFiscalYear,
  fetchFiscalYears,
  fetchOpeningBalances,
  upsertOpeningBalances,
} from "./api";
import { useUiStore } from "./store";
import { toastSaved } from "./toast";

/**
 * 年度 activo del ciclo multi-año fiscal. Lee el estado del store Zustand: al
 * cambiar de año todos los hooks que lo usan refetchean ese año. Reemplaza la
 * vieja constante `ACTIVE_YEAR = 2025` (la app ya no está congelada en 2025).
 */
export function useActiveYear(): number {
  return useUiStore((s) => s.activeYear);
}

/** Estado del 年度 activo, derivado de `GET /fiscal-years`. */
export function useActiveFiscalYear(): FiscalYearItem | undefined {
  const activeYear = useActiveYear();
  const { data } = useFiscalYears();
  return data?.years.find((fy) => fy.year === activeYear);
}

/** Bloqueo visual del 年度 activo: `closed` / `filed` se muestran read-only. */
export function useActiveYearLock(): {
  fiscalYear: FiscalYearItem | undefined;
  isReadOnly: boolean;
  label: string;
} {
  const fiscalYear = useActiveFiscalYear();
  const isReadOnly = fiscalYear?.status === "closed" || fiscalYear?.status === "filed";
  const label =
    fiscalYear?.status === "filed"
      ? "申告済み"
      : fiscalYear?.status === "closed"
        ? "締切済み"
        : "編集中";
  return { fiscalYear, isReadOnly, label };
}

export const queryKeys = {
  fiscalYears: ["fiscal-years"] as const,
  openingBalances: (year: number) => ["fiscal-years", year, "opening-balances"] as const,
  // La bandeja de 仕訳 depende del 年度: incluir el año para que cambiar de año
  // refetchee y no mezcle transacciones de años distintos.
  pendingReceipts: (year: number) => ["receipts", "pending", year] as const,
  evidence: (year: number, filters: EvidenceFilters) =>
    ["evidence", year, filters] as const,
  providers: ["ocr", "providers"] as const,
  ocrUsage: ["ocr", "usage"] as const,
  deductions: (year: number) => ["deductions", year] as const,
  deductionSummary: (year: number) => ["deductions", "summary", year] as const,
  deductionSuggestions: (year: number) =>
    ["deductions", "suggestions", year] as const,
  incomeSources: (year: number) => ["income-sources", year] as const,
  filingDraft: (year: number) => ["filing", "draft", year] as const,
  consumption: (year: number) => ["consumption", year] as const,
  taxpayer: ["taxpayer"] as const,
  onboarding: ["onboarding", "status"] as const,
  pastFilings: ["past-filings"] as const,
  recommendations: (year: number) => ["recommendations", year] as const,
  household: (year: number, month: number) =>
    ["household", year, month] as const,
  householdSummary: (year: number, month: number) =>
    ["household", "summary", year, month] as const,
  businessProfile: ["business-profile"] as const,
  salesCustomers: ["sales-customers"] as const,
  salesDocuments: (_year?: number) => ["sales-documents"] as const,
};

/** Bandeja de 仕訳: transacciones OCR en estado pending del 年度 activo. */
export function usePendingReceipts(): UseQueryResult<Transaction[]> {
  const year = useActiveYear();
  return useQuery({
    queryKey: queryKeys.pendingReceipts(year),
    queryFn: ({ signal }) => fetchPendingReceipts(year, signal),
  });
}

/** Archivo de 領収書・証明書 del 年度 activo con filtros de 電帳法. */
export function useEvidence(filters: EvidenceFilters = {}): UseQueryResult<EvidenceList> {
  const year = useActiveYear();
  return useQuery({
    queryKey: queryKeys.evidence(year, filters),
    queryFn: ({ signal }) => fetchEvidence(year, filters, signal),
  });
}

/**
 * Lista los 年度 del contribuyente (year + status) + el año activo por defecto.
 * Alimenta el selector de 年度 del header. `staleTime` corto: cambia poco (solo
 * al abrir/cerrar años), pero queremos ver un año nuevo recién creado.
 */
export function useFiscalYears(): UseQueryResult<FiscalYearList> {
  return useQuery({
    queryKey: queryKeys.fiscalYears,
    queryFn: ({ signal }) => fetchFiscalYears(signal),
    staleTime: 30_000,
  });
}

/**
 * Abre un 年度 nuevo (POST /fiscal-years, idempotente) e invalida la lista para
 * que aparezca en el selector. Al éxito, deja el año recién abierto como activo.
 */
export function useCreateFiscalYear() {
  const setActiveYear = useUiStore((s) => s.setActiveYear);
  const qc = useQueryClient();
  return useMutation<FiscalYearItem, Error, number>({
    mutationFn: (year: number) => createFiscalYear(year),
    onSuccess: (fy) => {
      void qc.invalidateQueries({ queryKey: queryKeys.fiscalYears });
      void qc.invalidateQueries({ queryKey: queryKeys.deductions(fy.year) });
      if (fy.year === 2026) {
        void qc.invalidateQueries({ queryKey: ["year-end-profile", 2026] });
      }
      if (fy.rules_available) setActiveYear(fy.year);
      toastSaved();
    },
  });
}

/** Saldos manuales de apertura del 年度 (期首残高). */
export function useOpeningBalances(
  year: number,
  enabled = true,
): UseQueryResult<OpeningBalanceSummary> {
  return useQuery({
    queryKey: queryKeys.openingBalances(year),
    queryFn: ({ signal }) => fetchOpeningBalances(year, signal),
    enabled,
  });
}

/** Guarda/reemplaza los 期首残高 e invalida los cálculos dependientes. */
export function useUpsertOpeningBalances(year: number) {
  const qc = useQueryClient();
  return useMutation<OpeningBalanceSummary, Error, OpeningBalanceLineInput[]>({
    mutationFn: (balances) => upsertOpeningBalances(year, balances),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.openingBalances(year) });
      void qc.invalidateQueries({ queryKey: queryKeys.filingDraft(year) });
      void qc.invalidateQueries({ queryKey: queryKeys.fiscalYears });
      toastSaved();
    },
  });
}

/** Estado de los proveedores OCR (toggles del settings). */
export function useOcrProviders(): UseQueryResult<ProvidersResponse> {
  return useQuery({
    queryKey: queryKeys.providers,
    queryFn: ({ signal }) => fetchOcrProviders(signal),
  });
}

/** Uso diario de cuota por proveedor cloud (contador del free tier). */
export function useOcrUsage(): UseQueryResult<UsageResponse> {
  return useQuery({
    queryKey: queryKeys.ocrUsage,
    queryFn: ({ signal }) => fetchOcrUsage(signal),
    // Refresca periodicamente para reflejar el consumo en vivo.
    refetchInterval: 30_000,
  });
}

// --- 控除ウィザード (Fase 3B-1) --------------------------------------------

/** Lista de 控除 registradas del 年度 + total efectivo (incl. 基礎控除). */
export function useDeductions(
  yearArg?: number,
): UseQueryResult<DeductionList> {
  const active = useActiveYear();
  const year = yearArg ?? active;
  return useQuery({
    queryKey: queryKeys.deductions(year),
    queryFn: ({ signal }) => fetchDeductions(year, signal),
  });
}

/** Efecto de las 控除 sobre el impuesto (total aplicado + 節税額 total). */
export function useDeductionSummary(
  yearArg?: number,
): UseQueryResult<DeductionSummary> {
  const active = useActiveYear();
  const year = yearArg ?? active;
  return useQuery({
    queryKey: queryKeys.deductionSummary(year),
    queryFn: ({ signal }) => fetchDeductionSummary(year, signal),
  });
}

/** Sugerencias proactivas de 控除 que el usuario podria estar perdiendo. */
type FreshQueryResult<T> = Omit<UseQueryResult<T>, "data" | "isLoading"> & {
  data: T | undefined;
  isLoading: boolean;
};

function freshQueryResult<T>(query: UseQueryResult<T>): FreshQueryResult<T> {
  return {
    ...query,
    data: query.isFetching || query.isError ? undefined : query.data,
    isLoading: query.isLoading || query.isFetching,
  };
}

export function useDeductionSuggestions(
  yearArg?: number,
): FreshQueryResult<DeductionSuggestion[]> {
  const active = useActiveYear();
  const year = yearArg ?? active;
  return freshQueryResult(useQuery({
    queryKey: queryKeys.deductionSuggestions(year),
    queryFn: ({ signal }) => fetchDeductionSuggestions(year, signal),
  }));
}

/** Recomendaciones fiscales priorizadas del 年度 (motor 節税, plan 08). */
export function useRecommendations(
  yearArg?: number,
): FreshQueryResult<RecommendationReport> {
  const active = useActiveYear();
  const year = yearArg ?? active;
  return freshQueryResult(useQuery({
    queryKey: queryKeys.recommendations(year),
    queryFn: ({ signal }) => fetchRecommendations(year, signal),
    // Depende del estado fiscal (控除/収入): cache corta para reflejar cambios.
    staleTime: 10_000,
  }));
}

/** Invalida todo lo que depende de las 控除 (lista, summary, sugerencias, filing). */
function useInvalidateDeductions(year: number) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: queryKeys.deductions(year) });
    void qc.invalidateQueries({ queryKey: queryKeys.deductionSummary(year) });
    void qc.invalidateQueries({ queryKey: queryKeys.deductionSuggestions(year) });
    // Las recomendaciones (節税) salen del mismo estado fiscal: revalidar.
    void qc.invalidateQueries({ queryKey: queryKeys.recommendations(year) });
    // El 予想納税額 del dashboard, el chip del header y el wizard salen del
    // mismo motor (`/filing/draft`): al cambiar una 控除 hay que recalcularlo.
    void qc.invalidateQueries({ queryKey: queryKeys.filingDraft(year) });
  };
}

/** Crea una 控除 e invalida el calculo (el impuesto baja al instante). */
export function useCreateDeduction(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const invalidate = useInvalidateDeductions(year);
  return useMutation({
    mutationFn: (payload: DeductionCreate) => createDeduction(year, payload),
    onSuccess: () => {
      invalidate();
      // Micro-feedback "保存しました" al registrar una 控除 en el wizard.
      toastSaved();
    },
  });
}

/** Edita el monto / meta de una 控除 e invalida el calculo. */
export function usePatchDeduction(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const invalidate = useInvalidateDeductions(year);
  return useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: string;
      patch: { amount?: number; meta?: Record<string, unknown> | null };
    }) => patchDeduction(id, patch),
    onSuccess: () => {
      invalidate();
      // Micro-feedback "保存しました" al actualizar una 控除 existente.
      toastSaved();
    },
  });
}

/** Borra una 控除 e invalida el calculo (el impuesto sube de nuevo). */
export function useDeleteDeduction(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const invalidate = useInvalidateDeductions(year);
  return useMutation({
    mutationFn: (id: string) => deleteDeduction(id),
    onSuccess: invalidate,
  });
}

// --- 控除証明書 XML import (Nivel 2 e-Tax) ---------------------------------

/**
 * Genera el preview de un XML de 控除証明書 (生命保険/地震/iDeCo/国民年金/寄附金):
 * detecta el tipo, calcula el 控除額 y NO persiste. El usuario lo revisa y
 * confirma, igual que el import de CSV.
 */
export function useKoujoXmlPreview(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  return useMutation<KoujoXmlPreview, Error, File>({
    mutationFn: (file: File) => previewKoujoXml(file, year),
  });
}

/**
 * Crea (o suma a) la 控除 con el monto confirmado del 控除証明書 e invalida el
 * cálculo (el impuesto baja al instante, como al registrar en el wizard).
 */
export function useKoujoXmlCommit(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const invalidate = useInvalidateDeductions(year);
  return useMutation<KoujoXmlCommitResponse, Error, KoujoXmlCommit>({
    mutationFn: (payload) => commitKoujoXml(year, payload),
    onSuccess: () => {
      invalidate();
      toastSaved();
    },
  });
}

/**
 * Confirma una transaccion (estampar el sello) e invalida la bandeja.
 *
 * Acepta correcciones opcionales para confirmar de un toque desde la camara:
 * el usuario toca el 科目 correcto y se manda todo junto. El backend aprende la
 * regla del 取引先 para la proxima foto de la misma tienda.
 */
export function useConfirmReceipt() {
  const year = useActiveYear();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, corrections }: { id: string; corrections?: ReceiptCorrections }) =>
      confirmReceipt(id, corrections),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.pendingReceipts(year) });
      // Confirmar un gasto lo suma al 事業所得 del filing: recalcular el 納付額.
      void qc.invalidateQueries({ queryKey: queryKeys.filingDraft(year) });
      void qc.invalidateQueries({ queryKey: queryKeys.consumption(year) });
    },
  });
}

/**
 * Edita campos de una transaccion (ej. 勘定科目) y persiste via PATCH. Hace
 * update optimista de la cache de la bandeja para que el cambio se vea al
 * instante, y revalida al confirmar el servidor.
 */
export function usePatchReceipt() {
  const year = useActiveYear();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: string;
      patch: { account_code?: string; vendor?: string; date?: string };
    }) => patchReceipt(id, patch),
    onSuccess: (updated) => {
      qc.setQueryData<Transaction[]>(queryKeys.pendingReceipts(year), (prev) =>
        prev?.map((t) => (t.id === updated.id ? { ...t, ...updated } : t)),
      );
      // Micro-feedback "保存しました" al editar el 勘定科目 (persistido por PATCH).
      toastSaved();
    },
  });
}

/** Persiste los toggles OCR (switch maestro + proveedores) e invalida el estado. */
export function usePatchOcrProviders() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: OcrSettingsPatch) => patchOcrProviders(patch),
    onSuccess: (data) => {
      qc.setQueryData<ProvidersResponse>(queryKeys.providers, data);
      // Ajustar el limite diario cambia el porcentaje/estado del contador.
      void qc.invalidateQueries({ queryKey: queryKeys.ocrUsage });
    },
  });
}

/** Confirma N transacciones en lote (batch review). */
export function useBatchConfirm() {
  const year = useActiveYear();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[]) => batchConfirmReceipts(ids),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.pendingReceipts(year) });
      // Confirmar gastos en lote cambia el 事業所得: recalcular el 納付額.
      void qc.invalidateQueries({ queryKey: queryKeys.filingDraft(year) });
      void qc.invalidateQueries({ queryKey: queryKeys.consumption(year) });
    },
  });
}

// --- 収入 (IncomeSource) — ingresos editables ------------------------------

/** Lista de fuentes de ingreso del 年度 + totales (売上 / 源泉). */
export function useIncomeSources(
  yearArg?: number,
): UseQueryResult<IncomeSourceList> {
  const active = useActiveYear();
  const year = yearArg ?? active;
  return useQuery({
    queryKey: queryKeys.incomeSources(year),
    queryFn: ({ signal }) => fetchIncomeSources(year, signal),
  });
}

/** Invalida la lista de 収入 + el filing draft (el impuesto se recalcula). */
function useInvalidateIncomeSources(year: number) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: queryKeys.incomeSources(year) });
    // El 売上 alimenta el 事業所得 y el 源泉 descuenta el 納付額: al cambiar un
    // ingreso hay que recalcular el draft (dashboard, header chip, filing) y el
    // summary de 控除 (que situa el tramo marginal con el 売上 real).
    void qc.invalidateQueries({ queryKey: queryKeys.filingDraft(year) });
    void qc.invalidateQueries({ queryKey: queryKeys.deductionSummary(year) });
    void qc.invalidateQueries({ queryKey: queryKeys.deductions(year) });
  };
}

/** Crea una fuente de ingreso e invalida el calculo (impuesto en vivo). */
export function useCreateIncomeSource(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const invalidate = useInvalidateIncomeSources(year);
  return useMutation({
    mutationFn: (payload: IncomeSourceCreate) =>
      createIncomeSource(year, payload),
    onSuccess: () => {
      invalidate();
      toastSaved();
    },
  });
}

/** Edita gross / withholding / expenses de una fuente e invalida el calculo. */
export function usePatchIncomeSource(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const invalidate = useInvalidateIncomeSources(year);
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: IncomeSourcePatch }) =>
      patchIncomeSource(id, patch),
    onSuccess: () => {
      invalidate();
      toastSaved();
    },
  });
}

/** Borra una fuente de ingreso e invalida el calculo. */
export function useDeleteIncomeSource(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const invalidate = useInvalidateIncomeSources(year);
  return useMutation({
    mutationFn: (id: string) => deleteIncomeSource(id),
    onSuccess: invalidate,
  });
}

// --- 確定申告 (Fase 3B-2) --------------------------------------------------

/**
 * Arma el 確定申告 del 年度 y devuelve el resumen completo (calculo, PL/BS,
 * checklist). El draft se (re)calcula de forma determinista desde los 仕訳
 * confirmados + las 控除 reales: por eso usamos `createFilingDraft` (POST) como
 * `queryFn` — es idempotente y siempre refleja el estado actual. Si el usuario
 * confirma mas 仕訳 o agrega 控除, refetch trae los numeros nuevos.
 */
export function useFilingDraft(
  yearArg?: number,
): FreshQueryResult<FilingSummary> {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const query = useQuery({
    queryKey: queryKeys.filingDraft(year),
    queryFn: () => createFilingDraft(year),
    staleTime: 10_000,
  });
  // React Query puede conservar datos anteriores tras un error de actualización.
  // Un cálculo antiguo no debe reaparecer en cabecera, panel ni otras pantallas.
  return freshQueryResult(query);
}

// --- 消費税 (Consumption tax) ----------------------------------------------

/**
 * Calcula el 消費税 del 年度 (las 3 opciones + recomendacion). Solo tiene sentido
 * si el contribuyente es 課税事業者; si es 免税, el backend devuelve
 * `is_taxable=false`.
 */
export function useConsumption(
  yearArg?: number,
): UseQueryResult<ConsumptionResult> {
  const active = useActiveYear();
  const year = yearArg ?? active;
  return useQuery({
    queryKey: queryKeys.consumption(year),
    queryFn: ({ signal }) => fetchConsumption(year, signal),
    staleTime: 10_000,
  });
}

/** Config del 消費税 del contribuyente (課税事業者 + metodo + 事業区分). */
export function useTaxpayer(): UseQueryResult<TaxpayerConsumption> {
  return useQuery({
    queryKey: queryKeys.taxpayer,
    queryFn: ({ signal }) => fetchTaxpayer(signal),
  });
}

/** Perfil mínimo para el borrador de 年末調整; no incluye My Number. */
export function useYearEndProfile(): UseQueryResult<YearEndProfile> {
  return useQuery({
    queryKey: ["year-end-profile", 2026],
    queryFn: ({ signal }) => fetchYearEndProfile(signal),
  });
}

/**
 * Actualiza la config del 消費税. Al cambiar 課税/metodo/区分 se recalcula el
 * 消費税 (la seccion aparece/desaparece y las opciones cambian).
 */
export function usePatchTaxpayer(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: TaxpayerConsumptionPatch) => patchTaxpayer(patch),
    onSuccess: (data) => {
      qc.setQueryData<TaxpayerConsumption>(queryKeys.taxpayer, data);
      void qc.invalidateQueries({ queryKey: queryKeys.consumption(year) });
      toastSaved();
    },
  });
}

// --- Onboarding guiado (primera vez) ---------------------------------------

/**
 * Estado del onboarding. La app lo consulta al cargar: si `onboarded` es
 * `false`, muestra el flujo guiado en vez del dashboard. `staleTime: Infinity`
 * porque solo cambia por accion explicita (completar / rehacer), que invalidan.
 */
export function useOnboardingStatus(): UseQueryResult<OnboardingStatus> {
  return useQuery({
    queryKey: queryKeys.onboarding,
    queryFn: ({ signal }) => fetchOnboardingStatus(signal),
    staleTime: Infinity,
  });
}

/**
 * Completa el onboarding con el perfil del usuario. Al terminar invalida TODO
 * lo que depende del perfil/ingresos (status, taxpayer, ingresos, draft) para
 * que el dashboard entre ya con los datos cargados.
 */
export function useCompleteOnboarding(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const qc = useQueryClient();
  return useMutation<OnboardingCompleteResult, Error, OnboardingComplete>({
    mutationFn: (payload) => completeOnboarding(payload, year),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.onboarding });
      void qc.invalidateQueries({ queryKey: queryKeys.taxpayer });
      void qc.invalidateQueries({ queryKey: queryKeys.incomeSources(year) });
      void qc.invalidateQueries({ queryKey: queryKeys.filingDraft(year) });
      void qc.invalidateQueries({ queryKey: queryKeys.consumption(year) });
    },
  });
}

/**
 * Rehacer el onboarding: marca `onboarded=false` en el Taxpayer (via PATCH
 * /taxpayer) e invalida el status para que la app vuelva a mostrar el flujo.
 */
export function useResetOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => patchTaxpayer({ onboarded: false }),
    onSuccess: (data) => {
      qc.setQueryData<TaxpayerConsumption>(queryKeys.taxpayer, data);
      void qc.invalidateQueries({ queryKey: queryKeys.onboarding });
    },
  });
}

/** Sube un recibo (multipart) e invalida la bandeja al terminar. */
export function useUploadReceipt() {
  const year = useActiveYear();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => uploadReceipt(file, year),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.pendingReceipts(year) });
      void qc.invalidateQueries({ queryKey: ["evidence", year] });
    },
  });
}

// --- CSV import 取り込み (Fase 4-1) ----------------------------------------

/**
 * Genera el preview de un CSV de banco/tarjeta (filas + 仕訳 propuesto + flag de
 * duplicado), SIN persistir. El usuario lo revisa antes de confirmar. Acepta un
 * mapeo manual opcional para cuando la auto-deteccion de columnas falla.
 */
export function useImportPreview() {
  return useMutation({
    mutationFn: ({
      file,
      mapping,
    }: {
      file: File;
      mapping?: CsvManualMapping;
    }) => previewCsvImport(file, mapping),
  });
}

/**
 * Persiste las filas seleccionadas como transacciones pending e invalida la
 * bandeja de 仕訳 (los nuevos asientos aparecen al instante). Idempotente: el
 * backend omite los duplicados.
 */
export function useImportCommit() {
  const year = useActiveYear();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (rows: CsvCommitRow[]) => commitCsvImport(rows),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.pendingReceipts(year) });
    },
  });
}

// --- 過去の申告 (archivo histórico de declaraciones anteriores) -------------

/** Lista las declaraciones históricas + la serie de comparación año a año. */
export function usePastFilings(): UseQueryResult<PastFilingList> {
  return useQuery({
    queryKey: queryKeys.pastFilings,
    queryFn: ({ signal }) => fetchPastFilings(signal),
  });
}

/**
 * Sube un PDF de 確定申告 viejo (+ año opcional) e invalida el listado. Devuelve
 * `duplicate`/`extracted` para que la pantalla muestre el feedback adecuado.
 */
export function useUploadPastFiling() {
  const qc = useQueryClient();
  return useMutation<PastFilingUpload, Error, { file: File; year?: number }>({
    mutationFn: ({ file, year }) => uploadPastFiling(file, year),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: queryKeys.pastFilings });
      // Toast distinto si fue duplicado (ya estaba) vs nuevo archivo.
      if (!data.duplicate) toastSaved();
    },
  });
}

/** Corrige los montos extraídos de un registro histórico e invalida el listado. */
export function usePatchPastFiling() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: PastFilingPatch }) =>
      patchPastFiling(id, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.pastFilings });
      toastSaved();
    },
  });
}

/** Borra un registro histórico e invalida el listado. */
export function useDeletePastFiling() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deletePastFiling(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.pastFilings });
    },
  });
}

// --- 家計簿 (libro de gastos personales, NO fiscal) ------------------------

/** Lista los gastos personales de un mes (家計簿). */
export function useHouseholdExpenses(
  year: number,
  month: number,
): UseQueryResult<HouseholdExpense[]> {
  return useQuery({
    queryKey: queryKeys.household(year, month),
    queryFn: ({ signal }) => fetchHouseholdExpenses(year, month, signal),
  });
}

/** Resumen del mes del 家計簿 (total + desglose por 費目). */
export function useHouseholdSummary(
  year: number,
  month: number,
): UseQueryResult<HouseholdSummary> {
  return useQuery({
    queryKey: queryKeys.householdSummary(year, month),
    queryFn: ({ signal }) => fetchHouseholdSummary(year, month, signal),
  });
}

/**
 * Invalida la lista y el resumen del mes del 家計簿. NO toca el filing draft ni
 * nada fiscal: el 家計簿 es 100% aditivo y no afecta la declaración.
 */
function useInvalidateHousehold(year: number, month: number) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: queryKeys.household(year, month) });
    void qc.invalidateQueries({
      queryKey: queryKeys.householdSummary(year, month),
    });
  };
}

/** Crea un gasto personal manual e invalida el mes. */
export function useCreateHouseholdExpense(year: number, month: number) {
  const invalidate = useInvalidateHousehold(year, month);
  return useMutation({
    mutationFn: (payload: HouseholdExpenseCreate) =>
      createHouseholdExpense(payload),
    onSuccess: () => {
      invalidate();
      toastSaved();
    },
  });
}

/** Edita un gasto personal e invalida el mes. */
export function usePatchHouseholdExpense(year: number, month: number) {
  const invalidate = useInvalidateHousehold(year, month);
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: HouseholdExpensePatch }) =>
      patchHouseholdExpense(id, patch),
    onSuccess: () => {
      invalidate();
      toastSaved();
    },
  });
}

/** Borra un gasto personal e invalida el mes. */
export function useDeleteHouseholdExpense(year: number, month: number) {
  const invalidate = useInvalidateHousehold(year, month);
  return useMutation({
    mutationFn: (id: string) => deleteHouseholdExpense(id),
    onSuccess: invalidate,
  });
}

/**
 * Mueve un ítem del 仕訳トレイ al 家計簿 (puente 事業→家計). Invalida la bandeja de
 * 仕訳 (la transacción sale como rechazada) y el 家計簿 del mes del gasto.
 */
export function useHouseholdFromTransaction() {
  const year = useActiveYear();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      transactionId,
      category,
    }: {
      transactionId: string;
      category: string;
    }) => householdFromTransaction(transactionId, category),
    onSuccess: (expense) => {
      // La transacción quedó rechazada: refrescar la bandeja de 仕訳.
      void qc.invalidateQueries({ queryKey: queryKeys.pendingReceipts(year) });
      // Refrescar el 家計簿 del mes del gasto recién creado.
      const d = new Date(expense.date);
      void qc.invalidateQueries({
        queryKey: queryKeys.household(d.getFullYear(), d.getMonth() + 1),
      });
      void qc.invalidateQueries({
        queryKey: queryKeys.householdSummary(d.getFullYear(), d.getMonth() + 1),
      });
      toastSaved();
    },
  });
}

// --- 売上・請求 -----------------------------------------------------------

export function useBusinessProfile(): UseQueryResult<BusinessProfile> {
  return useQuery({
    queryKey: queryKeys.businessProfile,
    queryFn: ({ signal }) => fetchBusinessProfile(signal),
  });
}

export function usePatchBusinessProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: BusinessProfilePatch) => patchBusinessProfile(patch),
    onSuccess: (profile) => {
      qc.setQueryData<BusinessProfile>(queryKeys.businessProfile, profile);
      toastSaved();
    },
  });
}

export function useSalesCustomers() {
  return useQuery({
    queryKey: queryKeys.salesCustomers,
    queryFn: ({ signal }) => fetchSalesCustomers(signal),
  });
}

export function useCreateSalesCustomer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (customer: SalesCustomerSnapshot) => createSalesCustomer(customer),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.salesCustomers });
      toastSaved();
    },
  });
}

export function useSalesDocuments(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  return useQuery({
    queryKey: queryKeys.salesDocuments(year),
    queryFn: ({ signal }) => fetchSalesDocuments(undefined, signal),
  });
}

function useInvalidateSalesDocuments(year: number) {
  const qc = useQueryClient();
  return (document?: SalesDocument) => {
    void qc.invalidateQueries({ queryKey: queryKeys.salesDocuments(year) });
    if (document) {
      qc.setQueryData<SalesDocument[]>(queryKeys.salesDocuments(year), (previous) => {
        if (!previous) return [document];
        const exists = previous.some((item) => item.id === document.id);
        return exists
          ? previous.map((item) => (item.id === document.id ? document : item))
          : [document, ...previous];
      });
    }
  };
}

export function useCreateSalesDocument(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const update = useInvalidateSalesDocuments(year);
  return useMutation<SalesDocument, Error, SalesDocumentCreate>({
    mutationFn: createSalesDocument,
    onSuccess: update,
  });
}

export function usePatchSalesDocument(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const update = useInvalidateSalesDocuments(year);
  return useMutation<
    SalesDocument,
    Error,
    { id: string; patch: SalesDocumentPatch }
  >({
    mutationFn: ({ id, patch }) => patchSalesDocument(id, patch),
    onSuccess: update,
  });
}

export function useIssueSalesDocument(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const update = useInvalidateSalesDocuments(year);
  return useMutation({ mutationFn: issueSalesDocument, onSuccess: update });
}

export function useConvertSalesDocument(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const update = useInvalidateSalesDocuments(year);
  return useMutation<
    SalesDocument,
    Error,
    { id: string; targetType: SalesDocumentType }
  >({
    mutationFn: ({ id, targetType }) => convertSalesDocument(id, targetType),
    onSuccess: update,
  });
}

export function useDuplicateSalesDocument(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const update = useInvalidateSalesDocuments(year);
  return useMutation({ mutationFn: duplicateSalesDocument, onSuccess: update });
}

export function useSendSalesDocument(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const update = useInvalidateSalesDocuments(year);
  return useMutation({ mutationFn: sendSalesDocument, onSuccess: update });
}

export function useVoidSalesDocument(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const update = useInvalidateSalesDocuments(year);
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      voidSalesDocument(id, reason),
    onSuccess: update,
  });
}

export function useCreateSalesPayment(yearArg?: number) {
  const active = useActiveYear();
  const year = yearArg ?? active;
  const update = useInvalidateSalesDocuments(year);
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: SalesPaymentCreate }) =>
      createSalesPayment(id, payload),
    onSuccess: () => update(),
  });
}
