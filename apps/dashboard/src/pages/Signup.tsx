import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { signup, verifySignupCode } from '@/lib/api'
import { apiErrorMessage } from '@/lib/logo-upload'
import { WhatsAppCodeForm } from '@/components/auth/whatsapp-code-form'
import { IntroConversation } from '@/components/onboarding/intro-conversation'
import { MesiriWordmark } from '@/components/brand/mesiri-logo'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/**
 * Web signup (SS-06): WhatsApp number → code → the same questions as the
 * WhatsApp signup → a trial company, then the welcome screen for the first
 * update (SS-18). The intro conversation plays beside the form; narrow, it
 * comes first and its button jumps down to the form.
 */
export default function Signup() {
  const navigate = useNavigate()
  const [ticket, setTicket] = useState<string | null>(null)
  const [ownerName, setOwnerName] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [siteName, setSiteName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!ticket) return
    setError(null)
    setLoading(true)
    try {
      await signup({
        signup_token: ticket,
        owner_name: ownerName,
        company_name: companyName,
        site_name: siteName,
      })
      navigate('/welcome', { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err))
      setLoading(false)
    }
  }

  const goToForm = () => {
    // Narrow, the form is at the top: back up to it.
    document.getElementById('start')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    document.getElementById(ticket ? 'owner-name' : 'phone')?.focus({ preventScroll: true })
  }

  return (
    // Narrow: the form first, the intro under it (nobody should have to
    // scroll past a slideshow to sign up). Desktop: side by side.
    <div className="flex min-h-svh flex-col bg-background lg:grid lg:grid-cols-[minmax(0,1fr)_400px]">
      <section aria-label="How Mesiri works" className="border-t px-4 pb-14 sm:px-8 lg:border-t-0 lg:px-12">
        <IntroConversation
          belowForm
          onStart={goToForm}
          headerAction={
            <Link to="/login" className="text-sm font-medium underline underline-offset-2">
              Sign in
            </Link>
          }
        />
      </section>

      <aside
        id="start"
        aria-label="Start your free trial"
        className="order-first scroll-mt-4 px-4 pt-7 pb-10 sm:px-8 lg:order-none lg:sticky lg:top-0 lg:flex lg:h-svh lg:items-center lg:overflow-y-auto lg:border-l lg:py-12"
      >
        <div className="mx-auto grid w-full max-w-sm gap-6">
          <div className="grid gap-6 lg:hidden">
            <div className="flex items-baseline justify-between gap-4">
              <MesiriWordmark className="text-lg" />
              <Link to="/login" className="text-sm font-medium underline underline-offset-2">
                Sign in
              </Link>
            </div>
            <p className="m-0 text-[28px] leading-[1.05] font-semibold tracking-[-0.03em] text-balance">
              One voice note in. <span className="text-muted-foreground">A finished daily report out.</span>
            </p>
          </div>
          <div className="grid gap-1.5">
            <h2 className="text-2xl font-semibold tracking-tight">Start your free trial</h2>
            <p className="text-sm text-muted-foreground">
              {ticket
                ? 'Three quick questions and your daily reports are ready to go.'
                : 'No password needed. We send a code to your WhatsApp.'}
            </p>
          </div>
          {!ticket ? (
            <WhatsAppCodeForm
              purpose="signup"
              submitLabel="Continue"
              phoneHint="The number you use on WhatsApp. Your site team reports to Mesiri on WhatsApp too."
              onCode={async (phone, code) => setTicket(await verifySignupCode(phone, code))}
            />
          ) : (
            <form onSubmit={handleCreate} className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="owner-name">Your name</Label>
                <Input
                  id="owner-name"
                  autoComplete="name"
                  required
                  autoFocus
                  value={ownerName}
                  onChange={(e) => setOwnerName(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="company-name">Company name</Label>
                <Input
                  id="company-name"
                  autoComplete="organization"
                  required
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="site-name">Which site are you working on now?</Label>
                <Input
                  id="site-name"
                  placeholder="Green Villa, Kakkanad"
                  required
                  value={siteName}
                  onChange={(e) => setSiteName(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">You can add more sites later.</p>
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? 'Setting up…' : 'Start free trial'}
              </Button>
            </form>
          )}
          <p className="text-sm text-muted-foreground">
            Already using Mesiri?{' '}
            <Link to="/login" className="font-medium text-foreground underline underline-offset-2">
              Sign in
            </Link>
          </p>
        </div>
      </aside>
    </div>
  )
}
