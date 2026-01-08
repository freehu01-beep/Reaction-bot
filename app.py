import os, random, asyncio
from datetime import date
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, UserIsBlocked

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
BOT_USERNAME = os.getenv("BOT_USERNAME")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))
LUVSMM_API_KEY = os.getenv("LUVSMM_API_KEY")

# ================= DB =================
mongo = MongoClient(MONGO_URL)
db = mongo.MultiReactionBot
users = db.users
projects = db.projects
promo_tokens = db.promo_tokens
reacted_posts = db.reacted_posts

# ================= BOT =================
bot = Client("multi_reaction_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ================= HELPERS =================
def get_user(uid):
    u = users.find_one({"_id": uid})
    if not u:
        users.insert_one({"_id": uid, "credits": 20, "ref_by": None, "referrals": 0})
        u = users.find_one({"_id": uid})
    return u

def reset_daily(project):
    today = str(date.today())
    if project.get("last_reset") != today:
        projects.update_one(
            {"_id": project["_id"]},
            {"$set": {"used_today": 0, "last_reset": today}}
        )
        project["used_today"] = 0
    return project

def luvsmm_react(post_link, quantity, reaction):
    import requests
    return requests.post(
        "https://luvsmm.com/api/v2",
        data={
            "key": LUVSMM_API_KEY,
            "action": "add",
            "service": 123,  # YOUR REACTION SERVICE ID
            "link": post_link,
            "quantity": quantity,
            "reaction": reaction
        }
    ).json()

# ================= START + REFERRAL =================
@bot.on_message(filters.command("start"))
async def start(c, m):
    uid = m.from_user.id
    args = m.text.split()
    user = users.find_one({"_id": uid})

    if not user:
        users.insert_one({"_id": uid, "credits": 20, "ref_by": None, "referrals": 0})
        if len(args) > 1:
            try:
                ref = int(args[1])
                if ref != uid and users.find_one({"_id": ref}):
                    users.update_one({"_id": uid}, {"$set": {"ref_by": ref}})
                    users.update_one({"_id": ref}, {"$inc": {"credits": 20, "referrals": 1}})
                    users.update_one({"_id": uid}, {"$inc": {"credits": 20}})
            except:
                pass

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ADD PROJECT", callback_data="add_proj")],
        [InlineKeyboardButton("⏸ Pause", callback_data="pause"),
         InlineKeyboardButton("▶️ Resume", callback_data="resume")],
        [InlineKeyboardButton("⚙️ Change Reactions/Post", callback_data="edit_qty")]
    ])
    await m.reply("🤖 Welcome to Multi Reactions Bot", reply_markup=kb)

# ================= ADD PROJECT =================
@bot.on_callback_query(filters.regex("^add_proj$"))
async def add_project(c, q):
    projects.delete_many({"owner": q.from_user.id, "status": "pending"})
    projects.insert_one({
        "owner": q.from_user.id,
        "status": "pending"
    })
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("10", callback_data="qty_10"),
         InlineKeyboardButton("20", callback_data="qty_20")],
        [InlineKeyboardButton("30", callback_data="qty_30"),
         InlineKeyboardButton("50", callback_data="qty_50")]
    ])
    await q.message.reply("Select reactions per post:", reply_markup=kb)

@bot.on_callback_query(filters.regex("^qty_"))
async def save_qty(c, q):
    qty = int(q.data.split("_")[1])
    projects.update_one(
        {"owner": q.from_user.id, "status": "pending"},
        {"$set": {
            "per_post": qty,
            "reactions": ["❤️", "🔥", "😍", "👍"],
            "status": "active",
            "daily_limit": 500,
            "used_today": 0,
            "last_reset": str(date.today())
        }}
    )
    await q.message.reply(f"✅ Project activated with {qty} reactions/post")

# ================= EDIT QTY =================
@bot.on_callback_query(filters.regex("^edit_qty$"))
async def edit_qty(c, q):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("10", callback_data="set_10"),
         InlineKeyboardButton("20", callback_data="set_20")],
        [InlineKeyboardButton("30", callback_data="set_30"),
         InlineKeyboardButton("50", callback_data="set_50")]
    ])
    await q.message.reply("Select new reactions/post:", reply_markup=kb)

@bot.on_callback_query(filters.regex("^set_"))
async def set_qty(c, q):
    qty = int(q.data.split("_")[1])
    projects.update_one(
        {"owner": q.from_user.id},
        {"$set": {"per_post": qty}}
    )
    await q.message.reply(f"✅ Updated to {qty} reactions/post")

# ================= PAUSE / RESUME =================
@bot.on_callback_query(filters.regex("^pause$"))
async def pause(c, q):
    projects.update_one({"owner": q.from_user.id}, {"$set": {"status": "paused"}})
    await q.message.reply("⏸ Project paused")

@bot.on_callback_query(filters.regex("^resume$"))
async def resume(c, q):
    projects.update_one({"owner": q.from_user.id}, {"$set": {"status": "active"}})
    await q.message.reply("▶️ Project resumed")

# ================= AUTO CHANNEL LISTENER =================
@bot.on_message(filters.channel)
async def listener(c, m):
    project = projects.find_one({"channel_id": m.chat.id, "status": "active"})
    if not project:
        return

    key = f"{m.chat.id}_{m.id}"
    if reacted_posts.find_one({"_id": key}):
        return

    project = reset_daily(project)
    owner = users.find_one({"_id": project["owner"]})

    if owner["credits"] < project["per_post"]:
        return
    if project["used_today"] + project["per_post"] > project["daily_limit"]:
        return

    link = f"https://t.me/{m.chat.username}/{m.id}"
    reaction = random.choice(project["reactions"])

    res = luvsmm_react(link, project["per_post"], reaction)
    if res.get("status") == "success":
        users.update_one({"_id": owner["_id"]}, {"$inc": {"credits": -project["per_post"]}})
        projects.update_one({"_id": project["_id"]}, {"$inc": {"used_today": project["per_post"]}})
        reacted_posts.insert_one({"_id": key})

# ================= ADMIN STATS =================
@bot.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def admin_stats(c, m):
    total_users = users.count_documents({})
    total_projects = projects.count_documents({"status": "active"})
    total_credits = sum(u["credits"] for u in users.find())

    await m.reply(
        f"📊 *ADMIN STATS*\n\n"
        f"👥 Users: {total_users}\n"
        f"📡 Active Projects: {total_projects}\n"
        f"💳 Total Credits: {total_credits}",
        parse_mode="markdown"
    )

# ================= SAFE BROADCAST =================
@bot.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS))
async def broadcast(c, m):
    if not m.reply_to_message:
        return await m.reply("Reply to a message to broadcast")

    sent = failed = 0
    for u in users.find():
        try:
            await m.reply_to_message.copy(u["_id"])
            sent += 1
            await asyncio.sleep(1.5)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except UserIsBlocked:
            failed += 1
        except:
            failed += 1

    await m.reply(f"✅ Broadcast done\nSent: {sent}\nFailed: {failed}")

# ================= RUN =================
bot.run()
