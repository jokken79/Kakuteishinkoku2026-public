/**
 * Captura (撮影). Mobile-first: escaner en vivo con guia azul/verde y **連続撮影**
 * — la camara no se cierra despues de cada foto: cada captura entra a una cola
 * que sube en segundo plano mientras se sigue fotografiando. Sin conexion, las
 * fotos quedan guardadas en el celular y se envian solas al volver la red.
 *
 * Cuando el OCR responde, el 仕訳 propuesto aparece en la tira de abajo con el
 * 科目 elegible y confirmacion de UN toque (sin pasar por la bandeja).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  useActiveYear,
  useActiveYearLock,
  useConfirmReceipt,
} from "../lib/hooks";
import { ApiError } from "../lib/api";
import { useCaptureQueue } from "../lib/useCaptureQueue";
import type { CaptureItem } from "../lib/captureQueue";
import { useUiStore } from "../lib/store";
import { Card, EmptyState } from "../components/ui";
import { Icon } from "../components/Icon";
import { CaptureQueueList } from "../components/CaptureQueueList";
import { screenVariants } from "../variants/layoutVariants";

type ScannerStatus = "idle" | "starting" | "searching" | "ready" | "blocked";

interface ScanState {
  status: ScannerStatus;
  brightness: number;
  contrast: number;
  edgeScore: number;
  progress: number;
  message: string;
}

const INITIAL_SCAN: ScanState = {
  status: "idle",
  brightness: 0,
  contrast: 0,
  edgeScore: 0,
  progress: 0,
  message: "カメラを起動してください。",
};

const READY_FRAMES = 7;
const ANALYSIS_WIDTH = 180;
const ANALYSIS_HEIGHT = 120;
/** Pausa despues de disparar, para no fotografiar dos veces el mismo recibo. */
const REARM_COOLDOWN_MS = 1200;

