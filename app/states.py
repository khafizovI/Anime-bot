from aiogram.fsm.state import State, StatesGroup


class AddAnimeStates(StatesGroup):
    waiting_id = State()
    waiting_title = State()
    waiting_description = State()
    waiting_title_photo = State()
    waiting_status = State()
    waiting_media = State()


class BroadcastStates(StatesGroup):
    waiting_message = State()


class SubscriptionStates(StatesGroup):
    waiting_channels = State()


class DeleteAnimeStates(StatesGroup):
    waiting_id = State()