"""
Reference notes from similar Excel/VBA sales & inventory systems reviewed online:

1. Manjirigajmal/Sales_Inventory_Tracker
   - Sales_Data sheet with Processed flag
   - Inventory with Reorder_Level / Status
   - VBA deducts stock only for unprocessed sales rows

2. Rohanborse0253/inventory-monitoring-excel-vba
   - Product / Supplier / Customer masters
   - Purchase Order + Details, Sales Order + Details
   - Available Stock in Inventory updated from transactions

3. Neha-Hafeez Excel POS + Inventory
   - Dashboard, CUSTOMER, STOCK, POS, receipt sheets
   - Point-of-sale entry with item scan / quick sale

4. Commercial motorshop patterns (Motodisk, CATAMA, EloERP)
   - Parts SKUs, oils, tires, accessories
   - Real-time stock deduction on sales
   - Daily / monthly sales and stock reporting

KYGSMOTO modernizes these spreadsheet workflows into a web app with
CSV/XLSX sales-file import that reads sold quantities and updates stock.
"""
