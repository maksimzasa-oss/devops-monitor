import logging
import os
import time

import psutil
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
TOKEN = os.environ["INFLUX_TOKEN"]
ORG = os.environ["INFLUX_ORG"]
BUCKET = os.environ["INFLUX_BUCKET"]
HOST = os.getenv("HOST_NAME", "local")
INTERVAL = int(os.getenv("COLLECT_INTERVAL", "10"))


def collect():
    return {
        "cpu": psutil.cpu_percent(interval=1),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent,
        "procs": len(psutil.pids()),
    }


def connect():
    client = InfluxDBClient(url=URL, token=TOKEN, org=ORG)
    return client.write_api(write_options=SYNCHRONOUS)


def main():
    write_api = None
    while True:
        try:
            if write_api is None:
                write_api = connect()
            metrics = collect()
            point = Point("system").tag("host", HOST)
            for name, value in metrics.items():
                point = point.field(name, float(value))
            write_api.write(bucket=BUCKET, record=point)
            logging.info("sent: %s", metrics)
        except Exception as exc:
            logging.warning("write failed, will retry: %s", exc)
            write_api = None
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
