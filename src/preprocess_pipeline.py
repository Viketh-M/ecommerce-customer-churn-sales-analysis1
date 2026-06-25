"""
==========================================================================================
 E-COMMERCE CUSTOMER CHURN & SALES ANALYSIS — DATA PREPROCESSING PIPELINE
==========================================================================================
Dataset : Olist Brazilian E-Commerce Public Dataset (Kaggle)
Author  : Senior Data Analyst Team
Purpose : Clean raw Olist CSVs, engineer churn / RFM / CLV / cohort / geo features,
          and export a set of flat, Power-BI-ready tables.

OUTPUT FILES (written to ./output/):
    1. fact_orders.csv          -> one row per order   (grain: order)
    2. dim_customers_rfm.csv    -> one row per customer (grain: customer, RFM + CLV + churn)
    3. cohort_table.csv         -> cohort_month x cohort_index retention matrix
    4. geo_sales.csv            -> sales aggregated by Brazilian state (for map visual)
    5. kpi_summary.csv          -> single-row sanity-check KPI snapshot

These five tables are designed to be loaded directly into Power BI Desktop
(Get Data -> Text/CSV) and linked on `customer_unique_id` and `order_id`.

Run:
    python preprocess_pipeline.py --data_dir ./data --output_dir ./output

Or import and call `run_pipeline(data_dir, output_dir)` from a notebook / Colab cell.
==========================================================================================
"""

import argparse
import logging
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------------
# A customer who has not purchased again within CHURN_WINDOW_DAYS of their last
# purchase (measured from the dataset's "snapshot" / most-recent-order date) is
# flagged as churned. 180 days (~6 months) is a common e-commerce churn window;
# adjust to match your business cycle.
CHURN_WINDOW_DAYS = 180

