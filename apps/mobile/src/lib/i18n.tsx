import * as React from 'react'
import { getLocales } from 'expo-localization'
import { getValue, setValue } from './storage'

// The app's own words, in the person's language. What Mesiri says comes from the assistant in their reply
// language already; what is saved is always English (assistant basic 1).

export type Lang = 'en' | 'ml'

const en = {
  appName: 'Mesiri',
  // sign in
  signInTitle: 'Sign in',
  signInLead: 'Use the WhatsApp number your company added for you.',
  phone: 'WhatsApp number',
  phonePlaceholder: '98470 12345',
  sendCode: 'Send code on WhatsApp',
  code: 'Code from WhatsApp',
  codeSent: 'We sent a code to your WhatsApp.',
  signIn: 'Sign in',
  otherNumber: 'Use another number',
  useEmail: 'Sign in with email instead',
  usePhone: 'Sign in with WhatsApp number',
  email: 'Email',
  password: 'Password',
  // tabs
  today: 'Today',
  site: 'Site',
  requests: 'Requests',
  more: 'More',
  speakToMesiri: 'Speak to Mesiri',
  // today
  todayOnSite: 'Today on site',
  todaysReport: "Today's report",
  doneOf: (done: number, all: number) => `${done} of ${all} done`,
  reportGoes: 'Goes to the office in the evening, or send it now',
  sendNow: 'Send now',
  sent: 'Sent',
  notToldYet: 'Not told yet · tap or speak',
  attendance: 'Attendance',
  workDone: 'Work done',
  materialsIn: 'Materials in',
  materialsUsed: 'Materials used',
  problems: 'Problems',
  photos: 'Photos',
  weather: 'Weather and site',
  people: (n: number) => `${n} ${n === 1 ? 'person' : 'people'}`,
  items: (n: number) => `${n} ${n === 1 ? 'entry' : 'entries'}`,
  photosToday: (n: number) => `${n} ${n === 1 ? 'photo' : 'photos'} today`,
  openProblems: (n: number) => `${n} open`,
  toCheck: (n: number) => `${n} waiting for the office to check`,
  draftMark: 'Office to check',
  // site
  stock: 'Stock',
  coming: 'Coming',
  runningLow: (n: number) => `${n} running low.`,
  daysLeft: (n: number) => `${n} ${n === 1 ? 'day' : 'days'} left`,
  low: 'Low',
  onOrder: (q: string) => `${q} on order`,
  notUsedThisWeek: 'Not used this week',
  askForMaterial: 'Ask for material',
  noStock: 'No stock recorded at this site yet.',
  noRequests: 'No requests from this site yet.',
  status: {
    waiting: 'Waiting',
    ordered: 'Ordered',
    sent: 'Sent from another site',
    done: 'Received',
    rejected: 'Not approved',
    cancelled: 'Cancelled',
  } as Record<string, string>,
  neededBy: (d: string) => `Needed by ${d}`,
  // speak
  listening: 'Listening',
  tapToStop: 'Tap to stop. Nothing is saved until you check it.',
  sayInOneGo: 'Say everything in one go, in any language:',
  hints: ['who came today', 'what arrived', 'work done', 'a problem', 'what we need'],
  hearing: 'Mesiri is listening to it…',
  thinking: 'Mesiri is working it out…',
  youSaid: 'You said',
  checkBeforeSaving: 'Check before saving',
  sayAChange: 'Say a change',
  typeInstead: 'Type instead',
  typeHere: 'Type the update…',
  send: 'Send',
  micDenied: 'Mesiri needs the microphone to hear you. Allow it in the phone settings, or type instead.',
  tryAgain: 'Try again',
  done: 'Done',
  speakNow: 'Tap the mic and speak',
  // forms (MOB-05)
  speakToFill: 'Speak to fill the form',
  speakToFillHint: 'Say it as you would on WhatsApp',
  fromVoice: 'From your voice',
  material: 'Material',
  searchMaterial: 'Type to find the material',
  howMuch: 'How much',
  unit: 'Unit',
  supplier: 'From (supplier)',
  usedFor: 'Used for (work)',
  note: 'Note',
  problemType: 'What kind of problem',
  severity: 'How serious',
  whatHappened: 'What happened',
  save: 'Save',
  saved: 'Saved',
  fillForm: 'Fill the form',
  nothingFromVoice: 'Mesiri did not prepare one from that. Try again, or fill it in.',
  pickMaterial: 'Choose the material first.',
  enterQuantity: 'Say or type how much.',
  describeProblem: 'Say or type what happened.',
  englishNote: 'Saved in English. Speak in any language to fill it.',
  // more
  switchSite: 'Which site are you on?',
  language: 'Mesiri talks to you in',
  languageNote: 'Speak in any language, any time. What is saved is always in English, so the office can read it.',
  signOut: 'Sign out',
  signedInAs: 'Signed in as',
  online: 'Online',
  offline: 'No signal',
  // common
  loading: 'Loading…',
  couldNotLoad: 'Could not load. Pull down to try again.',
  noSites: 'You are not on any site yet. Ask the office to add you to a project.',
  back: 'Back',
  close: 'Close',
}

