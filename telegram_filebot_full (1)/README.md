# Telegram FileBot

## 💾 نصب و اجرای پروژه

### اجرای محلی
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
python app/bot.py
```

متغیرهای محیطی مهم:
- `BOT_TOKEN`: توکن ربات تلگرام
- `API_BASE_URL`: آدرس API بک‌اند برای ربات
- `DOWNLOAD_DOMAIN`: دامنه‌ای که به کاربر برای دانلود نشان داده می‌شود
- `SUBSCRIPTION_REMINDER_DAYS`: تعداد روزهای مانده به انقضای اشتراک که یادآوری ارسال می‌شود

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
- `app/services/subscription_reminder.py`: ارسال یادآوری اتمام اشتراک
  (قابل اجرا به صورت دوره‌ای برای اطلاع‌رسانی به کاربران)

## 📑 اندپوینت‌های جدید
- `POST /file/upload` بارگذاری متادیتای فایل. نیازمند هدر `X-User-Id`.
- `POST /file/upload_link` دانلود فایل از لینک و ثبت آن.
- `GET /file/list` دریافت لیست فایل‌های کاربر.
- `DELETE /file/delete/{file_id}` حذف فایل متعلق به کاربر.

## 🤖 دستورات ربات
- `/files` نمایش لیست فایل‌های شما
- `/delete <file_id>` حذف فایل با شناسه داده شده
- `/uploadlink <URL>` دانلود فایل از لینک
- `/mysub` نمایش اطلاعات اشتراک شما

## 🧪 تست‌ها
به زودی اضافه می‌شود...
