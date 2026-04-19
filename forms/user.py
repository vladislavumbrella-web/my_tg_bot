from aiogram.fsm.state import State, StatesGroup



class Form(StatesGroup):
    name= State()
    birthday = State()
    id = State()