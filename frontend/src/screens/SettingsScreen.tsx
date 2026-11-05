/**
 * Settings (設定) — sub-paso OCR. Toggles on/off por proveedor (GET
 * /ocr/providers) con la implicacion de privacidad clara: local 🟢 (datos no
 * salen) vs cloud ⚠️ (datos salen). Switch maestro "外部OCRを許可".
 */
import { useState } from "react";
import { motion } from "framer-motion";
import {
  usePatchOcrProviders,
  useOcrProviders,
  useOcrUsage,
  useTaxpayer,
  usePatchTaxpayer,
  useResetOnboarding,
} from "../lib/hooks";
import type {
  ConsumptionMethodSetting,
  ProviderStatus,
  ProviderUsage,
  TaxpayerConsumption,
} from "../lib/api";
import { Card, ErrorState, Label, Skeleton } from "../components/ui";
import { useAuth, useLogout } from "../lib/useAuth";
import { Icon } from "../components/Icon";
import { HelpToggle, HelpSubtitle, HelpTerm } from "../components/HelpTerm";
import { screenVariants, staggerContainer, staggerItem } from "../variants/layoutVariants";
import { BusinessProfileSettings } from "../components/sales/BusinessProfileSettings";

/** Proveedores cuyo flag enabled se puede togglear (espejo del backend). */
const TOGGLEABLE = new Set(["paddle", "ollama", "glm", "azure", "google", "gemini"]);

const PROVIDER_LABELS: Record<string, { name: string; note: string }> = {
  paddle: { name: "PaddleOCR", note: "端末内で処理（PP-OCRv5）" },
  ollama: { name: "GLM-OCR (ローカル)", note: "端末内で処理（Ollama・無料）" },
  glm: { name: "GLM-OCR (Z.AI)", note: "Z.AI のクラウド（データは外部に送信）" },
  gemini: { name: "Gemini Vision", note: "Google のクラウドAI" },
  azure: { name: "Azure Document Intelligence", note: "Microsoft のクラウド" },
  google: { name: "Google Document AI", note: "Google のクラウド" },
  fake: { name: "テスト用OCR", note: "開発・デモ用" },
};

