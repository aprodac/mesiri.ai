import * as React from 'react'
import {
  Tags,
  Plus,
  Search,
  DollarSign,
  TrendingUp,
  MoreVertical,
  Edit2,
  Power,
  Eye,
  Grid,
  List,
  Tag,
} from 'lucide-react'
import { KpiCard } from '@/components/ui/kpi-card'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { fetchCategoriesApi, updateCategoryApi, type CategoryItem } from '@/lib/api'
import { CategoryDetailSheet } from '@/components/categories/category-detail-sheet'
import { CreateCategoryDialog } from '@/components/categories/create-category-dialog'

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount)
}

import { useToast } from '@/components/ui/toast-notification'

export default function CategoriesPage() {
  const toast = useToast()

  const [categories, setCategories] = React.useState<CategoryItem[]>([])
  const [loading, setLoading] = React.useState(true)
  const [search, setSearch] = React.useState('')
  const [statusFilter, setStatusFilter] = React.useState('ALL')
  const [viewMode, setViewMode] = React.useState<'grid' | 'table'>('grid')

  // Sheet & Dialog state
  const [selectedCategory, setSelectedCategory] = React.useState<CategoryItem | null>(null)
  const [detailSheetOpen, setDetailSheetOpen] = React.useState(false)

  const [createDialogOpen, setCreateDialogOpen] = React.useState(false)
  const [categoryToEdit, setCategoryToEdit] = React.useState<CategoryItem | null>(null)

  const loadCategories = React.useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchCategoriesApi()
      if (Array.isArray(data)) {
        setCategories(data)
      }
    } catch (err) {
      console.warn('Failed to load categories:', err)
      setCategories([])
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    loadCategories()
  }, [loadCategories])

  const filteredCategories = React.useMemo(() => {
    return categories.filter((cat) => {
      const matchesSearch =
        cat.name.toLowerCase().includes(search.toLowerCase()) ||
        (cat.code || '').toLowerCase().includes(search.toLowerCase())

      const matchesStatus =
        statusFilter === 'ALL' || cat.status.toLowerCase() === statusFilter.toLowerCase()

      return matchesSearch && matchesStatus
    })
  }, [categories, search, statusFilter])

  // Summary Metrics
  const metrics = React.useMemo(() => {
    const activeCats = categories.filter((c) => c.status === 'active')
    const totalSpent = categories.reduce((acc, curr) => acc + (curr.total_amount_spent || 0), 0)
    const totalRecords = categories.reduce((acc, curr) => acc + (curr.expense_count || 0), 0)

    let topCategory = activeCats.length > 0 ? activeCats[0] : null
    for (const cat of activeCats) {
      if (!topCategory || (cat.total_amount_spent || 0) > (topCategory.total_amount_spent || 0)) {
        topCategory = cat
      }
    }

    return {
      activeCount: activeCats.length,
      totalCount: categories.length,
      totalSpent,
      totalRecords,
      topCategoryName: topCategory ? topCategory.name : 'None',
      topCategoryAmount: topCategory ? topCategory.total_amount_spent || 0 : 0,
    }
  }, [categories])

  const handleToggleStatus = async (cat: CategoryItem) => {
    const nextStatus = cat.status === 'active' ? 'inactive' : 'active'
    try {
      await updateCategoryApi(cat.id, { status: nextStatus })
      toast.success(`Category "${cat.name}" updated`, `Status set to ${nextStatus.toUpperCase()}`)
      loadCategories()
    } catch (err: any) {
      toast.error('Failed to update category status', err.message || 'Server error')
    }
  }


  return (
    <div className="flex flex-col gap-4 w-full max-w-full relative pb-12">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3.5">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Expense categories</h1>
          </div>
        </div>

        <Button
          size="sm"
          className="h-9 px-3.5 text-xs font-semibold gap-1.5 shadow-2xs"
          onClick={() => {
            setCategoryToEdit(null)
            setCreateDialogOpen(true)
          }}
        >
          <Plus className="size-4" />
          Add Category
        </Button>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Active categories"
          value={<span>{metrics.activeCount} Active</span>}
          description="Operational classification rules"
          icon={<Tags  />}
        />
        <KpiCard
          title="Spend"
          value={<span>{formatCurrency(metrics.totalSpent)}</span>}
          description="Confirmed expense total"
          icon={<DollarSign  />}
        />
        <KpiCard
          title="Top category"
          value={<span className="text-purple-600 dark:text-purple-400 truncate block max-w-[160px]">{metrics.topCategoryName}</span>}
          description="Highest volume category"
          icon={<TrendingUp  />}
        />
      </div>

      {/* Filter & View Mode Controls */}
      <div className="flex flex-col sm:flex-row gap-2.5 items-center justify-between bg-card p-3 rounded-lg border shadow-2xs">
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
            <Input
              placeholder="Search by category name or code..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-8 text-xs"
            />
          </div>

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-8 text-xs w-[130px]">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL" className="text-xs">All Statuses</SelectItem>
              <SelectItem value="ACTIVE" className="text-xs">Active Only</SelectItem>
              <SelectItem value="INACTIVE" className="text-xs">Inactive Only</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-1.5 self-end sm:self-auto">
          <Button
            size="sm"
            variant={viewMode === 'grid' ? 'secondary' : 'ghost'}
            className="size-8 p-0"
            onClick={() => setViewMode('grid')}
            title="Grid View"
          >
            <Grid className="size-4" />
          </Button>
          <Button
            size="sm"
            variant={viewMode === 'table' ? 'secondary' : 'ghost'}
            className="size-8 p-0"
            onClick={() => setViewMode('table')}
            title="Table View"
          >
            <List className="size-4" />
          </Button>
        </div>
      </div>

      {/* Category Content View */}
      {loading ? (
        <div className="py-20 text-center text-xs text-muted-foreground">
          Loading expense categories...
        </div>
      ) : filteredCategories.length === 0 ? (
        <div className="py-20 border rounded-lg bg-card text-center flex flex-col items-center justify-center p-6 gap-2">
          <Tags className="size-10 text-muted-foreground/40" />
          <h3 className="text-sm font-semibold text-foreground">No Categories Found</h3>
          <p className="text-xs text-muted-foreground max-w-sm">
            {search ? 'No categories match your search criteria.' : 'Create your first expense category to classify expenses.'}
          </p>
          <Button
            size="sm"
            className="mt-2 text-xs font-semibold gap-1.5"
            onClick={() => {
              setCategoryToEdit(null)
              setCreateDialogOpen(true)
            }}
          >
            <Plus className="size-3.5" />
            Create Category
          </Button>
        </div>
      ) : viewMode === 'grid' ? (
        /* Grid View */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filteredCategories.map((cat) => (
            <div
              key={cat.id}
              className="group p-4 rounded-lg border bg-card hover:border-emerald-500/40 transition-all shadow-2xs flex flex-col justify-between gap-3 relative"
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2.5">
                    <div className="size-9 rounded-lg bg-emerald-500/10 text-emerald-600 flex items-center justify-center font-bold text-sm shrink-0">
                      <Tag className="size-4.5" />
                    </div>
                    <div>
                      <h3 className="font-bold text-sm text-foreground flex items-center gap-2">
                        {cat.name}
                      </h3>
                      {cat.code && (
                        <span className="text-[10px] font-mono text-muted-foreground uppercase">
                          Code: {cat.code}
                        </span>
                      )}
                    </div>
                  </div>

                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="sm" variant="ghost" className="size-7 p-0 text-muted-foreground">
                        <MoreVertical className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="text-xs">
                      <DropdownMenuItem
                        onClick={() => {
                          setSelectedCategory(cat)
                          setDetailSheetOpen(true)
                        }}
                      >
                        <Eye className="size-3.5 mr-2 text-emerald-500" />
                        View Expenses
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={() => {
                          setCategoryToEdit(cat)
                          setCreateDialogOpen(true)
                        }}
                      >
                        <Edit2 className="size-3.5 mr-2 text-blue-500" />
                        Edit Category
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => handleToggleStatus(cat)}>
                        <Power className="size-3.5 mr-2 text-amber-500" />
                        {cat.status === 'active' ? 'Deactivate' : 'Activate'}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-2 gap-2 p-2.5 rounded-md bg-muted/40 border text-xs">
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase font-semibold block">
                    Recorded Expenses
                  </span>
                  <span className="font-bold font-mono text-foreground">
                    {cat.expense_count} Records
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase font-semibold block">
                    Total Spend
                  </span>
                  <span className="font-bold font-mono text-emerald-600">
                    {formatCurrency(cat.total_amount_spent || 0)}
                  </span>
                </div>
              </div>

              {/* Action Button */}
              <Button
                variant="outline"
                size="sm"
                className="w-full text-xs h-8 font-semibold gap-1.5 text-foreground hover:bg-muted"
                onClick={() => {
                  setSelectedCategory(cat)
                  setDetailSheetOpen(true)
                }}
              >
                <Eye className="size-3.5 text-emerald-500" />
                View Category Expenses
              </Button>
            </div>
          ))}
        </div>
      ) : (
        /* Table View */
        <div className="border rounded-lg overflow-hidden bg-card shadow-2xs">
          <Table>
            <TableHeader className="bg-muted/40">
              <TableRow className="hover:bg-transparent">
                <TableHead className="text-xs font-semibold h-10">Category Name</TableHead>
                <TableHead className="text-xs font-semibold h-10">Code</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right">Expense Count</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right">Total Spent (₹)</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-center">Status</TableHead>
                <TableHead className="text-xs font-semibold h-10 text-right w-[60px]">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredCategories.map((cat) => (
                <TableRow key={cat.id} className="hover:bg-muted/40 text-xs">
                  <TableCell className="font-semibold text-foreground">
                    <div className="flex items-center gap-2">
                      <Tag className="size-3.5 text-emerald-500" />
                      <span>{cat.name}</span>
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-muted-foreground uppercase">
                    {cat.code || '—'}
                  </TableCell>
                  <TableCell className="text-right font-mono font-medium text-foreground">
                    {cat.expense_count}
                  </TableCell>
                  <TableCell className="text-right font-mono font-bold text-emerald-600">
                    {formatCurrency(cat.total_amount_spent || 0)}
                  </TableCell>
                  <TableCell className="text-center">
                    <Badge
                      className={
                        cat.status === 'active'
                          ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20 text-[10px]'
                          : 'bg-muted text-muted-foreground text-[10px]'
                      }
                    >
                      {cat.status.toUpperCase()}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="size-7 p-0"
                      onClick={() => {
                        setSelectedCategory(cat)
                        setDetailSheetOpen(true)
                      }}
                    >
                      <Eye className="size-4 text-emerald-500" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Category Expense Detail Sheet */}
      <CategoryDetailSheet
        category={selectedCategory}
        open={detailSheetOpen}
        onOpenChange={setDetailSheetOpen}
      />

      {/* Create / Edit Dialog */}
      <CreateCategoryDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        categoryToEdit={categoryToEdit}
        onSuccess={loadCategories}
      />
    </div>
  )
}
