import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login, loginWithCode } from '@/lib/api'
import { WhatsAppCodeForm } from '@/components/auth/whatsapp-code-form'
import { AuthShell } from '@/components/auth/auth-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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

  return (
    <AuthShell
      title="Sign in"
      subtitle="With a code on WhatsApp, or your email and password."
      footer={
        <>
          New to Mesiri?{' '}
          <Link to="/signup" className="font-medium text-foreground underline underline-offset-2">
            Start a free trial
          </Link>
        </>
      }
    >
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
    </AuthShell>
  )
}
