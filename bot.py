import os
import logging
from datetime import datetime
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    ConversationHandler, CallbackQueryHandler, CallbackContext
)
import pandas as pd
import matplotlib.pyplot as plt
from forex_python.converter import CurrencyRates

# Thiết lập logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Các trạng thái hội thoại
(CHOOSE_ACTION, ADD_TRANSACTION, CHOOSE_CATEGORY, 
 ENTER_AMOUNT, CHOOSE_CURRENCY, SET_BUDGET, 
 SET_SAVING_GOAL) = range(7)

# Khởi tạo cơ sở dữ liệu
def init_db():
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    # Bảng người dùng
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  pin TEXT,
                  default_currency TEXT)''')
    
    # Bảng danh mục
    c.execute('''CREATE TABLE IF NOT EXISTS categories
                 (id INTEGER PRIMARY KEY,
                  name TEXT,
                  type TEXT)''')
    
    # Bảng giao dịch
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY,
                  user_id INTEGER,
                  date TEXT,
                  category_id INTEGER,
                  amount REAL,
                  currency TEXT,
                  type TEXT,
                  note TEXT,
                  FOREIGN KEY (user_id) REFERENCES users (user_id),
                  FOREIGN KEY (category_id) REFERENCES categories (id))''')
    
    # Bảng ngân sách
    c.execute('''CREATE TABLE IF NOT EXISTS budgets
                 (id INTEGER PRIMARY KEY,
                  user_id INTEGER,
                  category_id INTEGER,
                  amount REAL,
                  currency TEXT,
                  period TEXT,
                  FOREIGN KEY (user_id) REFERENCES users (user_id),
                  FOREIGN KEY (category_id) REFERENCES categories (id))''')
    
    # Bảng mục tiêu tiết kiệm
    c.execute('''CREATE TABLE IF NOT EXISTS saving_goals
                 (id INTEGER PRIMARY KEY,
                  user_id INTEGER,
                  name TEXT,
                  target_amount REAL,
                  current_amount REAL,
                  currency TEXT,
                  deadline TEXT,
                  FOREIGN KEY (user_id) REFERENCES users (user_id))''')
    
    conn.commit()
    conn.close()

# Khởi tạo danh mục mặc định
def init_categories():
    categories = [
        ("Ăn uống", "expense"),
        ("Đi lại", "expense"),
        ("Hóa đơn", "expense"),
        ("Giải trí", "expense"),
        ("Mua sắm", "expense"),
        ("Lương", "income"),
        ("Thưởng", "income"),
        ("Thu nhập phụ", "income")
    ]
    
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    
    for cat in categories:
        c.execute("INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?)", cat)
    
    conn.commit()
    conn.close()

