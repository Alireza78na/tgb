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

## 📑 اندپوینت‌های جدید
- `POST /file/upload` بارگذاری متادیتای فایل. نیازمند هدر `X-User-Id`.
- `GET /file/list` دریافت لیست فایل‌های کاربر.
- `DELETE /file/delete/{file_id}` حذف فایل متعلق به کاربر.

## 🧪 تست‌ها
به زودی اضافه می‌شود...
