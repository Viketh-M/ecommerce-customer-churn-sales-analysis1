# E-Commerce Customer Churn & Sales Analysis

A complete, reproducible pipeline that turns the raw **Olist Brazilian
E-Commerce Public Dataset** into a Power BI dashboard covering sales KPIs,
customer churn, RFM segmentation, Customer Lifetime Value (CLV), cohort
retention, and geographic sales distribution.

---

## 1. Purpose

E-commerce businesses lose revenue quietly: customers who don't come back
rarely announce it. This project answers three core business questions:

1. **How healthy is the business overall?** (total sales, average order
   value, churn rate)
2. **Which customers are most valuable, and which are at risk of leaving?**
   (RFM segmentation + CLV)
3. **When, and how fast, do customers stop buying — and does it differ by
   signup cohort or region?** (cohort retention analysis + geographic sales map)

The output is a set of clean, analysis-ready tables plus a step-by-step guide
to assembling them into a Power BI dashboard.

---

## 2. Data source

**Olist Brazilian E-Commerce Public Dataset** — ~100k orders made on the
Olist marketplace between 2016 and 2018, across multiple Brazilian
marketplaces. Originally published on Kaggle by Olist.

Files used (place these in `data/`, already done if you're using the
provided `archive.zip`):

| File | Description |
|---|---|
| `olist_orders_dataset.csv` | Order status + key timestamps |
| `olist_customers_dataset.csv` | Customer ID, location |
| `olist_order_items_dataset.csv` | Line items: price, freight, product, seller |
| `olist_order_payments_dataset.csv` | Payment method, installments, amount paid |
| `olist_products_dataset.csv` | Product category, dimensions |
| `olist_sellers_dataset.csv` | Seller location |
| `olist_geolocation_dataset.csv` | Zip-code-prefix -> lat/lng lookup |
| `product_category_name_translation.csv` | PT -> EN category names |

> Note: `olist_products_dataset.csv`, `olist_sellers_dataset.csv`, and
> `product_category_name_translation.csv` are loaded for completeness/future
> extension (e.g. category-level analysis) but are not required by the
> current KPI/churn/cohort/map pipeline, which only needs orders, customers,
> items, payments, and geolocation.

---

## 3. Project structure

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

## 4. Preprocessing steps (what `preprocess_pipeline.py` actually does)

1. **Load** all raw CSVs with explicit dtypes where it matters (zip codes as
   zero-padded strings, not numbers).
2. **Clean dates**: every date column is parsed with `pd.to_datetime`;
   orders missing a purchase timestamp (unusable for time-based analysis) are
   dropped, with the drop count logged.
3. **Resolve revenue per order**: item price + freight is summed per order
   as a fallback, but the actual `payment_value` total is preferred when
   available (it reflects installments/vouchers actually paid).
4. **Collapse geolocation**: the raw geolocation table has many lat/lng rows
   per zip-code-prefix; these are reduced to one median lat/lng per prefix so
   they join 1:1 onto customers.
5. **Build `fact_orders`** (order grain): one row per order, with revenue,
   item count, customer location, lat/lng, valid-sale flag, and date parts.
6. **Build `dim_customers_rfm`** (customer grain):
   - **RFM**: Recency (days since last order, from a fixed snapshot date =
     the most recent order in the dataset), Frequency (distinct orders), and
     Monetary (total revenue) are each scored into quintiles (1-5, 5 = best)
     and combined into a segment label (Champions, Loyal Customers, At Risk,
     Lost/Hibernating, etc.) — see `rfm_segment_label()` for the exact rule set.
   - **Churn flag**: a customer is flagged `is_churned = True` if their
     recency exceeds `CHURN_WINDOW_DAYS` (default: 180 days / ~6 months,
     configurable at the top of the script).
   - **CLV**: `CLV_historical` is actual total revenue to date (ground
     truth). `CLV_projected` is a transparent, auditable estimate:
     `Avg Order Value × Purchase Frequency (orders/yr) × 2-year forward
     lifespan`, zeroed out for already-churned customers. The "observed
     years" denominator is floored at 1 year specifically to prevent
     single-order customers (near-zero tenure) from producing an absurd
     extrapolated purchase rate.
