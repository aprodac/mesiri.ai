import { useState, useMemo, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Building2,
  MapPin,
  Clock,
  Truck,
  User,
  CheckCircle2,
  Plus,
  Trash2,
  DollarSign,
  Sparkles,
  Info,
  Check,
  ShieldCheck,
  Navigation,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Avatar } from '@/components/ui/avatar'
import { Combobox } from '@/components/ui/combobox'
import { useToast } from '@/components/ui/toast-notification'

// ==========================================
// TYPES & DOMAIN INTERFACES
// ==========================================

export interface Customer {
  id: string
  code: string
  name: string
  contactPerson: string
  phone: string
  isFrequent?: boolean
}

export interface LocationOption {
  id: string
  label: string
  city: string
}

export interface QuotationMatch {
  id: string
  customerId: string
  origin: string
  destination: string
  operationType: 'Monthly' | 'Extra'
  lineType: 'Single Trip' | 'Round Trip' | '10 Hours Shift' | '12 Hours Shift'
  vehicleClass: string
  customerBillingMonthly?: number
  customerBillingPerTrip?: number
  driverPayoutPerTrip: number
}

export interface Driver {
  id: string
  name: string
  initials: string
  phone: string
  licenseNumber: string
  assignedVehicleClass: string
  defaultVehicleId?: string
}

export interface Vehicle {
  id: string
  plateNumber: string
  makeModel: string
  vehicleClass: string
  defaultDriverId?: string
}

export interface AdditionalCharge {
  id: string
  type: string
  amount: number
  description: string
}

// ==========================================
// PRE-POPULATED DEMO DATASETS (Strict matching)
// ==========================================

const SAMPLE_CUSTOMERS: Customer[] = [
  {
    id: 'cust-1',
    code: 'CUST-101',
    name: 'IMILE DELIVERY SAUDI LOGISTICS',
    contactPerson: 'Hamza Al-Otaibi',
    phone: '+966 50 111 2233',
    isFrequent: true,
  },
  {
    id: 'cust-2',
    code: 'CUST-102',
    name: 'ARAMEX SAUDI LIMITED',
    contactPerson: 'Sultan Mansoor',
    phone: '+966 55 222 3344',
    isFrequent: true,
  },
  {
    id: 'cust-3',
    code: 'CUST-103',
    name: 'DHL EXPRESS SAUDI ARABIA',
    contactPerson: 'Faris Al-Ghamdi',
    phone: '+966 54 333 4455',
    isFrequent: true,
  },
  {
    id: 'cust-4',
    code: 'CUST-104',
    name: 'SPL LOGISTICS (SAUDI POST)',
    contactPerson: 'Omar Al-Harbi',
    phone: '+966 56 444 5566',
    isFrequent: true,
  },
  {
    id: 'cust-5',
    code: 'CUST-105',
    name: 'NAQEL EXPRESS LOGISTICS',
    contactPerson: 'Youssef Al-Zahrani',
    phone: '+966 53 555 6677',
    isFrequent: false,
  },
]

const SAMPLE_LOCATIONS: LocationOption[] = [
  { id: 'loc-1', label: 'Riyadh Hub (King Khalid Intl Road)', city: 'Riyadh' },
  { id: 'loc-2', label: 'Al Baha Logistics Terminal', city: 'Al Baha' },
  { id: 'loc-3', label: 'Jeddah Islamic Port Gate 4', city: 'Jeddah' },
  { id: 'loc-4', label: 'Dammam Industrial City 2', city: 'Dammam' },
  { id: 'loc-5', label: 'Al Kharj Distribution Center', city: 'Al Kharj' },
  { id: 'loc-6', label: 'Medina Central Depot', city: 'Medina' },
  { id: 'loc-7', label: 'Tabuk Cargo Terminal', city: 'Tabuk' },
]

const SAMPLE_QUOTATIONS: QuotationMatch[] = [
  {
    id: 'q-101',
    customerId: 'cust-1',
    origin: 'Riyadh Hub (King Khalid Intl Road)',
    destination: 'Al Baha Logistics Terminal',
    operationType: 'Monthly',
    lineType: 'Single Trip',
    vehicleClass: '10 TON',
    customerBillingMonthly: 1750,
    driverPayoutPerTrip: 149,
  },
  {
    id: 'q-102',
    customerId: 'cust-2',
    origin: 'Jeddah Islamic Port Gate 4',
    destination: 'Riyadh Hub (King Khalid Intl Road)',
    operationType: 'Extra',
    lineType: 'Round Trip',
    vehicleClass: '20 TON',
    customerBillingPerTrip: 2800,
    driverPayoutPerTrip: 350,
  },
  {
    id: 'q-103',
    customerId: 'cust-3',
    origin: 'Riyadh Hub (King Khalid Intl Road)',
    destination: 'Dammam Industrial City 2',
    operationType: 'Monthly',
    lineType: '10 Hours Shift',
    vehicleClass: '5 TON',
    customerBillingMonthly: 3200,
    driverPayoutPerTrip: 210,
  },
]

const SAMPLE_DRIVERS: Driver[] = [
  {
    id: 'd-1',
    name: 'Muhammad Yasin',
    initials: 'MY',
    phone: '+966 50 123 4567',
    licenseNumber: 'Heavy Vehicle #8841',
    assignedVehicleClass: '10 TON',
    defaultVehicleId: 'v-1',
  },
  {
    id: 'd-2',
    name: 'Tariq Mahmood',
    initials: 'TM',
    phone: '+966 55 987 6543',
    licenseNumber: 'Heavy Trailer #3320',
    assignedVehicleClass: '20 TON',
    defaultVehicleId: 'v-2',
  },
  {
    id: 'd-3',
    name: 'Abdulrahman Al-Dosari',
    initials: 'AD',
    phone: '+966 54 321 0987',
    licenseNumber: 'Medium Truck #1192',
    assignedVehicleClass: '5 TON',
    defaultVehicleId: 'v-3',
  },
  {
    id: 'd-4',
    name: 'Ibrahim Al-Sayed',
    initials: 'IS',
    phone: '+966 56 444 2211',
    licenseNumber: 'Heavy Trailer #9910',
    assignedVehicleClass: '40 FEET',
    defaultVehicleId: 'v-4',
  },
]

