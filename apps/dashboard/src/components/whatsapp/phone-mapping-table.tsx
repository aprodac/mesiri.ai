import * as React from 'react'
import { Search, Smartphone, ShieldCheck, Send } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table'

export interface WhatsAppCustodianItem {
  id: string
  name: string
  whatsapp_number: string
  role: string
  project_name: string
  site_name?: string
  status: 'verified' | 'pending' | 'suspended'
  last_active: string
}

const MOCK_CUSTODIANS: WhatsAppCustodianItem[] = [
  {
    id: 'cust_01',
    name: 'Ramesh Kumar',
    whatsapp_number: '+91 98765 43210',
    role: 'Site Project Manager',
    project_name: 'Riverside Commercial Center',
    site_name: 'Tower A Excavation',
    status: 'verified',
    last_active: '5 mins ago',
  },
  {
    id: 'cust_02',
    name: 'Suresh Patil',
    whatsapp_number: '+91 98123 88765',
    role: 'Site Supervisor',
    project_name: 'Green Valley Housing',
    site_name: 'Block B Concreting',
    status: 'verified',
    last_active: '1 hour ago',
  },
  {
    id: 'cust_03',
    name: 'Anil Deshmukh',
    whatsapp_number: '+91 97654 11223',
    role: 'Procurement Specialist',
    project_name: 'Org Wide Treasury',
    status: 'verified',
    last_active: '2 days ago',
  },
  {
    id: 'cust_04',
    name: 'Vikram Singh',
    whatsapp_number: '+91 99000 44321',
    role: 'Subcontractor Lead',
    project_name: 'Riverside Commercial Center',
    status: 'pending',
    last_active: 'Never',
  },
]

import { fetchUsers } from '@/lib/api'

export function PhoneMappingTable() {
  const [search, setSearch] = React.useState('')
  const [custodians, setCustodians] = React.useState<WhatsAppCustodianItem[]>(MOCK_CUSTODIANS)

  React.useEffect(() => {
    let active = true
    async function loadCustodians() {
      try {
        const users = await fetchUsers()
        if (active && Array.isArray(users)) {
          // Filter users who have a whatsapp_number assigned or convert all users to table items
          const mapped: WhatsAppCustodianItem[] = users
            .filter((u: any) => u.whatsapp_number || u.phone_number)
            .map((u: any) => ({
              id: u.id,
              name: u.full_name || u.email || 'User',
              whatsapp_number: u.whatsapp_number || u.phone_number || 'Not Set',
              role: (u.role || 'Member').replace('_', ' ').toUpperCase(),
              project_name: u.project_name || 'Org Wide',
              site_name: u.site_name,
              status: u.status === 'active' ? 'verified' : 'pending',
              last_active: u.last_login_at || 'Recently',
            }))
          if (mapped.length > 0) {
            setCustodians(mapped)
          }
        }
      } catch (err) {
        console.warn('Failed to load real WhatsApp custodians:', err)
      }
    }
    loadCustodians()
    return () => {
      active = false
    }
  }, [])

  const filtered = React.useMemo(() => {
    return custodians.filter(
      (c) =>
        c.name.toLowerCase().includes(search.toLowerCase()) ||
        c.whatsapp_number.includes(search) ||
        c.project_name.toLowerCase().includes(search.toLowerCase())
    )
  }, [custodians, search])

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col sm:flex-row gap-2 items-center justify-between">
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input
            placeholder="Search custodian, phone, project..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-9 text-xs"
          />
        </div>

        <Button size="sm" variant="outline" className="h-8 text-xs font-semibold gap-1.5">
          <Send className="size-3.5 text-emerald-500" />
          Invite New Custodian
        </Button>
      </div>

      <div className="border rounded-lg overflow-hidden bg-card shadow-2xs">
        <Table>
          <TableHeader className="bg-muted/40">
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-xs font-semibold h-10">Custodian Name</TableHead>
              <TableHead className="text-xs font-semibold h-10">WhatsApp Number</TableHead>
              <TableHead className="text-xs font-semibold h-10">System Role</TableHead>
              <TableHead className="text-xs font-semibold h-10">Assigned Scope</TableHead>
              <TableHead className="text-xs font-semibold h-10 text-center">Identity Status</TableHead>
              <TableHead className="text-xs font-semibold h-10 text-right">Last Activity</TableHead>
              <TableHead className="text-xs font-semibold h-10 text-right w-[50px]">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((item) => (
              <TableRow key={item.id} className="hover:bg-muted/40 text-xs">
                <TableCell className="font-semibold text-foreground flex items-center gap-2">
                  <div className="size-6 rounded-full bg-emerald-500/10 text-emerald-600 flex items-center justify-center font-bold text-[10px]">
                    {item.name.charAt(0)}
                  </div>
                  {item.name}
                </TableCell>
                <TableCell className="font-mono text-foreground font-medium">
                  <span className="flex items-center gap-1.5">
                    <Smartphone className="size-3.5 text-emerald-500" />
                    {item.whatsapp_number}
                  </span>
                </TableCell>
                <TableCell className="text-muted-foreground">{item.role}</TableCell>
                <TableCell className="text-muted-foreground">
                  {item.project_name}
                  {item.site_name && (
                    <span className="text-[10px] text-muted-foreground/80 block font-mono">
                      / {item.site_name}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-center">
                  {item.status === 'verified' ? (
                    <Badge className="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 text-[10px] gap-1">
                      <ShieldCheck className="size-3" /> Verified
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-[10px] text-amber-600 border-amber-500/30">
                      Pending Invite
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-right text-muted-foreground font-mono text-[11px]">
                  {item.last_active}
                </TableCell>
                <TableCell className="text-right">
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
