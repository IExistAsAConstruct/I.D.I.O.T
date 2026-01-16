import os
from dotenv import main

from pymongo import MongoClient

main.load_dotenv()

DB_URI = os.getenv("DB_URI")

if not DB_URI:
    raise ValueError("DB_URI environment variable is not set.")

mongoClient = MongoClient(DB_URI)

try:
    mongoClient.admin.command("ping")  # Check if the connection is successful
    print("MongoDB connection successful.")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")
    raise

dbMembers = mongoClient["memberData"]
members = dbMembers["members"]
transactions = dbMembers["transactions"]

dbGuilds = mongoClient["guildData"]
guilds = dbGuilds["guilds"]

dbBotContent = mongoClient["botContent"]
bot_messages = dbBotContent["bot_messages"]

dbGambling = mongoClient["gamblingData"]
gambling_history = dbGambling["gambling_history"]