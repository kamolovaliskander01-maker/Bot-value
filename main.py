import logging
import asyncio
import os
from datetime import datetime
from typing import Optional

import requests
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
load_dotenv()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOZLAMALAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Railway'da BOT_TOKEN environment variable orqali o'rnatiladi
# Lokal ishlatishda to'g'ridan-to'g'ri yozilgan token ishlatiladi
API_TOKEN = os.getenv("BOT_TOKEN")
CBU_API_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
REQUEST_TIMEOUT = 10  # API so'rov kutish vaqti (soniya)
FAVORITES_MAX = 10  # Har bir foydalanuvchi uchun max sevimli valyutalar
PAGE_SIZE = 15  # Sahifalashda har bir xabardagi valyutalar soni

# Mashhur valyutalar (inline tugmalar uchun)
POPULAR_CURRENCIES = [
    "USD", "EUR", "RUB", "GBP", "CHF", "JPY",
    "CNY", "KRW", "TRY", "KZT", "AED", "CAD",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOGGING SOZLAMALARI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BOT VA DISPATCHER YARATISH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=storage)
router = Router(name="main_router")
dp.include_router(router)

# Foydalanuvchilar sevimli valyutalari (xotirada)
# Tuzilma: {user_id: ["USD", "EUR", ...]}
user_favorites: dict[int, list[str]] = {}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API FUNKSIYALARI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_all_rates() -> Optional[list[dict]]:
    """
    Markaziy Bank API dan barcha valyuta kurslarini oladi.
    Muvaffaqiyatsiz bo'lsa None qaytaradi.
    """
    try:
        response = requests.get(CBU_API_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        logger.info("API dan %d ta valyuta kursi olindi.", len(data))
        return data
    except requests.ConnectionError:
        logger.error("API ga ulanib bo'lmadi — internet aloqasini tekshiring.")
        return None
    except requests.Timeout:
        logger.error("API javob bermadi — %d soniya kutildi.", REQUEST_TIMEOUT)
        return None
    except requests.HTTPError as exc:
        logger.error("API HTTP xatosi: %s", exc)
        return None
    except Exception as exc:
        logger.error("API dan ma'lumot olishda kutilmagan xato: %s", exc)
        return None


def get_rate_by_code(code: str) -> Optional[dict]:
    """
    Bitta valyuta kodiga ko'ra kurs ma'lumotini qaytaradi.
    Topilmasa None qaytaradi.
    """
    data = get_all_rates()
    if data is None:
        return None
    code_upper = code.upper().strip()
    for item in data:
        if item.get("Ccy") == code_upper:
            return item
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# YORDAMCHI FUNKSIYALAR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def format_money(value: float) -> str:
    """Raqamni o'qishga qulay formatda qaytaradi: '12 785 000.00'."""
    return "{:,.2f}".format(value).replace(",", " ")


def diff_emoji(diff_str: str) -> str:
    """O'zgarish qiymatiga qarab emoji qaytaradi."""
    try:
        diff = float(diff_str)
    except (ValueError, TypeError):
        return "➖"
    if diff > 0:
        return "📈"
    elif diff < 0:
        return "📉"
    return "➖"


def build_main_keyboard() -> types.ReplyKeyboardMarkup:
    """Asosiy menyu keyboard ni yaratadi."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        types.KeyboardButton(text="💰 Asosiy kurslar (USD, EUR, RUB)"),
    )
    builder.row(
        types.KeyboardButton(text="🌍 Barcha valyutalar"),
        types.KeyboardButton(text="🔄 Konvertatsiya"),
    )
    builder.row(
        types.KeyboardButton(text="📊 Trend"),
        types.KeyboardButton(text="⭐ Sevimlilar"),
    )
    builder.row(
        types.KeyboardButton(text="🧮 Kalkulyator qo'llanma"),
    )
    return builder.as_markup(resize_keyboard=True)


def build_favorites_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Foydalanuvchining sevimli valyutalari uchun inline tugmalar."""
    favs = user_favorites.get(user_id, [])
    builder = InlineKeyboardBuilder()
    for code in favs:
        builder.button(text=f"💱 {code}", callback_data=f"rate_{code}")
    # Har bir qatorda 3 ta tugma
    builder.adjust(3)
    return builder.as_markup()


def build_popular_inline_keyboard() -> InlineKeyboardMarkup:
    """Mashhur 12 valyuta uchun inline tanlash tugmalari."""
    builder = InlineKeyboardBuilder()
    for code in POPULAR_CURRENCIES:
        builder.button(text=code, callback_data=f"rate_{code}")
    builder.adjust(4)
    return builder.as_markup()


def build_fav_toggle_keyboard(code: str, user_id: int) -> InlineKeyboardMarkup:
    """Valyuta kursini ko'rsatganda sevimlilarga qo'shish/olib tashlash tugmasi."""
    favs = user_favorites.get(user_id, [])
    builder = InlineKeyboardBuilder()
    if code in favs:
        builder.button(text="❌ Sevimlilardan olib tashlash", callback_data=f"fav_{code}")
    else:
        builder.button(text="⭐ Sevimlilarga qo'shish", callback_data=f"fav_{code}")
    return builder.as_markup()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /start — BOTNI ISHGA TUSHIRISH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    """Foydalanuvchini kutib oladi va asosiy menyuni ko'rsatadi."""
    logger.info(
        "Yangi foydalanuvchi: %s (id=%d)",
        message.from_user.full_name,
        message.from_user.id,
    )
    await message.answer(
        "🤖 <b>Valyuta Kursi Botiga xush kelibsiz!</b>\n\n"
        "Bu bot orqali O'zbekiston Markaziy Banki kurslarini\n"
        "real vaqt rejimida ko'rishingiz mumkin.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>Tezkor hisob:</b> Menga shunchaki yozing:\n"
        "<code>100 usd</code> yoki <code>5000 rub</code>\n\n"
        "📋 <b>Buyruqlar:</b>\n"
        "/rate USD — bitta valyuta kursi\n"
        "/convert 100 EUR — konvertatsiya\n"
        "/list — barcha valyutalar\n"
        "/help — to'liq yordam\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        parse_mode="HTML",
        reply_markup=build_main_keyboard(),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /help — YORDAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    """To'liq qo'llanma va barcha buyruqlar ro'yxati."""
    await message.answer(
        "📖 <b>Foydalanish Qo'llanmasi</b>\n\n"
        "━━ <b>Buyruqlar</b> ━━━━━━━━━━━━━\n"
        "/start — Botni qayta ishga tushirish\n"
        "/help — Shu yordam sahifasi\n"
        "/rate [KOD] — Bitta valyuta kursi\n"
        "   Misol: <code>/rate USD</code>\n"
        "/convert [miqdor] [KOD] — Konvertatsiya\n"
        "   Misol: <code>/convert 100 EUR</code>\n"
        "/list — Barcha valyutalar ro'yxati\n\n"
        "━━ <b>Tezkor Hisob</b> ━━━━━━━━━━\n"
        "Shunchaki matn yozing:\n"
        "• <code>100 usd</code> — 100 dollar so'mga\n"
        "• <code>5000 rub</code> — 5000 rubl so'mga\n"
        "• <code>50 eur</code> — 50 yevro so'mga\n"
        "• <code>1000 cny</code> — 1000 yuan so'mga\n\n"
        "━━ <b>Menu Tugmalari</b> ━━━━━━━━\n"
        "💰 Asosiy kurslar — USD, EUR, RUB\n"
        "🌍 Barcha valyutalar — 70+ valyuta\n"
        "🔄 Konvertatsiya — inline tanlash\n"
        "📊 Trend — ko'tarilgan/tushgan\n"
        "⭐ Sevimlilar — shaxsiy ro'yxat\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📡 Manba: O'zbekiston Markaziy Banki\n"
        "🔄 Kurslar har kuni yangilanadi",
        parse_mode="HTML",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /rate [KOD] — BITTA VALYUTA KURSI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(Command("rate"))
async def cmd_rate(message: types.Message, command: CommandObject):
    """Berilgan valyuta kodining kursini ko'rsatadi."""
    if not command.args:
        await message.answer(
            "⚠️ Valyuta kodini kiriting.\n"
            "Misol: <code>/rate USD</code>",
            parse_mode="HTML",
        )
        return

    code = command.args.strip().upper()
    item = get_rate_by_code(code)

    if item is None:
        await message.answer(
            f"❌ <b>{code}</b> valyutasi topilmadi yoki API ishlamayapti.\n"
            "Kodni tekshiring (masalan: USD, EUR, RUB, GBP).",
            parse_mode="HTML",
        )
        return

    rate = float(item["Rate"])
    diff = item.get("Diff", "0")
    emoji = diff_emoji(diff)
    date_str = item.get("Date", "—")

    # Teskari kurs hisoblash
    reverse = 1.0 / rate if rate > 0 else 0

    text = (
        f"🏦 <b>{item['CcyNm_UZ']}</b> ({item['Ccy']})\n\n"
        f"💰 1 {code} = <b>{format_money(rate)}</b> so'm\n"
        f"💰 1 so'm = <b>{reverse:.8f}</b> {code}\n\n"
        f"{emoji} O'zgarish: <b>{diff}</b> so'm\n"
        f"📅 Sana: {date_str}"
    )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=build_fav_toggle_keyboard(code, message.from_user.id),
    )
    logger.info(
        "Foydalanuvchi %d /rate %s so'radi.",
        message.from_user.id,
        code,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /convert [miqdor] [KOD] — KONVERTATSIYA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(Command("convert"))
async def cmd_convert(message: types.Message, command: CommandObject):
    """Berilgan miqdorni valyutadan so'mga konvertatsiya qiladi."""
    if not command.args or len(command.args.split()) < 2:
        await message.answer(
            "⚠️ Format: <code>/convert [miqdor] [valyuta]</code>\n"
            "Misol: <code>/convert 100 USD</code>",
            parse_mode="HTML",
        )
        return

    parts = command.args.split()
    try:
        amount = float(parts[0])
    except ValueError:
        await message.answer(
            "⚠️ Miqdor noto'g'ri. Raqam kiriting.\n"
            "Misol: <code>/convert 100 USD</code>",
            parse_mode="HTML",
        )
        return

    code = parts[1].upper()
    item = get_rate_by_code(code)

    if item is None:
        await message.answer(
            f"❌ <b>{code}</b> valyutasi topilmadi yoki API ishlamayapti.",
            parse_mode="HTML",
        )
        return

    rate = float(item["Rate"])
    result = amount * rate
    reverse = amount / rate if rate > 0 else 0

    text = (
        f"🧮 <b>Konvertatsiya natijasi</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 {format_money(amount)} {code} = <b>{format_money(result)}</b> so'm\n"
        f"💵 {format_money(amount)} so'm = <b>{reverse:.6f}</b> {code}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"ℹ️ Kurs: 1 {code} = {format_money(rate)} so'm\n"
        f"📅 Sana: {item.get('Date', '—')}"
    )

    await message.answer(text, parse_mode="HTML")
    logger.info(
        "Foydalanuvchi %d /convert %.2f %s so'radi. Natija: %.2f so'm",
        message.from_user.id,
        amount,
        code,
        result,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /list — BARCHA VALYUTALAR (SAHIFALANGAN)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(Command("list"))
async def cmd_list(message: types.Message):
    """Barcha valyutalarni sahifalab ko'rsatadi (15 tadan)."""
    data = get_all_rates()
    if not data:
        await message.answer("❌ Ma'lumot olishda xatolik yuz berdi. Keyinroq urinib ko'ring.")
        return

    # Sahifalash: 15 tadan bo'lib yuborish
    total = len(data)
    pages = [data[i : i + PAGE_SIZE] for i in range(0, total, PAGE_SIZE)]

    for page_num, page in enumerate(pages, start=1):
        text = f"🌍 <b>Valyuta kurslari</b> — sahifa {page_num}/{len(pages)}\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for item in page:
            emoji = diff_emoji(item.get("Diff", "0"))
            text += (
                f"{emoji} <b>{item['Ccy']}</b> ({item['CcyNm_UZ']})\n"
                f"    1 {item['Ccy']} = <b>{item['Rate']}</b> so'm"
                f" ({item.get('Diff', '0')})\n\n"
            )

        text += f"📡 Manba: Markaziy Bank | Jami: {total} ta valyuta"
        await message.answer(text, parse_mode="HTML")
        # Telegram flood limitidan himoya
        await asyncio.sleep(0.3)

    logger.info(
        "Foydalanuvchi %d /list — %d ta valyuta, %d sahifa.",
        message.from_user.id,
        total,
        len(pages),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 💰 ASOSIY KURSLAR TUGMASI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(F.text == "💰 Asosiy kurslar (USD, EUR, RUB)")
async def show_main_rates(message: types.Message):
    """USD, EUR, RUB kurslarini o'zgarish foizi bilan ko'rsatadi."""
    data = get_all_rates()
    if not data:
        await message.answer("❌ Ma'lumot olishda xatolik yuz berdi.")
        return

    main_codes = ("USD", "EUR", "RUB")
    text = "🏦 <b>Asosiy valyuta kurslari</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for item in data:
        if item["Ccy"] in main_codes:
            rate = float(item["Rate"])
            diff = float(item.get("Diff", 0))
            emoji = diff_emoji(item.get("Diff", "0"))

            # O'zgarish foizini hisoblash
            old_rate = rate - diff
            if old_rate > 0:
                percent = (diff / old_rate) * 100
            else:
                percent = 0.0

            sign = "+" if diff > 0 else ""

            text += (
                f"{'🇺🇸' if item['Ccy'] == 'USD' else '🇪🇺' if item['Ccy'] == 'EUR' else '🇷🇺'} "
                f"<b>{item['Ccy']}</b> — {item.get('CcyNm_UZ', '')}\n"
                f"   💰 1 {item['Ccy']} = <b>{format_money(rate)}</b> so'm\n"
                f"   {emoji} O'zgarish: {sign}{diff:.2f} so'm ({sign}{percent:.2f}%)\n\n"
            )

    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    text += f"━━━━━━━━━━━━━━━━━━━━━━━\n🕐 {now_str} | 📡 Markaziy Bank"

    await message.answer(text, parse_mode="HTML")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🌍 BARCHA VALYUTALAR TUGMASI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(F.text == "🌍 Barcha valyutalar")
async def show_all_rates(message: types.Message):
    """Menu tugmasi orqali barcha valyutalarni ko'rsatadi."""
    await cmd_list(message)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔄 KONVERTATSIYA TUGMASI (INLINE TANLASH)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(F.text == "🔄 Konvertatsiya")
async def show_convert_menu(message: types.Message):
    """Mashhur valyutalarni inline tugmalar bilan taklif qiladi."""
    await message.answer(
        "🔄 <b>Valyuta tanlang</b>\n\n"
        "Quyidagi tugmalardan birini bosing yoki\n"
        "<code>/convert 100 USD</code> formatida yozing:",
        parse_mode="HTML",
        reply_markup=build_popular_inline_keyboard(),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📊 TREND TAHLILI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(F.text == "📊 Trend")
async def show_trend(message: types.Message):
    """Kurslar ko'tarilgan va tushgan valyutalarni alohida ko'rsatadi."""
    data = get_all_rates()
    if not data:
        await message.answer("❌ Ma'lumot olishda xatolik yuz berdi.")
        return

    rising = []
    falling = []
    stable = []

    for item in data:
        try:
            diff = float(item.get("Diff", 0))
        except (ValueError, TypeError):
            diff = 0.0

        entry = {
            "code": item["Ccy"],
            "name": item.get("CcyNm_UZ", ""),
            "rate": item["Rate"],
            "diff": diff,
        }

        if diff > 0:
            rising.append(entry)
        elif diff < 0:
            falling.append(entry)
        else:
            stable.append(entry)

    # Eng ko'p ko'tarilganlarni tepaga, eng ko'p tushganlarni tepaga
    rising.sort(key=lambda x: x["diff"], reverse=True)
    falling.sort(key=lambda x: x["diff"])

    text = "📊 <b>Valyuta kurslari trendi</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    if rising:
        text += "📈 <b>Kursi ko'tarilgan:</b>\n"
        for entry in rising[:10]:
            text += (
                f"  🟢 {entry['code']} — {entry['rate']} so'm"
                f" (+{entry['diff']:.2f})\n"
            )
        text += "\n"

    if falling:
        text += "📉 <b>Kursi tushgan:</b>\n"
        for entry in falling[:10]:
            text += (
                f"  🔴 {entry['code']} — {entry['rate']} so'm"
                f" ({entry['diff']:.2f})\n"
            )
        text += "\n"

    if stable:
        text += f"➖ O'zgarmagan: {len(stable)} ta valyuta\n\n"

    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    text += f"━━━━━━━━━━━━━━━━━━━━━━━\n🕐 {now_str} | 📡 Markaziy Bank"

    await message.answer(text, parse_mode="HTML")
    logger.info("Foydalanuvchi %d trend so'radi.", message.from_user.id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⭐ SEVIMLILAR TIZIMI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(F.text == "⭐ Sevimlilar")
async def show_favorites(message: types.Message):
    """Foydalanuvchining sevimli valyutalarini ko'rsatadi."""
    user_id = message.from_user.id
    favs = user_favorites.get(user_id, [])

    if not favs:
        await message.answer(
            "⭐ <b>Sevimlilar ro'yxati bo'sh</b>\n\n"
            "Valyutani sevimlilarga qo'shish uchun:\n"
            "1. <code>/rate USD</code> buyrug'ini yuboring\n"
            "2. Chiqadigan tugmani bosing\n\n"
            "Yoki quyidagi valyutalardan tanlang:",
            parse_mode="HTML",
            reply_markup=build_popular_inline_keyboard(),
        )
        return

    # Sevimli valyutalar kurslarini olish
    data = get_all_rates()
    if not data:
        await message.answer("❌ Ma'lumot olishda xatolik yuz berdi.")
        return

    rates_map = {item["Ccy"]: item for item in data}

    text = "⭐ <b>Sevimli valyutalaringiz</b>\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for code in favs:
        item = rates_map.get(code)
        if item:
            emoji = diff_emoji(item.get("Diff", "0"))
            text += (
                f"{emoji} <b>{code}</b> ({item.get('CcyNm_UZ', '')})\n"
                f"   1 {code} = <b>{item['Rate']}</b> so'm\n\n"
            )
        else:
            text += f"⚠️ <b>{code}</b> — ma'lumot topilmadi\n\n"

    text += f"━━━━━━━━━━━━━━━━━━━━━━━\n📌 Jami: {len(favs)}/{FAVORITES_MAX}"

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=build_favorites_keyboard(user_id),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🧮 KALKULYATOR QO'LLANMA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(F.text == "🧮 Kalkulyator qo'llanma")
async def calc_info(message: types.Message):
    """Kalkulyator funksiyasidan foydalanish yo'riqnomasi."""
    await message.answer(
        "🧮 <b>Kalkulyatordan foydalanish</b>\n\n"
        "Menga shunchaki matn yozing:\n"
        "<code>[miqdor] [valyuta kodi]</code>\n\n"
        "━━ <b>Misollar</b> ━━━━━━━━━━━━━\n"
        "• <code>100 usd</code> → Dollar → So'm\n"
        "• <code>5000 rub</code> → Rubl → So'm\n"
        "• <code>50 eur</code> → Yevro → So'm\n"
        "• <code>1000 cny</code> → Yuan → So'm\n"
        "• <code>10 gbp</code> → Funt → So'm\n\n"
        "━━ <b>Natija</b> ━━━━━━━━━━━━━━━\n"
        "Bot sizga ikkala yo'nalishni ko'rsatadi:\n"
        "💵 100 USD → so'mga\n"
        "💵 100 so'm → USD ga\n\n"
        "📡 Markaziy Bank rasmiy kursi asosida",
        parse_mode="HTML",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CALLBACK QUERY HANDLER (INLINE TUGMALAR)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.callback_query(F.data.startswith("rate_"))
async def callback_rate(callback: CallbackQuery):
    """Inline tugma bosilganda valyuta kursini ko'rsatadi."""
    code = callback.data.replace("rate_", "").upper()
    item = get_rate_by_code(code)

    if item is None:
        await callback.answer(f"❌ {code} topilmadi!", show_alert=True)
        return

    rate = float(item["Rate"])
    diff = item.get("Diff", "0")
    emoji = diff_emoji(diff)
    reverse = 1.0 / rate if rate > 0 else 0

    text = (
        f"🏦 <b>{item.get('CcyNm_UZ', code)}</b> ({code})\n\n"
        f"💰 1 {code} = <b>{format_money(rate)}</b> so'm\n"
        f"💰 1 so'm = <b>{reverse:.8f}</b> {code}\n\n"
        f"{emoji} O'zgarish: <b>{diff}</b> so'm\n"
        f"📅 Sana: {item.get('Date', '—')}"
    )

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=build_fav_toggle_keyboard(code, callback.from_user.id),
    )
    await callback.answer()
    logger.info(
        "Foydalanuvchi %d inline rate_%s bosdi.",
        callback.from_user.id,
        code,
    )


@router.callback_query(F.data.startswith("fav_"))
async def callback_toggle_favorite(callback: CallbackQuery):
    """Valyutani sevimlilarga qo'shish yoki olib tashlash."""
    code = callback.data.replace("fav_", "").upper()
    user_id = callback.from_user.id

    if user_id not in user_favorites:
        user_favorites[user_id] = []

    favs = user_favorites[user_id]

    if code in favs:
        favs.remove(code)
        await callback.answer(f"❌ {code} sevimlilardan olib tashlandi.", show_alert=True)
        logger.info("Foydalanuvchi %d sevimlilardan %s olib tashladi.", user_id, code)
    else:
        if len(favs) >= FAVORITES_MAX:
            await callback.answer(
                f"⚠️ Maksimal {FAVORITES_MAX} ta valyuta saqlash mumkin!\n"
                "Avval bittasini olib tashlang.",
                show_alert=True,
            )
            return
        favs.append(code)
        await callback.answer(f"⭐ {code} sevimlilarga qo'shildi!", show_alert=True)
        logger.info("Foydalanuvchi %d sevimlilarga %s qo'shdi.", user_id, code)

    # Tugmani yangilash
    await callback.message.edit_reply_markup(
        reply_markup=build_fav_toggle_keyboard(code, user_id),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEZKOR KONVERTATSIYA (MATN HANDLER)
# "100 usd" yoki "5000 rub" formatida
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message(F.text.regexp(r"^\d+[\.\,]?\d*\s+[a-zA-Z]{2,5}$"))
async def quick_convert(message: types.Message):
    """Tezkor konvertatsiya: '100 usd' formatidagi xabarlarni qayta ishlaydi."""
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            return

        amount_str = parts[0].replace(",", ".")
        amount = float(amount_str)
        code = parts[1].upper()

        data = get_all_rates()
        if not data:
            await message.answer("❌ API dan ma'lumot olishda xatolik yuz berdi.")
            return

        # Valyutani qidirish
        found_item = None
        for item in data:
            if item["Ccy"] == code:
                found_item = item
                break

        if found_item is None:
            await message.answer(
                f"❌ <b>{code}</b> valyutasi topilmadi.\n"
                "Kodini tekshiring (masalan: USD, EUR, RUB, GBP, CNY).",
                parse_mode="HTML",
            )
            return

        rate = float(found_item["Rate"])
        result = amount * rate
        reverse = amount / rate if rate > 0 else 0

        # Chiroyli formatda natija
        text = (
            f"🧮 <b>Tezkor hisob-kitob</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 {format_money(amount)} {code} = <b>{format_money(result)}</b> so'm\n"
            f"💵 {format_money(amount)} so'm = <b>{reverse:.6f}</b> {code}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"ℹ️ Kurs: 1 {code} = {format_money(rate)} so'm\n"
            f"📅 Sana: {found_item.get('Date', '—')}\n"
            f"📡 Manba: Markaziy Bank"
        )

        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=build_fav_toggle_keyboard(code, message.from_user.id),
        )
        logger.info(
            "Tezkor konvertatsiya: foydalanuvchi %d — %.2f %s = %.2f so'm",
            message.from_user.id,
            amount,
            code,
            result,
        )

    except ValueError:
        # Son formatida xato — e'tibor bermaymiz
        pass
    except Exception as exc:
        logger.error(
            "Tezkor konvertatsiyada xato (foydalanuvchi %d): %s",
            message.from_user.id,
            exc,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# XATO XABAR HANDLERI
# Tushunilmagan xabarlar uchun
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.message()
async def unknown_message(message: types.Message):
    """Tanilmagan xabarlar uchun yordam ko'rsatadi."""
    await message.answer(
        "🤔 <b>Tushunmadim...</b>\n\n"
        "Quyidagilardan birini sinab ko'ring:\n"
        "• <code>100 usd</code> — tezkor konvertatsiya\n"
        "• /rate USD — valyuta kursi\n"
        "• /convert 100 EUR — konvertatsiya\n"
        "• /help — to'liq yordam\n\n"
        "Yoki menyu tugmalaridan foydalaning 👇",
        parse_mode="HTML",
    )
    logger.debug(
        "Tushunilmagan xabar (foydalanuvchi %d): %s",
        message.from_user.id,
        message.text[:50] if message.text else "(matn yo'q)",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BOTNI ISHGA TUSHIRISH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def main():
    """Botning asosiy ishga tushirish funksiyasi."""
    logger.info("=" * 50)
    logger.info("🤖 Valyuta Kursi Bot v2.0 ishga tushmoqda...")
    logger.info("📦 Aiogram 3.x | Python 3.10+")
    logger.info("📡 API: %s", CBU_API_URL)
    logger.info("=" * 50)

    # Eski xabarlarni o'tkazib yuborish
    await bot.delete_webhook(drop_pending_updates=True)
    # Pollingni boshlash
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())