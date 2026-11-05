/**
 * Iconos line-art (stroke) — esteticos y serenos, sin emojis.
 * Un solo componente que renderiza por nombre. `currentColor` para heredar.
 */

export type IconName =
  | "home"
  | "camera"
  | "tray"
  | "book"
  | "compass"
  | "file"
  | "archive"
  | "gear"
  | "check"
  | "edit"
  | "upload"
  | "shield"
  | "cloud"
  | "receipt"
  | "calendar"
  | "arrow"
  | "train"
  | "signal"
  | "box"
  | "cup"
  | "glass"
  | "bolt"
  | "sparkle"
  | "menu";

interface IconProps {
  name: IconName;
  className?: string;
  /** Grosor del trazo (line-art fino y sereno por defecto). */
  strokeWidth?: number;
}

const PATHS: Record<IconName, React.ReactNode> = {
  home: <path d="M3 10.5 12 4l9 6.5M5 9.5V20h14V9.5" />,
  camera: (
    <>
      <path d="M4 8h3l1.5-2h7L17 8h3v11H4z" />
      <circle cx="12" cy="13" r="3.2" />
    </>
  ),
  tray: (
    <>
      <path d="M4 13l2.5 4h11L20 13M4 13V5h16v8" />
      <path d="M9 9h6" />
    </>
  ),
  book: <path d="M5 4h9a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2zM16 6h3v14h-3" />,
  compass: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m15 9-2 5-4 1 2-5z" />
    </>
  ),
  file: <path d="M7 3h7l4 4v14H7zM14 3v4h4" />,
  archive: (
    <>
      <path d="M3 6h18v4H3zM5 10v10h14V10" />
      <path d="M9.5 14h5" />
    </>
  ),
  gear: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v3M12 18v3M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M3 12h3M18 12h3M5.2 18.8l2.1-2.1M16.7 7.3l2.1-2.1" />
    </>
  ),
  check: <path d="m5 12.5 4.2 4.2L19 7" />,
  edit: <path d="M4 20h4L19 9l-4-4L4 16zM14 6l4 4" />,
  upload: <path d="M12 16V5M7 9l5-5 5 5M5 19h14" />,
  shield: <path d="M12 3l7 3v6c0 4-3 6.5-7 9-4-2.5-7-5-7-9V6z" />,
  cloud: <path d="M7 18a4 4 0 0 1 0-8 5 5 0 0 1 9.6-1.4A3.5 3.5 0 0 1 17 18z" />,
  receipt: (
    <>
      <path d="M6 3h12v18l-2-1.3-2 1.3-2-1.3-2 1.3-2-1.3L6 21z" />
      <path d="M9 8h6M9 12h6" />
    </>
  ),
  calendar: (
    <>
      <path d="M4 6h16v15H4zM4 10h16M8 3v4M16 3v4" />
    </>
  ),
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  train: (
    <>
      <path d="M7 4h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
      <path d="M5 10h14M9 19l-2 2M15 19l2 2" />
      <circle cx="9" cy="13" r="0.6" />
      <circle cx="15" cy="13" r="0.6" />
    </>
  ),
  signal: (
    <>
      <path d="M5 18a9 9 0 0 1 14 0M8 15a5 5 0 0 1 8 0" />
      <circle cx="12" cy="18" r="0.8" />
    </>
  ),
  box: (
    <>
      <path d="M4 8l8-4 8 4v8l-8 4-8-4z" />
      <path d="M4 8l8 4 8-4M12 12v8" />
    </>
  ),
  cup: (
    <>
      <path d="M5 8h11v5a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4z" />
      <path d="M16 9h2.5a2 2 0 0 1 0 4H16M5 21h11" />
    </>
  ),
  glass: (
    <>
      <path d="M6 4h12l-5 7v6M13 17h-2m1 0v0M11 21h2M7 4l5 7" />
    </>
  ),
  bolt: <path d="M13 3 5 13h6l-1 8 8-10h-6z" />,
  sparkle: (
    <path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z" />
  ),
  menu: (
    <>
      <path d="M4 6h16M4 12h16M4 18h16" />
    </>
  ),
};

export function Icon({ name, className, strokeWidth = 1.6 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      {PATHS[name]}
    </svg>
  );
}
