#!/usr/bin/env python3
"""Run inside a Kernel Pod after installing psycopg, PyMySQL, pymongo and elasticsearch."""
import os

import psycopg
import pymysql
from elasticsearch import Elasticsearch
from pymongo import MongoClient


with psycopg.connect(
    host=os.getenv("POSTGRES_PROXY_HOST", "postgres-proxy"),
    port=5432,
    dbname="poc",
    user="gateway",
    password=os.getenv("POSTGRES_PROXY_PASSWORD", "mock-postgres-password"),
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("select id, name, score from demo_items order by id")
        assert cursor.fetchall() == [(1, "alpha", 91), (2, "beta", 87)]
print("PASS psycopg -> PgBouncer -> PostgreSQL")


connection = pymysql.connect(
    host=os.getenv("MYSQL_PROXY_HOST", "mysql-proxy"),
    port=6033,
    database="poc",
    user="gateway",
    password=os.getenv("MYSQL_PROXY_PASSWORD", "mock-mysql-password"),
)
with connection.cursor() as cursor:
    cursor.execute("select id, name, score from demo_items order by id")
    assert cursor.fetchall() == ((1, "alpha", 91), (2, "beta", 87))
connection.close()
print("PASS PyMySQL -> ProxySQL -> MySQL")


mongo = MongoClient(
    os.getenv("MONGO_PROXY_URI", "mongodb://root:mock-mongo-password@mongo-proxy:27017/?authSource=admin"),
    serverSelectionTimeoutMS=5000,
)
documents = list(mongo.poc.demo_items.find({}, {"name": 1, "score": 1}).sort("score", -1))
assert [(item["name"], item["score"]) for item in documents] == [("alpha", 91), ("beta", 87)]
print("PASS PyMongo -> HAProxy -> MongoDB")


elastic = Elasticsearch(os.getenv("ELASTICSEARCH_PROXY_URL", "http://elasticsearch-proxy:9200"))
hits = elastic.search(index="demo-items", query={"match_all": {}}, size=10)["hits"]["hits"]
assert sorted((item["_source"]["name"], item["_source"]["score"]) for item in hits) == [
    ("alpha", 91),
    ("beta", 87),
]
print("PASS Elasticsearch client -> Nginx -> Elasticsearch")