# Only orders with these statuses are treated as completed, revenue-generating sales.
# "canceled" and "unavailable" orders are excluded from revenue/RFM/cohort calculations
# (but are kept in a flag for funnel/operational analysis if needed later).
VALID_ORDER_STATUSES = ["delivered", "shipped", "invoiced", "processing", "approved"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("olist_pipeline")


# ------------------------------------------------------------------------------------
# 1. LOAD
# ------------------------------------------------------------------------------------
def load_raw_data(data_dir: str) -> dict:
    """Load all required Olist CSVs into a dict of DataFrames."""
    log.info("Loading raw CSV files from '%s' ...", data_dir)

    files = {
        "orders": "olist_orders_dataset.csv",
        "customers": "olist_customers_dataset.csv",
        "items": "olist_order_items_dataset.csv",
        "payments": "olist_order_payments_dataset.csv",
        "products": "olist_products_dataset.csv",
        "category_translation": "product_category_name_translation.csv",
        "geolocation": "olist_geolocation_dataset.csv",
    }

    data = {}
    for key, filename in files.items():
        path = os.path.join(data_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Required file not found: {path}\n"
                f"Make sure the Olist dataset CSVs are unzipped into '{data_dir}'."
            )
        data[key] = pd.read_csv(path)
        log.info("  loaded %-12s -> %s rows", key, f"{len(data[key]):,}")

    return data


# ------------------------------------------------------------------------------------
# 2. CLEAN
# ------------------------------------------------------------------------------------
def clean_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """Parse date columns and drop structurally broken rows."""
    orders = orders.copy()

    date_cols = [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]
    for col in date_cols:
        orders[col] = pd.to_datetime(orders[col], errors="coerce")

    # A row with no purchase timestamp is unusable for time-based analysis - drop it.
    before = len(orders)
    orders = orders.dropna(subset=["order_purchase_timestamp"])
    log.info("clean_orders: dropped %d rows with missing purchase timestamp", before - len(orders))

    return orders


def clean_geolocation(geo: pd.DataFrame) -> pd.DataFrame:
    """
    The raw geolocation table has multiple lat/lng pairs per zip code prefix
    (many addresses share a prefix). Collapse to ONE representative
    (median) lat/lng per zip prefix so it can be safely joined 1:1 onto customers.
    """
    geo = geo.copy()
    geo["geolocation_zip_code_prefix"] = geo["geolocation_zip_code_prefix"].astype(str).str.zfill(5)

    geo_agg = (
        geo.groupby("geolocation_zip_code_prefix")
        .agg(lat=("geolocation_lat", "median"), lng=("geolocation_lng", "median"))
        .reset_index()
    )
    return geo_agg


def clean_items_and_payments(items: pd.DataFrame, payments: pd.DataFrame) -> pd.DataFrame:
    """
    Build one revenue figure per order. We combine:
      - item-level (price + freight_value) summed per order, AND
      - payment-level (payment_value) summed per order
    and reconcile by preferring the payments total (it reflects what the customer
    actually paid, including installments/vouchers) but falling back to the
    item-level total when no payment record exists.
    """
    items = items.copy()
    payments = payments.copy()

    items["price"] = pd.to_numeric(items["price"], errors="coerce").fillna(0)
    items["freight_value"] = pd.to_numeric(items["freight_value"], errors="coerce").fillna(0)

    items_per_order = (
        items.groupby("order_id")
        .agg(
            items_total=("price", "sum"),
            freight_total=("freight_value", "sum"),
            n_items=("order_item_id", "count"),
        )
        .reset_index()
    )
    items_per_order["item_revenue"] = items_per_order["items_total"] + items_per_order["freight_total"]

    payments["payment_value"] = pd.to_numeric(payments["payment_value"], errors="coerce").fillna(0)
    payments_per_order = payments.groupby("order_id")["payment_value"].sum().reset_index()
    payments_per_order.columns = ["order_id", "payment_revenue"]

    revenue = items_per_order.merge(payments_per_order, on="order_id", how="outer")
    revenue["item_revenue"] = revenue["item_revenue"].fillna(0)
    revenue["payment_revenue"] = revenue["payment_revenue"].fillna(0)
    revenue["n_items"] = revenue["n_items"].fillna(0)

    # Prefer actual amount paid; fall back to item+freight total if no payment row.
    revenue["order_revenue"] = np.where(
        revenue["payment_revenue"] > 0, revenue["payment_revenue"], revenue["item_revenue"]
    )

    return revenue[["order_id", "order_revenue", "n_items"]]


# ------------------------------------------------------------------------------------
# 3. BUILD FACT_ORDERS
# ------------------------------------------------------------------------------------
def build_fact_orders(data: dict) -> pd.DataFrame:
    """Join orders -> customers -> revenue -> geolocation into one order-grain table."""
    orders = clean_orders(data["orders"])
    revenue = clean_items_and_payments(data["items"], data["payments"])
    customers = data["customers"].copy()
    geo_agg = clean_geolocation(data["geolocation"])

    customers["customer_zip_code_prefix"] = (
        customers["customer_zip_code_prefix"].astype(str).str.zfill(5)
    )

    fact = orders.merge(customers, on="customer_id", how="left")
    fact = fact.merge(revenue, on="order_id", how="left")
    fact = fact.merge(
        geo_agg, left_on="customer_zip_code_prefix", right_on="geolocation_zip_code_prefix", how="left"
    )

    # Handle missing values explicitly (no silent NaNs in the output file).
    fact["order_revenue"] = fact["order_revenue"].fillna(0)
    fact["n_items"] = fact["n_items"].fillna(0).astype(int)
    fact["customer_city"] = fact["customer_city"].fillna("unknown")
    fact["customer_state"] = fact["customer_state"].fillna("unknown")
    fact["lat"] = fact["lat"].fillna(np.nan)  # left as NaN -> Power BI will just skip unmapped points
    fact["lng"] = fact["lng"].fillna(np.nan)

    # Flag valid (revenue-generating) vs. canceled/unavailable orders.
    fact["is_valid_sale"] = fact["order_status"].isin(VALID_ORDER_STATUSES)

    # Useful date parts for Power BI date hierarchies / cohort calcs.
    fact["order_year_month"] = fact["order_purchase_timestamp"].dt.to_period("M").astype(str)
    fact["order_year"] = fact["order_purchase_timestamp"].dt.year
    fact["order_month"] = fact["order_purchase_timestamp"].dt.month

    cols = [
        "order_id",
        "customer_id",
        "customer_unique_id",
        "order_status",
        "is_valid_sale",
        "order_purchase_timestamp",
        "order_year_month",
        "order_year",
        "order_month",
        "order_revenue",
        "n_items",
        "customer_city",
        "customer_state",
        "lat",
        "lng",
    ]
    return fact[cols]


# ------------------------------------------------------------------------------------
# 4. RFM SEGMENTATION + CLV + CHURN  (CUSTOMER GRAIN)
# ------------------------------------------------------------------------------------
def rfm_segment_label(row) -> str:
    """Map an (R,F,M) score triple (1-5 each, 5=best) to a human-readable segment.
    This follows the widely-used RFM segment heuristic (Champions / Loyal / At Risk / etc.)."""
    r, f, m = row["R_score"], row["F_score"], row["M_score"]

    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if r >= 3 and f >= 3 and m >= 3:
        return "Loyal Customers"
    if r >= 4 and f <= 2:
        return "New / Promising"
    if r <= 2 and f >= 4 and m >= 4:
        return "At Risk (High Value)"
    if r <= 2 and f >= 3:
        return "At Risk"
    if r <= 2 and f <= 2 and m <= 2:
        return "Lost / Hibernating"
    return "Needs Attention"


def compute_rfm_clv_churn(fact_orders: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse the order-grain fact table to one row per customer with:
      - Recency, Frequency, Monetary + 1-5 scores (quintiles)
      - RFM segment label
      - Historical CLV (= total monetary value to date)
      - Projected CLV (simple formula: AOV x purchase frequency rate x avg lifespan)
      - Churn flag (no purchase within CHURN_WINDOW_DAYS of the dataset snapshot date)
    """
    sales = fact_orders[fact_orders["is_valid_sale"]].copy()

    # The "snapshot" date = the most recent purchase in the whole dataset.
    # All recency windows are measured back from this single reference point,
    # since the dataset itself is historical (not live).
    snapshot_date = sales["order_purchase_timestamp"].max()
    log.info("compute_rfm: using snapshot_date = %s", snapshot_date.date())

    cust = (
        sales.groupby("customer_unique_id")
        .agg(
            first_purchase_date=("order_purchase_timestamp", "min"),
            last_purchase_date=("order_purchase_timestamp", "max"),
            frequency=("order_id", "nunique"),
            monetary=("order_revenue", "sum"),
            customer_state=("customer_state", "first"),
            customer_city=("customer_city", "first"),
        )
        .reset_index()
    )

    cust["recency_days"] = (snapshot_date - cust["last_purchase_date"]).dt.days
    cust["tenure_days"] = (cust["last_purchase_date"] - cust["first_purchase_date"]).dt.days
    cust["avg_order_value"] = cust["monetary"] / cust["frequency"]

    # --- RFM quintile scoring (1 = worst, 5 = best) ---
    # Recency: LOWER days-since-last-purchase is better -> reverse the rank.
    cust["R_score"] = pd.qcut(cust["recency_days"].rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    cust["F_score"] = pd.qcut(cust["frequency"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    cust["M_score"] = pd.qcut(cust["monetary"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    cust["RFM_score"] = cust["R_score"].astype(str) + cust["F_score"].astype(str) + cust["M_score"].astype(str)
    cust["RFM_segment"] = cust.apply(rfm_segment_label, axis=1)

    # --- Churn flag ---
    cust["is_churned"] = cust["recency_days"] > CHURN_WINDOW_DAYS

    # --- CLV ---
    # Historical CLV: total revenue generated to date (ground truth, no assumptions).
    cust["CLV_historical"] = cust["monetary"]

    # Projected CLV (simple, transparent formula commonly used as a first-pass estimate):
    #   CLV = Avg Order Value  x  Purchase Frequency (orders / year of tenure)  x  Avg Customer Lifespan (years)
    # We assume a 2-year forward lifespan for an "active" (non-churned) customer, and
    # 0 forward value for a churned one (their projected future revenue is zero).
    # Floor the observation window at 1 year. Without this floor, a customer with
    # a single order and near-zero tenure (first purchase == last purchase) would
    # have their purchase rate divided by a near-zero denominator, producing an
    # absurd "365 orders/year" extrapolation. Flooring at 1 year means: "we have
    # at most 1 data point per year of observation" for low-tenure customers,
    # which is the conservative, defensible assumption.
    observed_years = (cust["tenure_days"] / 365.25).clip(lower=1.0)
    purchase_freq_per_year = cust["frequency"] / observed_years
    assumed_forward_lifespan_years = 2
    cust["CLV_projected"] = np.where(
        cust["is_churned"],
        0.0,
        cust["avg_order_value"] * purchase_freq_per_year * assumed_forward_lifespan_years,
    )
    cust["CLV_projected"] = cust["CLV_projected"].round(2)
    cust["CLV_historical"] = cust["CLV_historical"].round(2)
    cust["avg_order_value"] = cust["avg_order_value"].round(2)

    return cust


# ------------------------------------------------------------------------------------
# 5. COHORT TABLE
# ------------------------------------------------------------------------------------
def compute_cohort_table(fact_orders: pd.DataFrame) -> pd.DataFrame:
    """
    Classic monthly retention cohort:
      - cohort_month     = the calendar month of a customer's FIRST purchase
      - order_month      = the calendar month of any given order
      - cohort_index     = number of months between cohort_month and order_month (0,1,2,...)
    Output is a long table: cohort_month | cohort_index | n_customers | cohort_size | retention_rate
    This long format drops straight into a Power BI matrix visual (rows=cohort_month, cols=cohort_index).
    """
    sales = fact_orders[fact_orders["is_valid_sale"]].copy()
    sales["order_month_period"] = sales["order_purchase_timestamp"].dt.to_period("M")

    first_purchase = (
        sales.groupby("customer_unique_id")["order_month_period"].min().rename("cohort_month_period")
    )
    sales = sales.join(first_purchase, on="customer_unique_id")

    sales["cohort_index"] = (
        (sales["order_month_period"].dt.year - sales["cohort_month_period"].dt.year) * 12
        + (sales["order_month_period"].dt.month - sales["cohort_month_period"].dt.month)
    )

    cohort_counts = (
        sales.groupby(["cohort_month_period", "cohort_index"])["customer_unique_id"]
        .nunique()
        .reset_index(name="n_customers")
    )

    cohort_sizes = cohort_counts[cohort_counts["cohort_index"] == 0][
        ["cohort_month_period", "n_customers"]
    ].rename(columns={"n_customers": "cohort_size"})

    cohort = cohort_counts.merge(cohort_sizes, on="cohort_month_period", how="left")
    cohort["retention_rate"] = (cohort["n_customers"] / cohort["cohort_size"]).round(4)
    cohort["cohort_month"] = cohort["cohort_month_period"].astype(str)
    cohort = cohort.drop(columns=["cohort_month_period"])

    return cohort[["cohort_month", "cohort_index", "n_customers", "cohort_size", "retention_rate"]]


# ------------------------------------------------------------------------------------
# 6. GEO AGGREGATION (FOR MAP VISUAL)
# ------------------------------------------------------------------------------------
def compute_geo_sales(fact_orders: pd.DataFrame, customer_rfm: pd.DataFrame) -> pd.DataFrame:
    """Aggregate sales, order count, customer count and churn rate by Brazilian state."""
    sales = fact_orders[fact_orders["is_valid_sale"]].copy()

    geo = (
        sales.groupby("customer_state")
        .agg(
            total_sales=("order_revenue", "sum"),
            total_orders=("order_id", "nunique"),
            unique_customers=("customer_unique_id", "nunique"),
            avg_lat=("lat", "median"),
            avg_lng=("lng", "median"),
        )
        .reset_index()
    )
    geo["total_sales"] = geo["total_sales"].round(2)
    geo["avg_order_value"] = (geo["total_sales"] / geo["total_orders"]).round(2)

    churn_by_state = (
        customer_rfm.groupby("customer_state")["is_churned"].mean().reset_index(name="churn_rate")
    )
    churn_by_state["churn_rate"] = churn_by_state["churn_rate"].round(4)

    geo = geo.merge(churn_by_state, on="customer_state", how="left")
    return geo.sort_values("total_sales", ascending=False)


# ------------------------------------------------------------------------------------
# 7. KPI SUMMARY (SANITY-CHECK SNAPSHOT)
# ------------------------------------------------------------------------------------
def compute_kpi_summary(fact_orders: pd.DataFrame, customer_rfm: pd.DataFrame) -> pd.DataFrame:
    sales = fact_orders[fact_orders["is_valid_sale"]]

    kpis = {
        "total_sales": round(sales["order_revenue"].sum(), 2),
        "total_orders": sales["order_id"].nunique(),
        "unique_customers": sales["customer_unique_id"].nunique(),
        "average_order_value": round(sales["order_revenue"].sum() / sales["order_id"].nunique(), 2),
        "churn_rate": round(customer_rfm["is_churned"].mean(), 4),
        "avg_clv_historical": round(customer_rfm["CLV_historical"].mean(), 2),
        "avg_clv_projected": round(customer_rfm["CLV_projected"].mean(), 2),
        "churn_window_days": CHURN_WINDOW_DAYS,
    }
    return pd.DataFrame(list(kpis.items()), columns=["metric", "value"])


# ------------------------------------------------------------------------------------
# 8. MAIN PIPELINE ENTRY POINT
# ------------------------------------------------------------------------------------
def run_pipeline(data_dir: str = "./data", output_dir: str = "./output") -> dict:
    os.makedirs(output_dir, exist_ok=True)

    data = load_raw_data(data_dir)

    log.info("Building fact_orders ...")
    fact_orders = build_fact_orders(data)

    log.info("Computing RFM segmentation, CLV and churn flag ...")
    customer_rfm = compute_rfm_clv_churn(fact_orders)

    log.info("Computing cohort retention table ...")
    cohort_table = compute_cohort_table(fact_orders)

    log.info("Computing geo sales aggregation ...")
    geo_sales = compute_geo_sales(fact_orders, customer_rfm)

    log.info("Computing KPI summary ...")
    kpi_summary = compute_kpi_summary(fact_orders, customer_rfm)

    outputs = {
        "fact_orders.csv": fact_orders,
        "dim_customers_rfm.csv": customer_rfm,
        "cohort_table.csv": cohort_table,
        "geo_sales.csv": geo_sales,
        "kpi_summary.csv": kpi_summary,
    }

    for filename, df in outputs.items():
        path = os.path.join(output_dir, filename)
        df.to_csv(path, index=False)
        log.info("  wrote %-22s -> %s rows, %s cols", filename, f"{len(df):,}", df.shape[1])

    log.info("Pipeline complete. Files are in '%s'.", output_dir)
    return outputs


# ------------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Olist e-commerce churn/CLV/RFM preprocessing pipeline")
    parser.add_argument("--data_dir", default="./data", help="Folder containing the raw Olist CSV files")
    parser.add_argument("--output_dir", default="./output", help="Folder to write the cleaned output CSVs")
    args = parser.parse_args()

    try:
        run_pipeline(args.data_dir, args.output_dir)
    except FileNotFoundError as e:
        log.error(str(e))
        sys.exit(1)