export type Words = typeof en

const ml: Words = {
  ...en,
  signInTitle: 'സൈൻ ഇൻ',
  signInLead: 'കമ്പനി ചേർത്ത നിങ്ങളുടെ വാട്സ്ആപ്പ് നമ്പർ ഉപയോഗിക്കുക.',
  phone: 'വാട്സ്ആപ്പ് നമ്പർ',
  sendCode: 'വാട്സ്ആപ്പിൽ കോഡ് അയയ്ക്കുക',
  code: 'വാട്സ്ആപ്പിൽ വന്ന കോഡ്',
  codeSent: 'നിങ്ങളുടെ വാട്സ്ആപ്പിലേക്ക് ഒരു കോഡ് അയച്ചു.',
  signIn: 'സൈൻ ഇൻ',
  otherNumber: 'വേറെ നമ്പർ',
  useEmail: 'ഇമെയിൽ ഉപയോഗിച്ച് സൈൻ ഇൻ',
  usePhone: 'വാട്സ്ആപ്പ് നമ്പർ ഉപയോഗിച്ച് സൈൻ ഇൻ',
  email: 'ഇമെയിൽ',
  password: 'പാസ്‌വേഡ്',
  today: 'ഇന്ന്',
  site: 'സൈറ്റ്',
  requests: 'ആവശ്യങ്ങൾ',
  more: 'കൂടുതൽ',
  speakToMesiri: 'മെസിരിയോട് പറയുക',
  todayOnSite: 'ഇന്ന് സൈറ്റിൽ',
  todaysReport: 'ഇന്നത്തെ റിപ്പോർട്ട്',
  doneOf: (done, all) => `${all}-ൽ ${done} കഴിഞ്ഞു`,
  reportGoes: 'വൈകുന്നേരം ഓഫീസിലേക്ക് പോകും, അല്ലെങ്കിൽ ഇപ്പോൾ അയയ്ക്കാം',
  sendNow: 'ഇപ്പോൾ അയയ്ക്കുക',
  sent: 'അയച്ചു',
  notToldYet: 'ഇതുവരെ പറഞ്ഞിട്ടില്ല · ടാപ്പ് ചെയ്യുക അല്ലെങ്കിൽ പറയുക',
  attendance: 'ഹാജർ',
  workDone: 'ചെയ്ത പണി',
  materialsIn: 'വന്ന സാധനങ്ങൾ',
  materialsUsed: 'ഉപയോഗിച്ച സാധനങ്ങൾ',
  problems: 'പ്രശ്നങ്ങൾ',
  photos: 'ഫോട്ടോകൾ',
  weather: 'കാലാവസ്ഥയും സൈറ്റും',
  people: (n) => `${n} പേർ`,
  items: (n) => `${n} എണ്ണം`,
  photosToday: (n) => `ഇന്ന് ${n} ഫോട്ടോ`,
  openProblems: (n) => `${n} തുറന്നിരിക്കുന്നു`,
  toCheck: (n) => `${n} എണ്ണം ഓഫീസ് പരിശോധിക്കാനുണ്ട്`,
  draftMark: 'ഓഫീസ് നോക്കണം',
  stock: 'സ്റ്റോക്ക്',
  coming: 'വരാനുള്ളത്',
  runningLow: (n) => `${n} എണ്ണം തീരാറായി.`,
  daysLeft: (n) => `${n} ദിവസം കൂടി`,
  low: 'കുറവ്',
  onOrder: (q) => `${q} ഓർഡറിൽ`,
  notUsedThisWeek: 'ഈ ആഴ്ച ഉപയോഗിച്ചില്ല',
  askForMaterial: 'സാധനം ആവശ്യപ്പെടുക',
  noStock: 'ഈ സൈറ്റിൽ ഇതുവരെ സ്റ്റോക്ക് രേഖപ്പെടുത്തിയിട്ടില്ല.',
  noRequests: 'ഈ സൈറ്റിൽ നിന്ന് ഇതുവരെ ആവശ്യങ്ങളില്ല.',
  status: {
    waiting: 'കാത്തിരിക്കുന്നു',
    ordered: 'ഓർഡർ ചെയ്തു',
    sent: 'വേറെ സൈറ്റിൽ നിന്ന് അയച്ചു',
    done: 'കിട്ടി',
    rejected: 'അംഗീകരിച്ചില്ല',
    cancelled: 'റദ്ദാക്കി',
  },
  neededBy: (d) => `${d}-നകം വേണം`,
  listening: 'കേൾക്കുന്നു',
  tapToStop: 'നിർത്താൻ ടാപ്പ് ചെയ്യുക. നിങ്ങൾ നോക്കുന്നതുവരെ ഒന്നും സേവ് ആകില്ല.',
  sayInOneGo: 'എല്ലാം ഒറ്റയടിക്ക്, ഏത് ഭാഷയിലും പറയാം:',
  hints: ['ഇന്ന് ആരൊക്കെ വന്നു', 'എന്ത് വന്നു', 'ചെയ്ത പണി', 'ഒരു പ്രശ്നം', 'എന്ത് വേണം'],
  hearing: 'മെസിരി കേൾക്കുന്നു…',
  thinking: 'മെസിരി നോക്കുന്നു…',
  youSaid: 'നിങ്ങൾ പറഞ്ഞത്',
  checkBeforeSaving: 'സേവ് ചെയ്യുന്നതിന് മുമ്പ് നോക്കുക',
  sayAChange: 'മാറ്റം പറയുക',
  typeInstead: 'ടൈപ്പ് ചെയ്യുക',
  typeHere: 'അപ്ഡേറ്റ് ടൈപ്പ് ചെയ്യുക…',
  send: 'അയയ്ക്കുക',
  micDenied: 'നിങ്ങളെ കേൾക്കാൻ മെസിരിക്ക് മൈക്ക് വേണം. ഫോൺ സെറ്റിംഗ്സിൽ അനുവദിക്കുക, അല്ലെങ്കിൽ ടൈപ്പ് ചെയ്യുക.',
  tryAgain: 'വീണ്ടും ശ്രമിക്കുക',
  done: 'കഴിഞ്ഞു',
  speakNow: 'മൈക്ക് ടാപ്പ് ചെയ്ത് പറയുക',
  speakToFill: 'ഫോം പറഞ്ഞ് നിറയ്ക്കുക',
  speakToFillHint: 'വാട്സ്ആപ്പിൽ പറയുന്നതുപോലെ പറയുക',
  fromVoice: 'നിങ്ങളുടെ ശബ്ദത്തിൽ നിന്ന്',
  material: 'സാധനം',
  searchMaterial: 'സാധനം കണ്ടെത്താൻ ടൈപ്പ് ചെയ്യുക',
  howMuch: 'എത്ര',
  unit: 'അളവ്',
  supplier: 'എവിടെ നിന്ന് (സപ്ലയർ)',
  usedFor: 'എന്തിന് ഉപയോഗിച്ചു (പണി)',
  note: 'കുറിപ്പ്',
  problemType: 'എന്ത് തരം പ്രശ്നം',
  severity: 'എത്ര ഗുരുതരം',
  whatHappened: 'എന്ത് സംഭവിച്ചു',
  save: 'സേവ് ചെയ്യുക',
  saved: 'സേവ് ചെയ്തു',
  fillForm: 'ഫോം നിറയ്ക്കുക',
  nothingFromVoice: 'അതിൽ നിന്ന് മെസിരി ഒന്നും തയ്യാറാക്കിയില്ല. വീണ്ടും ശ്രമിക്കുക, അല്ലെങ്കിൽ നിറയ്ക്കുക.',
  pickMaterial: 'ആദ്യം സാധനം തിരഞ്ഞെടുക്കുക.',
  enterQuantity: 'എത്ര എന്ന് പറയുക അല്ലെങ്കിൽ ടൈപ്പ് ചെയ്യുക.',
  describeProblem: 'എന്ത് സംഭവിച്ചു എന്ന് പറയുക അല്ലെങ്കിൽ ടൈപ്പ് ചെയ്യുക.',
  englishNote: 'ഇംഗ്ലീഷിൽ സേവ് ആകും. ഏത് ഭാഷയിലും പറഞ്ഞ് നിറയ്ക്കാം.',
  switchSite: 'നിങ്ങൾ ഏത് സൈറ്റിലാണ്?',
  language: 'മെസിരി നിങ്ങളോട് സംസാരിക്കുന്ന ഭാഷ',
  languageNote: 'ഏത് ഭാഷയിലും എപ്പോഴും പറയാം. സേവ് ചെയ്യുന്നത് എപ്പോഴും ഇംഗ്ലീഷിലാണ്, ഓഫീസിന് വായിക്കാൻ.',
  signOut: 'സൈൻ ഔട്ട്',
  signedInAs: 'സൈൻ ഇൻ ചെയ്തത്',
  online: 'ഓൺലൈൻ',
  offline: 'സിഗ്നൽ ഇല്ല',
  loading: 'ലോഡ് ചെയ്യുന്നു…',
  couldNotLoad: 'ലോഡ് ആയില്ല. വീണ്ടും ശ്രമിക്കാൻ താഴേക്ക് വലിക്കുക.',
  noSites: 'നിങ്ങൾ ഇതുവരെ ഒരു സൈറ്റിലുമില്ല. ഒരു പ്രോജക്റ്റിൽ ചേർക്കാൻ ഓഫീസിനോട് പറയുക.',
  back: 'തിരികെ',
  close: 'അടയ്ക്കുക',
}

const WORDS: Record<Lang, Words> = { en, ml }
export const LANGS: { id: Lang; name: string }[] = [
  { id: 'ml', name: 'മലയാളം' },
  { id: 'en', name: 'English' },
]

const KEY = 'mesiri_app_language'

function deviceLang(): Lang {
  try {
    return getLocales()[0]?.languageCode === 'ml' ? 'ml' : 'en'
  } catch {
    return 'en'
  }
}

const Ctx = React.createContext<{ lang: Lang; t: Words; setLang: (l: Lang) => void }>({
  lang: 'en',
  t: en,
  setLang: () => undefined,
})

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = React.useState<Lang>(deviceLang)
  React.useEffect(() => {
    void getValue<Lang>(KEY).then((saved) => {
      if (saved === 'en' || saved === 'ml') setLangState(saved)
    })
  }, [])
  const setLang = React.useCallback((l: Lang) => {
    setLangState(l)
    void setValue(KEY, l)
  }, [])
  const value = React.useMemo(() => ({ lang, t: WORDS[lang], setLang }), [lang, setLang])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useWords = () => React.useContext(Ctx)
