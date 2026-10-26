import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login, loginWithCode } from '@/lib/api'
import { WhatsAppCodeForm } from '@/components/auth/whatsapp-code-form'
import { MesiriLogo } from '@/components/brand/mesiri-logo'
import { IntroConversation } from '@/components/onboarding/intro-conversation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export default function Login() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(email, password)
      navigate('/', { replace: true })
    } catch {
      setError('Invalid email or password.')
    } finally {
      setLoading(false)
    }
  }

  // Desktop: the intro conversation (SS-18) on the left, as on signup.
  // Narrower, only the form: someone signing in has come to work.
  return (
    <div className="min-h-svh bg-background lg:grid lg:grid-cols-[minmax(0,1fr)_400px]">
      <section aria-label="How Mesiri works" className="hidden px-12 pb-14 lg:block">
        <IntroConversation
          onStart={() => navigate('/signup')}
          headerAction={
            <Link to="/signup" className="text-sm font-medium underline underline-offset-2">
              Start a free trial
            </Link>
          }
        />
      </section>

      <div className="flex min-h-svh items-center justify-center p-4 lg:sticky lg:top-0 lg:h-svh lg:border-l lg:px-8">
        <Card className="w-full max-w-sm border-0 shadow-none lg:bg-transparent">
          <CardHeader>
            <MesiriLogo className="mb-3 lg:hidden" />
            <CardTitle className="text-2xl">Sign in</CardTitle>
            <CardDescription>Use your WhatsApp number, or your email and password.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Tabs defaultValue="whatsapp">
              <TabsList className="w-full">
                <TabsTrigger value="whatsapp">WhatsApp code</TabsTrigger>
                <TabsTrigger value="password">Email</TabsTrigger>
              </TabsList>
              <TabsContent value="whatsapp" className="pt-2">
                <WhatsAppCodeForm
                  purpose="login"
                  submitLabel="Sign in"
                  onCode={async (phone, code) => {
                    await loginWithCode(phone, code)
                    navigate('/', { replace: true })
                  }}
                />
              </TabsContent>
              <TabsContent value="password" className="pt-2">
                <form onSubmit={handleSubmit} className="grid gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      autoComplete="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="password">Password</Label>
                    <Input
                      id="password"
                      type="password"
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </div>
                  {error && <p className="text-sm text-destructive">{error}</p>}
                  <Button type="submit" className="w-full" disabled={loading}>
                    {loading ? 'Signing in…' : 'Sign in'}
                  </Button>
                </form>
              </TabsContent>
            </Tabs>
            <p className="text-center text-sm text-muted-foreground">
              New to Mesiri?{' '}
              <Link to="/signup" className="font-medium text-foreground underline underline-offset-2">
                Start a free trial
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
