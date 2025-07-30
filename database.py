import os
from dotenv import main

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

main.load_dotenv()

mongoClient = MongoClient(os.getenv("DB_URI"), server_api=ServerApi('1'))
dbMembers = mongoClient["memberData"]
members = dbMembers["members"]
transanctions = dbMembers["transactions"]