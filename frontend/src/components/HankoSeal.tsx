/**
 * Sello 印 (hanko) — el signature visual. Disco rojo shuiro con el kanji 確
 * (確認 = confirmado). Se usa como overlay efimero al estampar y como marca
 * estatica en tarjetas ya confirmadas.
 */
import { motion } from "framer-motion";
import { hankoStampVariants, hankoInkVariants } from "../variants/hankoVariants";

interface HankoSealProps {
  /** Tamano en px del disco. */
  size?: number;
  /** Kanji central (確 por defecto = 確認). */
  glyph?: string;
  /** Si true, anima el gesto de estampado al montar. */
  animate?: boolean;
  className?: string;
}

export function HankoSeal({
  size = 64,
  glyph = "確",
  animate = false,
  className,
}: HankoSealProps) {
  return (
    <div
      className={`relative grid place-items-center ${className ?? ""}`}
      style={{ width: size, height: size }}
    >
      {animate && (
        <motion.span
          aria-hidden
          variants={hankoInkVariants}
          initial="hidden"
          animate="stamp"
          className="absolute inset-0 rounded-full"
          style={{ background: "var(--color-shuiro)", filter: "blur(6px)" }}
        />
      )}
      <motion.span
        variants={animate ? hankoStampVariants : undefined}
        initial={animate ? "hidden" : false}
        animate={animate ? "stamp" : false}
        className="hanko-ink relative grid place-items-center rounded-full text-white shadow-[var(--shadow-paper)]"
        style={{
          width: size,
          height: size,
          border: "2.5px solid var(--color-shuiro-deep)",
          fontFamily: "var(--font-sans)",
          fontWeight: 700,
          fontSize: size * 0.46,
          lineHeight: 1,
          // Textura sutil de tinta dispareja.
          boxShadow: "inset 0 0 0 2px rgba(255,255,255,0.12)",
        }}
      >
        {glyph}
      </motion.span>
    </div>
  );
}
