import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Card, EmptyState, ErrorState, Skeleton } from "../components/ui";
import {
  useBusinessProfile,
  useConvertSalesDocument,
  useCreateSalesCustomer,
  useCreateSalesDocument,
  useCreateSalesPayment,
  useDuplicateSalesDocument,
  useIssueSalesDocument,
  usePatchSalesDocument,
  useSalesCustomers,
  useSalesDocuments,
  useSendSalesDocument,
  useVoidSalesDocument,
} from "../lib/hooks";
import {
  salesDocumentPdfUrl,
  type BusinessProfile,
  type SalesDocument,
  type SalesDocumentCreate,
  type SalesDocumentStatus,
  type SalesDocumentType,
  type SalesLineInput,
  type SalesPriceMode,
  type SalesTaxCategory,
} from "../lib/api";
import { resolveBrandImageSrc } from "../lib/brandAssets";
import { formatYen } from "../lib/format";
import { screenVariants } from "../variants/layoutVariants";

const TYPE_LABEL: Record<SalesDocumentType, string> = {
  estimate: "見積書",
  delivery_note: "納品書",
  invoice: "請求書",
  receipt: "領収書",
  purchase_order: "発注書",
  order_acknowledgement: "発注請書",
  consolidated_invoice: "合算請求書",
  corrected_invoice: "修正請求書",
};

const STATUS_LABEL: Record<SalesDocumentStatus, string> = {
  draft: "下書き",
  issued: "発行済み",
  sent: "送付済み",
  awaiting_payment: "入金待ち",
  partially_paid: "一部入金",
  paid: "入金済み",
  voided: "取消",
};

const STATUS_TONE: Record<SalesDocumentStatus, string> = {
  draft: "bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]",
  issued: "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]",
  sent: "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]",
  awaiting_payment: "bg-[var(--color-kohaku-soft)] text-[var(--color-kohaku)]",
  partially_paid: "bg-[var(--color-kohaku-soft)] text-[var(--color-kohaku)]",
  paid: "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]",
  voided: "bg-red-50 text-[var(--color-shuiro)]",
};

const PAYABLE_DOCUMENT_TYPES = new Set<SalesDocumentType>([
  "invoice",
  "consolidated_invoice",
  "corrected_invoice",
]);
const QUALIFIED_DOCUMENT_TYPES = new Set<SalesDocumentType>([
  ...PAYABLE_DOCUMENT_TYPES,
  "receipt",
]);

function isPayableDocument(type: SalesDocumentType): boolean {
  return PAYABLE_DOCUMENT_TYPES.has(type);
}

function canBeQualifiedDocument(type: SalesDocumentType): boolean {
  return QUALIFIED_DOCUMENT_TYPES.has(type);
}

const fieldClass =
  "w-full rounded-lg border border-[var(--color-hairline)] bg-white px-3 py-2.5 text-sm text-[var(--color-sumi)] outline-none transition focus:border-[var(--color-seiji)]";

interface EditorLine {
  key: string;
  description: string;
  quantity: string;
  unit: string;
  unitPrice: string;
  discountAmount: string;
  taxCategory: SalesTaxCategory;
}

