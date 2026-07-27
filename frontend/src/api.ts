const API_BASE = import.meta.env.VITE_API_BASE || '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options)
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

export const api = {
  dashboard: () => request<Dashboard>('/reports/dashboard'),
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
  categories: () => request<Category[]>('/categories'),
  customers: () => request<Customer[]>('/customers'),
  createCustomer: (body: Partial<Customer>) =>
    request<Customer>('/customers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  suppliers: () => request<Supplier[]>('/suppliers'),
  sales: () => request<Sale[]>('/sales'),
  createSale: (body: SaleCreate) =>
    request<Sale>('/sales', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  purchases: () => request<Purchase[]>('/purchases'),
  createPurchase: (body: PurchaseCreate) =>
    request<Purchase>('/purchases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
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
  imports: () => request<ImportBatch[]>('/imports'),
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
  phone?: string
  motorcycle_model?: string
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
  items: { product_id: number; quantity: number; unit_price?: number }[]
}

export type Purchase = {
  id: number
  po_no: string
  purchase_date: string
  supplier_name?: string
  total: number
  items: {
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
  items: { product_id: number; quantity: number; unit_cost?: number }[]
}

export type Dashboard = {
  shop_name: string
  total_products: number
  low_stock_count: number
  out_of_stock_count: number
  inventory_value_cost: number
  inventory_value_retail: number
  sales_today: number
  sales_month: number
  sales_year: number
  profit_month: number
  transactions_today: number
  transactions_month: number
  top_products: { name: string; qty: number; amount: number }[]
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
  top_products: { name: string; qty: number; amount: number }[]
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
    sku?: string
    product_name?: string
    quantity?: number
    unit_price?: number
    matched_product_name?: string
    current_stock?: number
    status: string
    message?: string
  }[]
  matched_count: number
  unmatched_count: number
  total_qty: number
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

export function peso(n: number | undefined | null) {
  return `₱${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