export function SettingsScreen() {
  const { data, isLoading, isError, refetch } = useOcrProviders();
  const usageQuery = useOcrUsage();
  const patchOcr = usePatchOcrProviders();

  // No mostramos el provider 'fake' en runtime (es de dev).
  const providers = (data?.providers ?? []).filter((p) => p.name !== "fake");

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-2xl px-4 py-6 sm:px-8 sm:py-10"
    >
      <div className="mb-6">
        <h2 className="text-xl font-bold text-[var(--color-sumi)]">設定</h2>
        <p className="mt-1 text-sm text-[var(--color-sumi-soft)]">
          表示・OCR・プライバシーの設定です。
        </p>
      </div>

      {/* Ayuda en castellano (capa ES). Siempre visible (no depende del backend). */}
      <div className="mb-4">
        <div className="mb-2 px-1">
          <Label>表示ヘルプ</Label>
        </div>
        <Card className="p-5">
          <HelpToggle variant="full" />
        </Card>
      </div>

      <AccountCard />

      <BusinessProfileSettings />

      {/* Rehacer el onboarding guiado */}
      <div className="mb-4">
        <div className="mb-2 px-1">
          <Label>初期設定</Label>
          <HelpSubtitle className="mt-0.5">Configuración inicial</HelpSubtitle>
        </div>
        <RedoOnboardingCard />
      </div>

      {/* 消費税 — 課税事業者 toggle + metodo + 事業区分 */}
      <div className="mb-4">
        <div className="mb-2 px-1">
          <Label>消費税（申告区分）</Label>
          <HelpSubtitle className="mt-0.5">IVA japonés (consumo)</HelpSubtitle>
        </div>
        <ConsumptionSettings />
      </div>

      <div className="mb-2 px-1">
        <Label>OCR</Label>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : isError || !data ? (
        <Card>
          <ErrorState
            message="設定の読み込みに失敗しました。バックエンドの接続をご確認ください。"
            onRetry={() => void refetch()}
          />
        </Card>
      ) : (
        <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="space-y-4">
          {/* Switch maestro: 外部OCRを許可 */}
          <motion.div variants={staggerItem}>
            <Card className="p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="flex gap-3">
                  <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]">
                    <Icon name="shield" className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-[var(--color-sumi)]">
                      外部OCRを許可
                    </p>
                    <p className="mt-1 max-w-md text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                      オフのあいだは、領収書データが端末の外に出ることはありません。低信頼の場合のみクラウドOCRを使うには、これをオンにします。
                    </p>
                  </div>
                </div>
                <Toggle
                  on={data.allow_external_ocr}
                  disabled={patchOcr.isPending}
                  onChange={(next) =>
                    patchOcr.mutate({ allow_external_ocr: next })
                  }
                  label="外部OCRを許可"
                />
              </div>
              {!data.allow_external_ocr && (
                <div className="mt-4 flex items-center gap-2 rounded-lg bg-[var(--color-seiji-soft)] px-3 py-2">
                  <span className="h-2 w-2 rounded-full bg-[var(--color-seiji)]" />
                  <p className="text-xs font-medium text-[var(--color-seiji)]">
                    現在：データは端末内のみ（プライバシー保護モード）
                  </p>
                </div>
              )}
            </Card>
          </motion.div>

          {/* Lista de proveedores */}
          <motion.div variants={staggerItem}>
            <div className="mb-2 px-1">
              <Label>OCRプロバイダー</Label>
            </div>
            <div className="space-y-3">
              {providers.map((p) => (
                <ProviderRow
                  key={p.name}
                  provider={p}
                  isPrimary={p.name === data.primary}
                  allowExternal={data.allow_external_ocr}
                  pending={patchOcr.isPending}
                  onToggle={(next) =>
                    patchOcr.mutate({ providers: { [p.name]: next } })
                  }
                />
              ))}
            </div>
          </motion.div>

          {/* Contador diario de cuota (free tier de los proveedores cloud) */}
          {(() => {
            const cloudUsage = (usageQuery.data?.providers ?? []).filter((u) =>
              providers.some((p) => p.name === u.provider && p.sends_data_externally),
            );
            if (!cloudUsage.length) return null;
            return (
              <motion.div variants={staggerItem}>
                <div className="mb-2 px-1">
                  <Label>無料枠の使用状況</Label>
                  <HelpSubtitle className="mt-0.5">
                    Uso diario / Límite gratis
                  </HelpSubtitle>
                </div>
                <div className="space-y-3">
                  {cloudUsage.map((u) => (
                    <QuotaCounter
                      key={u.provider}
                      usage={u}
                      pending={patchOcr.isPending}
                      onLimitChange={(limit) =>
                        patchOcr.mutate({ daily_limits: { [u.provider]: limit } })
                      }
                    />
                  ))}
                </div>
              </motion.div>
            );
          })()}
        </motion.div>
      )}
    </motion.div>
  );
}

/**
 * Contador diario de cuota de un proveedor cloud (free tier). Muestra
 * "今日: N / límite" con barra de progreso (seiji -> kohaku -> shuiro segun %),
 * el texto de reset (太平洋時間) y un input para ajustar el límite diario.
 * shuiro (rojo del sello) SOLO cuando se alcanzo el límite (alerta).
 */
