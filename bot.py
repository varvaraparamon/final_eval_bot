import asyncio
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from models import Base, User, Team, Case, FinalEvaluation

load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, echo=False)
Base.metadata.create_all(engine)
Session = scoped_session(sessionmaker(bind=engine))

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Оценить команду")],
        [KeyboardButton(text="Сменить аккаунт")]
    ],
    resize_keyboard=True
)


AUTHORIZED: dict[int, int] = {}

class EvalForm(StatesGroup):
    login = State()
    password = State()
    case = State()
    team = State()
    product_value = State()
    scalability = State()
    ux = State()
    presentation = State()
    confirm = State()


def get_team_keyboard(teams: list[Team], page: int, per_page: int = 10) -> InlineKeyboardMarkup:
    start = page * per_page
    buttons = [
        [InlineKeyboardButton(text=t.name, callback_data=f"team_{t.id}")]
        for t in teams[start:start + per_page]
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page_{page - 1}"))
    if start + per_page < len(teams):
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"page_{page + 1}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def ask_score(destination, title: str, prefix: str):
    """
    destination - объект с методом answer (например message или callback.message)
    """
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="0", callback_data=f"{prefix}_0"),
            InlineKeyboardButton(text="0.5", callback_data=f"{prefix}_05"),
            InlineKeyboardButton(text="1", callback_data=f"{prefix}_1"),
        ]
    ])
    await destination.answer(f"Оцените: {title}", reply_markup=kb)



@dp.message(F.text == "/start")
async def start(message: types.Message, state: FSMContext):
    await state.set_state(EvalForm.login)
    await message.answer("Введите логин:")


@dp.message(EvalForm.login)
async def get_login(message: types.Message, state: FSMContext):
    await state.update_data(login=message.text.strip())
    await state.set_state(EvalForm.password)
    await message.answer("Введите пароль:")


@dp.message(EvalForm.password)
async def get_password(message: types.Message, state: FSMContext):
    data = await state.get_data()
    login = data.get("login")
    password = message.text.strip()

    session = Session()
    user = session.query(User).filter_by(login=login).first()

    if not user:
        session.close()
        await state.clear()
        await message.answer("❌ Пользователь не найден. Попробуйте снова: /start")
        return

    if not user.check_password(password):
        session.close()
        await state.clear()
        await message.answer("❌ Неверный пароль. Попробуйте снова: /start")
        return


    AUTHORIZED[message.from_user.id] = user.id
    session.close()
    await state.clear()

    await message.answer("✅ Успешный вход!", reply_markup=menu_kb)
    await message.answer(
        "ℹ️ Используйте кнопки:\n"
        "• <b>Оценить команду</b> — начать выставлять оценки\n"
        "• <b>Сменить аккаунт</b> — выйти и войти заново",
        parse_mode="HTML"
    )


@dp.message(F.text == "Сменить аккаунт")
async def change_account(message: types.Message, state: FSMContext):
    AUTHORIZED.pop(message.from_user.id, None)
    await state.clear()
    await message.answer("Вы вышли из аккаунта. Для входа используйте /start")


@dp.message(F.text == "Оценить команду")
async def start_eval(message: types.Message, state: FSMContext):
    if message.from_user.id not in AUTHORIZED:
        await message.answer("⚠️ Сначала войдите с помощью /start")
        return

    session = Session()
    cases = session.query(Case).all()
    session.close()
    if not cases:
        await message.answer("Кейсов нет.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=c.title, callback_data=f"case_{c.id}")] for c in cases]
    )
    await state.set_state(EvalForm.case)
    await message.answer("Выберите кейс:", reply_markup=kb)


