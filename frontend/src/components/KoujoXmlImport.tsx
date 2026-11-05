/**
 * 控除証明書（XML）取り込み — Nivel 2 del roadmap e-Tax.
 *
 * Sube el XML de un 控除証明書 electrónico (生命保険・地震・iDeCo・国民年金・寄附金)
 * que el usuario baja de su aseguradora/institución. La app detecta el tipo,
 * calcula el 控除額 y muestra un preview editable; al confirmar, crea la 控除.
 *
 * Reusa el patrón del ImportScreen (dropzone + preview) pero para una sola
 * 控除 por archivo. UI en japonés con ayuda ES; nada se persiste hasta confirmar.
 */
import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { useKoujoXmlCommit, useKoujoXmlPreview } from "../lib/hooks";
import { ApiError, type KoujoXmlPreview } from "../lib/api";
import { formatYen } from "../lib/format";
import { Card, Label } from "./ui";
import { Icon } from "./Icon";
import { HelpTerm } from "./HelpTerm";

export function KoujoXmlImport({ readOnly = false }: { readOnly?: boolean }) {
  const preview = useKoujoXmlPreview();
  const commit = useKoujoXmlCommit();
  const fileInput = useRef<HTMLInputElement>(null);

  const [dragging, setDragging] = useState(false);
  const [data, setData] = useState<KoujoXmlPreview | null>(null);
  // Monto editable del preview (el usuario lo confirma/ajusta antes de guardar).
  const [amount, setAmount] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const handleFile = (file: File | undefined) => {
    if (!file || readOnly) return;
    setError(null);
    setDone(null);
    preview.mutate(file, {
      onSuccess: (res) => {
        setData(res);
        setAmount(String(res.amount));
      },
      onError: (err) =>
        setError(
          err instanceof ApiError
            ? err.message
            : "XMLの読み取りに失敗しました。ファイル形式をご確認ください。",
        ),
    });
  };

  const reset = () => {
    setData(null);
    setAmount("");
    setError(null);
  };

  const parsedAmount = Number(amount.replaceAll(",", "")) || 0;

  const handleCommit = () => {
    if (!data || readOnly || parsedAmount <= 0) return;
    commit.mutate(
      {
        deduction_type: data.deduction_type,
        amount: parsedAmount,
        issuer: data.issuer,
        year: data.year,
        koujo_type: data.koujo_type,
      },
      {
        onSuccess: (res) => {
          setDone(
            res.created
              ? `${data.koujo_type}を登録しました（控除額 ${formatYen(res.amount)}）`
              : `${data.koujo_type}を合算しました（合計 ${formatYen(res.amount)}）`,
          );
          reset();
        },
        onError: (err) =>
          setError(
            err instanceof ApiError ? err.message : "登録に失敗しました。",
          ),
      },
    );
  };

  return (
    <section className="mt-8">
      <div className="mb-3 flex items-center gap-2">
        <Icon name="file" className="h-4 w-4 text-[var(--color-sumi-soft)]" />
        <Label>控除証明書（XML）を取り込む</Label>
      </div>

      <Card className="p-5">
        <p className="text-sm leading-relaxed text-[var(--color-sumi)]">
          保険会社や金融機関から電子発行された
          <HelpTerm term="控除証明書" />
          のXMLファイルを取り込むと、種類と控除額を自動で読み取ります。
        </p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
          対応：生命保険料・地震保険料・iDeCo（小規模企業共済）・国民年金・寄附金（XML）。
          内容を確認してから登録できます。
        </p>

        <input
          ref={fileInput}
          type="file"
          accept=".xml,text/xml,application/xml"
          className="hidden"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />

        {/* Resultado del commit */}
        {done && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-4 flex items-start gap-3 rounded-[var(--radius-card)] border border-[var(--color-seiji)] bg-[var(--color-seiji-soft)] p-4"
          >
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[var(--color-seiji)] text-white">
              <Icon name="check" className="h-4 w-4" />
            </span>
            <p className="text-sm font-medium text-[var(--color-sumi)]">{done}</p>
          </motion.div>
        )}

        {/* Error */}
        {error && (
          <div className="mt-4 flex items-start gap-3 rounded-[var(--radius-card)] border border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] p-4">
            <Icon
              name="shield"
              className="mt-0.5 h-5 w-5 shrink-0 text-[var(--color-kohaku)]"
            />
            <p className="text-sm text-[var(--color-sumi)]">{error}</p>
          </div>
        )}

        {/* Zona de subida (cuando no hay preview) */}
        {!data && (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              handleFile(e.dataTransfer.files?.[0]);
            }}
            className={`mt-4 flex flex-col items-center rounded-[var(--radius-card)] border-2 border-dashed p-6 text-center transition-colors ${dragging ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)]" : "border-[var(--color-hairline)]"}`}
          >
            {preview.isPending ? (
              <div className="flex flex-col items-center py-2">
                <motion.div
                  className="h-9 w-9 rounded-full border-2 border-[var(--color-hairline)] border-t-[var(--color-seiji)]"
                  animate={{ rotate: 360 }}
                  transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
                />
                <p className="mt-3 text-xs text-[var(--color-sumi-soft)]">
                  XMLを解析中…
                </p>
              </div>
            ) : (
              <>
                <div className="mb-3 grid h-12 w-12 place-items-center rounded-full bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
                  <Icon name="upload" className="h-5 w-5" />
                </div>
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  disabled={readOnly}
                  className="flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
                >
                  <Icon name="file" className="h-4 w-4" />
                  XMLファイルを選択
                </button>
                <p className="mt-2 text-xs text-[var(--color-sumi-soft)]">
                  ここにXMLをドラッグしても取り込めます。
                </p>
              </>
            )}
          </div>
        )}

        {/* Preview editable */}
        {data && (
          <KoujoPreviewCard
            data={data}
            amount={amount}
            onAmountChange={setAmount}
            parsedAmount={parsedAmount}
            onCancel={reset}
            onCommit={handleCommit}
            committing={commit.isPending}
            readOnly={readOnly}
          />
        )}
      </Card>
    </section>
  );
}