7. **Build `cohort_table`**: classic monthly cohort retention — group
   customers by the calendar month of their *first* purchase
   (`cohort_month`), then for every subsequent order compute how many months
   later it occurred (`cohort_index`), and express that count as a
   `retention_rate` relative to the original cohort size.
8. **Build `geo_sales`**: sales, orders, customers, AOV, and churn rate
   aggregated by Brazilian state, with a representative lat/lng per state for
   mapping.
9. **Build `kpi_summary`**: a single reference table (total sales, churn
   rate, AOV, avg CLV, etc.) — useful for sanity-checking the dashboard's
   numbers match the underlying data.

---

## 4b. Dashboard preview

![Executive Dashboard](dashboard/Executive%20Dashboard.jpeg)
![Customer Retention Analytics](dashboard/Customer%20Retention%20Analytics.jpeg)

---

## 5. Power BI dashboard — what it shows

See `dashboard/Ecommerce_Churn_Analysis.pbix` for the built report.
Summary of what's delivered:

- **KPI cards**: Total Sales, Churn Rate, Average Order Value, Total
  Customers, Average CLV.
- **Cohort analysis**: a retention heatmap (matrix visual) showing, for each
  monthly signup cohort, what percentage of customers were still buying N
  months later — plus an overlaid line-chart view of decay curves.
- **Map visual**: bubble (or filled choropleth) map of Brazil showing total
  sales by state, with order count / AOV / churn rate in tooltips.
- Optional extras: RFM segment bar chart, recency-frequency-monetary bubble
  scatter, and a monthly sales trend line.

---

## 6. How to run (Google Colab)

1. Open **`Colab.ipynb`** in Google Colab
   (`File -> Upload notebook`, or drag it into https://colab.research.google.com).
2. Run the cells top to bottom:
   - Cell 1 confirms `pandas`/`numpy` are available.
   - Cell 2 prompts you to upload the raw Olist data — upload either the
     original Kaggle `archive.zip` or the individual `olist_*.csv` files.
   - Cell 3 prompts you to upload `preprocess_pipeline.py` (from this
     project's `src/` folder) if it isn't already in the Colab session.
   - Cell 4 runs the pipeline and prints the KPI summary.
   - Cell 5 (optional) renders quick sanity-check charts directly in Colab.
   - Cell 6 zips the `output/` folder and downloads it to your computer.
3. Unzip the downloaded file and load the 4 main CSVs
   (`fact_orders.csv`, `dim_customers_rfm.csv`, `cohort_table.csv`,
   `geo_sales.csv`) into Power BI Desktop.

## 6b. How to run (local machine instead of Colab)

```bash
pip install -r requirements.txt
python src/preprocess_pipeline.py --data_dir ./data --output_dir ./output
```

Or from a notebook / Python shell:

```python
from src.preprocess_pipeline import run_pipeline
outputs = run_pipeline(data_dir="data", output_dir="output")
```

---

## 7. Configuration knobs

All at the top of `src/preprocess_pipeline.py`:

| Variable | Default | Meaning |
|---|---|---|
| `CHURN_WINDOW_DAYS` | `180` | Days of inactivity after which a customer is considered churned |
| `VALID_ORDER_STATUSES` | `["delivered","shipped","invoiced","processing","approved"]` | Order statuses counted as real sales (excludes `canceled`, `unavailable`, `created`) |

Adjust these to match your business's actual churn cycle and order-status
definitions, then re-run the pipeline.

---

## 8. Known limitations / assumptions

- The dataset is **historical and static** (2016-2018), so "churn" is
  measured relative to a fixed snapshot date (the last order in the dataset),
  not a live "today." In a production setting, replace `snapshot_date` with
  `datetime.now()`.
- `CLV_projected` is a simple, transparent heuristic (not a probabilistic
  model like BG/NBD or Pareto/NBD). It's meant as a readable first-pass
  estimate, not a precision forecast — swap in a proper CLV model if the
  business needs forecast accuracy.
- Geolocation lat/lng is approximated at the zip-code-prefix level (median of
  all points sharing that prefix), not exact addresses.