@dp.callback_query(F.data.startswith("case_"))
async def choose_case(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id not in AUTHORIZED:
        await callback.answer("⚠️ Сначала войдите: /start", show_alert=True)
        return

    case_id = int(callback.data.split("_", 1)[1])
    await state.update_data(case_id=case_id)
    await state.set_state(EvalForm.team)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    session = Session()
    teams = session.query(Team).filter_by(case_id=case_id).all()
    session.close()

    if not teams:
        await callback.message.answer("Нет команд в этом кейсе.")
        return

    kb = get_team_keyboard(teams, 0)
    await callback.message.answer("Выберите команду:", reply_markup=kb)


@dp.callback_query(F.data.startswith("page_"))
async def paginate(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id not in AUTHORIZED:
        await callback.answer("⚠️ Сначала войдите: /start", show_alert=True)
        return

    page = int(callback.data.split("_", 1)[1])
    data = await state.get_data()
    case_id = data.get("case_id")
    if case_id is None:
        await callback.message.answer("Сначала выберите кейс.")
        return

    session = Session()
    teams = session.query(Team).filter_by(case_id=case_id).all()
    session.close()

    kb = get_team_keyboard(teams, page)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:

        await callback.message.answer("Навигация:", reply_markup=kb)


@dp.callback_query(F.data.startswith("team_"))
async def choose_team(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id not in AUTHORIZED:
        await callback.answer("⚠️ Сначала войдите: /start", show_alert=True)
        return

    team_id = int(callback.data.split("_", 1)[1])
    await state.update_data(team_id=team_id)
    await state.set_state(EvalForm.product_value)


    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await ask_score(callback.message, "Продуктовая ценность", "prod")


@dp.callback_query(F.data.startswith("prod_"))
async def score_product(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id not in AUTHORIZED:
        await callback.answer("⚠️ Сначала войдите: /start", show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    score = float(callback.data.split("_", 1)[1].replace("05", "0.5"))
    await state.update_data(product_value=score)
    await state.set_state(EvalForm.scalability)
    await ask_score(callback.message, "Реалистичность и масштабируемость", "scal")


@dp.callback_query(F.data.startswith("scal_"))
async def score_scal(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id not in AUTHORIZED:
        await callback.answer("⚠️ Сначала войдите: /start", show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    score = float(callback.data.split("_", 1)[1].replace("05", "0.5"))
    await state.update_data(scalability=score)
    await state.set_state(EvalForm.ux)
    await ask_score(callback.message, "Пользовательский опыт (UX)", "ux")


@dp.callback_query(F.data.startswith("ux_"))
async def score_ux(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id not in AUTHORIZED:
        await callback.answer("⚠️ Сначала войдите: /start", show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    score = float(callback.data.split("_", 1)[1].replace("05", "0.5"))
    await state.update_data(ux=score)
    await state.set_state(EvalForm.presentation)
    await ask_score(callback.message, "Презентация и коммуникация", "pres")


@dp.callback_query(F.data.startswith("pres_"))
async def score_pres(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id not in AUTHORIZED:
        await callback.answer("⚠️ Сначала войдите: /start", show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    score = float(callback.data.split("_", 1)[1].replace("05", "0.5"))
    await state.update_data(presentation=score)

    data = await state.get_data()
    summary = (
        f"✅ Оценки:\n"
        f"- Продуктовая ценность: {data.get('product_value')}\n"
        f"- Масштабируемость: {data.get('scalability')}\n"
        f"- UX: {data.get('ux')}\n"
        f"- Презентация: {data.get('presentation')}\n\n"
        f"Сохранить?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Сохранить", callback_data="save")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit")]
    ])
    await state.set_state(EvalForm.confirm)
    await callback.message.answer(summary, reply_markup=kb)


@dp.callback_query(F.data == "save")
async def save_eval(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id not in AUTHORIZED:
        await callback.answer("⚠️ Сначала войдите: /start", show_alert=True)
        return

    data = await state.get_data()
    required = ("case_id", "team_id", "product_value", "scalability", "ux", "presentation")
    if not all(k in data for k in required):
        await callback.message.answer("Некорректные данные — начните заново.")
        await state.clear()
        return

    evaluator_id = AUTHORIZED[callback.from_user.id]

    session = Session()
    evaluation = FinalEvaluation(
        case_id=data["case_id"],
        team_id=data["team_id"],
        evaluator_id=evaluator_id,
        product_value=data["product_value"],
        scalability=data["scalability"],
        ux=data["ux"],
        presentation=data["presentation"],
    )
    session.add(evaluation)
    session.commit()
    session.close()

    await state.clear()
    await callback.message.answer("✅ Оценка сохранена!", reply_markup=menu_kb)


@dp.callback_query(F.data == "edit")
async def edit_eval(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.from_user.id not in AUTHORIZED:
        await callback.answer("⚠️ Сначала войдите: /start", show_alert=True)
        return

    await state.set_state(EvalForm.product_value)
    await ask_score(callback.message, "Продуктовая ценность", "prod")


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
