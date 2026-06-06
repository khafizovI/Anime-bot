# AniLow

`aiogram` asosidagi Telegram anime bot.

## Imkoniyatlar

- User anime'ni ID orqali qidiradi
- Anime qismi saqlovchi channel orqali tarqatiladi
- `/admin` panel orqali yangi anime qo'shish
- Qismlarni ketma-ket yuklash va `Done` bilan yakunlash
- Har anime uchun umumiy matn va jami qism soni
- Statistika: userlar, aktiv userlar, anime soni
- Broadcast: user, group va channel'lara xabar yuborish
- Majburiy obuna kanallarini admin paneldan boshqarish

## O'rnatish

1. Virtual environment yarating.
2. Kutubxonalarni o'rnating:

```bash
pip install -r requirements.txt
```

3. `.env.example` faylidan nusxa olib `.env` yarating va to'ldiring:

- `BOT_TOKEN`: bot token
- `ADMIN_IDS`: admin Telegram ID'lari, vergul bilan
- `STORAGE_CHANNEL_ID`: barcha anime qismlari saqlanadigan channel ID
- `DATABASE_PATH`: SQLite fayl yo'li

## Muhim eslatmalar

- Bot `STORAGE_CHANNEL_ID` kanalida admin bo'lishi kerak.
- Majburiy obuna uchun public `@username` yoki `https://t.me/username` format ishlating.
- Private invite link orqali obuna tekshirish Telegram API bilan ishonchli ishlamaydi.
- Broadcast group/channel'ga ishlashi uchun bot o'sha chatlarda xabar yubora olishi kerak.

## Ishga tushirish

```bash
python bot.py
```

`BOT_TOKEN` noto'g'ri bo'lsa bot endi tushunarli log bilan to'xtaydi.