function QuotaCounter({
  usage,
  pending,
  onLimitChange,
}: {
  usage: ProviderUsage;
  pending: boolean;
  onLimitChange: (limit: number) => void;
}) {
  const meta = PROVIDER_LABELS[usage.provider] ?? { name: usage.provider, note: "" };
  const [limitDraft, setLimitDraft] = useState(String(usage.daily_limit));

  // Color de la barra segun el estado de consumo:
  //   <80% seiji (celadon, ok) · 80-99% kohaku (ambar, aviso) · >=100% shuiro (alerta).
  const tone = usage.over_limit ? "shuiro" : usage.warn ? "kohaku" : "seiji";
  const barColor = `var(--color-${tone})`;
  const pct = Math.min(100, usage.percent);

  const reset = new Date(usage.resets_at);
  const resetTime = Number.isNaN(reset.getTime())
    ? ""
    : reset.toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit" });

  const commitLimit = () => {
    const parsed = parseInt(limitDraft, 10);
    if (Number.isFinite(parsed) && parsed > 0 && parsed !== usage.daily_limit) {
      onLimitChange(parsed);
    } else {
      setLimitDraft(String(usage.daily_limit));
    }
  };

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-[var(--color-sumi)]">{meta.name}</p>
        <p className="tabular text-sm font-medium" style={{ color: barColor }}>
          今日: {usage.used_today} / {usage.daily_limit}
        </p>
      </div>

      {/* Barra de progreso */}
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-[var(--color-paper-sink)]">
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: barColor }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ type: "spring", stiffness: 200, damping: 30 }}
        />
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="text-[11px] text-[var(--color-sumi-soft)]">
          {usage.over_limit
            ? "本日の上限に達しました（ローカルOCRにフォールバック）"
            : "太平洋時間の0時にリセット"}
          {resetTime && !usage.over_limit ? `（${resetTime}頃）` : ""}
        </p>
        {usage.over_limit && (
          <span className="rounded-full bg-[var(--color-shuiro)] px-2 py-0.5 text-[10px] font-medium text-white">
            上限
          </span>
        )}
      </div>

      {/* Input para ajustar el límite diario */}
      <div className="mt-3 flex items-center gap-2">
        <label className="text-[11px] text-[var(--color-sumi-soft)]" htmlFor={`limit-${usage.provider}`}>
          1日の上限
        </label>
        <input
          id={`limit-${usage.provider}`}
          name={`limit-${usage.provider}`}
          type="number"
          min={1}
          max={100000}
          inputMode="numeric"
          value={limitDraft}
          disabled={pending}
          onChange={(e) => setLimitDraft(e.target.value)}
          onBlur={commitLimit}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          className="tabular w-24 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-2 py-1 text-sm text-[var(--color-sumi)] focus:border-[var(--color-seiji)] focus:outline-none"
        />
        <HelpSubtitle>(ajusta tu límite gratis)</HelpSubtitle>
      </div>
    </Card>
  );
}

