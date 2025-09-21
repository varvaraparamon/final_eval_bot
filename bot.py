import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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


async def check_login(callback: CallbackQuery, state: FSMContext) -> bool:
    data = await state.get_data()
    if "evaluator_id" not in data:
        await state.clear()
        await callback.message.answer("⚠️ Сначала войдите в систему: /start")
        return False
    return True


@dp.message(F.text == "/start")
async def start(message: types.Message, state: FSMContext):
    await state.set_state(EvalForm.login)
    await message.answer("Введите логин:")


@dp.message(EvalForm.login)
async def get_login(message: types.Message, state: FSMContext):
    await state.update_data(login=message.text)
    await state.set_state(EvalForm.password)
    await message.answer("Введите пароль:")


@dp.message(EvalForm.password)
async def get_password(message: types.Message, state: FSMContext):
    data = await state.get_data()
    login = data.get("login")
    password = message.text

    if not login:
        await message.answer("⚠️ Сначала введите логин: /start")
        await state.clear()
        return

    session = Session()
    user = session.query(User).filter_by(login=login).first()

    if not user:
        await message.reply("❌ Пользователь не найден. Попробуйте снова: /start")
        await state.clear()
        session.close()
        return

    if not user.check_password(password):
        await message.reply("❌ Неверный пароль. Попробуйте снова: /start")
        await state.clear()
        session.close()
        return

    await state.update_data(evaluator_id=user.id)
    await state.set_state(EvalForm.case)

    cases = session.query(Case).all()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=c.title, callback_data=f"case_{c.id}")] for c in cases]
    )

    await message.reply("✅ Успешный вход! Выберите кейс:", reply_markup=kb)
    session.close()



@dp.callback_query(F.data.startswith("case_"))
async def choose_case(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    if callback.data == "case_done":
        session = Session()
        cases = session.query(Case).all()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=c.title, callback_data=f"case_{c.id}")]
                for c in cases
            ]
        )
        session.close()

        await state.set_state(EvalForm.case)
        await callback.message.answer("Выберите новый кейс:", reply_markup=kb)
        return

    case_id = int(callback.data.split("_")[1])
    await state.update_data(case_id=case_id)
    await state.set_state(EvalForm.team)

    session = Session()
    case = session.get(Case, case_id)
    teams = session.query(Team).filter_by(case_id=case_id).all()
    kb = get_team_keyboard(teams, 0)

    await callback.message.edit_text(f"Вы выбрали кейс: <b>{case.title}</b>", parse_mode="HTML")
    await callback.message.answer("Выберите команду:", reply_markup=kb)
    session.close()


def get_team_keyboard(teams, page, per_page=10):
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


@dp.callback_query(F.data.startswith("page_"))
async def paginate(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    page = int(callback.data.split("_")[1])
    data = await state.get_data()
    case_id = data["case_id"]

    session = Session()
    teams = session.query(Team).filter_by(case_id=case_id).all()
    kb = get_team_keyboard(teams, page)
    await callback.message.edit_reply_markup(reply_markup=kb)
    session.close()


@dp.callback_query(F.data.startswith("team_"))
async def choose_team(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    team_id = int(callback.data.split("_")[1])
    await state.update_data(team_id=team_id)
    await state.set_state(EvalForm.product_value)

    session = Session()
    team = session.get(Team, team_id)
    session.close()

    await callback.message.edit_text(f"Вы выбрали команду: <b>{team.name}</b>", parse_mode="HTML")
    await ask_score(callback.message, "Продуктовая ценность", "prod")


async def ask_score(message, title, prefix):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="0", callback_data=f"{prefix}_0"),
            InlineKeyboardButton(text="0.5", callback_data=f"{prefix}_05"),
            InlineKeyboardButton(text="1", callback_data=f"{prefix}_1"),
        ]
    ])
    await message.answer(f"Оцените: {title}", reply_markup=kb)


