const API_BASE = import.meta.env.VITE_API_BASE || '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    ...options,
    headers: {
      ...(options?.headers || {}),
    },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json()
}


// ---------------------------------------------------------------- analytics

export interface MoverRow {
  product_id: number
  sku: string
  name: string
  supplier: string
  unit_cost: number
  sell_price: number
  on_hand: number
  stock_value: number
  sold_qty: number
  revenue: number
  demand_value: number
  gross_profit: number
  daily_rate: number
  monthly_rate: number
  demand_pattern: string
  method: string
  abc: string
  xyz: string
  abc_xyz: string
  movement: string
  last_sold: string | null
  lead_time_days: number
  review_days: number
  safety_stock: number
  reorder_point: number
  reorder_level: number
  eoq: number
  days_of_cover: number | null
  urgency: number
  value_share: number
  cumulative_share: number
}

export interface ReorderRow extends MoverRow {
  suggested_qty: number
  order_cost: number
  projected_stockout: string | null
  reason: string
}

export interface AnalyticsWindow {
  from: string
  to: string
  days: number
  measured_from?: string
}

export interface MoversOut {
  direction: string
  window: AnalyticsWindow
  count: number
  items: MoverRow[]
}

export interface ReorderOut {
  window: AnalyticsWindow
  count: number
  total_cost: number
  by_supplier: { supplier: string; supplier_id: number | null; lines: number; units: number; cost: number }[]
  suggestions: ReorderRow[]
}

export interface AbcOut {
  window: AnalyticsWindow
  summary: { class: string; items: number; revenue: number; stock_value: number; gross_profit: number }[]
  matrix: { cell: string; items: number; policy: string }[]
  items: MoverRow[]
}

export interface OverviewOut {
  window: AnalyticsWindow
  sku_count: number
  stock_value: number
  movement: Record<string, number>
  dead_stock_value: number
  dead_stock_pct: number
  out_of_stock: number
  fast_movers_out_of_stock: number
  below_reorder_point: number
  reorder_lines: number
  reorder_cost: number
  stock_turnover_annualised: number
  urgent: ReorderRow[]
  at_risk_fast_movers: MoverRow[]
}

export interface ProductForecast {
  product: {
    id: number; sku: string; name: string; stock_qty: number
    cost_price: number; sell_price: number; reorder_level: number; supplier: string
  }
  window: AnalyticsWindow
  pattern: { pattern: string; method?: string; adi?: number; cv2?: number }
  daily_rate: number
  forecast: { next_7d: number; next_30d: number; next_90d: number }
  replenishment: {
    lead_time_days: number; review_days: number; safety_stock: number
    reorder_point: number; economic_order_qty: number
    days_of_cover: number | null; projected_stockout: string | null
  }
  weekly_demand: { week_of: string; qty: number }[]
  weekday_seasonality: { day: string; index: number }[]
}


// ------------------------------------------------------------------- jobs

export interface JobLine {
  id: number
  product_id: number
  sku: string | null
  product_name: string
  quantity: number
  unit_price: number
  discount: number
  line_total: number
  is_labour: boolean
  on_hand: number
  short: boolean
}

export interface Job {
  id: number
  job_no: string
  status: string
  priority: string
  customer_id: number | null
  customer_name: string
  contact: string
  plate_no: string
  motorcycle: string
  complaint: string
  notes: string
  mechanic: string
  created_at: string
  started_at: string | null
  ready_at: string | null
  completed_at: string | null
  cancelled_at: string | null
  cancel_reason: string
  sale_id: number | null
  invoice_no: string | null
  hours_open: number | null
  lines: JobLine[]
  line_count: number
  parts_total: number
  labour_total: number
  discount_total: number
  total: number
  short_lines: number
}

export interface JobBoard {
  counts: Record<string, number>
  open_total: number
  open_value: number
  jobs: Job[]
}

