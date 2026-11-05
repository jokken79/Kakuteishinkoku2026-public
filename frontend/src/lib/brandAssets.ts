export const DEFAULT_LOGO_REF = "";

export function resolveBrandImageSrc(ref: string | null | undefined): string | null {
  if (!ref) return null;
  const value = ref.trim();
  if (value.startsWith("/") || value.startsWith("http://") || value.startsWith("https://")) {
    return value;
  }
  return null;
}
