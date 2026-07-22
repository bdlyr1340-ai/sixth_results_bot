from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_report = State()