interface EditorState {
  id: string | null;
  type: SalesDocumentType;
  status: SalesDocumentStatus;
  number: string | null;
  customerId: string | null;
  customerName: string;
  honorific: string;
  subject: string;
  issueDate: string;
  dueDate: string;
  notes: string;
  priceMode: SalesPriceMode;
  qualified: boolean;
  lines: EditorLine[];
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function newLine(): EditorLine {
  return {
    key: crypto.randomUUID(),
    description: "",
    quantity: "1",
    unit: "式",
    unitPrice: "",
    discountAmount: "0",
    taxCategory: "standard_10",
  };
}

function emptyEditor(type: SalesDocumentType, profile: BusinessProfile): EditorState {
  const issueDate = today();
  const due = new Date();
  due.setDate(due.getDate() + (profile.payment_terms_days ?? 30));
  const defaultNotes =
    type === "receipt"
      ? profile.receipt_message || "上記金額を正に領収いたしました。"
      : isPayableDocument(type)
        ? profile.invoice_message || profile.transfer_fee_note || ""
        : "";
  return {
    id: null,
    type,
    status: "draft",
    number: null,
    customerId: null,
    customerName: "",
    honorific: profile.default_customer_honorific || "御中",
    subject: type === "receipt" ? profile.receipt_proviso ?? "" : "",
    issueDate,
    dueDate: due.toISOString().slice(0, 10),
    notes: defaultNotes,
    priceMode: profile.price_mode,
    qualified: false,
    lines: [newLine()],
  };
}

function editorFromDocument(document: SalesDocument): EditorState {
  return {
    id: document.id,
    type: document.document_type,
    status: document.status,
    number: document.document_number,
    customerId: document.customer_id,
    customerName: document.customer.name,
    honorific: document.customer.honorific,
    subject: document.subject ?? "",
    issueDate: document.issue_date,
    dueDate: document.due_date ?? "",
    notes: document.notes ?? "",
    priceMode: document.price_mode,
    qualified: document.is_qualified_invoice,
    lines: document.lines.map((line) => ({
      key: line.id,
      description: line.description,
      quantity: String(line.quantity),
      unit: line.unit,
      unitPrice: String(line.unit_price),
      discountAmount: String(line.discount_amount ?? 0),
      taxCategory: line.tax_category,
    })),
  };
}

function payloadFromEditor(editor: EditorState): SalesDocumentCreate {
  const lines: SalesLineInput[] = editor.lines
    .filter((line) => line.description.trim() && Number(line.unitPrice) >= 0)
    .map((line) => ({
      description: line.description.trim(),
      quantity: line.quantity || "1",
      unit: line.unit || "式",
      unit_price: Number(line.unitPrice || 0),
      discount_amount: Number(line.discountAmount || 0),
      tax_category: line.taxCategory,
    }));
  return {
    document_type: editor.type,
    customer_id: editor.customerId,
    customer: editor.customerId
      ? undefined
      : { name: editor.customerName.trim(), honorific: editor.honorific },
    subject: editor.subject || null,
    issue_date: editor.issueDate,
    due_date: isPayableDocument(editor.type) ? editor.dueDate || null : null,
    notes: editor.notes || null,
    price_mode: editor.priceMode,
    is_qualified_invoice: editor.qualified,
    lines,
  };
}

export function SalesDocumentsScreen() {
  const documentsQuery = useSalesDocuments();
  const profileQuery = useBusinessProfile();
  const customersQuery = useSalesCustomers();
  const createCustomerMutation = useCreateSalesCustomer();
  const createMutation = useCreateSalesDocument();
  const patchMutation = usePatchSalesDocument();
  const issueMutation = useIssueSalesDocument();
  const convertMutation = useConvertSalesDocument();
  const duplicateMutation = useDuplicateSalesDocument();
  const sendMutation = useSendSalesDocument();
  const voidMutation = useVoidSalesDocument();
  const paymentMutation = useCreateSalesPayment();
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [filter, setFilter] = useState<"all" | SalesDocumentType>("all");
  const [paymentOpen, setPaymentOpen] = useState(false);

  const documents = documentsQuery.data ?? [];
  const filtered = filter === "all" ? documents : documents.filter((item) => item.document_type === filter);
  const outstanding = documents.reduce((sum, item) => sum + item.outstanding, 0);
  const awaitingCount = documents.filter((item) =>
    ["awaiting_payment", "partially_paid"].includes(item.status),
  ).length;
  const currentDocument = editor?.id
    ? documents.find((item) => item.id === editor.id) ?? null
    : null;
  const pending =
    createCustomerMutation.isPending ||
    createMutation.isPending ||
    patchMutation.isPending ||
    issueMutation.isPending ||
    convertMutation.isPending ||
    duplicateMutation.isPending ||
    sendMutation.isPending ||
    voidMutation.isPending ||
    paymentMutation.isPending;
  const error =
    createCustomerMutation.error ??
    createMutation.error ??
    patchMutation.error ??
    issueMutation.error ??
    convertMutation.error ??
    duplicateMutation.error ??
    sendMutation.error ??
    voidMutation.error ??
    paymentMutation.error;

  const startNew = (type: SalesDocumentType) => {
    if (!profileQuery.data) return;
    setEditor(emptyEditor(type, profileQuery.data));
    setPaymentOpen(false);
  };

  const save = async (): Promise<SalesDocument | null> => {
    if (!editor) return null;
    const payload = payloadFromEditor(editor);
    const document = editor.id
      ? await patchMutation.mutateAsync({ id: editor.id, patch: payload })
      : await createMutation.mutateAsync(payload);
    setEditor(editorFromDocument(document));
    return document;
  };

  const issue = async () => {
    const saved = await save();
    if (!saved) return;
    const issued = await issueMutation.mutateAsync(saved.id);
    setEditor(editorFromDocument(issued));
  };

  const actOnDocument = async (
    action: "duplicate" | "send" | "void" | "invoice" | "delivery" | "receipt",
  ) => {
    if (!editor?.id) return;
    let document: SalesDocument;
    if (action === "duplicate") document = await duplicateMutation.mutateAsync(editor.id);
    else if (action === "send") document = await sendMutation.mutateAsync(editor.id);
    else if (action === "void") {
      document = await voidMutation.mutateAsync({ id: editor.id, reason: "画面から取消" });
    } else {
      const targetType: SalesDocumentType =
        action === "invoice" ? "invoice" : action === "delivery" ? "delivery_note" : "receipt";
      document = await convertMutation.mutateAsync({ id: editor.id, targetType });
    }
    setEditor(editorFromDocument(document));
    setPaymentOpen(false);
  };

  if (documentsQuery.isLoading || profileQuery.isLoading) {
    return (
      <div className="mx-auto max-w-[1500px] space-y-4 px-4 py-6 sm:px-8">
        <Skeleton className="h-32" />
        <Skeleton className="h-[520px]" />
      </div>
    );
  }
  if (documentsQuery.isError || profileQuery.isError) {
    return (
      <ErrorState
        message="売上書類を読み込めませんでした。"
        onRetry={() => {
          void documentsQuery.refetch();
          void profileQuery.refetch();
        }}
      />
    );
  }

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-[1500px] px-4 py-6 sm:px-8 sm:py-8"
    >
      <header className="relative overflow-hidden rounded-[22px] bg-[var(--color-sumi)] px-5 py-6 text-white sm:px-8 sm:py-8">
        <div className="absolute right-20 top-10 h-24 w-24 rotate-12 border border-white/5" />
        <div className="relative flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
          <div>
            <p className="text-[10px] font-semibold tracking-[0.24em] text-white/55">SALES DOCUMENTS</p>
            <h2 className="mt-2 text-2xl font-bold tracking-[0.08em] sm:text-3xl">売上・請求</h2>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-white/65">
              見積書から領収書まで。必要な書類だけを、{profileQuery.data?.trade_name ?? "事業者"}の書式で美しく発行します。
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {([
              ["invoice", "請求書"],
              ["receipt", "領収書"],
              ["estimate", "見積書"],
              ["delivery_note", "納品書"],
            ] as const).map(([type, label]) => (
              <button
                key={type}
                type="button"
                onClick={() => startNew(type)}
                className="rounded-xl border border-white/15 bg-white/8 px-4 py-3 text-left transition hover:bg-white/14"
              >
                <span className="block text-lg leading-none">＋</span>
                <span className="mt-2 block whitespace-nowrap text-xs font-semibold">{label}を作成</span>
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="発行書類" value={`${documents.length}件`} />
        <Metric label="入金待ち" value={`${awaitingCount}件`} accent />
        <Metric label="未入金残高" value={formatYen(outstanding)} />
        <Metric label="発行者" value={profileQuery.data?.trade_name ?? "事業者"} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Card className="overflow-hidden self-start xl:sticky xl:top-4">
          <div className="border-b border-[var(--color-hairline)] px-4 py-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-[var(--color-sumi)]">書類一覧</h3>
              <span className="text-xs text-[var(--color-sumi-soft)]">{filtered.length}件</span>
            </div>
            <div className="mt-3 flex gap-1 overflow-x-auto pb-1">
              {([
                ["all", "すべて"],
                ["invoice", "請求"],
                ["receipt", "領収"],
                ["estimate", "見積"],
                ["delivery_note", "納品"],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setFilter(value)}
                  className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition ${filter === value ? "bg-[var(--color-sumi)] text-white" : "bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {filtered.length === 0 ? (
            <EmptyState
              icon="file"
              title="まだ書類がありません"
              hint="上のボタンから、必要な書類を直接作成できます。"
            />
          ) : (
            <div className="max-h-[620px] divide-y divide-[var(--color-hairline)] overflow-y-auto">
              {filtered.map((document) => (
                <button
                  key={document.id}
                  type="button"
                  onClick={() => {
                    setEditor(editorFromDocument(document));
                    setPaymentOpen(false);
                  }}
                  className={`w-full px-4 py-3.5 text-left transition hover:bg-[var(--color-paper-sink)]/65 ${editor?.id === document.id ? "bg-[var(--color-seiji-soft)]/55" : ""}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold text-[var(--color-sumi)]">
                      {TYPE_LABEL[document.document_type]}
                    </span>
                    <StatusBadge status={document.status} />
                  </div>
                  <p className="mt-1 truncate text-xs text-[var(--color-sumi-soft)]">
                    {document.customer.name || "取引先未設定"}
                  </p>
                  <div className="mt-2 flex items-end justify-between gap-2">
                    <span className="tabular text-[10px] text-[var(--color-sumi-soft)]">
                      {document.document_number ?? "DRAFT"}
                    </span>
                    <span className="tabular text-sm font-bold text-[var(--color-sumi)]">
                      {formatYen(document.total)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Card>

        {editor ? (
          <DocumentWorkspace
            editor={editor}
            setEditor={setEditor}
            profile={profileQuery.data!}
            customers={customersQuery.data ?? []}
            currentDocument={currentDocument}
            pending={pending}
            error={error?.message ?? null}
            paymentOpen={paymentOpen}
            setPaymentOpen={setPaymentOpen}
            onSave={() => void save()}
            onIssue={() => void issue()}
            onSaveCustomer={async () => {
              if (!editor.customerName.trim()) return;
              const customer = await createCustomerMutation.mutateAsync({
                name: editor.customerName.trim(),
                honorific: editor.honorific,
              });
              setEditor((current) =>
                current ? { ...current, customerId: customer.id } : current,
              );
            }}
            onAction={(action) => void actOnDocument(action)}
            onPayment={async (amount, method, paymentDate) => {
              if (!editor.id) return;
              await paymentMutation.mutateAsync({
                id: editor.id,
                payload: {
                  payment_date: paymentDate,
                  amount,
                  method,
                  idempotency_key: crypto.randomUUID(),
                  create_receipt: true,
                },
              });
              const refreshed = await documentsQuery.refetch();
              const updated = refreshed.data?.find((item) => item.id === editor.id);
              if (updated) setEditor(editorFromDocument(updated));
              setPaymentOpen(false);
            }}
          />
        ) : (
          <Card className="min-h-[560px]">
            <EmptyState
              icon="receipt"
              title="作成する書類を選んでください"
              hint="請求書や領収書を直接作ることも、既存の書類を変換することもできます。"
              action={
                <button
                  type="button"
                  onClick={() => startNew("invoice")}
                  className="rounded-full bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-semibold text-white"
                >
                  請求書を作成
                </button>
              }
            />
          </Card>
        )}
      </div>
    </motion.div>
  );
}

function DocumentWorkspace({
  editor,
  setEditor,
  profile,
  customers,
  currentDocument,
  pending,
  error,
  paymentOpen,
  setPaymentOpen,
  onSave,
  onIssue,
  onSaveCustomer,
  onAction,
  onPayment,
}: {
  editor: EditorState;
  setEditor: React.Dispatch<React.SetStateAction<EditorState | null>>;
  profile: NonNullable<ReturnType<typeof useBusinessProfile>["data"]>;
  customers: NonNullable<ReturnType<typeof useSalesCustomers>["data"]>;
  currentDocument: SalesDocument | null;
  pending: boolean;
  error: string | null;
  paymentOpen: boolean;
  setPaymentOpen: (open: boolean) => void;
  onSave: () => void;
  onIssue: () => void;
  onSaveCustomer: () => Promise<void>;
  onAction: (action: "duplicate" | "send" | "void" | "invoice" | "delivery" | "receipt") => void;
  onPayment: (amount: number, method: "cash" | "bank_transfer" | "card" | "other", date: string) => Promise<void>;
}) {
  const editable = editor.status === "draft";
  const update = (patch: Partial<EditorState>) => setEditor((current) => (current ? { ...current, ...patch } : current));
  const updateLine = (key: string, patch: Partial<EditorLine>) =>
    update({ lines: editor.lines.map((line) => (line.key === key ? { ...line, ...patch } : line)) });
  const totals = useMemo(() => previewTotals(editor), [editor]);

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-hairline)] bg-white px-4 py-3 sm:px-5">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-lg border border-[var(--color-sumi)] text-sm font-bold text-[var(--color-sumi)]">書</span>
            <div>
              <p className="text-sm font-bold text-[var(--color-sumi)]">{TYPE_LABEL[editor.type]}</p>
              <p className="tabular text-[10px] text-[var(--color-sumi-soft)]">{editor.number ?? "新規下書き"}</p>
            </div>
            <StatusBadge status={editor.status} />
            {currentDocument?.sent_at && (
              <span className="text-[10px] font-semibold text-[var(--color-seiji)]">
                送付済み
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {editable ? (
              <>
                <ActionButton label="下書き保存" onClick={onSave} disabled={pending} />
                <button
                  type="button"
                  onClick={onIssue}
                  disabled={pending}
                  className="rounded-full bg-[var(--color-shuiro)] px-5 py-2 text-xs font-bold text-white transition hover:bg-[var(--color-shuiro-deep)] disabled:opacity-40"
                >
                  発行する
                </button>
              </>
            ) : (
              <>
                <a
                  href={editor.id ? salesDocumentPdfUrl(editor.id) : "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full bg-[var(--color-sumi)] px-4 py-2 text-xs font-semibold text-white"
                >
                  PDF出力
                </a>
                {editor.status !== "voided" && <ActionButton label="複製" onClick={() => onAction("duplicate")} disabled={pending} />}
              </>
            )}
          </div>
        </div>

        <div className="grid xl:grid-cols-[minmax(320px,0.9fr)_minmax(350px,1.1fr)]">
          <div className="space-y-5 border-b border-[var(--color-hairline)] p-4 sm:p-5 xl:border-b-0 xl:border-r">
            <fieldset disabled={!editable || pending} className="space-y-5 disabled:opacity-75">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="書類の種類">
                  <select className={fieldClass} value={editor.type} onChange={(event) => update({ type: event.target.value as SalesDocumentType })}>
                    {Object.entries(TYPE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </Field>
                <Field label="取引先">
                  <select
                    className={fieldClass}
                    value={editor.customerId ?? ""}
                    onChange={(event) => {
                      const customer = customers.find((item) => item.id === event.target.value);
                      update({
                        customerId: customer?.id ?? null,
                        customerName: customer?.name ?? editor.customerName,
                        honorific: customer?.honorific ?? editor.honorific,
                      });
                    }}
                  >
                    <option value="">直接入力</option>
                    {customers.filter((item) => item.is_active).map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}
                  </select>
                </Field>
                <Field label="宛名">
                  <input className={fieldClass} value={editor.customerName} onChange={(event) => update({ customerName: event.target.value, customerId: null })} />
                  {!editor.customerId && editor.customerName.trim() && (
                    <button
                      type="button"
                      onClick={() => void onSaveCustomer()}
                      className="mt-1.5 text-[10px] font-semibold text-[var(--color-seiji)]"
                    >
                      ＋ 取引先として保存
                    </button>
                  )}
                </Field>
                <Field label="敬称">
                  <select className={fieldClass} value={editor.honorific} onChange={(event) => update({ honorific: event.target.value })}>
                    <option value="御中">御中</option>
                    <option value="様">様</option>
                  </select>
                </Field>
                <Field label="件名" className="sm:col-span-2">
                  <input className={fieldClass} value={editor.subject} onChange={(event) => update({ subject: event.target.value })} />
                </Field>
                <Field label="発行日">
                  <input type="date" className={fieldClass} value={editor.issueDate} onChange={(event) => update({ issueDate: event.target.value })} />
                </Field>
                {isPayableDocument(editor.type) && (
                  <Field label="お支払期限">
                    <input type="date" className={fieldClass} value={editor.dueDate} onChange={(event) => update({ dueDate: event.target.value })} />
                  </Field>
                )}
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-xs font-bold text-[var(--color-sumi)]">明細</p>
                  <button type="button" onClick={() => update({ lines: [...editor.lines, newLine()] })} className="text-xs font-semibold text-[var(--color-seiji)]">＋ 明細を追加</button>
                </div>
                <div className="space-y-3">
                  {editor.lines.map((line, index) => (
                    <div key={line.key} className="rounded-xl border border-[var(--color-hairline)] bg-[var(--color-paper)] p-3">
                      <div className="flex items-start gap-2">
                        <span className="tabular mt-2.5 text-[10px] text-[var(--color-sumi-soft)]">{String(index + 1).padStart(2, "0")}</span>
                        <input aria-label={`明細${index + 1}の品名`} className={fieldClass} placeholder="品名・作業内容" value={line.description} onChange={(event) => updateLine(line.key, { description: event.target.value })} />
                        {editor.lines.length > 1 && <button type="button" aria-label={`明細${index + 1}を削除`} onClick={() => update({ lines: editor.lines.filter((item) => item.key !== line.key) })} className="mt-2 text-sm text-[var(--color-sumi-soft)] hover:text-[var(--color-shuiro)]">×</button>}
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
                        <MiniField label="数量"><input inputMode="decimal" className={fieldClass} value={line.quantity} onChange={(event) => updateLine(line.key, { quantity: event.target.value })} /></MiniField>
                        <MiniField label="単位"><input className={fieldClass} value={line.unit} onChange={(event) => updateLine(line.key, { unit: event.target.value })} /></MiniField>
                        <MiniField label="単価"><input inputMode="numeric" className={fieldClass} value={line.unitPrice} onChange={(event) => updateLine(line.key, { unitPrice: event.target.value.replace(/\D/g, "") })} /></MiniField>
                        <MiniField label="値引き"><input inputMode="numeric" className={fieldClass} value={line.discountAmount} onChange={(event) => updateLine(line.key, { discountAmount: event.target.value.replace(/\D/g, "") })} /></MiniField>
                        <MiniField label="税区分"><select className={fieldClass} value={line.taxCategory} onChange={(event) => updateLine(line.key, { taxCategory: event.target.value as SalesTaxCategory })}><option value="standard_10">10%</option><option value="reduced_8">8%※</option><option value="exempt">非課税</option><option value="out_of_scope">対象外</option></select></MiniField>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="金額表示">
                  <select className={fieldClass} value={editor.priceMode} onChange={(event) => update({ priceMode: event.target.value as SalesPriceMode })}><option value="exclusive">税抜</option><option value="inclusive">税込</option></select>
                </Field>
                {canBeQualifiedDocument(editor.type) && (
                  <label className="flex items-center gap-2 self-end rounded-lg border border-[var(--color-hairline)] px-3 py-2.5 text-xs font-medium text-[var(--color-sumi)]">
                    <input type="checkbox" checked={editor.qualified} disabled={!profile.is_invoice_issuer} onChange={(event) => update({ qualified: event.target.checked })} />
                    適格請求書として発行
                  </label>
                )}
                <Field label="備考" className="sm:col-span-2">
                  <textarea className={`${fieldClass} min-h-20 resize-y`} value={editor.notes} onChange={(event) => update({ notes: event.target.value })} />
                </Field>
              </div>
            </fieldset>

            {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-xs text-[var(--color-shuiro)]">{error}</p>}

            {!editable && editor.status !== "voided" && (
              <div className="flex flex-wrap gap-2 border-t border-[var(--color-hairline)] pt-4">
                {editor.type === "estimate" && <ActionButton label="納品書に変換" onClick={() => onAction("delivery")} disabled={pending} />}
                {["estimate", "delivery_note"].includes(editor.type) && <ActionButton label="請求書に変換" onClick={() => onAction("invoice")} disabled={pending} />}
                <ActionButton
                  label={currentDocument?.sent_at ? "送付済み" : "送付済みにする"}
                  onClick={() => onAction("send")}
                  disabled={pending || Boolean(currentDocument?.sent_at)}
                />
                {isPayableDocument(editor.type) && editor.status !== "paid" && <ActionButton label="入金を登録" onClick={() => setPaymentOpen(!paymentOpen)} disabled={pending} />}
                <button type="button" onClick={() => onAction("void")} disabled={pending} className="rounded-full px-3 py-2 text-xs font-medium text-[var(--color-sumi-soft)] hover:text-[var(--color-shuiro)]">取消</button>
              </div>
            )}

            {paymentOpen && currentDocument && (
              <PaymentPanel document={currentDocument} pending={pending} onSubmit={onPayment} />
            )}
          </div>

          <div className="bg-[#e9e7e1] p-3 sm:p-6">
            <DocumentPreview editor={editor} profile={profile} totals={totals} />
          </div>
        </div>
      </Card>
    </div>
  );
}

function DocumentPreview({ editor, profile, totals }: { editor: EditorState; profile: NonNullable<ReturnType<typeof useBusinessProfile>["data"]>; totals: ReturnType<typeof previewTotals> }) {
  const issuerAddress = [profile.postal_code, profile.address_line1 || profile.address, profile.address_line2]
    .filter(Boolean)
    .join(" ");
  const logoSrc = profile.show_logo ? resolveBrandImageSrc(profile.logo_ref) : null;
  if (editor.type === "receipt") {
    return (
      <article aria-label="領収書プレビュー" className="mx-auto aspect-[1/1.414] w-full max-w-[620px] overflow-hidden bg-[#fffefa] p-[6%] text-[#17212b] shadow-[0_18px_50px_-24px_rgba(23,33,43,0.35)]">
        <div className="h-1.5 w-full bg-[#2d7d6d]" />
        <div className="mt-5 flex items-start justify-between">
          <div>
            <p className="text-[8px] tracking-[0.22em] text-[#66707a]">RECEIPT</p>
            <h3 className="mt-1 text-2xl font-bold tracking-[0.32em]">領 収 書</h3>
          </div>
          <div className="tabular text-right text-[8px] leading-5 text-[#66707a] sm:text-[10px]">
            <p>No. {editor.number ?? "DRAFT"}</p>
            <p>発行日　{editor.issueDate}</p>
          </div>
        </div>
        <div className="mt-7 flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <p className="truncate border-b border-[#17212b] pb-2 text-sm font-bold sm:text-base">
              {editor.customerName || "取引先名"}　{editor.honorific || "様"}
            </p>
          </div>
          {profile.show_stamp_box && (
            <div className="grid h-16 w-20 place-items-center rounded-lg border border-[#d7d9d8] bg-[#f5efe9] text-[8px] text-[#4b5563]">
              収入印紙
            </div>
          )}
        </div>
        <div className="mt-7 rounded-xl bg-[#1f5f53] px-5 py-4 text-white">
          <p className="text-[9px] text-white/70">領収金額</p>
          <p className="mt-1 text-2xl font-bold tabular-nums sm:text-3xl">{formatYen(totals.total)}</p>
          <p className="mt-1 text-right text-[8px] text-white/70">消費税等を含む</p>
        </div>
        <p className="mt-5 text-[9px] text-[#17212b]">
          但し　{editor.subject || profile.receipt_proviso || "商品・サービス代"}　として
        </p>
        <p className="mt-2 text-[8px] leading-4 text-[#66707a]">
          {editor.notes || profile.receipt_message || "上記金額を正に領収いたしました。"}
        </p>
        <div className="mt-5 rounded-xl border border-[#d7d9d8] p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-bold">{profile.trade_name}</p>
              {profile.show_representative && profile.representative_name && <p className="mt-1 text-[8px] text-[#66707a]">代表　{profile.representative_name}</p>}
              {(profile.department_name || profile.contact_person_name) && <p className="mt-1 text-[8px] text-[#66707a]">担当　{profile.department_name} {profile.contact_person_name}</p>}
              {issuerAddress && <p className="mt-1 max-w-72 text-[8px] leading-4 text-[#66707a]">{issuerAddress}</p>}
              {(profile.phone || profile.email) && <p className="mt-1 text-[8px] text-[#66707a]">{profile.phone} {profile.email}</p>}
              {editor.qualified && profile.registration_number && <p className="mt-1 text-[8px] font-semibold text-[#2d7d6d]">登録番号 {profile.registration_number}</p>}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {logoSrc && (
                <img
                  src={logoSrc}
                  alt="事業者 ロゴ"
                  className="h-14 w-20 rounded-lg border border-[#d7d9d8] object-cover"
                />
              )}
              {profile.show_seal && (
                <div className="grid h-16 w-16 place-items-center rounded-full border border-[#b24036] text-[10px] font-bold text-[#b24036]">
                  {profile.seal_text || "領収"}
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="mt-5 overflow-hidden">
          <div className="grid grid-cols-[minmax(0,1fr)_52px_64px_76px] bg-[#17212b] px-2 py-2 text-[8px] font-medium text-white sm:text-[9px]"><span>取引内容</span><span className="text-right">数量</span><span className="text-right">税区分</span><span className="text-right">金額</span></div>
          {editor.lines.slice(0, 5).map((line) => {
            const amount = Math.max(0, Math.round(Number(line.quantity || 0) * Number(line.unitPrice || 0)) - Number(line.discountAmount || 0));
            return <div key={line.key} className="grid grid-cols-[minmax(0,1fr)_52px_64px_76px] border-b border-[#d7d9d8] px-2 py-2.5 text-[8px] sm:text-[9px]"><span className="truncate">{line.description || "品名"}</span><span className="tabular text-right">{line.quantity} {line.unit}</span><span className="text-right text-[#66707a]">{taxShort(line.taxCategory)}</span><span className="tabular text-right font-medium">{formatYen(amount)}</span></div>;
          })}
        </div>
        <div className="ml-auto mt-5 w-[62%] text-[9px] sm:text-[10px]"><TotalRow label="消費税（8%）" value={totals.tax8} /><TotalRow label="消費税（10%）" value={totals.tax10} /><div className="mt-1 flex items-center justify-between bg-[#eaf3f0] px-3 py-3 text-sm font-bold"><span>合計金額</span><span className="tabular">{formatYen(totals.total)}</span></div></div>
        <p className="mt-4 text-center text-[8px] text-[#66707a]">※ 軽減税率対象品目には「※」を表示しています。</p>
      </article>
    );
  }
  return (
    <article aria-label={`${TYPE_LABEL[editor.type]}プレビュー`} className="mx-auto aspect-[1/1.414] w-full max-w-[620px] overflow-hidden bg-[#fffefa] p-[6%] text-[#17212b] shadow-[0_18px_50px_-24px_rgba(23,33,43,0.35)]">
      <div className="h-1.5 w-full bg-[#2d7d6d]" />
      <div className="mt-5 flex items-start justify-between gap-4">
        <h3 className="text-xl font-bold tracking-[0.28em] sm:text-2xl">{spacedTitle(TYPE_LABEL[editor.type])}</h3>
        <div className="tabular text-right text-[8px] leading-5 text-[#66707a] sm:text-[10px]"><p>No. {editor.number ?? "DRAFT"}</p><p>発行日　{editor.issueDate}</p>{isPayableDocument(editor.type) && editor.dueDate && <p>お支払期限　{editor.dueDate}</p>}</div>
      </div>
      <div className="mt-7 flex items-start justify-between gap-5">
        <div className="min-w-0 flex-1"><p className="truncate border-b border-[#17212b] pb-2 text-sm font-bold sm:text-base">{editor.customerName || "取引先名"}　{editor.honorific}</p>{editor.subject && <p className="mt-2 text-[9px] text-[#66707a]">件名　{editor.subject}</p>}</div>
        <div className="shrink-0 text-right">{logoSrc && <img src={logoSrc} alt="事業者 ロゴ" className="mb-2 ml-auto h-14 w-24 rounded-lg border border-[#d7d9d8] object-cover" />}<p className="text-sm font-bold sm:text-base">{profile.trade_name}</p>{profile.show_representative && profile.representative_name && <p className="mt-1 text-[9px] text-[#66707a]">代表　{profile.representative_name}</p>}<p className="mt-1 max-w-48 text-[8px] leading-4 text-[#66707a]">{issuerAddress}</p>{editor.qualified && profile.registration_number && <p className="mt-1 text-[8px] font-semibold text-[#2d7d6d]">登録番号 {profile.registration_number}</p>}</div>
      </div>
      <div className="mt-7 overflow-hidden">
        <div className="grid grid-cols-[minmax(0,1fr)_52px_72px_76px] bg-[#17212b] px-2 py-2 text-[8px] font-medium text-white sm:text-[9px]"><span>品名・内容</span><span className="text-right">数量</span><span className="text-right">単価</span><span className="text-right">金額</span></div>
        {editor.lines.map((line) => {
          const amount = Math.max(0, Math.round(Number(line.quantity || 0) * Number(line.unitPrice || 0)) - Number(line.discountAmount || 0));
          return <div key={line.key} className="grid grid-cols-[minmax(0,1fr)_52px_72px_76px] border-b border-[#d7d9d8] px-2 py-2.5 text-[8px] sm:text-[9px]"><span className="truncate">{line.description || "品名"} <small className="text-[#66707a]">{taxShort(line.taxCategory)}</small></span><span className="tabular text-right">{line.quantity} {line.unit}</span><span className="tabular text-right">{formatYen(Number(line.unitPrice || 0))}</span><span className="tabular text-right font-medium">{formatYen(amount)}</span></div>;
        })}
      </div>
      <div className="ml-auto mt-5 w-[58%] text-[9px] sm:text-[10px]"><TotalRow label="小計" value={totals.subtotal} /><TotalRow label="消費税（8%）" value={totals.tax8} /><TotalRow label="消費税（10%）" value={totals.tax10} /><div className="mt-1 flex items-center justify-between bg-[#eaf3f0] px-3 py-3 text-sm font-bold"><span>合計金額</span><span className="tabular">{formatYen(totals.total)}</span></div></div>
      {editor.notes && <p className="mt-5 border-t border-[#d7d9d8] pt-3 text-[8px] leading-4 text-[#66707a]">備考　{editor.notes}</p>}
      {isPayableDocument(editor.type) && profile.show_bank_details && profile.bank_name && <p className="mt-3 text-[8px] leading-4 text-[#66707a]">振込先　{profile.bank_name} {profile.bank_branch} {profile.bank_account_type} {profile.bank_account_number} {profile.bank_account_holder}</p>}
      <p className="mt-4 text-center text-[8px] text-[#66707a]">※ 軽減税率対象品目には「※」を表示しています。</p>
    </article>
  );
}

function PaymentPanel({ document, pending, onSubmit }: { document: SalesDocument; pending: boolean; onSubmit: (amount: number, method: "cash" | "bank_transfer" | "card" | "other", date: string) => Promise<void> }) {
  const [amount, setAmount] = useState(String(document.outstanding));
  const [method, setMethod] = useState<"cash" | "bank_transfer" | "card" | "other">("bank_transfer");
  const [paymentDate, setPaymentDate] = useState(today());
  return <div className="rounded-xl border border-[var(--color-seiji)]/25 bg-[var(--color-seiji-soft)]/55 p-4"><p className="text-sm font-bold text-[var(--color-sumi)]">入金を登録して領収書を発行</p><p className="mt-1 text-xs text-[var(--color-sumi-soft)]">未入金残高 {formatYen(document.outstanding)}</p><div className="mt-3 grid gap-2 sm:grid-cols-3"><input aria-label="入金日" type="date" className={fieldClass} value={paymentDate} onChange={(event) => setPaymentDate(event.target.value)} /><input aria-label="入金額" inputMode="numeric" className={fieldClass} value={amount} onChange={(event) => setAmount(event.target.value.replace(/\D/g, ""))} /><select aria-label="入金方法" className={fieldClass} value={method} onChange={(event) => setMethod(event.target.value as typeof method)}><option value="bank_transfer">銀行振込</option><option value="cash">現金</option><option value="card">カード</option><option value="other">その他</option></select></div><button type="button" disabled={pending || Number(amount) <= 0 || Number(amount) > document.outstanding} onClick={() => void onSubmit(Number(amount), method, paymentDate)} className="mt-3 rounded-full bg-[var(--color-seiji)] px-5 py-2 text-xs font-bold text-white disabled:opacity-40">入金登録・領収書発行</button></div>;
}

function previewTotals(editor: EditorState) {
  const amounts = editor.lines.map((line) => ({ amount: Math.max(0, Math.round(Number(line.quantity || 0) * Number(line.unitPrice || 0)) - Number(line.discountAmount || 0)), tax: line.taxCategory }));
  const gross8 = amounts.filter((line) => line.tax === "reduced_8").reduce((sum, line) => sum + line.amount, 0);
  const gross10 = amounts.filter((line) => line.tax === "standard_10").reduce((sum, line) => sum + line.amount, 0);
  const untaxed = amounts.filter((line) => line.tax === "exempt" || line.tax === "out_of_scope").reduce((sum, line) => sum + line.amount, 0);
  if (editor.priceMode === "inclusive") { const tax8 = Math.floor((gross8 * 8) / 108); const tax10 = Math.floor((gross10 * 10) / 110); return { subtotal: gross8 + gross10 + untaxed - tax8 - tax10, tax8, tax10, total: gross8 + gross10 + untaxed }; }
  const tax8 = Math.floor(gross8 * 0.08); const tax10 = Math.floor(gross10 * 0.1); const subtotal = gross8 + gross10 + untaxed; return { subtotal, tax8, tax10, total: subtotal + tax8 + tax10 };
}

function Metric({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) { return <Card className="p-4"><p className="text-[10px] font-semibold tracking-[0.14em] text-[var(--color-sumi-soft)]">{label}</p><p className={`tabular mt-2 truncate text-lg font-bold ${accent ? "text-[var(--color-kohaku)]" : "text-[var(--color-sumi)]"}`}>{value}</p></Card>; }
function StatusBadge({ status }: { status: SalesDocumentStatus }) { return <span className={`rounded-full px-2 py-1 text-[9px] font-semibold ${STATUS_TONE[status]}`}>{STATUS_LABEL[status]}</span>; }
function ActionButton({ label, onClick, disabled }: { label: string; onClick: () => void; disabled: boolean }) { return <button type="button" onClick={onClick} disabled={disabled} className="rounded-full border border-[var(--color-hairline)] bg-white px-4 py-2 text-xs font-semibold text-[var(--color-sumi)] transition hover:bg-[var(--color-paper-sink)] disabled:opacity-40">{label}</button>; }
function Field({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) { return <label className={`block text-xs font-medium text-[var(--color-sumi-soft)] ${className}`}><span className="mb-1.5 block">{label}</span>{children}</label>; }
function MiniField({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block text-[9px] font-medium text-[var(--color-sumi-soft)]"><span className="mb-1 block">{label}</span>{children}</label>; }
function TotalRow({ label, value }: { label: string; value: number }) { return <div className="flex items-center justify-between border-b border-[#d7d9d8] px-3 py-1.5"><span>{label}</span><span className="tabular">{formatYen(value)}</span></div>; }
function spacedTitle(value: string) { return value.split("").join(" "); }
function taxShort(value: SalesTaxCategory) { return value === "standard_10" ? "10%" : value === "reduced_8" ? "8%※" : value === "exempt" ? "非課税" : "対象外"; }
