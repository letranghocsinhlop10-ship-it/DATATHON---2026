#DOC LIBRARY 
import pandas as pd
import numpy as np 
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 140)
#DOC LOAD DATA
customers = pd.read_csv("customers.csv")
geography = pd.read_csv("geography.csv")
inventory = pd.read_csv("inventory.csv")
order_items = pd.read_csv("order_items.csv")
orders = pd.read_csv("orders.csv")
payments = pd.read_csv("payments.csv")
products = pd.read_csv("products.csv")
promotions = pd.read_csv("promotions.csv")
returns = pd.read_csv("returns.csv")
reviews = pd.read_csv("reviews.csv")
sales = pd.read_csv("sales.csv")
sample_submission = pd.read_csv("sample_submission.csv")
shipments = pd.read_csv("shipments.csv")
web_traffic = pd.read_csv("web_traffic.csv")
# DOI TEXT THANH DATETIME
customers ["signup_date"] = pd.to_datetime(customers["signup_date"])
inventory ["snapshot_date"] = pd.to_datetime(inventory["snapshot_date"])
orders ["order_date"] = pd.to_datetime(orders["order_date"])
promotions ["start_date"] = pd.to_datetime(promotions["start_date"])
promotions ["end_date"] = pd.to_datetime(promotions["end_date"])
returns ["return_date"] = pd.to_datetime(returns["return_date"])
reviews ["review_date"] = pd.to_datetime(reviews["review_date"])
shipments ["ship_date"] = pd.to_datetime(shipments["ship_date"])
shipments ["delivery_date"] = pd.to_datetime(shipments["delivery_date"])
# ANSWER QUESTIONS
# inter - ofder gap
question1 = orders.sort_values(by = ["customer_id", "order_id"]).copy()
question1["prev_date"] = question1.groupby("customer_id")["order_date"].shift(1)
question1["gap days"] = (question1["order_date"] - question1["prev_date"]).dt.days
median_gap = question1["gap days"].dropna().median()
print("Median gap days between orders:", median_gap)
# segmentation - phân khúc khách hàng 
question2 = products.copy()
question2 ["gross margin"] = question2["price"] - question2["cogs"]/question2["price"]
question2 ["gross margin average"] = question2. groupby("segment")["gross margin"].mean()
print(question2["gross margin average"])
# reason for returns - products - products category
question3 = returns.merge(products[["product_id", "category"]], on = "product_id", how = "left")
question3["category"] = question3[question3["category"] == "Streetwear"]["return_reason"].value_counts().idxmax()
print(question3["category"])
# Bounce_rate - web traffic
mean_bouce_rate = web_traffic.groupby("traffic_source")["bounce_rate"].mean().idxmin()
print("Mean bounce rate by traffic source:")
print(mean_bouce_rate)
# question 5 - percentage of orders with promotions
question5 = order_items["promo_id"].notna().mean() * 100
print(question5)
# question 6 - so don trung binh cua 1 khach hang
question6 = customers[customers["age_group"].notna()][["customer_id", "age_group"]]
orders_age = orders.merge(question6, on = "customer_id", how = "inner")
order_per_group = orders_age.groupby("age_group")["order_id"].nunique()
question6_result = order_per_group / customers["age_group"].value_counts()
print(question6_result)