class FinanceBot:
    def __init__(self, token):
        self.updater = Updater(token, use_context=True)
        self.dp = self.updater.dispatcher
        self.currency_converter = CurrencyRates()
        
        # Khởi tạo cơ sở dữ liệu
        init_db()
        init_categories()
        
        # Thêm handlers
        self.add_handlers()

    def add_handlers(self):
        # Command handlers
        self.dp.add_handler(CommandHandler("start", self.start))
        self.dp.add_handler(CommandHandler("help", self.help))
        
        # Conversation handler cho thêm giao dịch
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('add', self.start_add_transaction)],
            states={
                CHOOSE_ACTION: [CallbackQueryHandler(self.choose_action)],
                CHOOSE_CATEGORY: [CallbackQueryHandler(self.choose_category)],
                ENTER_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, self.enter_amount)],
                CHOOSE_CURRENCY: [CallbackQueryHandler(self.choose_currency)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )
        self.dp.add_handler(conv_handler)

    def start(self, update: Update, context: CallbackContext):
        keyboard = [
            [InlineKeyboardButton("Thêm giao dịch", callback_data='add_transaction')],
            [InlineKeyboardButton("Xem báo cáo", callback_data='view_report')],
            [InlineKeyboardButton("Đặt ngân sách", callback_data='set_budget')],
            [InlineKeyboardButton("Mục tiêu tiết kiệm", callback_data='saving_goal')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            'Chào mừng đến với Bot Quản lý Tài chính! \n'
            'Bạn muốn làm gì?',
            reply_markup=reply_markup
        )
        return CHOOSE_ACTION

    def help(self, update: Update, context: CallbackContext):
        help_text = """
Các lệnh có sẵn:
/start - Bắt đầu bot
/add - Thêm giao dịch mới
/report - Xem báo cáo tài chính
/budget - Quản lý ngân sách
/goals - Quản lý mục tiêu tiết kiệm
/export - Xuất dữ liệu
/help - Hiển thị trợ giúp
"""
        update.message.reply_text(help_text)

    def start_add_transaction(self, update: Update, context: CallbackContext):
        keyboard = [
            [InlineKeyboardButton("Chi tiêu", callback_data='expense'),
             InlineKeyboardButton("Thu nhập", callback_data='income')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text('Bạn muốn thêm giao dịch gì?', reply_markup=reply_markup)
        return CHOOSE_CATEGORY

    def choose_category(self, update: Update, context: CallbackContext):
        query = update.callback_query
        query.answer()
        
        transaction_type = query.data
        context.user_data['transaction_type'] = transaction_type
        
        # Lấy danh sách danh mục từ database
        conn = sqlite3.connect('finance.db')
        c = conn.cursor()
        c.execute("SELECT name FROM categories WHERE type=?", (transaction_type,))
        categories = c.fetchall()
        conn.close()
        
        keyboard = [[InlineKeyboardButton(cat[0], callback_data=cat[0])] 
                   for cat in categories]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text('Chọn danh mục:', reply_markup=reply_markup)
        return ENTER_AMOUNT

    def enter_amount(self, update: Update, context: CallbackContext):
        try:
            amount = float(update.message.text)
            context.user_data['amount'] = amount
            
            # Hiển thị lựa chọn tiền tệ
            keyboard = [
                [InlineKeyboardButton("VND", callback_data='VND'),
                 InlineKeyboardButton("USD", callback_data='USD'),
                 InlineKeyboardButton("EUR", callback_data='EUR')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text('Chọn loại tiền tệ:', reply_markup=reply_markup)
            return CHOOSE_CURRENCY
            
        except ValueError:
            update.message.reply_text('Vui lòng nhập số tiền hợp lệ!')
            return ENTER_AMOUNT

    def choose_currency(self, update: Update, context: CallbackContext):
        query = update.callback_query
        query.answer()
        
        currency = query.data
        amount = context.user_data['amount']
        transaction_type = context.user_data['transaction_type']
        
        # Lưu giao dịch vào database
        conn = sqlite3.connect('finance.db')
        c = conn.cursor()
        c.execute("""
            INSERT INTO transactions 
            (user_id, date, amount, currency, type) 
            VALUES (?, ?, ?, ?, ?)
        """, (
            update.effective_user.id,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            amount,
            currency,
            transaction_type
        ))
        conn.commit()
        conn.close()
        
        query.edit_message_text(
            f'Đã thêm giao dịch: {amount} {currency}\n'
            f'Loại: {transaction_type}'
        )
        return ConversationHandler.END

    def cancel(self, update: Update, context: CallbackContext):
        update.message.reply_text('Đã hủy thao tác.')
        return ConversationHandler.END

    def generate_report(self, user_id, period='month'):
        conn = sqlite3.connect('finance.db')
        df = pd.read_sql_query("""
            SELECT date, amount, currency, type, categories.name as category
            FROM transactions 
            LEFT JOIN categories ON transactions.category_id = categories.id
            WHERE user_id = ?
            ORDER BY date DESC
        """, conn, params=(user_id,))
        conn.close()
        
        # Xử lý và tạo báo cáo
        if not df.empty:
            # Chuyển đổi tất cả về một loại tiền tệ (VND)
            for idx, row in df.iterrows():
                if row['currency'] != 'VND':
                    try:
                        df.at[idx, 'amount'] = self.currency_converter.convert(
                            row['currency'], 'VND', row['amount']
                        )
                    except:
                        pass
            
            # Tạo biểu đồ
            plt.figure(figsize=(10, 6))
            expenses = df[df['type'] == 'expense'].groupby('category')['amount'].sum()
            expenses.plot(kind='pie')
            plt.title('Phân bổ chi tiêu')
            plt.savefig('report.png')
            
            return {
                'total_income': df[df['type'] == 'income']['amount'].sum(),
                'total_expense': df[df['type'] == 'expense']['amount'].sum(),
                'by_category': df.groupby(['type', 'category'])['amount'].sum().to_dict(),
                'chart_path': 'report.png'
            }
        return None

    def run(self):
        self.updater.start_polling()
        self.updater.idle()

import os

if __name__ == '__main__':
    # Lấy token từ biến môi trường
    bot_token = os.getenv("BOT_TOKEN")
    
    # Kiểm tra xem token có được cung cấp hay không
    if not bot_token:
        raise ValueError("Không tìm thấy BOT_TOKEN trong Config Vars")

    # Khởi chạy bot
    bot = FinanceBot(bot_token)
    bot.run()