export interface JobCreateIn {
  customer_id?: number | null
  save_customer?: boolean
  customer_name?: string
  contact?: string
  plate_no?: string
  motorcycle?: string
  complaint?: string
  notes?: string
  mechanic?: string
  priority?: string
  lines?: { product_id: number; quantity: number; unit_price?: number; discount?: number }[]
}


// ------------------------------------------------------------ held sales

export interface HeldLine {
  id: number
  product_id: number
  sku: string | null
  product_name: string
  quantity: number
  unit_price: number
  discount: number
  line_total: number
  is_labour: boolean
}

export interface HeldSale {
  id: number
  reference: string
  label: string
  customer_id: number | null
  customer_name: string
  contact: string
  plate_no: string
  motorcycle: string
  note: string
  payment_method: string
  created_at: string
  held_for_minutes: number | null
  lines: HeldLine[]
  line_count: number
  parts_total: number
  labour_total: number
  discount_total: number
  total: number
}

export interface HeldSaleCreateIn {
  label?: string
  customer_id?: number | null
  customer_name?: string
  contact?: string
  plate_no?: string
  motorcycle?: string
  note?: string
  payment_method?: string
  save_customer?: boolean
  lines: { product_id: number; quantity: number; unit_price?: number; discount?: number }[]
}

export const api = {
  holds: (q = '') =>
    request<{ holds: HeldSale[]; count: number; total_value: number }>(
      `/holds${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  hold: (id: number) => request<HeldSale>(`/holds/${id}`),
  createHold: (body: HeldSaleCreateIn) =>
    request<HeldSale>('/holds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteHold: (id: number) =>
    request<{ deleted: boolean; reference: string }>(`/holds/${id}`, { method: 'DELETE' }),

  jobBoard: () => request<JobBoard>('/jobs/board'),
  jobs: (status = 'open', q = '') => {
    const p = new URLSearchParams({ status })
    if (q) p.set('q', q)
    return request<{ jobs: Job[] }>(`/jobs?${p}`)
  },
  job: (id: number) => request<Job>(`/jobs/${id}`),
  createJob: (body: JobCreateIn) =>
    request<Job>('/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateJob: (id: number, body: Record<string, string>) =>
    request<Job>(`/jobs/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  addJobLine: (id: number, product_id: number, quantity: number, discount = 0) =>
    request<Job>(`/jobs/${id}/lines`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id, quantity, discount }),
    }),
  removeJobLine: (id: number, lineId: number) =>
    request<Job>(`/jobs/${id}/lines/${lineId}`, { method: 'DELETE' }),
  cancelJob: (id: number, reason: string) =>
    request<Job>(`/jobs/${id}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }),
  checkoutJob: (id: number, body: { discount?: number; payment_method?: string; allow_negative_stock?: boolean }) =>
    request<{ job: Job; sale: Sale }>(`/jobs/${id}/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  movers: (direction: 'fast' | 'slow' | 'dead', days = 90, limit = 100) =>
    request<MoversOut>(`/analytics/movers?direction=${direction}&days=${days}&limit=${limit}`),
  reorder: (days = 90, supplierId?: number) => {
    const q = new URLSearchParams({ days: String(days) })
    if (supplierId) q.set('supplier_id', String(supplierId))
    return request<ReorderOut>(`/analytics/reorder?${q}`)
  },
  abc: (days = 90) => request<AbcOut>(`/analytics/abc?days=${days}`),
  stockOverview: (days = 90) => request<OverviewOut>(`/analytics/overview?days=${days}`),
  productForecast: (id: number, days = 180) =>
    request<ProductForecast>(`/analytics/products/${id}/forecast?days=${days}`),

  dashboard: (year?: number, month?: number) => {
    const q = new URLSearchParams()
    if (year) q.set('year', String(year))
    if (month) q.set('month', String(month))
    const qs = q.toString() ? `?${q}` : ''
    return request<Dashboard>(`/reports/dashboard${qs}`)
  },
  productPerformance: (opts: {
    period?: string
    year?: number
    month?: number
    metric?: 'amount' | 'qty' | 'profit'
    limit?: number
  } = {}) => {
    const q = new URLSearchParams()
    q.set('period', opts.period || 'monthly')
    q.set('metric', opts.metric || 'amount')
    if (opts.year) q.set('year', String(opts.year))
    if (opts.month) q.set('month', String(opts.month))
    if (opts.limit) q.set('limit', String(opts.limit))
    return request<ProductPerformance>(`/reports/product-performance?${q}`)
  },
  products: (params: string = '') => request<Product[]>(`/products${params}`),
  createProduct: (body: Partial<Product>) =>
    request<Product>('/products', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  adjustStock: (id: number, quantity_change: number, notes?: string) =>
    request<Product>(`/products/${id}/adjust`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quantity_change, notes }),
    }),
  deleteProduct: (id: number, hard = false) =>
    request<{ ok: boolean; mode: string; id: number }>(`/products/${id}?hard=${hard}`, {
      method: 'DELETE',
    }),
  categories: () => request<Category[]>('/categories'),
  customers: () => request<Customer[]>('/customers'),
  createCustomer: (body: Partial<Customer>) =>
    request<Customer>('/customers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  suppliers: () => request<Supplier[]>('/suppliers'),
  sales: (params: string = '') => request<Sale[]>(`/sales${params}`),
  createSale: (body: SaleCreate) =>
    request<Sale>('/sales', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  purchases: () => request<Purchase[]>('/purchases'),
  getPurchase: (id: number) => request<Purchase>(`/purchases/${id}`),
  createPurchase: (body: PurchaseCreate) =>
    request<Purchase>('/purchases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updatePurchase: (id: number, body: PurchaseUpdate) =>
    request<Purchase>(`/purchases/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  uploadPurchaseReceipt: async (id: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<{ ok: boolean; receipt_filename: string; message: string }>(`/purchases/${id}/receipt`, {
      method: 'POST',
      body: fd,
    })
  },
  purchaseReceiptUrl: (id: number) => `${API_BASE}/purchases/${id}/receipt`,
  deletePurchaseReceipt: (id: number) =>
    request<{ ok: boolean }>(`/purchases/${id}/receipt`, { method: 'DELETE' }),
  salesReport: (period: string, year?: number, month?: number) => {
    const q = new URLSearchParams({ period })
    if (year) q.set('year', String(year))
    if (month) q.set('month', String(month))
    return request<PeriodReport>(`/reports/sales?${q}`)
  },
  inventoryReport: () => request<InventoryReport>('/reports/inventory'),
  previewImport: async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<ImportPreview>('/imports/sales/preview', { method: 'POST', body: fd })
  },
  runImport: async (file: File, deductStock = true) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('deduct_stock', String(deductStock))
    fd.append('skip_processed', 'true')
    return request<ImportResult>('/imports/sales', { method: 'POST', body: fd })
  },
  previewSalesPhoto: async (file: File, signal?: AbortSignal) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<OcrPreview>('/imports/sales/ocr-preview', { method: 'POST', body: fd, signal })
  },
  previewPurchasePhoto: async (file: File, signal?: AbortSignal) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<OcrPreview>('/imports/purchases/ocr-preview', { method: 'POST', body: fd, signal })
  },
  confirmSalesRows: (body: {
    filename?: string
    deduct_stock?: boolean
    rows: OcrEditableRow[]
  }) =>
    request<ImportResult>('/imports/sales/confirm-rows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  confirmPurchaseRows: (body: {
    filename?: string
    supplier_id?: number | null
    notes?: string
    purchase_date?: string | null
    rows: OcrEditableRow[]
  }) =>
    request<PurchaseImportResult>('/imports/purchases/confirm-rows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  productSuggestions: (q: string) =>
    request<OcrSuggestion[]>(`/imports/product-suggestions?q=${encodeURIComponent(q)}`),
  imports: () => request<ImportBatch[]>('/imports'),
  importWorkbook: async (file: File, replaceExisting = true) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('replace_existing', String(replaceExisting))
    return request<WorkbookImportResult>('/imports/workbook', { method: 'POST', body: fd })
  },

  previewStockImport: async (file: File, mode: 'set' | 'adjust' | 'upsert' = 'set') => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('mode', mode)
    return request<StockPreview>('/imports/stock/preview', { method: 'POST', body: fd })
  },
  runStockImport: async (file: File, mode: 'set' | 'adjust' | 'upsert' = 'set') => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('mode', mode)
    return request<StockImportResult>('/imports/stock', { method: 'POST', body: fd })
  },
}

export type Product = {
  id: number
  sku: string
  name: string
  brand?: string
  category_id?: number
  supplier_id?: number
  fitment?: string
  unit: string
  cost_price: number
  sell_price: number
  stock_qty: number
  reorder_level: number
  location?: string
  is_active: boolean
  category_name?: string
  supplier_name?: string
  stock_status?: string
}

export type Category = { id: number; name: string; description?: string }
export type Customer = {
  id: number
  name: string
  phone?: string | null
  email?: string | null
  address?: string | null
  motorcycle_model?: string | null
  notes?: string | null
}
export type Supplier = { id: number; name: string; phone?: string; email?: string }

export type SaleItem = {
  id?: number
  product_id?: number
  sku?: string
  product_name: string
  quantity: number
  unit_price: number
  cost_price: number
  line_total: number
}

export type Sale = {
  id: number
  invoice_no: string
  sale_date: string
  customer_id?: number
  customer_name?: string
  payment_method: string
  payment_status: string
  amount_paid: number
  subtotal: number
  discount: number
  tax: number
  total: number
  source: string
  items: SaleItem[]
}

export type SaleCreate = {
  customer_id?: number | null
  payment_method: string
  discount?: number
  sale_date?: string | null
  items: { product_id: number; quantity: number; unit_price?: number }[]
}

export type Purchase = {
  id: number
  po_no: string
  purchase_date: string
  supplier_id?: number | null
  supplier_name?: string
  notes?: string | null
  total: number
  has_receipt?: boolean
  receipt_filename?: string | null
  items: {
    id?: number
    product_id: number
    product_name?: string
    sku?: string
    quantity: number
    unit_cost: number
    line_total: number
  }[]
}

export type PurchaseCreate = {
  supplier_id?: number | null
  notes?: string
  purchase_date?: string | null
  items: { id?: number; product_id: number; quantity: number; unit_cost?: number }[]
}

export type PurchaseUpdate = PurchaseCreate

export type Dashboard = {
  shop_name: string
  selected_year: number
  selected_month: number
  total_products: number
  low_stock_count: number
  out_of_stock_count: number
  inventory_value_cost: number
  inventory_value_retail: number
  sales_today: number
  sales_week: number
  sales_month: number
  sales_year: number
  profit_month: number
  profit_year: number
  transactions_today: number
  transactions_month: number
  top_products: ProductStat[]
  top_products_month: ProductStat[]
  top_products_year: ProductStat[]
  top_profit_month: ProductStat[]
  top_profit_year: ProductStat[]
  low_stock_items: {
    id: number
    sku: string
    name: string
    stock_qty: number
    reorder_level: number
    status: string
  }[]
  recent_sales: {
    id: number
    invoice_no: string
    sale_date: string
    total: number
    customer: string
    items: number
  }[]
  monthly_trend: { label: string; total: number }[]
}

export type ProductStat = {
  name: string
  sku?: string
  qty: number
  amount: number
  profit?: number
}

export type ProductPerformance = {
  period: string
  metric: string
  start_date: string
  end_date: string
  year: number
  month: number
  items: ProductStat[]
}

export type PeriodReport = {
  period: string
  start_date: string
  end_date: string
  total_sales: number
  total_cost: number
  gross_profit: number
  transaction_count: number
  items_sold: number
  by_day: { date: string; total: number }[]
  by_month: { month: string; total: number }[]
  by_category: { category: string; total: number }[]
  by_payment: { method: string; total: number }[]
  top_products: { name: string; qty: number; amount: number; profit?: number }[]
}

export type InventoryReport = {
  total_skus: number
  total_units: number
  value_at_cost: number
  value_at_retail: number
  low_stock: {
    sku: string
    name: string
    category: string
    stock_qty: number
    reorder_level: number
    status: string
  }[]
  by_category: { category: string; skus: number; units: number; value_cost: number }[]
  movements: {
    product?: string
    sku?: string
    type: string
    change: number
    before: number
    after: number
    reference?: string
    created_at: string
  }[]
}

export type ImportPreview = {
  filename: string
  rows: {
    row_number: number
    invoice_no?: string
    sale_date?: string
    sku?: string
    product_name?: string
    quantity?: number
    unit_price?: number
    matched_product_name?: string
    matched_product_id?: number
    current_stock?: number
    status: string
    message?: string
  }[]
  matched_count: number
  unmatched_count: number
  total_qty: number
}

export type OcrSuggestion = {
  id: number
  sku: string
  name: string
  sell_price: number
  cost_price?: number
  stock_qty: number
  score: number
}

export type OcrEditableRow = {
  row_number: number
  invoice_no?: string | null
  sale_date?: string | null
  purchase_date?: string | null
  sku?: string | null
  product_name?: string | null
  quantity?: number | null
  unit_price?: number | null
  unit_cost?: number | null
  uom?: string | null
  line_amount?: number | null
  customer?: string | null
  matched_product_id?: number | null
  matched_product_name?: string | null
  current_stock?: number | null
  ocr_text?: string | null
  suggestions?: OcrSuggestion[]
  status?: string
  message?: string | null
  include?: boolean
}

export type OcrPreview = {
  filename: string
  engine: string
  raw_text: string
  rows: OcrEditableRow[]
  matched_count: number
  unmatched_count: number
  total_qty: number
  message: string
  mode?: string
  document_type?: string
}

export type PurchaseImportResult = {
  batch_id?: number
  filename: string
  po_no?: string
  rows_imported: number
  rows_skipped: number
  stock_added: number
  unmatched_skus: string[]
  purchases_created: number
  message: string
}

export type ImportResult = {
  batch_id: number
  filename: string
  rows_total: number
  rows_imported: number
  rows_skipped: number
  stock_deducted: number
  unmatched_skus: string[]
  sales_created: number
  message: string
}

export type ImportBatch = {
  id: number
  filename: string
  file_type: string
  status: string
  rows_total: number
  rows_imported: number
  rows_skipped: number
  stock_deducted: number
  unmatched_skus?: string
  summary?: string
  created_at: string
}

export type WorkbookImportResult = {
  filename: string
  products_created: number
  services_created: number
  delisted_count: number
  categories: number
  suppliers: number
  sales_created: number
  sale_lines: number
  unmatched_skus: string[]
  batch_id: number
  message: string
}

export type StockPreview = {
  filename: string
  mode: string
  rows: {
    row_number: number
    sku?: string
    product_name?: string
    csv_stock?: number
    csv_adjust?: number
    current_stock?: number
    new_stock?: number
    status: string
    message?: string
  }[]
  matched_count: number
  unmatched_count: number
  will_create_count: number
}

export type StockImportResult = {
  batch_id: number
  filename: string
  mode: string
  rows_total: number
  rows_updated: number
  rows_created: number
  rows_skipped: number
  unmatched_skus: string[]
  net_qty_change: number
  message: string
}

export function peso(n: number | undefined | null) {
  return `₱${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
