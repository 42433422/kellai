export function htmlToSpeechText(value: unknown) {
  return String(value ?? "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h\d)>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "和")
    .replace(/&lt;/g, "")
    .replace(/&gt;/g, "")
    .replace(/[①]/g, "一")
    .replace(/[②]/g, "二")
    .replace(/[③]/g, "三")
    .replace(/[④]/g, "四")
    .replace(/[⑤]/g, "五")
    .replace(/[⑥]/g, "六")
    .replace(/[→]/g, "到")
    .replace(/[•·]/g, "。")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildOnboardingSpeechText(title?: unknown, description?: unknown) {
  return [title, description]
    .map(htmlToSpeechText)
    .filter(Boolean)
    .join("。")
    .slice(0, 520);
}

export function estimateSpeechHoldMs(text: string, audioDurationSeconds?: number | null) {
  const cjkCount = (text.match(/[\u3400-\u9fff]/g) || []).length;
  const latinWordCount = (text.match(/[A-Za-z0-9]+/g) || []).length;
  const pauseCount = (text.match(/[。！？；：,.，、\n]/g) || []).length;
  const textEstimate = cjkCount * 210 + latinWordCount * 320 + pauseCount * 220 + 1200;
  const audioEstimate = Number.isFinite(audioDurationSeconds)
    ? Number(audioDurationSeconds) * 1000
    : 0;
  return Math.min(70000, Math.max(4500, textEstimate, audioEstimate));
}
