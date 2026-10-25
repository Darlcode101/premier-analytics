// F-6a: why a card was shown, in plain words. The reason comes from the match data (never AI).
import { fill, fromCatalogues } from './locales'
import type { Language } from './types'

export type CardReason = 'late_tackle' | 'tactical_foul' | 'holding' | 'handball' | 'dissent' | 'time_wasting'
  | 'serious_foul_play' | 'denied_goal_chance' | 'violent_conduct' | 'offensive_language'

type Phrase = [withVictim: (v: string) => string, alone: string]

const HAND_WRITTEN: Record<'en' | 'es' | 'ar', Record<CardReason, Phrase>> = {
  en: {
    late_tackle: [v => `Late tackle on ${v}`, 'Late tackle'],
    tactical_foul: [v => `Fouled ${v} to stop a counter-attack`, 'Foul to stop a counter-attack'],
    holding: [v => `Pulled back ${v}`, 'Holding an opponent'],
    handball: [() => 'Handball', 'Handball'],
    dissent: [() => 'Dissent towards the referee', 'Dissent towards the referee'],
    time_wasting: [() => 'Time-wasting', 'Time-wasting'],
    serious_foul_play: [v => `Dangerous tackle on ${v}`, 'Dangerous tackle'],
    denied_goal_chance: [v => `Denied ${v} a clear chance to score`, 'Denied a clear chance to score'],
    violent_conduct: [() => 'Violent conduct', 'Violent conduct'],
    offensive_language: [() => 'Offensive language towards the referee', 'Offensive language towards the referee'],
  },
  es: {
    late_tackle: [v => `Entrada tardía a ${v}`, 'Entrada tardía'],
    tactical_foul: [v => `Falta a ${v} para cortar un contraataque`, 'Falta para cortar un contraataque'],
    holding: [v => `Agarrón a ${v}`, 'Agarrón a un rival'],
    handball: [() => 'Mano', 'Mano'],
    dissent: [() => 'Protestar al árbitro', 'Protestar al árbitro'],
    time_wasting: [() => 'Pérdida de tiempo', 'Pérdida de tiempo'],
    serious_foul_play: [v => `Entrada peligrosa a ${v}`, 'Entrada peligrosa'],
    denied_goal_chance: [v => `Evitó una ocasión clara de gol de ${v}`, 'Evitó una ocasión clara de gol'],
    violent_conduct: [() => 'Conducta violenta', 'Conducta violenta'],
    offensive_language: [() => 'Lenguaje ofensivo hacia el árbitro', 'Lenguaje ofensivo hacia el árbitro'],
  },
  ar: {
    late_tackle: [v => `تدخل متأخر على ${v}`, 'تدخل متأخر'],
    tactical_foul: [v => `خطأ على ${v} لإيقاف هجمة مرتدة`, 'خطأ لإيقاف هجمة مرتدة'],
    holding: [v => `جذب ${v} من الخلف`, 'إعاقة الخصم بالإمساك'],
    handball: [() => 'لمس الكرة باليد', 'لمس الكرة باليد'],
    dissent: [() => 'الاعتراض على الحكم', 'الاعتراض على الحكم'],
    time_wasting: [() => 'إضاعة الوقت', 'إضاعة الوقت'],
    serious_foul_play: [v => `تدخل خطير على ${v}`, 'تدخل خطير'],
    denied_goal_chance: [v => `حرم ${v} من فرصة هدف محققة`, 'منع فرصة هدف محققة'],
    violent_conduct: [() => 'سلوك عنيف', 'سلوك عنيف'],
    offensive_language: [() => 'ألفاظ مسيئة للحكم', 'ألفاظ مسيئة للحكم'],
  },
}

const REASONS: Record<Language, Record<CardReason, Phrase>> = {
  ...HAND_WRITTEN,
  ...fromCatalogues(c => Object.fromEntries(Object.entries(c.cards).map(
    ([r, [withVictim, alone]]) => [r, [(v: string) => fill(withVictim, { v }), alone]])) as Record<CardReason, Phrase>),  // DK-12
}

const SECOND: Record<Language, string> = { en: 'Second yellow', es: 'Segunda amarilla', ar: 'إنذار ثانٍ',
  ...fromCatalogues(c => c.secondYellow) }

/** "Late tackle on Kai Greaves"; a second yellow says so first. Null when the reason is unknown. */
export function cardReasonText(reason: string | null | undefined, victim: string | null, lang: Language,
  secondYellow = false): string | null {
  const phrase = reason ? REASONS[lang][reason as CardReason] : undefined
  if (!phrase) return null
  const text = victim ? phrase[0](victim) : phrase[1]
  return secondYellow ? `${SECOND[lang]}: ${text}` : text
}
