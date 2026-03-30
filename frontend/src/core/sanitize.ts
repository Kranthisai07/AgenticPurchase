import DOMPurify from "dompurify";

/**
 * Sanitize vendor-supplied strings before rendering.
 * Strips all HTML tags and JavaScript.
 * Use on: offer titles, descriptions, seller names,
 *          vendor URLs displayed to user.
 */
export function sanitizeText(input: unknown): string {
  if (typeof input !== "string") return "";
  // TEXT_ONLY: strips all tags, returns plain text
  return DOMPurify.sanitize(input, {
    ALLOWED_TAGS: [],
    ALLOWED_ATTR: [],
  });
}

/**
 * Sanitize a URL — only allow http/https schemes.
 * Prevents javascript: and data: URI injection.
 */
export function sanitizeUrl(input: unknown): string {
  if (typeof input !== "string") return "#";
  const cleaned = DOMPurify.sanitize(input, {
    ALLOWED_TAGS: [],
    ALLOWED_ATTR: [],
  });
  try {
    const url = new URL(cleaned);
    if (!["http:", "https:"].includes(url.protocol)) {
      return "#";
    }
    return cleaned;
  } catch {
    return "#";
  }
}
