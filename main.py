import os
import logging
from dotenv import load_dotenv

from motor.motor_asyncio import AsyncIOMotorClient

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB setup
mongo_client = AsyncIOMotorClient(MONGODB_URI)
db = mongo_client.xobot

# States for ConversationHandler
WAITING_FOR_OPPONENT = 1
IN_GAME = 2

# Game constants
EMPTY = "⬜"
PLAYER_X = "❌"
PLAYER_O = "⭕"

# Helper Functions

def render_board(board):
    # Board is list of 9 str (⬜, ❌, ⭕)
    lines = []
    for i in range(0, 9, 3):
        lines.append("".join(board[i:i+3]))
    return "\n".join(lines)

def check_winner(board):
    win_positions = [
        [0,1,2],[3,4,5],[6,7,8],  # rows
        [0,3,6],[1,4,7],[2,5,8],  # cols
        [0,4,8],[2,4,6]           # diagonals
    ]
    for pos in win_positions:
        line = [board[i] for i in pos]
        if line[0] != EMPTY and all(s == line[0] for s in line):
            return line[0]
    return None

def board_full(board):
    return all(cell != EMPTY for cell in board)

def other_player(player):
    return PLAYER_O if player == PLAYER_X else PLAYER_X

def player_name(user):
    return user.first_name or user.username or str(user.id)

# DB helpers for stats

async def get_user_stats(user_id):
    stats = await db.stats.find_one({"user_id": user_id})
    if not stats:
        return {"played": 0, "wins": 0, "losses": 0, "draws": 0}
    return stats

async def update_user_stats(user_id, result):
    # result in {"win", "loss", "draw"}
    stats = await get_user_stats(user_id)
    stats["played"] += 1
    if result == "win":
        stats["wins"] += 1
    elif result == "loss":
        stats["losses"] += 1
    elif result == "draw":
        stats["draws"] += 1
    await db.stats.update_one({"user_id": user_id}, {"$set": stats}, upsert=True)

# DB helpers for game lobby and active games

async def create_game(owner_id, owner_name):
    game = {
        "owner_id": owner_id,
        "owner_name": owner_name,
        "opponent_id": None,
        "opponent_name": None,
        "board": [EMPTY]*9,
        "turn": PLAYER_X,  # owner always X and starts first
        "status": "waiting"  # waiting, playing, finished
    }
    result = await db.games.insert_one(game)
    return str(result.inserted_id)

async def join_game(game_id, user_id, user_name):
    game = await db.games.find_one({"_id": game_id})
    if not game or game["status"] != "waiting":
        return None
    await db.games.update_one(
        {"_id": game_id},
        {
            "$set": {
                "opponent_id": user_id,
                "opponent_name": user_name,
                "status": "playing"
            }
        }
    )
    return await db.games.find_one({"_id": game_id})

async def get_game(game_id):
    return await db.games.find_one({"_id": game_id})

async def update_game(game_id, updates: dict):
    await db.games.update_one({"_id": game_id}, {"$set": updates})

async def delete_game(game_id):
    await db.games.delete_one({"_id": game_id})

# Telegram command handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Hello! I am XO Game Bot.\n\n"
        "Commands:\n"
        "/playxo or /newgame - Start a new game\n"
        "/stats - Show your game stats\n"
        "/cancel - Cancel current game or lobby\n"
        "/help - Show help message"
    )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Commands:\n"
        "/playxo or /newgame - Start a new game and wait for opponent\n"
        "/stats - Show your personal stats\n"
        "/cancel - Cancel your current game or lobby\n"
        "/help - Show this help"
    )
    await update.message.reply_text(text)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = await get_user_stats(user_id)
    text = (
        f"📊 Your Stats:\n"
        f"🕹 Games played: {stats['played']}\n"
        f"✅ Wins: {stats['wins']}\n"
        f"❌ Losses: {stats['losses']}\n"
        f"🤝 Draws: {stats['draws']}"
    )
    await update.message.reply_text(text)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    game = await db.games.find_one(
        {"$or": [{"owner_id": user_id}, {"opponent_id": user_id}], "status": {"$in": ["waiting", "playing"]}}
    )
    if game:
        await delete_game(game["_id"])
        await update.message.reply_text("Your game or lobby was canceled.")
    else:
        await update.message.reply_text("You have no active game or lobby.")

async def playxo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Check if user already has active game or lobby
    active = await db.games.find_one(
        {"$or": [{"owner_id": user.id}, {"opponent_id": user.id}], "status": {"$in": ["waiting", "playing"]}}
    )
    if active:
        await update.message.reply_text("You already have an active game or lobby. Use /cancel to cancel it.")
        return

    game_id = await create_game(user.id, player_name(user))
    keyboard = [
        [InlineKeyboardButton("Join Game", callback_data=f"join_{game_id}")]
    ]
    text = (
        f"🕹 *New XO Game Lobby Created*\n\n"
        f"Waiting for opponent to join...\n"
        f"Owner: {player_name(user)} (❌)\n\n"
        "Press *Join Game* to start playing."
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# CallbackQuery handler to join game

async def join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user

    await query.answer()

    # Extract game_id
    data = query.data
    if not data.startswith("join_"):
        return

    game_id = data.split("_", 1)[1]

    # Get game document
    game = await db.games.find_one({"_id": game_id})
    if not game:
        await query.edit_message_text("Game not found or already started.")
        return

    if game["status"] != "waiting":
        await query