export function CaptureScreen() {
  const setActiveSection = useUiStore((s) => s.setActiveSection);
  const year = useActiveYear();
  const { isReadOnly, label: lockLabel } = useActiveYearLock();
  const { queue, items, pending, online } = useCaptureQueue(year);
  const confirm = useConfirmReceipt();
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [autoCapture, setAutoCapture] = useState(true);
  const [shotsThisSession, setShotsThisSession] = useState(0);
  const [confirming, setConfirming] = useState<ReadonlySet<string>>(new Set());
  const [scan, setScan] = useState<ScanState>(INITIAL_SCAN);
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const analysisCanvas = useRef<HTMLCanvasElement>(null);
  const captureCanvas = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const loopRef = useRef<number | null>(null);
  const readyFrames = useRef(0);
  const lastAnalysisAt = useRef(0);
  // El disparo automatico se re-arma recien cuando el recibo sale del cuadro,
  // asi el modo continuo no dispara N veces sobre el mismo ticket.
  const armed = useRef(true);
  const cooldownUntil = useRef(0);

  const cameraSupported =
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function";

  /** Encola una imagen: la subida y el OCR corren en segundo plano. */
  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file || isReadOnly) return;
      setError(null);
      void queue.enqueue(file, file.name || `receipt-${Date.now()}.jpg`, year);
      setShotsThisSession((n) => n + 1);
    },
    [isReadOnly, queue, year],
  );

  const stopScanner = useCallback(() => {
    if (loopRef.current != null) {
      window.cancelAnimationFrame(loopRef.current);
      loopRef.current = null;
    }
    for (const track of streamRef.current?.getTracks() ?? []) {
      track.stop();
    }
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    readyFrames.current = 0;
    armed.current = true;
    cooldownUntil.current = 0;
    lastAnalysisAt.current = 0;
    setScan(INITIAL_SCAN);
  }, []);

  const closeScanner = useCallback(() => {
    stopScanner();
    setScannerOpen(false);
  }, [stopScanner]);

  /** Dispara y **deja la camara abierta**: el recibo siguiente entra enseguida. */
  const captureFromVideo = useCallback(() => {
    const video = videoRef.current;
    const canvas = captureCanvas.current;
    if (!video || !canvas || video.videoWidth === 0 || video.videoHeight === 0) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          setError("撮影画像を作成できませんでした。ファイル選択でお試しください。");
          return;
        }
        const file = new File([blob], `receipt-${Date.now()}.jpg`, {
          type: "image/jpeg",
        });
        handleFile(file);
      },
      "image/jpeg",
      0.92,
    );
    armed.current = false;
    cooldownUntil.current = performance.now() + REARM_COOLDOWN_MS;
    readyFrames.current = 0;
  }, [handleFile]);

  const analyzeFrame = useCallback(() => {
    const video = videoRef.current;
    const canvas = analysisCanvas.current;
    const ctx = canvas?.getContext("2d", { willReadFrequently: true });
    const now = performance.now();
    if (now - lastAnalysisAt.current < 160) {
      loopRef.current = window.requestAnimationFrame(analyzeFrame);
      return;
    }
    lastAnalysisAt.current = now;
    if (!video || !canvas || !ctx || video.readyState < 2) {
      loopRef.current = window.requestAnimationFrame(analyzeFrame);
      return;
    }

    canvas.width = ANALYSIS_WIDTH;
    canvas.height = ANALYSIS_HEIGHT;
    ctx.drawImage(video, 0, 0, ANALYSIS_WIDTH, ANALYSIS_HEIGHT);
    const data = ctx.getImageData(0, 0, ANALYSIS_WIDTH, ANALYSIS_HEIGHT).data;

    let sum = 0;
    let sumSq = 0;
    let edges = 0;
    let samples = 0;
    const step = 4;
    for (let y = 10; y < ANALYSIS_HEIGHT - 10; y += step) {
      for (let x = 10; x < ANALYSIS_WIDTH - 10; x += step) {
        const i = (y * ANALYSIS_WIDTH + x) * 4;
        const luma = data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
        const right = i + step * 4;
        const down = ((y + step) * ANALYSIS_WIDTH + x) * 4;
        const rightLuma =
          data[right] * 0.299 + data[right + 1] * 0.587 + data[right + 2] * 0.114;
        const downLuma =
          data[down] * 0.299 + data[down + 1] * 0.587 + data[down + 2] * 0.114;
        sum += luma;
        sumSq += luma * luma;
        edges += Math.abs(luma - rightLuma) + Math.abs(luma - downLuma);
        samples += 1;
      }
    }

    const brightness = samples > 0 ? sum / samples : 0;
    const variance = samples > 0 ? sumSq / samples - brightness * brightness : 0;
    const contrast = Math.sqrt(Math.max(variance, 0));
    const edgeScore = samples > 0 ? edges / samples : 0;

    const brightEnough = brightness > 45 && brightness < 225;
    const contrastEnough = contrast > 24;
    const edgesEnough = edgeScore > 13;
    const ready = brightEnough && contrastEnough && edgesEnough;
    readyFrames.current = ready
      ? Math.min(READY_FRAMES, readyFrames.current + 1)
      : Math.max(0, readyFrames.current - 1);
    const stable = readyFrames.current >= READY_FRAMES;

    // Re-armado: el cuadro tiene que quedar vacio (recibo retirado) y haber
    // pasado el cooldown antes de permitir el proximo disparo automatico.
    if (!armed.current && readyFrames.current === 0 && now >= cooldownUntil.current) {
      armed.current = true;
    }

    let message = "青い枠にレシート全体を入れてください。";
    if (!armed.current) {
      message = "次のレシートに入れ替えてください。";
    } else if (!brightEnough) {
      message =
        brightness <= 45
          ? "少し明るい場所で撮影してください。"
          : "反射が強いです。角度を少し変えてください。";
    } else if (!contrastEnough) {
      message = "文字がぼやけています。少し近づけてください。";
    } else if (!edgesEnough) {
      message = "レシートの四隅が見えるように合わせてください。";
    } else if (stable) {
      message = "読み取り準備OK。緑の枠で撮影できます。";
    }

    setScan({
      status: stable && armed.current ? "ready" : "searching",
      brightness: Math.round(brightness),
      contrast: Math.round(contrast),
      edgeScore: Math.round(edgeScore),
      progress: readyFrames.current / READY_FRAMES,
      message,
    });

    if (stable && autoCapture && armed.current) {
      captureFromVideo();
    }

    loopRef.current = window.requestAnimationFrame(analyzeFrame);
  }, [autoCapture, captureFromVideo]);

  const startScanner = useCallback(async () => {
    if (isReadOnly) return;
    if (!cameraSupported) {
      setScan({
        ...INITIAL_SCAN,
        status: "blocked",
        message: "このブラウザではライブカメラを利用できません。",
      });
      return;
    }
    setError(null);
    setScannerOpen(true);
    setShotsThisSession(0);
    setScan({ ...INITIAL_SCAN, status: "starting", message: "カメラを起動中です。" });
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      readyFrames.current = 0;
      armed.current = true;
      cooldownUntil.current = 0;
      lastAnalysisAt.current = 0;
      setScan({
        ...INITIAL_SCAN,
        status: "searching",
        message: "青い枠にレシート全体を入れてください。",
      });
      loopRef.current = window.requestAnimationFrame(analyzeFrame);
    } catch {
      setScan({
        ...INITIAL_SCAN,
        status: "blocked",
        message: "カメラを許可できませんでした。写真ファイルを選択してください。",
      });
    }
  }, [analyzeFrame, cameraSupported, isReadOnly]);

  useEffect(() => () => stopScanner(), [stopScanner]);

  /** Confirma el 仕訳 de una captura con el 科目 elegido, en un solo toque. */
  const confirmCapture = useCallback(
    (item: CaptureItem, accountCode: string) => {
      const id = item.result?.transaction.id;
      if (!id || isReadOnly) return;
      setConfirming((prev) => new Set(prev).add(item.id));
      // `mutateAsync` y no `mutate`: el hook comparte un solo observer y los
      // callbacks por-llamada solo corren para la ultima, asi que confirmar dos
      // capturas seguidas dejaba la primera colgada en "登録中…" para siempre.
      void confirm
        .mutateAsync({ id, corrections: { account_code: accountCode } })
        .then(() => queue.markConfirmed(item.id))
        .catch((err: unknown) => {
          setError(
            err instanceof ApiError
              ? err.message
              : "登録に失敗しました。もう一度お試しください。",
          );
        })
        .finally(() => {
          setConfirming((prev) => {
            const next = new Set(prev);
            next.delete(item.id);
            return next;
          });
        });
    },
    [confirm, isReadOnly, queue],
  );

  const scanReady = scan.status === "ready";
  const scanColor = scanReady ? "var(--color-seiji)" : "#2563eb";
  const scanMetrics = useMemo(
    () => [
      { label: "明るさ", value: scan.brightness },
      { label: "文字", value: scan.contrast },
      { label: "輪郭", value: scan.edgeScore },
    ],
    [scan.brightness, scan.contrast, scan.edgeScore],
  );
  const awaitingReview = items.filter(
    (item) => item.result !== null && !item.confirmed,
  ).length;
  const finished = items.some(
    (item) => item.status === "done" || item.status === "duplicate",
  );

  return (
    <motion.div
      variants={screenVariants}
      initial="hidden"
      animate="visible"
      className="mx-auto max-w-2xl px-4 py-6 sm:px-8 sm:py-10"
    >
      <div className="mb-6">
        <h2 className="text-xl font-bold text-[var(--color-sumi)]">領収書を撮影</h2>
        <p className="mt-1 text-sm text-[var(--color-sumi-soft)]">
          続けて撮るだけ。読み取りは裏で進み、オフラインでも端末に保存して後で自動送信します。
        </p>
      </div>

      {!online && (
        <Card className="mb-4 border-[var(--color-kohaku)] p-4">
          <div className="flex items-start gap-3">
            <Icon
              name="cloud"
              className="mt-0.5 h-5 w-5 shrink-0 text-[var(--color-kohaku)]"
            />
            <p className="text-sm text-[var(--color-sumi)]">
              オフラインです。撮影した写真は端末に保存され、接続が戻ると自動で送信します。
            </p>
          </div>
        </Card>
      )}

      {/* Zona de captura */}
      <input
        ref={fileInput}
        type="file"
        accept="image/*,application/pdf"
        multiple
        className="hidden"
        onChange={(e) => {
          for (const file of e.target.files ?? []) handleFile(file);
          e.target.value = "";
        }}
      />
      <input
        ref={cameraInput}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => {
          handleFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      <Card as="section" className="relative overflow-hidden p-3 sm:p-4">
        {isReadOnly && (
          <div className="mb-3 rounded-[var(--radius-card)] border border-[var(--color-kohaku)] bg-[var(--color-kohaku-soft)] p-4">
            <p className="text-sm font-medium text-[var(--color-sumi)]">
              {lockLabel}の年度は読み取り専用です。新しい領収書は追加できません。
            </p>
          </div>
        )}
        <div
          className={`relative overflow-hidden rounded-[12px] border-2 transition-colors ${
            scannerOpen
              ? "border-[var(--color-hairline)] bg-[var(--color-sumi)]"
              : dragging
                ? "border-dashed border-[var(--color-seiji)] bg-[var(--color-seiji-soft)]"
                : "border-dashed border-[var(--color-hairline)] bg-[var(--color-surface)]"
          }`}
        >
          {scannerOpen ? (
            <div className="relative aspect-[3/4] min-h-[440px] overflow-hidden bg-[var(--color-sumi)] sm:aspect-[4/3]">
              <video
                ref={videoRef}
                playsInline
                muted
                className="h-full w-full object-cover"
                aria-label="ライブカメラプレビュー"
              />
              <canvas ref={analysisCanvas} className="hidden" />
              <canvas ref={captureCanvas} className="hidden" />

              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_center,transparent_34%,rgba(27,32,48,0.46)_78%)]" />
              <motion.div
                className="pointer-events-none absolute left-1/2 top-1/2 aspect-[7/10] w-[78%] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-[18px] border-[3px]"
                animate={{
                  borderColor: scanColor,
                  boxShadow: `0 0 0 999px rgba(27,32,48,0.18), inset 0 0 0 1px rgba(255,255,255,0.22)`,
                }}
                transition={{ duration: 0.22 }}
              >
                <span
                  className="absolute -left-1 -top-1 h-8 w-8 rounded-tl-[18px] border-l-4 border-t-4"
                  style={{ borderColor: scanColor }}
                />
                <span
                  className="absolute -right-1 -top-1 h-8 w-8 rounded-tr-[18px] border-r-4 border-t-4"
                  style={{ borderColor: scanColor }}
                />
                <span
                  className="absolute -bottom-1 -left-1 h-8 w-8 rounded-bl-[18px] border-b-4 border-l-4"
                  style={{ borderColor: scanColor }}
                />
                <span
                  className="absolute -bottom-1 -right-1 h-8 w-8 rounded-br-[18px] border-b-4 border-r-4"
                  style={{ borderColor: scanColor }}
                />
              </motion.div>

              <div className="absolute inset-x-3 top-3 rounded-[14px] border border-white/15 bg-[rgba(27,32,48,0.68)] p-3 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] backdrop-blur-md">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold">
                    {scanReady ? "読み取り準備OK" : "自動スキャン中"}
                  </p>
                  <div className="flex items-center gap-2">
                    <span className="tabular rounded-[var(--radius-pill)] bg-white/12 px-2 py-0.5 text-[11px] font-semibold">
                      {shotsThisSession}枚
                    </span>
                    <span
                      className="rounded-[var(--radius-pill)] px-2 py-0.5 text-[11px] font-semibold"
                      style={{
                        backgroundColor: scanReady ? "var(--color-seiji-soft)" : "#dbeafe",
                        color: scanReady ? "var(--color-seiji)" : "#1d4ed8",
                      }}
                    >
                      {scanReady ? "OK" : "調整中"}
                    </span>
                  </div>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-white/82">{scan.message}</p>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/18">
                  <motion.div
                    className="h-full rounded-full"
                    style={{ backgroundColor: scanColor }}
                    animate={{ width: `${Math.round(scan.progress * 100)}%` }}
                  />
                </div>
              </div>

              <div className="absolute inset-x-3 bottom-3 rounded-[16px] border border-white/15 bg-[rgba(27,32,48,0.72)] p-3 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] backdrop-blur-md">
                <div className="grid grid-cols-3 gap-2">
                  {scanMetrics.map((metric) => (
                    <div key={metric.label} className="rounded-[10px] bg-white/10 px-2 py-1.5">
                      <p className="text-[10px] text-white/62">{metric.label}</p>
                      <p className="tabular text-sm font-semibold">{metric.value}</p>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={captureFromVideo}
                    disabled={scan.status === "starting"}
                    className="flex flex-1 items-center justify-center gap-2 rounded-[var(--radius-pill)] bg-white px-4 py-2.5 text-sm font-semibold text-[var(--color-sumi)] transition-transform active:translate-y-px disabled:opacity-50"
                  >
                    <Icon name="camera" className="h-4 w-4" />
                    撮影する
                  </button>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={autoCapture}
                    onClick={() => setAutoCapture((v) => !v)}
                    className={`rounded-[var(--radius-pill)] px-3 py-2 text-xs font-semibold transition-colors ${
                      autoCapture
                        ? "bg-[var(--color-seiji-soft)] text-[var(--color-seiji)]"
                        : "bg-white/10 text-white"
                    }`}
                  >
                    AUTO
                  </button>
                  <button
                    type="button"
                    onClick={closeScanner}
                    className="rounded-[var(--radius-pill)] border border-white/20 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-white/10"
                  >
                    撮影を終える
                  </button>
                </div>
                {pending > 0 && (
                  <p className="mt-2 text-[11px] text-white/70">
                    {pending}枚を裏で送信中。撮り続けて大丈夫です。
                  </p>
                )}
              </div>
            </div>
          ) : null}

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              for (const file of e.dataTransfer.files ?? []) handleFile(file);
            }}
            className={`flex flex-col items-center ${scannerOpen ? "hidden" : "p-8 text-center"}`}
          >
            <div className="mb-4 grid h-16 w-16 place-items-center rounded-full bg-[var(--color-paper-sink)] text-[var(--color-sumi-soft)]">
              <Icon name="camera" className="h-7 w-7" />
            </div>
            <p className="text-base font-medium text-[var(--color-sumi)]">
              レシートを枠に合わせて連続撮影
            </p>
            <p className="mt-1.5 max-w-sm text-sm text-[var(--color-sumi-soft)]">
              1枚ごとに待つ必要はありません。撮ったそばから読み取りが進みます。
            </p>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                onClick={() => void startScanner()}
                disabled={!cameraSupported || isReadOnly}
                className="flex items-center gap-2 rounded-[var(--radius-pill)] bg-[var(--color-sumi)] px-5 py-2.5 text-sm font-medium text-white transition-transform active:translate-y-px disabled:opacity-50"
              >
                <Icon name="camera" className="h-4 w-4" />
                連続スキャンを始める
              </button>
              <button
                type="button"
                onClick={() => cameraInput.current?.click()}
                disabled={isReadOnly}
                className="flex items-center gap-2 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-5 py-2.5 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)] sm:hidden"
              >
                <Icon name="camera" className="h-4 w-4" />
                端末カメラ
              </button>
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                disabled={isReadOnly}
                className="flex items-center gap-2 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] bg-[var(--color-surface)] px-5 py-2.5 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
              >
                <Icon name="upload" className="h-4 w-4" />
                ファイルを選択
              </button>
            </div>
            {/* Segunda via: import masivo desde CSV (sin fotografiar) */}
            <button
              type="button"
              onClick={() => setActiveSection("import")}
              className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-[var(--color-seiji)] underline-offset-4 transition-opacity hover:underline"
            >
              <Icon name="archive" className="h-4 w-4" />
              明細CSVでまとめて取り込む
            </button>
          </div>
        </div>
      </Card>

      {/* Error con voz clara */}
      {error && (
        <Card className="mt-4 border-[var(--color-kohaku)] p-4">
          <div className="flex items-start gap-3">
            <Icon
              name="shield"
              className="mt-0.5 h-5 w-5 shrink-0 text-[var(--color-kohaku)]"
            />
            <p className="text-sm text-[var(--color-sumi)]">{error}</p>
          </div>
        </Card>
      )}

      {/* Tira de capturas: estado de subida + 仕訳 con confirmacion de 1 toque */}
      {items.length > 0 && (
        <div className="mt-6">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-[var(--color-sumi)]">
              今回の撮影（{items.length}枚
              {awaitingReview > 0 ? `・確認待ち ${awaitingReview}` : ""}）
            </p>
            {finished && (
              <button
                type="button"
                onClick={() => void queue.clearFinished()}
                className="text-xs font-medium text-[var(--color-sumi-soft)] underline-offset-4 hover:underline"
              >
                完了分を片づける
              </button>
            )}
          </div>
          <CaptureQueueList
            items={items}
            confirming={confirming}
            disabled={isReadOnly}
            onConfirm={confirmCapture}
            onAccountChange={(item, accountCode) =>
              queue.setAccount(item.id, accountCode)
            }
            onRetry={(id) => queue.retry(id)}
            onDismiss={(id) => void queue.remove(id)}
          />
          <button
            type="button"
            onClick={() => setActiveSection("journal-tray")}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-[var(--radius-pill)] border border-[var(--color-hairline)] py-2.5 text-sm font-medium text-[var(--color-sumi)] transition-colors hover:bg-[var(--color-paper-sink)]"
          >
            仕訳トレイでまとめて確認
            <Icon name="arrow" className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Nota guia cuando no hay actividad */}
      {items.length === 0 && !error && (
        <div className="mt-2">
          <EmptyState
            icon="shield"
            title="プライバシーを最優先"
            hint="OCRは端末内（PaddleOCR）で処理され、外部に送信されません。設定で外部OCRを許可しない限り、データは外に出ません。"
          />
        </div>
      )}
    </motion.div>
  );
}