/** Tarjeta de preview de un 控除証明書 (tipo + 控除額 editable + desglose). */
function KoujoPreviewCard({
  data,
  amount,
  onAmountChange,
  parsedAmount,
  onCancel,
  onCommit,
  committing,
  readOnly,
}: {
  data: KoujoXmlPreview;
  amount: string;
  onAmountChange: (v: string) => void;
  parsedAmount: number;
  onCancel: () => void;
  onCommit: () => void;
  committing: boolean;
  readOnly: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mt-4 rounded-[var(--radius-card)] border border-[var(--color-hairline)] bg-[var(--color-paper-sink)] p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[var(--color-sumi)]">
            {data.koujo_type}
          </p>
          {data.issuer && (
            <p className="mt-0.5 truncate text-xs text-[var(--color-sumi-soft)]">
              {data.issuer}
              {data.year != null && ` ・ ${data.year}年分`}
            </p>
          )}
        </div>
        {data.already_registered && (
          <span className="shrink-0 rounded-full bg-[var(--color-kohaku-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-kohaku)]">
            既存に合算
          </span>
        )}
      </div>

      {/* Desglose por categoría (solo 生命保険) */}
      {data.seimei_categories.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-[var(--color-hairline)] pt-3">
          {data.seimei_categories.map((c) => (
            <li
              key={c.category}
              className="flex items-center justify-between text-xs text-[var(--color-sumi-soft)]"
            >
              <span>{c.label}</span>
              <span className="tabular">{formatYen(c.deduction)}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Aviso (cómo se calculó / qué confirmar) */}
      {data.note && (
        <p
          className={`mt-3 flex items-start gap-1.5 text-xs leading-relaxed ${data.needs_confirmation ? "text-[var(--color-kohaku)]" : "text-[var(--color-sumi-soft)]"}`}
        >
          <Icon
            name={data.needs_confirmation ? "shield" : "sparkle"}
            className="mt-0.5 h-3.5 w-3.5 shrink-0"
          />
          <span>{data.note}</span>
        </p>
      )}

      {/* 控除額 editable */}
      <label htmlFor="koujo-xml-amount" className="mt-4 block">
        <span className="mb-1 block text-xs font-medium text-[var(--color-sumi-soft)]">
          控除額（確認・修正できます）
        </span>
        <div className="flex items-center rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] pl-3.5 pr-3 focus-within:border-[var(--color-seiji)]">
          <span className="tabular mr-0.5 text-sm text-[var(--color-sumi-soft)]">¥</span>
          <input
            id="koujo-xml-amount"
            type="text"
            inputMode="numeric"
            value={amount}
            disabled={readOnly}
            onChange={(e) => onAmountChange(e.target.value.replace(/[^0-9,]/g, ""))}
            className="tabular w-full bg-transparent px-2 py-2.5 text-right text-sm text-[var(--color-sumi)] outline-none"
          />
        </div>
      </label>

      <div className="mt-4 flex items-center gap-2">
        <button
          type="button"
          onClick={onCommit}
          disabled={readOnly || committing || parsedAmount <= 0}
          className="flex items-center gap-1.5 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          <Icon name="check" className="h-4 w-4" />
          {committing ? "登録中…" : "この控除を登録"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={committing}
          className="rounded-[var(--radius-pill)] px-3 py-2.5 text-sm font-medium text-[var(--color-sumi-soft)] transition-colors hover:text-[var(--color-shuiro)]"
        >
          別のファイル
        </button>
      </div>
    </motion.div>
  );
}