function ProviderRow({
  provider,
  isPrimary,
  allowExternal,
  pending,
  onToggle,
}: {
  provider: ProviderStatus;
  isPrimary: boolean;
  allowExternal: boolean;
  pending: boolean;
  onToggle: (next: boolean) => void;
}) {
  const meta = PROVIDER_LABELS[provider.name] ?? { name: provider.name, note: "" };
  const external = provider.sends_data_externally;
  // El toggle refleja el flag `enabled` (lo que el usuario controla). El estado
  // "bloqueado por privacidad" se muestra aparte (cloud sin consentimiento).
  const blockedByPrivacy = provider.enabled && external && !allowExternal;
  const canToggle = TOGGLEABLE.has(provider.name);

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex gap-3">
          <div
            className={`grid h-10 w-10 shrink-0 place-items-center rounded-lg ${external ? "bg-[var(--color-kohaku-soft)] text-[var(--color-kohaku)]" : "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]"}`}
          >
            <Icon name={external ? "cloud" : "shield"} className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold text-[var(--color-sumi)]">
                {meta.name}
              </p>
              {isPrimary && (
                <span className="rounded-full bg-[var(--color-paper-sink)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-sumi-soft)]">
                  優先
                </span>
              )}
              <span
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${external ? "bg-[var(--color-kohaku-soft)] text-[var(--color-kohaku)]" : "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]"}`}
              >
                {external ? "⚠ データが外部に送信" : "🟢 データは端末内"}
              </span>
            </div>
            <p className="mt-1 text-xs text-[var(--color-sumi-soft)]">{meta.note}</p>
            {provider.reason && !provider.available && (
              <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--color-sumi-soft)]">
                {provider.reason}
              </p>
            )}
            {blockedByPrivacy && (
              <p className="mt-1.5 text-[11px] font-medium leading-relaxed text-[var(--color-kohaku)]">
                プライバシー保護のため停止中（「外部OCRを許可」をオンにすると使用できます）
              </p>
            )}
          </div>
        </div>
        <Toggle
          on={provider.enabled}
          disabled={!canToggle || pending}
          onChange={onToggle}
          label={`${meta.name} を有効化`}
        />
      </div>
    </Card>
  );
}

/**
 * Tarjeta para rehacer el onboarding guiado. Marca `onboarded=false` en el
 * Taxpayer (PATCH /taxpayer): la app vuelve a mostrar el flujo paso a paso, sin
 * borrar los datos ya cargados (el onboarding los re-confirma/edita).
 */
function RedoOnboardingCard() {
  const reset = useResetOnboarding();
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
            <Icon name="compass" className="h-5 w-5" />
          </div>
          <div>
            <p className="text-sm font-semibold text-[var(--color-sumi)]">
              セットアップをやり直す
            </p>
            <p className="mt-1 max-w-md text-xs leading-relaxed text-[var(--color-sumi-soft)]">
              質問に答えるだけの初期設定を、もう一度最初から表示します。プロフィールや申告区分を見直したいときに使います。
            </p>
            <HelpSubtitle className="mt-1">
              Al finalizar puedes sobrescribir ajustes e ingresos existentes. El IVA y la
              oficina fiscal son ajustes generales que pueden afectar otros ejercicios.
              Haz una copia de seguridad antes de rehacerla.
            </HelpSubtitle>
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            if (window.confirm("La configuración guiada puede sobrescribir ajustes e ingresos existentes al finalizar. Los ajustes generales pueden afectar otros ejercicios. Haz una copia de seguridad antes de continuar. ¿Quieres abrirla?")) reset.mutate();
          }}
          disabled={reset.isPending}
          className="shrink-0 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-4 py-2 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)] disabled:opacity-50"
        >
          {reset.isPending ? "…" : "やり直す"}
        </button>
      </div>
    </Card>
  );
}

/**
 * Config del 消費税: toggle "課税事業者として申告する" (default OFF = 免税) +
 * selector de metodo (本則 / 簡易 / 2割特例) + selector de 事業区分 (1〜6, solo
 * para 簡易課税). Al activarlo aparece la seccion 消費税 en la navegacion.
 */
const METHOD_OPTIONS: { value: ConsumptionMethodSetting; label: string; es: string }[] = [
  { value: "tokurei_2wari", label: "2割特例", es: "Especial 20%" },
  { value: "honsoku", label: "本則課税", es: "Régimen general" },
  { value: "kani", label: "簡易課税", es: "Régimen simplificado" },
];

function ConsumptionSettings() {
  const { data, isLoading, isError, refetch } = useTaxpayer();
  const patch = usePatchTaxpayer();

  if (isLoading) return <Skeleton className="h-28 w-full" />;
  if (isError || !data) {
    return (
      <Card>
        <ErrorState
          message="納税者情報の読み込みに失敗しました。"
          onRetry={() => void refetch()}
        />
      </Card>
    );
  }

  const taxable = data.is_taxable_consumption;
  const method: ConsumptionMethodSetting = data.consumption_method ?? "tokurei_2wari";
  const category = data.consumption_business_category ?? 5;

  return (
    <Card className="p-5">
      {/* Toggle 課税事業者 */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
            <Icon name="box" className="h-5 w-5" />
          </div>
          <div>
            <p className="flex items-center text-sm font-semibold text-[var(--color-sumi)]">
              課税事業者として申告する
              <HelpTerm term="課税事業者" />
            </p>
            <p className="mt-1 max-w-md text-xs leading-relaxed text-[var(--color-sumi-soft)]">
              オフのあいだは<strong>免税事業者</strong>として扱い、消費税の申告は不要です。基準期間の課税売上が1,000万円超、またはインボイス登録をした場合にオンにします。
            </p>
            <HelpSubtitle className="mt-1">
              Off = exento (免税): no declara IVA. Actívalo solo si superas 10M¥ de
              ventas base o te registras como インボイス.
            </HelpSubtitle>
          </div>
        </div>
        <Toggle
          on={taxable}
          disabled={patch.isPending}
          onChange={(next) => patch.mutate({ is_taxable_consumption: next })}
          label="課税事業者として申告する"
        />
      </div>

      {/* Metodo + 事業区分 (solo si 課税) */}
      {taxable && (
        <div className="mt-5 space-y-4 border-t border-[var(--color-hairline)] pt-4">
          <div>
            <p className="mb-2 flex items-center text-xs font-medium text-[var(--color-sumi-soft)]">
              計算方法
              <HelpTerm term="本則課税" size="sm" />
            </p>
            <div className="flex flex-wrap gap-2">
              {METHOD_OPTIONS.map((opt) => {
                const active = method === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    disabled={patch.isPending}
                    onClick={() =>
                      patch.mutate({ consumption_method: opt.value })
                    }
                    className={`rounded-[var(--radius-pill)] border px-3.5 py-2 text-sm font-medium transition-colors ${
                      active
                        ? "border-[var(--color-seiji)] bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]"
                        : "border-[var(--color-hairline)] text-[var(--color-sumi-soft)] hover:bg-[var(--color-paper-sink)]"
                    }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* 事業区分 (solo relevante para 簡易課税) */}
          {method === "kani" && (
            <div>
              <p className="mb-2 flex items-center text-xs font-medium text-[var(--color-sumi-soft)]">
                事業区分（みなし仕入率）
                <HelpTerm term="事業区分" size="sm" />
              </p>
              <select
                value={category}
                disabled={patch.isPending}
                onChange={(e) =>
                  patch.mutate({
                    consumption_business_category: Number(e.target.value),
                  })
                }
                className="w-full rounded-lg border border-[var(--color-hairline)] bg-[var(--color-surface)] px-3 py-2.5 text-sm text-[var(--color-sumi)] focus:border-[var(--color-seiji)] focus:outline-none"
              >
                {Object.entries(data.business_category_labels).map(
                  ([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ),
                )}
              </select>
            </div>
          )}

          <ConsumptionHint data={data} />
        </div>
      )}
    </Card>
  );
}

