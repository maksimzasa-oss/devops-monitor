import logging
import os
import time

import pandas as pd
import requests
from influxdb_client import InfluxDBClient
from sklearn.ensemble import IsolationForest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
TOKEN = os.environ["INFLUX_TOKEN"]
ORG = os.environ["INFLUX_ORG"]
BUCKET = os.environ["INFLUX_BUCKET"]
NOTIFIER_URL = os.getenv("NOTIFIER_URL", "http://notifier:8080/alert")
TARGET = os.environ["TARGET_CONTAINER"]

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "10"))
HISTORY_MIN = int(os.getenv("HISTORY_MIN", "120"))
WINDOW_MIN = int(os.getenv("WINDOW_MIN", "2"))
MIN_TRAIN_ROWS = int(os.getenv("MIN_TRAIN_ROWS", "5"))
ANOMALY_SHARE = float(os.getenv("ANOMALY_SHARE", "0.6"))
COOLDOWN = int(os.getenv("COOLDOWN_SEC", "300"))

FEATURES = ["cpu", "ram", "disk", "procs", "ram_delta"]

FLUX = """
from(bucket: "{bucket}")
  |> range(start: -{minutes}m)
  |> filter(fn: (r) => r._measurement == "system")
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
"""


def load_data(client):
    df = client.query_api().query_data_frame(
        FLUX.format(bucket=BUCKET, minutes=HISTORY_MIN)
    )
    if isinstance(df, list):
        df = pd.concat(df) if df else pd.DataFrame()
    if df.empty:
        return df
    df = df.sort_values("_time").reset_index(drop=True)
    df["ram_delta"] = df["ram"].diff().fillna(0)
    return df[["_time"] + FEATURES]


def check(df):
    if df.empty:
        return None

    # Ограничитель (порог) полностью отключен, чтобы дать памяти вырасти.
    # Работает только чистый анализ аномалий ИИ (Isolation Forest).

    window = df.tail(WINDOW_MIN)
    train = df.iloc[:-WINDOW_MIN]
    if len(train) < MIN_TRAIN_ROWS:
        return None

    model = IsolationForest(n_estimators=100, contamination=0.02, random_state=42)
    model.fit(train[FEATURES])
    flags = model.predict(window[FEATURES])
    share = float((flags == -1).mean())
    return share if share >= ANOMALY_SHARE else None


def send_alert(share, last):
    payload = {
        "container": TARGET,
        "reason": "Anomaly in metrics",
        "share": round(share, 2),
        "ram": round(float(last["ram"]), 1),
        "cpu": round(float(last["cpu"]), 1),
    }
    requests.post(NOTIFIER_URL, json=payload, timeout=30).raise_for_status()


def main():
    client = InfluxDBClient(url=URL, token=TOKEN, org=ORG)
    last_alert = 0.0
    while True:
        try:
            df = load_data(client)
            if not df.empty:
                share = check(df)
                if share is not None and time.time() - last_alert > COOLDOWN:
                    send_alert(share, df.iloc[-1])
                    last_alert = time.time()
                    logging.warning("🚨 ANOMALY DETECTED! share=%.2f, alert sent", share)
                else:
                    logging.info("rows=%d, state ok or cooldown", len(df))
        except Exception as exc:
            logging.warning("check failed: %s", exc)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
