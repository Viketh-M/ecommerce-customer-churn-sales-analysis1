# E Commerce Customer Churn & Sales Analysis

Power BI and Python-based analytics work for customer churn prediction, RFM segmentation, CLV analysis, retention analytics, and sales performance monitoring using e-commerce transaction data.

---

## Overview

This repository contains code, notebooks and a Power BI report that transform the public Olist Brazilian E‑Commerce dataset into analysis-ready tables and visualizations for sales and customer analytics. The materials are suitable for exploration, teaching, and reproducible reporting.

Key highlights:
- RFM segmentation and CLV calculations at the customer level
- Cohort retention and monthly sales trends
- Geographic sales mapping (Brazil)
- Power BI report with KPIs and detailed drilldowns

---

## Repo metadata

- Repository: Viketh-M/ecommerce-customer-churn-sales-analysis1 (ID: 1280056870)
- Language composition: Python (77.2%), Jupyter Notebook (22.8%)

---

## Data

Source: Olist Brazilian E‑Commerce Public Dataset (Kaggle) — ~100k orders (2016–2018).

Required files (place in `data/` or provide `archive.zip`):

| File | Description |
|---|---|
| `olist_orders_dataset.csv` | Order status + timestamps |
| `olist_customers_dataset.csv` | Customer IDs and locations |
| `olist_order_items_dataset.csv` | Line items (price, freight, product) |
| `olist_order_payments_dataset.csv` | Payment details and amounts |
| `olist_geolocation_dataset.csv` | Zip-code-prefix → lat/lng lookup |
| `product_category_name_translation.csv` | (optional) PT → EN category names |

Note: product and seller files are included for future extensions but are not required for the core pipeline.

---

## Project structure

```
project/
├── README.md
├── requirements.txt
├── Colab.ipynb
├── dashboard/
│   ├── Customer Retention Analytics.jpeg
│   ├── Ecommerce_Churn_Analysis.pbix
│   └── Executive Dashboard.jpeg
├── data/
│   └── olist_*.csv
├── src/
│   └── preprocess_pipeline.py
└── output/
    ├── fact_orders.csv
    ├── dim_customers_rfm.csv
    ├── cohort_table.csv
    ├── geo_sales.csv
    └── kpi_summary.csv
```

---

## What the pipeline produces

- fact_orders: order-level table (revenue, items, customer location, valid-sale flag, date parts)
- dim_customers_rfm: customer-level RFM scores, rfm segment label, is_churned flag, CLV_historical and CLV_projected
- cohort_table: monthly cohort retention rates
- geo_sales: aggregated sales, AOV and churn by state (with representative lat/lng)
- kpi_summary: reference KPIs for dashboard sanity checks

---

## How RFM, churn and CLV are computed (summary)

- Recency: days since last order at a fixed snapshot date (end of dataset by default)
- Frequency: distinct orders per customer
- Monetary: total revenue per customer
- RFM scoring: quintiles (1–5) for each metric and mapped to segment labels
- Churn flag: `is_churned = True` when recency > `CHURN_WINDOW_DAYS` (default 180 days)
- CLV_historical: observed total revenue to date
- CLV_projected: Avg Order Value × Purchase Frequency (orders/yr) × 2-year horizon (set to zero for churned customers)

See `src/preprocess_pipeline.py` for exact formulas and implementation details.

---

## Power BI report

The Power BI file `dashboard/Ecommerce_Churn_Analysis.pbix` includes:
- KPI cards (Total Sales, Churn Rate, AOV, Total Customers, Avg CLV)
- Recency vs Frequency scatter, RFM segment CLV bar chart, and CLV treemap
- Cohort retention heatmap and decay curves
- Map of sales by Brazilian state
- Top customers table by CLV

---

## Run the pipeline

Quick (local):

```bash
pip install -r requirements.txt
python src/preprocess_pipeline.py --data_dir ./data --output_dir ./output
```

Or run `Colab.ipynb` in Google Colab and follow the instructions in the notebook.

---

## Configuration

Primary knobs in `src/preprocess_pipeline.py`:

| Variable | Default | Meaning |
|---|---|---|
| `CHURN_WINDOW_DAYS` | `180` | Days of inactivity after which a customer is considered churned |
| `VALID_ORDER_STATUSES` | `["delivered","shipped","invoiced","processing","approved"]` | Order statuses counted as valid sales |

---

## Important note on dashboard metrics

A visual review of the report screenshots revealed inconsistent churn figures between different tiles. That discrepancy typically indicates different filters/cohorts or a source aggregation mismatch. To align numbers, point all visuals to a single pre-aggregated customer-level view (for example `dim_customers_rfm` or a dedicated `customer_metrics_view`) and verify the cohort/time window used by each tile.

Suggested quick SQL check (run against your canonical customer view):

```sql
SELECT
  SUM(CASE WHEN is_churned = 1 THEN 1 ELSE 0 END) AS churned_customers,
  SUM(CASE WHEN is_churned = 0 THEN 1 ELSE 0 END) AS active_customers,
  COUNT(*) AS total_customers,
  SUM(CASE WHEN is_churned = 1 THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*),0) AS churn_rate
FROM dim_customers_rfm;
```

---

## Attribution and contributors

This repository is an individual analytics project by the repository owner (Viketh‑M). It uses the public Olist dataset and standard open-source tools (Python, pandas, Jupyter, Power BI). If you reuse parts of this work, please attribute the Olist dataset and follow its license terms.

---

## Contact

For questions or corrections, open an issue or contact the repository owner.