/** Nota que confirma el estado y dirige a la seccion 消費税. */
function ConsumptionHint({ data }: { data: TaxpayerConsumption }) {
  const label =
    data.consumption_method === "honsoku"
      ? "本則課税"
      : data.consumption_method === "kani"
        ? "簡易課税"
        : "2割特例";
  return (
    <div className="flex items-center gap-2 rounded-lg bg-[var(--color-seiji-soft)] px-3 py-2">
      <span className="h-2 w-2 rounded-full bg-[var(--color-seiji)]" />
      <p className="text-xs font-medium text-[var(--color-seiji)]">
        課税事業者：{label}で計算します（「消費税」画面で比較・申告書を確認）
      </p>
    </div>
  );
}

/** Switch funcional (persiste via PATCH); accesible por teclado. */
function Toggle({
  on,
  disabled = false,
  onChange,
  label,
}: {
  on: boolean;
  disabled?: boolean;
  onChange?: (next: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange?.(!on)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors ${on ? "bg-[var(--color-seiji)]" : "bg-[var(--color-hairline)]"} ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
    >
      <motion.span
        layout
        className="inline-block h-5 w-5 rounded-full bg-white shadow-[var(--shadow-paper)]"
        animate={{ x: on ? 22 : 2 }}
        transition={{ type: "spring", stiffness: 500, damping: 32 }}
      />
    </button>
  );
}


/**
 * Cuenta y cierre de sesión. Solo aparece cuando el backend tiene el login con
 * Google activo: sin login no hay sesión que cerrar.
 */
function AccountCard() {
  const auth = useAuth();
  const logout = useLogout();

  if (auth.status?.enabled !== true) return null;

  return (
    <div className="mb-4">
      <div className="mb-2 px-1">
        <Label>アカウント</Label>
      </div>
      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-[var(--color-sumi)]">
              {auth.status.email ?? "—"}
            </p>
            <p className="mt-0.5 text-xs text-[var(--color-sumi-soft)]">
              Googleアカウントでログイン中
            </p>
          </div>
          <button
            type="button"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
            className="rounded-[var(--radius-pill)] border border-[var(--color-hairline)] px-4 py-2 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)] disabled:opacity-50"
          >
            {logout.isPending ? "ログアウト中…" : "ログアウト"}
          </button>
        </div>
      </Card>
    </div>
  );
}
