import os
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
games = {}

BOARD_TEMPLATE = ['⬜'] * 9

def render_board(board):
    return "\n".join(["".join(board[i:i+3]) for i in range(0, 9, 3)])

def create_keyboard(game_id):
    board = games[game_id]['board']
    keyboard = [
        [InlineKeyboardButton(board[i], callback_data=f"{game_id}:{i}") for i in range(j, j+3)]
        for j in range(0, 9, 3)
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to XO Bot!\nUse /playxo to start a new game.")

async def playxo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    game_id = str(user_id)
    board = BOARD_TEMPLATE.copy()
    games[game_id] = {'board': board, 'turn': '❌'}
    await update.message.reply_text(
        f"Game started! ❌ goes first.\n{render_board(board)}",
        reply_markup=create_keyboard(game_id)
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Stats feature is not implemented yet.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if str(user_id) in games:
        del games[str(user_id)]
        await update.message.reply_text("Game cancelled.")
    else:
        await update.message.reply_text("No active game found.")

def check_winner(board):
    wins = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]
    for i, j, k in wins:
        if board[i] == board[j] == board[k] and board[i] != '⬜':
            return board[i]
    return None

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    game_id, idx = query.data.split(":")
    idx = int(idx)

    if game_id not in games:
        await query.edit_message_text("Game not found or cancelled.")
        return

    game = games[game_id]
    board = game['board']
    turn = game['turn']

    if board[idx] != '⬜':
        return

    board[idx] = turn
    winner = check_winner(board)

    if winner:
        await query.edit_message_text(f"{render_board(board)}\n{winner} wins!")
        del games[game_id]
    elif '⬜' not in board:
        await query.edit_message_text(f"{render_board(board)}\nIt's a draw!")
        del games[game_id]
    else:
        game['turn'] = '⭕' if turn == '❌' else '❌'
        await query.edit_message_text(
            f"{render_board(board)}\n{game['turn']}'s turn.",
            reply_markup=create_keyboard(game_id)
        )

if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("playxo", playxo))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling()
