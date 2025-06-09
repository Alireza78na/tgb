# Telegram FileBot

## 💾 نصب و اجرای پروژه

### اجرای محلی
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
python app/bot.py
```

### اجرای با Docker
```bash
docker-compose up --build
```

## 🔐 احراز هویت ادمین
همه routeهای `/admin/` نیازمند header زیر هستند:
```
X-Admin-Token: SuperSecretAdminToken123
```

## 📦 ساختار
- `app/main.py`: اجرای FastAPI
- `app/bot.py`: اجرای ربات تلگرام
- `app/services/cleanup.py`: پاک‌سازی فایل‌های منقضی

## ✨ امکانات جدید
- لیست فایل‌های کاربر با فراخوانی `GET /file/my` (هدر `X-User-Id` الزامی است)
- دریافت جزئیات فایل با `GET /file/{id}`
- حذف فایل توسط `DELETE /file/{id}`

## 🧪 تست‌ها
به زودی اضافه می‌شود...
