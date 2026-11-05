import { useEffect, useState } from "react";
import { Card, ErrorState, Label, Skeleton } from "../ui";
import { useBusinessProfile, usePatchBusinessProfile } from "../../lib/hooks";
import type { BusinessProfilePatch } from "../../lib/api";
import { DEFAULT_LOGO_REF, resolveBrandImageSrc } from "../../lib/brandAssets";

const inputClass =
  "mt-1.5 w-full rounded-xl border border-[var(--color-hairline)] bg-white px-3.5 py-2.5 text-sm text-[var(--color-sumi)] outline-none transition focus:border-[var(--color-seiji)] focus:shadow-[0_0_0_3px_rgba(45,125,109,0.10)]";

const textareaClass = `${inputClass} min-h-24 resize-y leading-relaxed`;

export function BusinessProfileSettings() {
  const profile = useBusinessProfile();
  const patch = usePatchBusinessProfile();
  const [form, setForm] = useState<BusinessProfilePatch>({});

  useEffect(() => {
    if (!profile.data) return;
    const { id: _id, updated_at: _updatedAt, ...editable } = profile.data;
    setForm(editable);
  }, [profile.data]);

  if (profile.isLoading) return <Skeleton className="h-[720px]" />;
  if (profile.isError || !profile.data) {
    return <ErrorState message="事業者情報を読み込めませんでした。" onRetry={() => void profile.refetch()} />;
  }

  const set = <K extends keyof BusinessProfilePatch>(key: K, value: BusinessProfilePatch[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const displayAddress = [form.postal_code, form.address_line1 || form.address, form.address_line2]
    .filter(Boolean)
    .join(" ");
  const logoSrc = resolveBrandImageSrc(form.logo_ref);

  return (
    <section className="mb-4">
      <div className="mb-2 px-1">
        <Label>事業者情報・帳票テンプレート</Label>
      </div>
      <Card className="overflow-hidden">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div>
            <div className="border-b border-[var(--color-hairline)] bg-[var(--color-paper-sink)]/60 px-5 py-4 sm:px-6">
              <p className="text-[10px] font-semibold tracking-[0.24em] text-[var(--color-seiji)]">
                DOCUMENT SETTINGS
              </p>
              <h3 className="mt-1 text-lg font-bold tracking-[0.05em] text-[var(--color-sumi)]">
                {form.trade_name || "事業者"}
              </h3>
              <p className="mt-1 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                見積書・請求書・領収書に差し込む自社情報です。発行済みPDFは発行時の情報を保持します。
              </p>
            </div>

            <div className="space-y-7 p-5 sm:p-6">
              <SettingsBlock
                title="基本情報"
                description="屋号、正式名称、代表者、事業内容など帳票の顔になる情報です。"
              >
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="屋号・表示名" required>
                    <input
                      className={inputClass}
                      value={form.trade_name ?? ""}
                      onChange={(event) => set("trade_name", event.target.value)}
                    />
                  </Field>
                  <Field label="正式名称">
                    <input
                      className={inputClass}
                      value={form.legal_name ?? ""}
                      onChange={(event) => set("legal_name", event.target.value)}
                    />
                  </Field>
                  <Field label="正式名称（ふりがな）">
                    <input
                      className={inputClass}
                      value={form.legal_name_kana ?? ""}
                      onChange={(event) => set("legal_name_kana", event.target.value)}
                    />
                  </Field>
                  <Field label="法人番号（任意）">
                    <input
                      className={inputClass}
                      inputMode="numeric"
                      maxLength={13}
                      value={form.corporate_number ?? ""}
                      onChange={(event) =>
                        set("corporate_number", event.target.value.replace(/\D/g, ""))
                      }
                    />
                  </Field>
                  <Field label="事業内容" className="sm:col-span-2">
                    <input
                      className={inputClass}
                      placeholder="例：システム保守、清掃業務、業務委託サービス"
                      value={form.business_description ?? ""}
                      onChange={(event) => set("business_description", event.target.value)}
                    />
                  </Field>
                  <Field label="代表者名">
                    <input
                      className={inputClass}
                      value={form.representative_name ?? ""}
                      onChange={(event) => set("representative_name", event.target.value)}
                    />
                  </Field>
                  <Field label="自社担当者名">
                    <input
                      className={inputClass}
                      value={form.contact_person_name ?? ""}
                      onChange={(event) => set("contact_person_name", event.target.value)}
                    />
                  </Field>
                  <Field label="部署名">
                    <input
                      className={inputClass}
                      value={form.department_name ?? ""}
                      onChange={(event) => set("department_name", event.target.value)}
                    />
                  </Field>
                  <Field label="取引先敬称の初期値">
                    <select
                      className={inputClass}
                      value={form.default_customer_honorific ?? "御中"}
                      onChange={(event) => set("default_customer_honorific", event.target.value)}
                    >
                      <option value="御中">御中</option>
                      <option value="様">様</option>
                      <option value="">なし</option>
                    </select>
                  </Field>
                </div>
                <ToggleRow
                  label="代表者名を帳票に表示する"
                  description="有効にした場合だけ、屋号の下に代表者名を表示します。"
                  checked={form.show_representative ?? false}
                  onChange={(value) => set("show_representative", value)}
                />
              </SettingsBlock>

              <SettingsBlock
                title="所在地・連絡先"
                description="郵送、メール送付、問い合わせに必要な連絡情報です。未入力項目は帳票に表示しません。"
              >
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="郵便番号">
                    <input
                      className={inputClass}
                      value={form.postal_code ?? ""}
                      onChange={(event) => set("postal_code", event.target.value)}
                    />
                  </Field>
                  <Field label="電話番号">
                    <input
                      className={inputClass}
                      value={form.phone ?? ""}
                      onChange={(event) => set("phone", event.target.value)}
                    />
                  </Field>
                  <Field label="住所1" className="sm:col-span-2">
                    <input
                      className={inputClass}
                      placeholder="都道府県・市区町村・番地"
                      value={form.address_line1 ?? form.address ?? ""}
                      onChange={(event) => {
                        set("address_line1", event.target.value);
                        set("address", event.target.value);
                      }}
                    />
                  </Field>
                  <Field label="住所2" className="sm:col-span-2">
                    <input
                      className={inputClass}
                      placeholder="建物名・部屋番号"
                      value={form.address_line2 ?? ""}
                      onChange={(event) => set("address_line2", event.target.value)}
                    />
                  </Field>
                  <Field label="FAX">
                    <input
                      className={inputClass}
                      value={form.fax ?? ""}
                      onChange={(event) => set("fax", event.target.value)}
                    />
                  </Field>
                  <Field label="メールアドレス">
                    <input
                      type="email"
                      className={inputClass}
                      value={form.email ?? ""}
                      onChange={(event) => set("email", event.target.value)}
                    />
                  </Field>
                  <Field label="Webサイト" className="sm:col-span-2">
                    <input
                      className={inputClass}
                      placeholder="https://..."
                      value={form.website_url ?? ""}
                      onChange={(event) => set("website_url", event.target.value)}
                    />
                  </Field>
                </div>
              </SettingsBlock>

              <SettingsBlock
                title="振込先・入金条件"
                description="請求書に表示する口座情報と、入金期限の初期値です。"
              >
                <ToggleRow
                  label="振込先を帳票に表示する"
                  description="請求書・合算請求書・訂正請求書に口座情報を表示します。"
                  checked={form.show_bank_details ?? true}
                  onChange={(value) => set("show_bank_details", value)}
                />
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="入金期限（日数）">
                    <input
                      className={inputClass}
                      inputMode="numeric"
                      value={String(form.payment_terms_days ?? 30)}
                      onChange={(event) =>
                        set("payment_terms_days", Number(event.target.value.replace(/\D/g, "")))
                      }
                    />
                  </Field>
                  <Field label="振込手数料メモ">
                    <input
                      className={inputClass}
                      value={form.transfer_fee_note ?? ""}
                      onChange={(event) => set("transfer_fee_note", event.target.value)}
                    />
                  </Field>
                  <Field label="銀行名">
                    <input
                      className={inputClass}
                      value={form.bank_name ?? ""}
                      onChange={(event) => set("bank_name", event.target.value)}
                    />
                  </Field>
                  <Field label="支店名">
                    <input
                      className={inputClass}
                      value={form.bank_branch ?? ""}
                      onChange={(event) => set("bank_branch", event.target.value)}
                    />
                  </Field>
                  <Field label="口座種別">
                    <select
                      className={inputClass}
                      value={form.bank_account_type ?? "普通"}
                      onChange={(event) => set("bank_account_type", event.target.value)}
                    >
                      <option value="普通">普通</option>
                      <option value="当座">当座</option>
                      <option value="貯蓄">貯蓄</option>
                    </select>
                  </Field>
                  <Field label="口座番号">
                    <input
                      className={inputClass}
                      value={form.bank_account_number ?? ""}
                      onChange={(event) => set("bank_account_number", event.target.value)}
                    />
                  </Field>
                  <Field label="口座名義" className="sm:col-span-2">
                    <input
                      className={inputClass}
                      value={form.bank_account_holder ?? ""}
                      onChange={(event) => set("bank_account_holder", event.target.value)}
                    />
                  </Field>
                </div>
              </SettingsBlock>

              <SettingsBlock
                title="インボイス・税設定"
                description="適格請求書発行事業者の登録番号、金額入力、端数処理を設定します。"
              >
                <div className="rounded-2xl border border-[var(--color-hairline)] bg-white p-4">
                  <ToggleRow
                    label="適格請求書発行事業者"
                    description="登録番号を取得している場合だけ有効にしてください。"
                    checked={form.is_invoice_issuer ?? false}
                    onChange={(value) => set("is_invoice_issuer", value)}
                  />
                  <ToggleRow
                    label="登録番号を帳票に表示する"
                    description="請求書・領収書をインボイスとして発行する時に表示します。"
                    checked={form.show_registration_number ?? true}
                    onChange={(value) => set("show_registration_number", value)}
                  />
                  <Field label="適格請求書発行事業者登録番号" className="mt-4">
                    <input
                      className={inputClass}
                      placeholder="T1234567890123"
                      maxLength={14}
                      value={form.registration_number ?? ""}
                      onChange={(event) =>
                        set("registration_number", event.target.value.toUpperCase())
                      }
                      disabled={!form.is_invoice_issuer}
                    />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="金額入力">
                    <select
                      className={inputClass}
                      value={form.price_mode ?? "exclusive"}
                      onChange={(event) =>
                        set("price_mode", event.target.value as "exclusive" | "inclusive")
                      }
                    >
                      <option value="exclusive">税抜</option>
                      <option value="inclusive">税込</option>
                    </select>
                  </Field>
                  <Field label="消費税の端数処理">
                    <select
                      className={inputClass}
                      value={form.rounding_mode ?? "floor"}
                      onChange={(event) =>
                        set("rounding_mode", event.target.value as "floor" | "round" | "ceil")
                      }
                    >
                      <option value="floor">切り捨て</option>
                      <option value="round">四捨五入</option>
                      <option value="ceil">切り上げ</option>
                    </select>
                  </Field>
                </div>
              </SettingsBlock>

              <SettingsBlock
                title="帳票文言・領収書デザイン"
                description="freee風に、共通メッセージ、但し書き、印影、収入印紙枠を管理します。"
              >
                <div className="grid gap-4">
                  <Field label="請求書メッセージ">
                    <textarea
                      className={textareaClass}
                      value={form.invoice_message ?? ""}
                      onChange={(event) => set("invoice_message", event.target.value)}
                    />
                  </Field>
                  <Field label="領収書メッセージ">
                    <textarea
                      className={textareaClass}
                      value={form.receipt_message ?? ""}
                      placeholder="上記金額を正に領収いたしました。"
                      onChange={(event) => set("receipt_message", event.target.value)}
                    />
                  </Field>
                  <Field label="領収書 但し書きの初期値">
                    <input
                      className={inputClass}
                      placeholder="商品・サービス代"
                      value={form.receipt_proviso ?? ""}
                      onChange={(event) => set("receipt_proviso", event.target.value)}
                    />
                  </Field>
                  <Field label="共通備考">
                    <textarea
                      className={textareaClass}
                      value={form.document_footer_note ?? ""}
                      onChange={(event) => set("document_footer_note", event.target.value)}
                    />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <ToggleRow
                    label="領収書に収入印紙枠を表示"
                    description="必要な場合に貼付するための枠を出します。"
                    checked={form.show_stamp_box ?? true}
                    onChange={(value) => set("show_stamp_box", value)}
                  />
                  <ToggleRow
                    label="電子印影を表示"
                    description="画像アップロード前でも、赤い印影風の表示を使えます。"
                    checked={form.show_seal ?? true}
                    onChange={(value) => set("show_seal", value)}
                  />
                  <Field label="印影文字">
                    <input
                      className={inputClass}
                      maxLength={16}
                      value={form.seal_text ?? "領収"}
                      onChange={(event) => set("seal_text", event.target.value)}
                    />
                  </Field>
                  <Field label="社印ファイル参照">
                    <input
                      className={inputClass}
                      value={form.seal_ref ?? ""}
                      onChange={(event) => set("seal_ref", event.target.value)}
                    />
                  </Field>
                  <ToggleRow
                    label="ロゴ表示"
                    description="帳票PDFとプレビューに事業者のロゴを表示します。"
                    checked={form.show_logo ?? false}
                    onChange={(value) => set("show_logo", value)}
                  />
                  <Field label="ロゴファイル参照">
                    <input
                      className={inputClass}
                      placeholder={DEFAULT_LOGO_REF}
                      value={form.logo_ref ?? DEFAULT_LOGO_REF}
                      onChange={(event) => set("logo_ref", event.target.value)}
                    />
                  </Field>
                </div>
              </SettingsBlock>

              {patch.error && (
                <p role="alert" className="rounded-xl bg-red-50 px-4 py-3 text-sm text-[var(--color-shuiro)]">
                  {patch.error.message}
                </p>
              )}
              <button
                type="button"
                onClick={() => patch.mutate(form)}
                disabled={patch.isPending || !form.trade_name?.trim()}
                className="rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-6 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 active:translate-y-px disabled:opacity-40"
              >
                {patch.isPending ? "保存中…" : "帳票設定を保存"}
              </button>
            </div>
          </div>

          <div className="border-t border-[var(--color-hairline)] bg-[#f7f4ee] p-5 lg:border-l lg:border-t-0">
            <div className="sticky top-4 rounded-[24px] bg-[#fffefa] p-5 shadow-[0_24px_55px_-35px_rgba(23,33,43,0.35)]">
              <p className="text-[10px] font-semibold tracking-[0.24em] text-[var(--color-seiji)]">
                LIVE PREVIEW
              </p>
              {form.show_logo && logoSrc && (
                <img
                  src={logoSrc}
                  alt="事業者 ロゴ"
                  className="mt-4 h-24 w-full rounded-2xl border border-[var(--color-hairline)] object-cover shadow-[0_18px_35px_-28px_rgba(23,33,43,0.65)]"
                />
              )}
              <div className="mt-4 border-t-4 border-[var(--color-seiji)] pt-5">
                <p className="text-xl font-bold tracking-[0.22em] text-[var(--color-sumi)]">
                  領 収 書
                </p>
                <div className="mt-5 rounded-xl bg-[var(--color-sumi)] px-4 py-3 text-white">
                  <p className="text-[10px] text-white/65">領収金額</p>
                  <p className="mt-1 text-2xl font-bold tabular-nums">¥128,700</p>
                </div>
                <div className="mt-5 text-sm font-bold text-[var(--color-sumi)]">
                  {form.trade_name || "事業者"}
                </div>
                {form.show_representative && form.representative_name && (
                  <p className="mt-1 text-xs text-[var(--color-sumi-soft)]">
                    代表　{form.representative_name}
                  </p>
                )}
                {displayAddress && (
                  <p className="mt-2 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
                    {displayAddress}
                  </p>
                )}
                {form.is_invoice_issuer && form.show_registration_number && form.registration_number && (
                  <p className="mt-2 text-xs font-semibold text-[var(--color-seiji)]">
                    登録番号 {form.registration_number}
                  </p>
                )}
                <div className="mt-5 grid grid-cols-[1fr_72px] gap-3">
                  <div className="rounded-xl border border-[var(--color-hairline)] p-3 text-xs text-[var(--color-sumi-soft)]">
                    但し　{form.receipt_proviso || "商品・サービス代"}　として
                  </div>
                  {form.show_seal && (
                    <div className="grid h-[72px] place-items-center rounded-full border border-[#b24036] text-xs font-bold text-[#b24036]">
                      {form.seal_text || "領収"}
                    </div>
                  )}
                </div>
                {form.show_stamp_box && (
                  <div className="mt-5 w-24 rounded-xl border border-[var(--color-hairline)] bg-[#f5efe9] px-3 py-4 text-center text-xs text-[#4b5563]">
                    収入印紙
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </Card>
    </section>
  );
}

function SettingsBlock({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div>
        <h4 className="text-sm font-bold tracking-[0.05em] text-[var(--color-sumi)]">{title}</h4>
        <p className="mt-1 text-xs leading-relaxed text-[var(--color-sumi-soft)]">{description}</p>
      </div>
      {children}
    </section>
  );
}

function Field({
  label,
  children,
  className = "",
  required = false,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
  required?: boolean;
}) {
  return (
    <label className={`block text-xs font-medium text-[var(--color-sumi-soft)] ${className}`}>
      {label}
      {required && <span className="ml-1 text-[var(--color-shuiro)]">必須</span>}
      {children}
    </label>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl border border-[var(--color-hairline)] bg-white px-4 py-3">
      <div>
        <p className="text-sm font-semibold text-[var(--color-sumi)]">{label}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-[var(--color-sumi-soft)]">
          {description}
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative h-7 w-12 shrink-0 rounded-full transition-colors active:translate-y-px ${checked ? "bg-[var(--color-seiji)]" : "bg-[var(--color-hairline)]"}`}
      >
        <span
          className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-6" : "translate-x-1"}`}
        />
      </button>
    </div>
  );
}
