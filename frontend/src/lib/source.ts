/**
 * Нэг харагдацад НЭГ `source` (LLD §16.2, AC-21).
 *
 * Backend нь нэг ХАРИУ дотор холимог source гарахыг хориглодог
 * (`MixedSourceError`). Frontend дээр жагсаалт нь мөр тус бүрийн source-ыг
 * агуулж болох тул хориг ЭНД дахин хэрэгтэй: live ба backtest мөр нэг
 * хүснэгтэд хольж харуулах нь «аль нь бодит вэ» гэдгийг бүрхэг болгоно.
 */
export function distinctSources(values: (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}