const SAMPLE_VEHICLES: Vehicle[] = [
  { id: 'v-1', plateNumber: 'DRA-6455', makeModel: 'Mercedes Actros 10T', vehicleClass: '10 TON', defaultDriverId: 'd-1' },
  { id: 'v-2', plateNumber: 'JED-9921', makeModel: 'Volvo FH 20T', vehicleClass: '20 TON', defaultDriverId: 'd-2' },
  { id: 'v-3', plateNumber: 'RUH-3104', makeModel: 'Isuzu Forward 5T', vehicleClass: '5 TON', defaultDriverId: 'd-3' },
  { id: 'v-4', plateNumber: 'DMM-7788', makeModel: 'MAN TGX 40FT', vehicleClass: '40 FEET', defaultDriverId: 'd-4' },
]

export default function CreateTripPage() {
  const navigate = useNavigate()
  const { addToast } = useToast()

  // Stepper State: 1 = Customer, 2 = Route & Timing, 3 = Service & Assignment, 4 = Review
  const [currentStep, setCurrentStep] = useState<number>(1)

  // ==========================================
  // STEP 1 STATE: CUSTOMER
  // ==========================================
  const [selectedCustomerId, setSelectedCustomerId] = useState<string>('')

  const selectedCustomer = useMemo(() => {
    return SAMPLE_CUSTOMERS.find((c) => c.id === selectedCustomerId)
  }, [selectedCustomerId])

  // ==========================================
  // STEP 2 STATE: TRIP / ROUTE & TIMING
  // ==========================================
  const [pickupLocation, setPickupLocation] = useState<string>('loc-1')
  const [destinationLocation, setDestinationLocation] = useState<string>('loc-2')
  const [stops, setStops] = useState<string[]>([])
  
  const [pickupDate, setPickupDate] = useState<string>(() => new Date().toISOString().split('T')[0])
  const [pickupTime, setPickupTime] = useState<string>('08:00')
  const [dropoffDate, setDropoffDate] = useState<string>(() => new Date().toISOString().split('T')[0])
  const [dropoffTime, setDropoffTime] = useState<string>('18:00')

  // Estimated Distance & Duration derived from route
  const routeEstimate = useMemo(() => {
    const stopCount = stops.length
    return {
      distanceKm: 850 + stopCount * 45,
      durationHours: 9.5 + stopCount * 0.75,
    }
  }, [stops])

  // ==========================================
  // STEP 3 STATE: SERVICE & ASSIGNMENT
  // ==========================================
  const [operationType, setOperationType] = useState<'Monthly' | 'Extra'>('Monthly')
  const [lineType, setLineType] = useState<'Single Trip' | 'Round Trip' | '10 Hours Shift' | '12 Hours Shift'>('Single Trip')
  const [vehicleClass, setVehicleClass] = useState<string>('10 TON')

  // Quotation matching logic
  const matchedQuotation = useMemo(() => {
    if (!selectedCustomerId || !pickupLocation || !destinationLocation) return null
    const pickupObj = SAMPLE_LOCATIONS.find((l) => l.id === pickupLocation)
    const destObj = SAMPLE_LOCATIONS.find((l) => l.id === destinationLocation)
    if (!pickupObj || !destObj) return null

    return (
      SAMPLE_QUOTATIONS.find(
        (q) =>
          q.customerId === selectedCustomerId &&
          q.origin === pickupObj.label &&
          q.destination === destObj.label
      ) || null
    )
  }, [selectedCustomerId, pickupLocation, destinationLocation])

  const [isManualQuotation, setIsManualQuotation] = useState<boolean>(false)
  const [manualBillingMonthly, setManualBillingMonthly] = useState<number>(1750)
  const [manualBillingPerTrip, setManualBillingPerTrip] = useState<number>(250)
  const [manualDriverPayout, setManualDriverPayout] = useState<number>(149)

  // Auto-sync configuration when matched quotation is surfaced
  useEffect(() => {
    if (matchedQuotation && !isManualQuotation) {
      setOperationType(matchedQuotation.operationType)
      setLineType(matchedQuotation.lineType)
      setVehicleClass(matchedQuotation.vehicleClass)
    }
  }, [matchedQuotation, isManualQuotation])

  // Driver & Vehicle assignment state
  const [selectedDriverId, setSelectedDriverId] = useState<string>('d-1')
  const [selectedVehicleId, setSelectedVehicleId] = useState<string>('v-1')

  // Intelligent assignment link: Driver -> Vehicle & Vehicle Class
  const handleDriverChange = (driverId: string) => {
    setSelectedDriverId(driverId)
    const drv = SAMPLE_DRIVERS.find((d) => d.id === driverId)
    if (drv) {
      if (drv.defaultVehicleId) {
        setSelectedVehicleId(drv.defaultVehicleId)
      }
      if (drv.assignedVehicleClass) {
        setVehicleClass(drv.assignedVehicleClass)
      }
    }
  }

  const handleVehicleChange = (vehicleId: string) => {
    setSelectedVehicleId(vehicleId)
    const veh = SAMPLE_VEHICLES.find((v) => v.id === vehicleId)
    if (veh) {
      setVehicleClass(veh.vehicleClass)
      if (veh.defaultDriverId) {
        setSelectedDriverId(veh.defaultDriverId)
      }
    }
  }

  // Additional Charges state
  const [additionalCharges, setAdditionalCharges] = useState<AdditionalCharge[]>([])
  const [showAddChargeForm, setShowAddChargeForm] = useState<boolean>(false)
  const [newChargeType, setNewChargeType] = useState<string>('Waiting')
  const [newChargeAmount, setNewChargeAmount] = useState<string>('')
  const [newChargeDesc, setNewChargeDesc] = useState<string>('')

  const handleAddAdditionalCharge = () => {
    const amt = parseFloat(newChargeAmount)
    if (isNaN(amt) || amt <= 0) return
    const newCharge: AdditionalCharge = {
      id: `chg-${Date.now()}`,
      type: newChargeType,
      amount: amt,
      description: newChargeDesc || `${newChargeType} Charge`,
    }
    setAdditionalCharges((prev) => [...prev, newCharge])
    setNewChargeAmount('')
    setNewChargeDesc('')
    setShowAddChargeForm(false)
  }

  const handleRemoveCharge = (id: string) => {
    setAdditionalCharges((prev) => prev.filter((c) => c.id !== id))
  }

  // Financial calculations
  const financialSummary = useMemo(() => {
    let customerBillingText = ''
    let monthlyBillingVal = 0
    let perTripBillingVal = 0
    let dailyOperationalEq = 0

    if (matchedQuotation && !isManualQuotation) {
      if (matchedQuotation.operationType === 'Monthly' && matchedQuotation.customerBillingMonthly) {
        monthlyBillingVal = matchedQuotation.customerBillingMonthly
        dailyOperationalEq = monthlyBillingVal / 30.0
        customerBillingText = `SAR ${monthlyBillingVal.toLocaleString()} / month`
      } else if (matchedQuotation.customerBillingPerTrip) {
        perTripBillingVal = matchedQuotation.customerBillingPerTrip
        dailyOperationalEq = perTripBillingVal
        customerBillingText = `SAR ${perTripBillingVal.toLocaleString()} / trip`
      }
    } else {
      if (operationType === 'Monthly') {
        monthlyBillingVal = manualBillingMonthly
        dailyOperationalEq = monthlyBillingVal / 30.0
        customerBillingText = `SAR ${monthlyBillingVal.toLocaleString()} / month`
      } else {
        perTripBillingVal = manualBillingPerTrip
        dailyOperationalEq = perTripBillingVal
        customerBillingText = `SAR ${perTripBillingVal.toLocaleString()} / trip`
      }
    }

    const driverPayoutVal =
      matchedQuotation && !isManualQuotation
        ? matchedQuotation.driverPayoutPerTrip
        : manualDriverPayout

    const totalAddlCharges = additionalCharges.reduce((acc, c) => acc + c.amount, 0)

    const estimatedMarginVal =
      operationType === 'Monthly'
        ? monthlyBillingVal - driverPayoutVal * 20 - totalAddlCharges
        : (perTripBillingVal || dailyOperationalEq) - driverPayoutVal - totalAddlCharges

    return {
      customerBillingText,
      monthlyBillingVal,
      dailyOperationalEq,
      driverPayoutVal,
      totalAddlCharges,
      estimatedMarginVal,
    }
  }, [
    matchedQuotation,
    isManualQuotation,
    operationType,
    manualBillingMonthly,
    manualBillingPerTrip,
    manualDriverPayout,
    additionalCharges,
  ])

  // ==========================================
  // HELPER FUNCTIONS & NAVIGATION HANDLERS
  // ==========================================

  const selectedDriver = SAMPLE_DRIVERS.find((d) => d.id === selectedDriverId)
  const selectedVehicle = SAMPLE_VEHICLES.find((v) => v.id === selectedVehicleId)
  const pickupObj = SAMPLE_LOCATIONS.find((l) => l.id === pickupLocation)
  const destObj = SAMPLE_LOCATIONS.find((l) => l.id === destinationLocation)

  const handleNextFromStep1 = () => {
    if (!selectedCustomerId) {
      addToast({
        title: 'Customer Required',
        description: 'Please select a customer before continuing.',
        type: 'error',
      })
      return
    }
    setCurrentStep(2)
  }

  const handleNextFromStep2 = () => {
    if (!pickupLocation || !destinationLocation) {
      addToast({
        title: 'Locations Required',
        description: 'Please select both pickup and destination locations.',
        type: 'error',
      })
      return
    }
    setCurrentStep(3)
  }

  const handleNextFromStep3 = () => {
    if (!selectedDriverId || !selectedVehicleId) {
      addToast({
        title: 'Assignment Required',
        description: 'Please assign both a driver and a vehicle.',
        type: 'error',
      })
      return
    }
    setCurrentStep(4)
  }

  const handleCreateTripSubmit = () => {
    addToast({
      title: '✓ Trip Created Successfully',
      description: `Trip #TRIP-${Math.floor(10000 + Math.random() * 90000)} created for ${selectedCustomer?.name}.`,
      type: 'success',
    })
    navigate('/operations/dashboard')
  }

  // ==========================================
  // RENDER: MERCON DESIGN SYSTEM LAYOUT
  // ==========================================

  return (
    <div className="min-h-screen bg-[#EEF1F6] p-4 md:p-8 text-[#3E3C3D]">
      <div className="mx-auto max-w-5xl space-y-6">
        
        {/* TOP HEADER */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-gray-200 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <Badge className="bg-[#FA634E] text-white hover:bg-[#FA634E]/90 text-xs font-semibold px-2.5 py-0.5 rounded">
                CREATE TRIP WIZARD
              </Badge>
              <span className="text-xs text-[#6E6E80] font-mono">/trips/new</span>
            </div>
            <h1 className="text-2xl font-bold text-[#3E3C3D] mt-1 tracking-tight">
              New Commercial Dispatch Trip
            </h1>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/operations/dashboard')}
            className="border-gray-300 text-[#3E3C3D] hover:bg-white hover:text-black cursor-pointer text-xs"
          >
            Cancel & Exit
          </Button>
        </div>

        {/* STEPPER BAR (4-STEP APPROVED IA) */}
        <div className="bg-white rounded-lg border border-gray-200 p-3 shadow-xs">
          <div className="grid grid-cols-4 gap-2">
            {[
              { step: 1, title: 'STEP 1 — CUSTOMER', subtitle: 'Who?' },
              { step: 2, title: 'STEP 2 — TRIP / ROUTE', subtitle: 'Where & When?' },
              { step: 3, title: 'STEP 3 — SERVICE & ASSIGNMENT', subtitle: 'Service & Assignment' },
              { step: 4, title: 'STEP 4 — REVIEW', subtitle: 'Review & Create' },
            ].map((s) => {
              const isActive = currentStep === s.step
              const isCompleted = currentStep > s.step
              return (
                <button
                  key={s.step}
                  type="button"
                  onClick={() => {
                    if (isCompleted || s.step < currentStep) setCurrentStep(s.step)
                  }}
                  disabled={s.step > currentStep && !isCompleted}
                  className={`flex flex-col text-left p-2.5 rounded-md border transition-all cursor-pointer ${
                    isActive
                      ? 'bg-[#EEF1F6] border-[#FA634E] ring-1 ring-[#FA634E]'
                      : isCompleted
                      ? 'bg-white border-gray-200 hover:border-gray-300'
                      : 'bg-gray-50 border-gray-100 opacity-60 cursor-not-allowed'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider ${
                        isActive ? 'text-[#FA634E]' : isCompleted ? 'text-[#3E3C3D]' : 'text-gray-400'
                      }`}
                    >
                      {s.title}
                    </span>
                    {isCompleted && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />}
                  </div>
                  <span className="text-xs font-semibold text-[#3E3C3D] mt-0.5 truncate">
                    {s.subtitle}
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        {/* ========================================== */}
        {/* STEP 1: CUSTOMER                           */}
        {/* ========================================== */}
        {currentStep === 1 && (
          <Card className="bg-white border-gray-200 p-6 shadow-xs space-y-6">
            <div>
              <h2 className="text-lg font-bold text-[#3E3C3D] flex items-center gap-2">
                <Building2 className="h-5 w-5 text-[#FA634E]" />
                Who is requesting this trip?
              </h2>
              <p className="text-xs text-[#6E6E80] mt-1">
                Select the billing customer for this movement. Shortcuts for frequent corporate accounts are available below.
              </p>
            </div>

            {/* FREQUENT CUSTOMERS SHORTCUTS */}
            <div className="space-y-2">
              <span className="text-xs font-semibold text-[#6E6E80] uppercase tracking-wider">
                Recent & Frequent Customers
              </span>
              <div className="flex flex-wrap gap-2">
                {SAMPLE_CUSTOMERS.filter((c) => c.isFrequent).map((cust) => {
                  const isSelected = selectedCustomerId === cust.id
                  return (
                    <button
                      key={cust.id}
                      type="button"
                      onClick={() => {
                        setSelectedCustomerId(cust.id)
                      }}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-all cursor-pointer flex items-center gap-1.5 ${
                        isSelected
                          ? 'bg-[#FA634E] text-white border-[#FA634E] shadow-xs'
                          : 'bg-white text-[#3E3C3D] border-gray-300 hover:bg-[#EEF1F6]'
                      }`}
                    >
                      {cust.name}
                      {isSelected && <Check className="h-3.5 w-3.5" />}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* SEARCHABLE COMBOBOX SELECTOR */}
            <div className="space-y-2 pt-2">
              <label className="text-xs font-semibold text-[#3E3C3D] block">
                Search Customer Account
              </label>
              <Combobox
                options={SAMPLE_CUSTOMERS.map((c) => ({
                  value: c.id,
                  label: `${c.name} (${c.code}) — Contact: ${c.contactPerson}`,
                }))}
                value={selectedCustomerId}
                onValueChange={(val) => setSelectedCustomerId(val)}
                placeholder="Search by customer name, account code, or contact..."
                searchPlaceholder="Type customer name or code..."
                emptyText="No customer matching search found."
                className="w-full"
              />
            </div>

            {/* CONFIRMED SELECTION BADGE DISPLAY */}
            {selectedCustomer ? (
              <div className="bg-[#EEF1F6] border border-emerald-300 rounded-md p-4 flex items-center justify-between animate-in fade-in duration-200">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-full bg-emerald-600 text-white flex items-center justify-center font-bold text-sm">
                    ✓
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-[#3E3C3D] text-sm">
                        {selectedCustomer.name}
                      </span>
                      <Badge className="bg-emerald-100 text-emerald-800 text-[10px] font-mono border-emerald-200">
                        {selectedCustomer.code}
                      </Badge>
                    </div>
                    <p className="text-xs text-[#6E6E80] mt-0.5">
                      Contact: {selectedCustomer.contactPerson} · {selectedCustomer.phone}
                    </p>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedCustomerId('')}
                  className="text-xs text-[#6E6E80] hover:text-red-600 hover:bg-white cursor-pointer"
                >
                  Change
                </Button>
              </div>
            ) : (
              <div className="border border-dashed border-gray-300 rounded-md p-6 text-center text-xs text-[#6E6E80]">
                Select a customer above to continue to Route & Timing configuration.
              </div>
            )}

            {/* STEP 1 NAVIGATION BUTTON */}
            <div className="flex justify-end pt-4 border-t border-gray-200">
              <Button
                onClick={handleNextFromStep1}
                disabled={!selectedCustomerId}
                className="bg-[#FA634E] hover:bg-[#FA634E]/90 text-white font-semibold text-xs px-6 py-2 cursor-pointer shadow-xs"
              >
                Continue to Trip / Route →
              </Button>
            </div>
          </Card>
        )}

        {/* ========================================== */}
        {/* STEP 2: TRIP / ROUTE                      */}
        {/* ========================================== */}
        {currentStep === 2 && (
          <Card className="bg-white border-gray-200 p-6 shadow-xs space-y-6">
            <div>
              <h2 className="text-lg font-bold text-[#3E3C3D] flex items-center gap-2">
                <Navigation className="h-5 w-5 text-[#FA634E]" />
                Where and when is this trip happening?
              </h2>
              <p className="text-xs text-[#6E6E80] mt-1">
                Define the physical route stops and timing schedule for this shipment.
              </p>
            </div>

            {/* ROUTE CONFIGURATION (WHERE?) */}
            <div className="space-y-4 border border-gray-200 rounded-lg p-4 bg-gray-50/50">
              <h3 className="text-xs font-bold text-[#3E3C3D] uppercase tracking-wider flex items-center gap-1.5">
                <MapPin className="h-4 w-4 text-[#FA634E]" />
                Route Information (WHERE?)
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-[#3E3C3D]">Pickup Location</label>
                  <Combobox
                    options={SAMPLE_LOCATIONS.map((l) => ({ value: l.id, label: l.label }))}
                    value={pickupLocation}
                    onValueChange={(val) => setPickupLocation(val)}
                    placeholder="Select pickup terminal/city..."
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-[#3E3C3D]">Destination Location</label>
                  <Combobox
                    options={SAMPLE_LOCATIONS.map((l) => ({ value: l.id, label: l.label }))}
                    value={destinationLocation}
                    onValueChange={(val) => setDestinationLocation(val)}
                    placeholder="Select destination terminal/city..."
                  />
                </div>
              </div>

              {/* DYNAMIC STOPS ARRAY */}
              {stops.length > 0 && (
                <div className="space-y-2 pt-2 border-t border-gray-200">
                  <span className="text-xs font-semibold text-[#6E6E80]">Intermediate Waypoints / Stops</span>
                  {stops.map((stopLocId, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <Badge className="bg-gray-200 text-[#3E3C3D] text-[10px]">Stop {idx + 1}</Badge>
                      <div className="flex-1">
                        <Combobox
                          options={SAMPLE_LOCATIONS.map((l) => ({ value: l.id, label: l.label }))}
                          value={stopLocId}
                          onValueChange={(val) => {
                            const updated = [...stops]
                            updated[idx] = val
                            setStops(updated)
                          }}
                          placeholder="Select stop location..."
                        />
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setStops(stops.filter((_, i) => i !== idx))
                        }}
                        className="text-red-500 hover:text-red-700 hover:bg-red-50 h-8 w-8 p-0 cursor-pointer"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}

              <Button
                variant="outline"
                size="sm"
                onClick={() => setStops([...stops, 'loc-5'])}
                className="text-xs text-[#FA634E] border-[#FA634E]/40 hover:bg-[#FA634E]/10 cursor-pointer"
              >
                <Plus className="h-3.5 w-3.5 mr-1" /> Add Stop
              </Button>

              {/* ROUTE VISUAL PREVIEW & ESTIMATES */}
              <div className="bg-white border border-gray-200 rounded-md p-3 flex flex-col md:flex-row md:items-center justify-between text-xs gap-3">
                <div className="flex items-center gap-2 text-[#3E3C3D]">
                  <span className="font-bold">{pickupObj?.label.split(' ')[0]}</span>
                  {stops.map((_, i) => (
                    <span key={i} className="text-gray-400">→ Stop {i + 1}</span>
                  ))}
                  <span className="text-gray-400">→</span>
                  <span className="font-bold">{destObj?.label.split(' ')[0]}</span>
                </div>
                <div className="flex items-center gap-4 text-[#6E6E80] font-mono">
                  <span>Dist: <strong>{routeEstimate.distanceKm} km</strong></span>
                  <span>Est. Duration: <strong>{routeEstimate.durationHours} hrs</strong></span>
                </div>
              </div>
            </div>

            {/* DATE / TIME CONFIGURATION (WHEN?) */}
            <div className="space-y-4 border border-gray-200 rounded-lg p-4 bg-gray-50/50">
              <h3 className="text-xs font-bold text-[#3E3C3D] uppercase tracking-wider flex items-center gap-1.5">
                <Clock className="h-4 w-4 text-[#FA634E]" />
                Schedule & Timing (WHEN?)
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <label className="text-[11px] font-semibold text-[#3E3C3D]">Pickup Date</label>
                    <Input
                      type="date"
                      value={pickupDate}
                      onChange={(e) => setPickupDate(e.target.value)}
                      className="text-xs bg-white"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[11px] font-semibold text-[#3E3C3D]">Pickup Time</label>
                    <Input
                      type="time"
                      value={pickupTime}
                      onChange={(e) => setPickupTime(e.target.value)}
                      className="text-xs bg-white"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <label className="text-[11px] font-semibold text-[#3E3C3D]">Drop-off Date</label>
                    <Input
                      type="date"
                      value={dropoffDate}
                      onChange={(e) => setDropoffDate(e.target.value)}
                      className="text-xs bg-white"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[11px] font-semibold text-[#3E3C3D]">Drop-off Time</label>
                    <Input
                      type="time"
                      value={dropoffTime}
                      onChange={(e) => setDropoffTime(e.target.value)}
                      className="text-xs bg-white"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* STEP 2 NAVIGATION BUTTONS */}
            <div className="flex items-center justify-between pt-4 border-t border-gray-200">
              <Button
                variant="outline"
                onClick={() => setCurrentStep(1)}
                className="text-xs text-[#3E3C3D] border-gray-300 hover:bg-gray-100 cursor-pointer"
              >
                ← Back to Customer
              </Button>
              <Button
                onClick={handleNextFromStep2}
                className="bg-[#FA634E] hover:bg-[#FA634E]/90 text-white font-semibold text-xs px-6 py-2 cursor-pointer shadow-xs"
              >
                Continue to Service & Assignment →
              </Button>
            </div>
          </Card>
        )}

        {/* ========================================== */}
        {/* STEP 3: SERVICE & ASSIGNMENT               */}
        {/* ========================================== */}
        {currentStep === 3 && (
          <div className="space-y-6">
            
            {/* A. SERVICE / QUOTATION CONFIGURATION */}
            <Card className="bg-white border-gray-200 p-6 shadow-xs space-y-6">
              <div>
                <h2 className="text-lg font-bold text-[#3E3C3D] flex items-center gap-2">
                  <Sparkles className="h-5 w-5 text-[#FA634E]" />
                  A. Service & Quotation Configuration
                </h2>
                <p className="text-xs text-[#6E6E80] mt-1">
                  Automatic quotation matching runs based on selected Customer + Route.
                </p>
              </div>

              {/* AUTOMATIC QUOTATION MATCHED BANNER */}
              {matchedQuotation && !isManualQuotation ? (
                <div className="bg-emerald-50 border border-emerald-300 rounded-lg p-4 space-y-3 animate-in fade-in duration-200">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <ShieldCheck className="h-5 w-5 text-emerald-600" />
                      <span className="font-bold text-xs uppercase tracking-wider text-emerald-900">
                        ✓ QUOTATION MATCHED
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setIsManualQuotation(true)}
                      className="text-xs text-emerald-800 hover:bg-emerald-100 cursor-pointer"
                    >
                      [Change / Custom Rate]
                    </Button>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-4 gap-3 bg-white p-3 rounded border border-emerald-200 text-xs">
                    <div>
                      <span className="text-[#6E6E80] text-[10px] block">Service Type</span>
                      <strong className="text-[#3E3C3D]">
                        {matchedQuotation.operationType} · {matchedQuotation.lineType}
                      </strong>
                    </div>
                    <div>
                      <span className="text-[#6E6E80] text-[10px] block">Vehicle Class</span>
                      <strong className="text-[#3E3C3D]">{matchedQuotation.vehicleClass}</strong>
                    </div>
                    <div>
                      <span className="text-[#6E6E80] text-[10px] block">Customer Billing</span>
                      <strong className="text-emerald-700">
                        {financialSummary.customerBillingText}
                      </strong>
                    </div>
                    <div>
                      <span className="text-[#6E6E80] text-[10px] block">Driver Payout</span>
                      <strong className="text-[#3E3C3D]">
                        SAR {financialSummary.driverPayoutVal} / trip
                      </strong>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="space-y-4 border border-gray-200 rounded-lg p-4 bg-gray-50/50">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-[#3E3C3D] uppercase tracking-wider">
                      Manual Service & Rate Configuration
                    </span>
                    {matchedQuotation && (
                      <Button
                        variant="link"
                        size="sm"
                        onClick={() => setIsManualQuotation(false)}
                        className="text-xs text-[#FA634E] p-0 h-auto cursor-pointer"
                      >
                        Restore Matched Quotation
                      </Button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-[#3E3C3D]">Operation Type</label>
                      <select
                        value={operationType}
                        onChange={(e) => setOperationType(e.target.value as any)}
                        className="w-full h-9 rounded-md border border-gray-300 bg-white px-3 text-xs text-[#3E3C3D]"
                      >
                        <option value="Monthly">Monthly</option>
                        <option value="Extra">Extra</option>
                      </select>
                    </div>

                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-[#3E3C3D]">Line Type / Category</label>
                      <select
                        value={lineType}
                        onChange={(e) => setLineType(e.target.value as any)}
                        className="w-full h-9 rounded-md border border-gray-300 bg-white px-3 text-xs text-[#3E3C3D]"
                      >
                        <option value="Single Trip">Single Trip</option>
                        <option value="Round Trip">Round Trip</option>
                        <option value="10 Hours Shift">10 Hours Shift</option>
                        <option value="12 Hours Shift">12 Hours Shift</option>
                      </select>
                    </div>

                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-[#3E3C3D]">Vehicle Class</label>
                      <select
                        value={vehicleClass}
                        onChange={(e) => setVehicleClass(e.target.value)}
                        className="w-full h-9 rounded-md border border-gray-300 bg-white px-3 text-xs text-[#3E3C3D]"
                      >
                        <option value="3–4 TON">3–4 TON</option>
                        <option value="5 TON">5 TON</option>
                        <option value="10 TON">10 TON</option>
                        <option value="20 TON">20 TON</option>
                        <option value="40 FEET">40 FEET</option>
                      </select>
                    </div>
                  </div>

                  {/* MANUAL RATES INPUTS */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2 border-t border-gray-200">
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-[#3E3C3D]">
                        {operationType === 'Monthly' ? 'Customer Monthly Rate (SAR)' : 'Customer Per Trip Rate (SAR)'}
                      </label>
                      <Input
                        type="number"
                        value={operationType === 'Monthly' ? manualBillingMonthly : manualBillingPerTrip}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value) || 0
                          if (operationType === 'Monthly') setManualBillingMonthly(val)
                          else setManualBillingPerTrip(val)
                        }}
                        className="text-xs bg-white font-mono"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-[#3E3C3D]">Driver Payout Rate (SAR/trip)</label>
                      <Input
                        type="number"
                        value={manualDriverPayout}
                        onChange={(e) => setManualDriverPayout(parseFloat(e.target.value) || 0)}
                        className="text-xs bg-white font-mono"
                      />
                    </div>
                  </div>
                </div>
              )}
            </Card>

            {/* B. ASSIGNMENT: DRIVER & VEHICLE */}
            <Card className="bg-white border-gray-200 p-6 shadow-xs space-y-6">
              <div>
                <h2 className="text-lg font-bold text-[#3E3C3D] flex items-center gap-2">
                  <Truck className="h-5 w-5 text-[#FA634E]" />
                  B. Driver & Vehicle Assignment
                </h2>
                <p className="text-xs text-[#6E6E80] mt-1">
                  Selecting a driver or vehicle intelligently narrows vehicle class and default assignments.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* DRIVER SELECTOR */}
                <div className="space-y-3 border border-gray-200 rounded-lg p-4 bg-gray-50/50">
                  <label className="text-xs font-bold text-[#3E3C3D] uppercase tracking-wider flex items-center gap-1.5">
                    <User className="h-4 w-4 text-[#FA634E]" />
                    Driver Selector
                  </label>
                  <Combobox
                    options={SAMPLE_DRIVERS.map((d) => ({
                      value: d.id,
                      label: `${d.name} (${d.assignedVehicleClass}) — Lic: ${d.licenseNumber}`,
                    }))}
                    value={selectedDriverId}
                    onValueChange={handleDriverChange}
                    placeholder="Select driver..."
                  />

                  {selectedDriver && (
                    <div className="bg-white p-3 rounded border border-gray-200 flex items-center gap-3 text-xs mt-2">
                      <Avatar className="h-9 w-9 bg-[#FA634E] text-white flex items-center justify-center font-bold text-xs">
                        {selectedDriver.initials}
                      </Avatar>
                      <div>
                        <strong className="text-[#3E3C3D] block">{selectedDriver.name}</strong>
                        <span className="text-[#6E6E80] text-[11px] block">{selectedDriver.phone}</span>
                        <Badge className="bg-gray-100 text-[#3E3C3D] text-[10px] border-gray-300 mt-1">
                          {selectedDriver.licenseNumber}
                        </Badge>
                      </div>
                    </div>
                  )}
                </div>

                {/* VEHICLE SELECTOR */}
                <div className="space-y-3 border border-gray-200 rounded-lg p-4 bg-gray-50/50">
                  <label className="text-xs font-bold text-[#3E3C3D] uppercase tracking-wider flex items-center gap-1.5">
                    <Truck className="h-4 w-4 text-[#FA634E]" />
                    Vehicle Selector
                  </label>
                  <Combobox
                    options={SAMPLE_VEHICLES.map((v) => ({
                      value: v.id,
                      label: `${v.plateNumber} — ${v.makeModel} (${v.vehicleClass})`,
                    }))}
                    value={selectedVehicleId}
                    onValueChange={handleVehicleChange}
                    placeholder="Select vehicle..."
                  />

                  {selectedVehicle && (
                    <div className="bg-white p-3 rounded border border-gray-200 flex items-center gap-3 text-xs mt-2">
                      <div className="h-9 w-9 rounded-md bg-gray-200 flex items-center justify-center text-[#3E3C3D]">
                        <Truck className="h-5 w-5" />
                      </div>
                      <div>
                        <strong className="text-[#3E3C3D] block font-mono text-sm">
                          {selectedVehicle.plateNumber}
                        </strong>
                        <span className="text-[#6E6E80] text-[11px] block">{selectedVehicle.makeModel}</span>
                        <Badge className="bg-blue-50 text-blue-800 border-blue-200 text-[10px] mt-1">
                          Class: {selectedVehicle.vehicleClass}
                        </Badge>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </Card>

            {/* C. FINANCIAL SUMMARY (UNIFIED) */}
            <Card className="bg-[#3E3C3D] text-white p-6 shadow-md rounded-lg space-y-4">
              <div className="flex items-center justify-between border-b border-gray-600 pb-3">
                <h3 className="text-sm font-bold uppercase tracking-wider text-[#FA634E] flex items-center gap-2">
                  <DollarSign className="h-4 w-4" />
                  Unified Financial Summary
                </h3>
                <Badge className="bg-gray-700 text-gray-200 text-[10px] font-mono">
                  Derived Calculation
                </Badge>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
                <div className="bg-gray-800/80 p-3 rounded border border-gray-700">
                  <span className="text-gray-400 text-[10px] uppercase block">Customer Billing</span>
                  <strong className="text-lg font-bold text-white block mt-1">
                    {financialSummary.customerBillingText}
                  </strong>
                </div>

                <div className="bg-gray-800/80 p-3 rounded border border-gray-700">
                  <span className="text-gray-400 text-[10px] uppercase block flex items-center gap-1">
                    Daily Operational Eq.
                    <span title="Monthly quotation ÷ 30">
                      <Info className="h-3 w-3 text-gray-400" />
                    </span>
                  </span>
                  <strong className="text-lg font-bold text-amber-400 block mt-1">
                    SAR {financialSummary.dailyOperationalEq.toFixed(2)} / day
                  </strong>
                  <span className="text-[9px] text-gray-400 block mt-0.5">
                    (Contractual monthly rate stays unchanged)
                  </span>
                </div>

                <div className="bg-gray-800/80 p-3 rounded border border-gray-700">
                  <span className="text-gray-400 text-[10px] uppercase block">Driver Payout</span>
                  <strong className="text-lg font-bold text-emerald-400 block mt-1">
                    SAR {financialSummary.driverPayoutVal} / trip
                  </strong>
                  <span className="text-[9px] text-gray-400 block mt-0.5">
                    (Strictly per trip)
                  </span>
                </div>

                <div className="bg-gray-800/80 p-3 rounded border border-gray-700">
                  <span className="text-gray-400 text-[10px] uppercase block">Est. Net Balance / Margin</span>
                  <strong className="text-lg font-bold text-[#FA634E] block mt-1">
                    SAR {financialSummary.estimatedMarginVal.toLocaleString()}
                  </strong>
                </div>
              </div>
            </Card>

            {/* D. ADDITIONAL CHARGES (OPTIONAL) */}
            <Card className="bg-white border-gray-200 p-6 shadow-xs space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-bold text-[#3E3C3D] uppercase tracking-wider">
                    Additional Charges (Optional / Exceptional)
                  </h3>
                  <p className="text-xs text-[#6E6E80]">
                    Only add charges if waiting, extra stops, or labour fees apply.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowAddChargeForm(!showAddChargeForm)}
                  className="text-xs text-[#FA634E] border-[#FA634E]/40 hover:bg-[#FA634E]/10 cursor-pointer"
                >
                  <Plus className="h-3.5 w-3.5 mr-1" /> Add Charge
                </Button>
              </div>

              {showAddChargeForm && (
                <div className="bg-[#EEF1F6] p-4 rounded-md border border-gray-300 grid grid-cols-1 md:grid-cols-4 gap-3 text-xs animate-in fade-in">
                  <div>
                    <label className="text-[11px] font-semibold text-[#3E3C3D]">Charge Type</label>
                    <select
                      value={newChargeType}
                      onChange={(e) => setNewChargeType(e.target.value)}
                      className="w-full h-8 rounded border border-gray-300 bg-white px-2 text-xs"
                    >
                      <option value="Waiting">Waiting Fee</option>
                      <option value="Labour">Labour Charge</option>
                      <option value="Extra Stop">Extra Stop Fee</option>
                      <option value="Offloading">Offloading Fee</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold text-[#3E3C3D]">Amount (SAR)</label>
                    <Input
                      type="number"
                      placeholder="e.g. 150"
                      value={newChargeAmount}
                      onChange={(e) => setNewChargeAmount(e.target.value)}
                      className="h-8 bg-white text-xs font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold text-[#3E3C3D]">Description</label>
                    <Input
                      type="text"
                      placeholder="Notes..."
                      value={newChargeDesc}
                      onChange={(e) => setNewChargeDesc(e.target.value)}
                      className="h-8 bg-white text-xs"
                    />
                  </div>
                  <div className="flex items-end">
                    <Button
                      onClick={handleAddAdditionalCharge}
                      className="bg-[#FA634E] hover:bg-[#FA634E]/90 text-white h-8 w-full text-xs font-semibold cursor-pointer"
                    >
                      Save Charge
                    </Button>
                  </div>
                </div>
              )}

              {additionalCharges.length > 0 ? (
                <div className="border border-gray-200 rounded-md overflow-hidden text-xs">
                  <table className="w-full text-left">
                    <thead className="bg-gray-50 border-b border-gray-200 text-[#6E6E80]">
                      <tr>
                        <th className="p-2.5">Type</th>
                        <th className="p-2.5">Description</th>
                        <th className="p-2.5 text-right">Amount</th>
                        <th className="p-2.5 w-10"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {additionalCharges.map((chg) => (
                        <tr key={chg.id}>
                          <td className="p-2.5 font-semibold text-[#3E3C3D]">{chg.type}</td>
                          <td className="p-2.5 text-[#6E6E80]">{chg.description}</td>
                          <td className="p-2.5 text-right font-mono font-bold text-[#3E3C3D]">
                            SAR {chg.amount.toFixed(2)}
                          </td>
                          <td className="p-2.5 text-center">
                            <button
                              type="button"
                              onClick={() => handleRemoveCharge(chg.id)}
                              className="text-red-500 hover:text-red-700 cursor-pointer"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-xs text-[#6E6E80] italic">No additional charges added.</div>
              )}
            </Card>

            {/* STEP 3 NAVIGATION BUTTONS */}
            <div className="flex items-center justify-between pt-4 border-t border-gray-200">
              <Button
                variant="outline"
                onClick={() => setCurrentStep(2)}
                className="text-xs text-[#3E3C3D] border-gray-300 hover:bg-gray-100 cursor-pointer"
              >
                ← Back to Route
              </Button>
              <Button
                onClick={handleNextFromStep3}
                className="bg-[#FA634E] hover:bg-[#FA634E]/90 text-white font-semibold text-xs px-6 py-2 cursor-pointer shadow-xs"
              >
                Continue to Review →
              </Button>
            </div>
          </div>
        )}

        {/* ========================================== */}
        {/* STEP 4: REVIEW                             */}
        {/* ========================================== */}
        {currentStep === 4 && (
          <Card className="bg-white border-gray-200 p-6 shadow-xs space-y-6">
            <div>
              <h2 className="text-lg font-bold text-[#3E3C3D] flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                Is everything correct before creating the trip?
              </h2>
              <p className="text-xs text-[#6E6E80] mt-1">
                Compact final review. Click [Edit] on any section to return and modify details.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              
              {/* SUMMARY: CUSTOMER */}
              <div className="border border-gray-200 rounded-lg p-4 bg-gray-50/50 space-y-2">
                <div className="flex items-center justify-between border-b border-gray-200 pb-2">
                  <span className="font-bold text-[#3E3C3D] uppercase tracking-wider text-[11px] flex items-center gap-1.5">
                    <Building2 className="h-3.5 w-3.5 text-[#FA634E]" /> Customer
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setCurrentStep(1)}
                    className="text-[11px] text-[#FA634E] h-6 px-2 cursor-pointer hover:bg-white"
                  >
                    [Edit]
                  </Button>
                </div>
                <strong className="text-sm text-[#3E3C3D] block">{selectedCustomer?.name}</strong>
                <p className="text-[#6E6E80]">
                  Code: {selectedCustomer?.code} · Contact: {selectedCustomer?.contactPerson} ({selectedCustomer?.phone})
                </p>
              </div>

              {/* SUMMARY: ROUTE & TIMING */}
              <div className="border border-gray-200 rounded-lg p-4 bg-gray-50/50 space-y-2">
                <div className="flex items-center justify-between border-b border-gray-200 pb-2">
                  <span className="font-bold text-[#3E3C3D] uppercase tracking-wider text-[11px] flex items-center gap-1.5">
                    <MapPin className="h-3.5 w-3.5 text-[#FA634E]" /> Route & Schedule
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setCurrentStep(2)}
                    className="text-[11px] text-[#FA634E] h-6 px-2 cursor-pointer hover:bg-white"
                  >
                    [Edit]
                  </Button>
                </div>
                <div className="text-[#3E3C3D] font-medium">
                  {pickupObj?.label} → {destObj?.label}
                </div>
                <p className="text-[#6E6E80] text-[11px]">
                  Pickup: {pickupDate} {pickupTime} · Drop-off: {dropoffDate} {dropoffTime}
                </p>
                <p className="text-[#6E6E80] text-[11px] font-mono">
                  Dist: {routeEstimate.distanceKm} km · Est. Duration: {routeEstimate.durationHours} hrs
                </p>
              </div>

              {/* SUMMARY: SERVICE CONFIGURATION */}
              <div className="border border-gray-200 rounded-lg p-4 bg-gray-50/50 space-y-2">
                <div className="flex items-center justify-between border-b border-gray-200 pb-2">
                  <span className="font-bold text-[#3E3C3D] uppercase tracking-wider text-[11px] flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5 text-[#FA634E]" /> Service Configuration
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setCurrentStep(3)}
                    className="text-[11px] text-[#FA634E] h-6 px-2 cursor-pointer hover:bg-white"
                  >
                    [Edit]
                  </Button>
                </div>
                <div className="flex items-center gap-2">
                  <Badge className="bg-[#3E3C3D] text-white text-[10px]">
                    {operationType}
                  </Badge>
                  <Badge className="bg-gray-200 text-[#3E3C3D] text-[10px]">
                    {lineType}
                  </Badge>
                  <Badge className="bg-blue-100 text-blue-800 text-[10px]">
                    {vehicleClass}
                  </Badge>
                </div>
              </div>

              {/* SUMMARY: ASSIGNMENT */}
              <div className="border border-gray-200 rounded-lg p-4 bg-gray-50/50 space-y-2">
                <div className="flex items-center justify-between border-b border-gray-200 pb-2">
                  <span className="font-bold text-[#3E3C3D] uppercase tracking-wider text-[11px] flex items-center gap-1.5">
                    <Truck className="h-3.5 w-3.5 text-[#FA634E]" /> Driver & Vehicle
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setCurrentStep(3)}
                    className="text-[11px] text-[#FA634E] h-6 px-2 cursor-pointer hover:bg-white"
                  >
                    [Edit]
                  </Button>
                </div>
                <div className="text-[#3E3C3D]">
                  Driver: <strong>{selectedDriver?.name}</strong> ({selectedDriver?.phone})
                </div>
                <div className="text-[#3E3C3D]">
                  Vehicle: <strong>{selectedVehicle?.plateNumber}</strong> ({selectedVehicle?.makeModel})
                </div>
              </div>

            </div>

            {/* SUMMARY: FINANCIALS BAR */}
            <div className="bg-[#EEF1F6] border border-gray-300 rounded-lg p-4 space-y-3 text-xs">
              <div className="flex items-center justify-between border-b border-gray-300 pb-2">
                <span className="font-bold text-[#3E3C3D] uppercase tracking-wider text-[11px]">
                  Financial Breakdown
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setCurrentStep(3)}
                  className="text-[11px] text-[#FA634E] h-6 px-2 cursor-pointer hover:bg-white"
                >
                  [Edit]
                </Button>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
                <div className="bg-white p-2 rounded border border-gray-200">
                  <span className="text-[#6E6E80] text-[10px] block">Customer Billing</span>
                  <strong className="text-[#3E3C3D] block text-sm font-bold mt-0.5">
                    {financialSummary.customerBillingText}
                  </strong>
                </div>
                <div className="bg-white p-2 rounded border border-gray-200">
                  <span className="text-[#6E6E80] text-[10px] block">Daily Operational Eq.</span>
                  <strong className="text-amber-700 block text-sm font-bold mt-0.5">
                    SAR {financialSummary.dailyOperationalEq.toFixed(2)}/day
                  </strong>
                </div>
                <div className="bg-white p-2 rounded border border-gray-200">
                  <span className="text-[#6E6E80] text-[10px] block">Driver Payout</span>
                  <strong className="text-emerald-700 block text-sm font-bold mt-0.5">
                    SAR {financialSummary.driverPayoutVal}/trip
                  </strong>
                </div>
                <div className="bg-white p-2 rounded border border-gray-200">
                  <span className="text-[#6E6E80] text-[10px] block">Additional Charges</span>
                  <strong className="text-[#3E3C3D] block text-sm font-bold mt-0.5">
                    SAR {financialSummary.totalAddlCharges}
                  </strong>
                </div>
              </div>
            </div>

            {/* STEP 4 FINAL ACTION BUTTONS */}
            <div className="flex items-center justify-between pt-4 border-t border-gray-200">
              <Button
                variant="outline"
                onClick={() => setCurrentStep(3)}
                className="text-xs text-[#3E3C3D] border-gray-300 hover:bg-gray-100 cursor-pointer"
              >
                ← Back to Service & Assignment
              </Button>
              <Button
                onClick={handleCreateTripSubmit}
                className="bg-[#FA634E] hover:bg-[#FA634E]/90 text-white font-bold text-sm px-8 py-3 cursor-pointer shadow-md"
              >
                ✓ Create Trip
              </Button>
            </div>
          </Card>
        )}

      </div>
    </div>
  )
}