@dp.callback_query(F.data.startswith("prod_"))
async def score_product(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    score = float(callback.data.split("_")[1].replace("05", "0.5"))
    await state.update_data(product_value=score)
    await state.set_state(EvalForm.scalability)

    await callback.message.edit_text(f"Продуктовая ценность: {score}")
    await ask_score(callback.message, "Реалистичность и масштабируемость", "scal")


@dp.callback_query(F.data.startswith("scal_"))
async def score_scal(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    score = float(callback.data.split("_")[1].replace("05", "0.5"))
    await state.update_data(scalability=score)
    await state.set_state(EvalForm.ux)

    await callback.message.edit_text(f"Масштабируемость: {score}")
    await ask_score(callback.message, "Пользовательский опыт (UX)", "ux")


@dp.callback_query(F.data.startswith("ux_"))
async def score_ux(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    score = float(callback.data.split("_")[1].replace("05", "0.5"))
    await state.update_data(ux=score)
    await state.set_state(EvalForm.presentation)

    await callback.message.edit_text(f"UX: {score}")
    await ask_score(callback.message, "Презентация и коммуникация", "pres")


@dp.callback_query(F.data.startswith("pres_"))
async def score_pres(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    score = float(callback.data.split("_")[1].replace("05", "0.5"))
    await state.update_data(presentation=score)

    await callback.message.edit_text(f"Презентация: {score}")

    data = await state.get_data()
    session = Session()
    case = session.get(Case, data["case_id"])
    team = session.get(Team, data["team_id"])
    session.close()

    summary = (
        f"✅ Оценки:\n"
        f"Кейс: <b>{case.title}</b>\n"
        f"Команда: <b>{team.name}</b>\n\n"
        f"- Продуктовая ценность: {data['product_value']}\n"
        f"- Масштабируемость: {data['scalability']}\n"
        f"- UX: {data['ux']}\n"
        f"- Презентация: {data['presentation']}\n\n"
        f"Сохранить?"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Сохранить", callback_data="save")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit")]
    ])

    await state.set_state(EvalForm.confirm)
    await callback.message.answer(summary, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "save")
async def save_eval(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    data = await state.get_data()
    session = Session()

    evaluation = FinalEvaluation(
        case_id=data["case_id"],
        team_id=data["team_id"],
        evaluator_id=data["evaluator_id"],
        product_value=data["product_value"],
        scalability=data["scalability"],
        ux=data["ux"],
        presentation=data["presentation"],
    )
    session.add(evaluation)
    session.commit()

    case = session.get(Case, data["case_id"])
    team = session.get(Team, data["team_id"])
    session.close()

    await callback.message.answer("✅ Оценка сохранена!")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Следующая команда", callback_data="next_team")],
        [InlineKeyboardButton(text="📂 Выбрать новый кейс", callback_data="case_done")],
        [InlineKeyboardButton(text="🚪 Выйти из аккаунта", callback_data="logout")]
    ])

    await callback.message.answer("Хотите продолжить?", reply_markup=kb)


@dp.callback_query(F.data == "case_done")
async def case_done(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    session = Session()
    cases = session.query(Case).all()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=c.title, callback_data=f"case_{c.id}")]
            for c in cases
        ]
    )
    session.close()

    await state.set_state(EvalForm.case)
    await callback.message.answer("Выберите новый кейс:", reply_markup=kb)


@dp.callback_query(F.data == "next_team")
async def next_team(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    data = await state.get_data()
    case_id = data["case_id"]

    session = Session()
    teams = session.query(Team).filter_by(case_id=case_id).all()
    kb = get_team_keyboard(teams, 0)
    session.close()

    await state.set_state(EvalForm.team)
    await callback.message.answer("Выберите команду:", reply_markup=kb)


@dp.callback_query(F.data == "logout")
async def logout(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("🚪 Вы вышли из аккаунта.\nЧтобы войти снова — используйте команду /start")


@dp.callback_query(F.data == "edit")
async def edit_eval(callback: CallbackQuery, state: FSMContext):
    if not await check_login(callback, state):
        return

    await state.set_state(EvalForm.product_value)
    await ask_score(callback.message, "Продуктовая ценность", "prod")


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
